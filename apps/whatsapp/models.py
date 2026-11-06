"""Models do WhatsApp: estado dos templates na Meta e execuções dos fluxos conversacionais.

O conteúdo dos templates fica versionado em templates_catalog.py; aqui fica só o que a
Meta informa (status, categoria, motivo de rejeição). Os fluxos são definidos em código
(apps/whatsapp/flows, ADR 0007); FlowRun guarda em que nó cada conversa está.
"""

from __future__ import annotations

from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.core.models import Contact, Conversation


class MessageTemplate(models.Model):
    """Template como está na Meta, atualizado pelo sync e pelo webhook de status."""

    name = models.CharField("nome", max_length=512)
    language = models.CharField("idioma", max_length=20)
    category = models.CharField("categoria", max_length=30, blank=True)
    status = models.CharField(
        "status na Meta",
        max_length=30,
        blank=True,
        help_text="APPROVED, PENDING, REJECTED, PAUSED, DISABLED...",
    )
    meta_id = models.CharField("ID na Meta", max_length=64, blank=True)
    rejected_reason = models.CharField("motivo", max_length=255, blank=True)
    components = models.JSONField("componentes", default=list, blank=True)
    raw = models.JSONField("último retorno da Meta", default=dict, blank=True)
    updated_at = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        ordering = ["name", "language"]
        verbose_name = "template do WhatsApp"
        verbose_name_plural = "templates do WhatsApp"
        constraints = [
            models.UniqueConstraint(fields=["name", "language"], name="whatsapp_template_unique"),
        ]

    def __str__(self) -> str:
        return f"{self.name} [{self.language}] {self.status or '-'}"

    @property
    def is_approved(self) -> bool:
        return self.status == "APPROVED"


class FlowRunStatus(models.TextChoices):
    ACTIVE = "active", "Em andamento"
    HANDOFF = "handoff", "Com humano"
    COMPLETED = "completed", "Concluído"
    CANCELLED = "cancelled", "Cancelado"
    EXPIRED = "expired", "Expirado"


class FlowRun(models.Model):
    """Execução de um fluxo em uma conversa: nó atual, respostas e tentativas."""

    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="flow_runs", verbose_name="conversa"
    )
    contact = models.ForeignKey(
        Contact, on_delete=models.CASCADE, related_name="flow_runs", verbose_name="contato"
    )
    flow_key = models.CharField("fluxo", max_length=60)
    node = models.CharField("nó atual", max_length=60, blank=True)
    status = models.CharField(
        "status", max_length=20, choices=FlowRunStatus.choices, default=FlowRunStatus.ACTIVE
    )
    state = models.JSONField("respostas e dados", default=dict, blank=True)
    attempts = models.PositiveSmallIntegerField("tentativas no nó atual", default=0)
    started_at = models.DateTimeField("iniciado em", default=timezone.now)
    updated_at = models.DateTimeField("atualizado em", auto_now=True)
    finished_at = models.DateTimeField("encerrado em", null=True, blank=True)

    class Meta:
        ordering = ["-started_at"]
        verbose_name = "execução de fluxo"
        verbose_name_plural = "execuções de fluxo"
        constraints = [
            # No máximo uma execução aberta (ativa ou com humano) por conversa
            models.UniqueConstraint(
                fields=["conversation"],
                condition=Q(status__in=["active", "handoff"]),
                name="whatsapp_flowrun_one_open",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.flow_key} · {self.contact} · {self.get_status_display()}"

    def finish(self, status: str) -> None:
        self.status = status
        self.finished_at = timezone.now()


class WhatsAppForm(models.Model):
    """WhatsApp Flow (formulário nativo) como está na Meta.

    O conteúdo fica versionado em forms_catalog.py; aqui ficam o ID, o status e os
    erros de validação devolvidos pela Meta.
    """

    name = models.CharField("nome", max_length=200, unique=True)
    meta_id = models.CharField("ID na Meta", max_length=64, blank=True)
    status = models.CharField(
        "status na Meta", max_length=20, blank=True, help_text="DRAFT, PUBLISHED, DEPRECATED..."
    )
    categories = models.JSONField("categorias", default=list, blank=True)
    validation_errors = models.JSONField("erros de validação", default=list, blank=True)
    raw = models.JSONField("último retorno da Meta", default=dict, blank=True)
    updated_at = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "formulário do WhatsApp (Flow)"
        verbose_name_plural = "formulários do WhatsApp (Flows)"

    def __str__(self) -> str:
        return f"{self.name} {self.status or '-'}"

    @property
    def send_mode(self) -> str:
        """Publicado vai em modo normal; rascunho só pode ser enviado em modo de teste."""
        return "published" if self.status == "PUBLISHED" else "draft"
