"""Registro bruto de cada webhook recebido."""

from django.db import models
from django.db.models import Q
from django.utils import timezone


class DeliveryStatus(models.TextChoices):
    RECEIVED = "received", "Recebida"
    PROCESSED = "processed", "Processada"
    IGNORED = "ignored", "Ignorada (sem handler)"
    FAILED = "failed", "Falhou"
    REJECTED = "rejected", "Rejeitada (assinatura inválida)"


class WebhookDelivery(models.Model):
    """Uma chamada recebida de um provedor, guardada antes de qualquer processamento."""

    provider = models.CharField("provedor", max_length=40, db_index=True)
    route_key = models.CharField(
        "rota", max_length=100, blank=True, help_text="Ex.: o campo object da Meta."
    )
    dedupe_key = models.CharField(
        "chave de deduplicação",
        max_length=128,
        blank=True,
        help_text="ID do evento informado pelo provedor ou hash SHA-256 do corpo.",
    )
    signature_valid = models.BooleanField("assinatura válida", default=False)
    status = models.CharField(
        "status", max_length=20, choices=DeliveryStatus.choices, default=DeliveryStatus.RECEIVED
    )
    headers = models.JSONField("cabeçalhos", default=dict, blank=True)
    raw_body = models.TextField("corpo bruto", blank=True)
    raw_payload = models.JSONField("payload bruto", default=dict, blank=True)
    attempts = models.PositiveIntegerField("tentativas", default=0)
    error = models.TextField("erro", blank=True)
    received_at = models.DateTimeField("recebida em", default=timezone.now, db_index=True)
    processed_at = models.DateTimeField("processada em", null=True, blank=True)

    class Meta:
        ordering = ["-received_at"]
        verbose_name = "entrega de webhook"
        verbose_name_plural = "entregas de webhook"
        constraints = [
            # Só entregas autênticas deduplicam: uma falsificada não pode bloquear a verdadeira
            models.UniqueConstraint(
                fields=["provider", "dedupe_key"],
                condition=Q(signature_valid=True) & ~Q(dedupe_key=""),
                name="webhooks_delivery_unique_dedupe",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.provider}/{self.route_key or '-'} #{self.pk} ({self.get_status_display()})"
