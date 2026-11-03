"""Modelo de dados central do laboratório (CLAUDE.md, seção 4).

Toda integração grava aqui, não em estruturas isoladas. Os models evitam recursos
exclusivos do SQLite para facilitar a migração futura para PostgreSQL.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone

from .phone import InvalidPhoneNumber, normalize_phone


class Channel(models.TextChoices):
    """Canais de relacionamento com os contatos."""

    WHATSAPP = "whatsapp", "WhatsApp"
    INSTAGRAM = "instagram", "Instagram"
    FACEBOOK = "facebook", "Facebook"
    THREADS = "threads", "Threads"
    YOUTUBE = "youtube", "YouTube"
    EMAIL = "email", "Email"
    VOICE = "voice", "Voz"
    SITE = "site", "Site"


# Canais com janela de atendimento: fora dela, só template aprovado ou equivalente
SERVICE_WINDOW_HOURS: dict[str, int] = {
    Channel.WHATSAPP: 24,
    Channel.INSTAGRAM: 24,
    Channel.FACEBOOK: 24,
}


class Tag(models.Model):
    """Etiqueta para segmentar contatos."""

    name = models.CharField("nome", max_length=60, unique=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "etiqueta"
        verbose_name_plural = "etiquetas"

    def __str__(self) -> str:
        return self.name


def _clean_handle(value: str) -> str:
    return value.strip().lstrip("@").lower()


class Contact(models.Model):
    """Pessoa única, independente do canal por onde chegou."""

    name = models.CharField("nome", max_length=200, blank=True)
    email = models.EmailField("email", blank=True)
    phone = models.CharField("telefone (E.164)", max_length=20, blank=True)
    instagram_handle = models.CharField("Instagram", max_length=100, blank=True)
    facebook_handle = models.CharField("Facebook", max_length=100, blank=True)
    threads_handle = models.CharField("Threads", max_length=100, blank=True)
    youtube_handle = models.CharField("YouTube", max_length=100, blank=True)
    source = models.CharField(
        "origem",
        max_length=100,
        blank=True,
        help_text="Ex.: instagram_comment, site_form, campanha B2G-XXXXX.",
    )
    tags = models.ManyToManyField(
        Tag, blank=True, related_name="contacts", verbose_name="etiquetas"
    )
    created_at = models.DateTimeField("criado em", auto_now_add=True)
    updated_at = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "contato"
        verbose_name_plural = "contatos"
        constraints = [
            models.UniqueConstraint(
                fields=["phone"], condition=~Q(phone=""), name="core_contact_unique_phone"
            ),
            models.UniqueConstraint(
                fields=["email"], condition=~Q(email=""), name="core_contact_unique_email"
            ),
        ]

    def __str__(self) -> str:
        return self.name or self.email or self.phone or f"Contato #{self.pk}"

    def save(self, *args, **kwargs) -> None:
        """Normaliza telefone (E.164), email e handles antes de gravar."""
        if self.phone:
            self.phone = normalize_phone(self.phone)
        self.email = self.email.strip().lower()
        for field in ("instagram_handle", "facebook_handle", "threads_handle", "youtube_handle"):
            setattr(self, field, _clean_handle(getattr(self, field)))
        super().save(*args, **kwargs)

    def clean(self) -> None:
        """Valida o telefone para mostrar o erro no formulário em vez de quebrar no save."""
        if self.phone:
            try:
                self.phone = normalize_phone(self.phone)
            except InvalidPhoneNumber as exc:
                raise ValidationError({"phone": str(exc)}) from exc


class ChannelIdentity(models.Model):
    """Vínculo de um contato a um identificador em um canal (wa_id, IGSID, PSID...)."""

    contact = models.ForeignKey(
        Contact, on_delete=models.CASCADE, related_name="identities", verbose_name="contato"
    )
    channel = models.CharField("canal", max_length=20, choices=Channel.choices)
    account_id = models.CharField(
        "conta Brave2Grow",
        max_length=100,
        blank=True,
        help_text=(
            "Página, número ou conta que recebeu o contato. PSID e IGSID são escopados por conta."
        ),
    )
    external_id = models.CharField("ID externo", max_length=255)
    handle = models.CharField("handle", max_length=100, blank=True)
    first_seen_at = models.DateTimeField("visto pela primeira vez", default=timezone.now)
    last_seen_at = models.DateTimeField("visto por último", default=timezone.now)

    class Meta:
        verbose_name = "identidade em canal"
        verbose_name_plural = "identidades em canais"
        constraints = [
            models.UniqueConstraint(
                fields=["channel", "account_id", "external_id"],
                name="core_identity_unique_external",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.get_channel_display()}: {self.handle or self.external_id}"


class ConsentPurpose(models.TextChoices):
    """Finalidades de consentimento (LGPD)."""

    SERVICE = "service", "Atendimento e mensagens de utilidade"
    MARKETING = "marketing", "Marketing"
    PROFILE_LINKING = "profile_linking", "Vínculo de perfis sociais (F06)"


class ConsentQuerySet(models.QuerySet):
    def active(self) -> ConsentQuerySet:
        """Consentimentos ainda não revogados."""
        return self.filter(revoked_at__isnull=True)


class Consent(models.Model):
    """Registro de consentimento por canal e finalidade. A revogação preserva o histórico."""

    contact = models.ForeignKey(
        Contact, on_delete=models.CASCADE, related_name="consents", verbose_name="contato"
    )
    channel = models.CharField("canal", max_length=20, choices=Channel.choices)
    purpose = models.CharField("finalidade", max_length=30, choices=ConsentPurpose.choices)
    granted_at = models.DateTimeField("concedido em", default=timezone.now)
    source = models.CharField(
        "origem", max_length=100, help_text="Ex.: whatsapp_flow, site_form, double_opt_in."
    )
    consent_text = models.TextField("texto aceito", blank=True)
    evidence = models.JSONField(
        "evidência", default=dict, blank=True, help_text="ID da mensagem, hash de IP etc."
    )
    revoked_at = models.DateTimeField("revogado em", null=True, blank=True)
    revocation_source = models.CharField("origem da revogação", max_length=100, blank=True)

    objects = ConsentQuerySet.as_manager()

    class Meta:
        ordering = ["-granted_at"]
        verbose_name = "consentimento"
        verbose_name_plural = "consentimentos"
        constraints = [
            # No máximo um consentimento ativo por contato, canal e finalidade
            models.UniqueConstraint(
                fields=["contact", "channel", "purpose"],
                condition=Q(revoked_at__isnull=True),
                name="core_consent_one_active",
            ),
        ]

    def __str__(self) -> str:
        state = "ativo" if self.is_active else "revogado"
        channel, purpose = self.get_channel_display(), self.get_purpose_display()
        return f"{self.contact} · {channel} · {purpose} ({state})"

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None


class ConversationStatus(models.TextChoices):
    OPEN = "open", "Aberta"
    HANDOFF = "handoff", "Com humano"
    CLOSED = "closed", "Encerrada"


class Conversation(models.Model):
    """Conversa de um contato em um canal, com controle da janela de atendimento."""

    contact = models.ForeignKey(
        Contact, on_delete=models.CASCADE, related_name="conversations", verbose_name="contato"
    )
    channel = models.CharField("canal", max_length=20, choices=Channel.choices)
    account_id = models.CharField("conta Brave2Grow", max_length=100, blank=True)
    external_id = models.CharField(
        "ID externo", max_length=255, blank=True, help_text="ID da thread, quando o canal fornece."
    )
    status = models.CharField(
        "status", max_length=20, choices=ConversationStatus.choices, default=ConversationStatus.OPEN
    )
    last_inbound_at = models.DateTimeField("última mensagem do contato", null=True, blank=True)
    last_message_at = models.DateTimeField("última mensagem", null=True, blank=True)
    created_at = models.DateTimeField("criada em", auto_now_add=True)
    updated_at = models.DateTimeField("atualizada em", auto_now=True)

    class Meta:
        ordering = ["-last_message_at", "-created_at"]
        verbose_name = "conversa"
        verbose_name_plural = "conversas"

    def __str__(self) -> str:
        return f"{self.contact} · {self.get_channel_display()}"

    @property
    def service_window_expires_at(self) -> datetime | None:
        """Fim da janela de atendimento.

        None se o canal não tem janela ou se o contato nunca escreveu.
        """
        hours = SERVICE_WINDOW_HOURS.get(self.channel)
        if hours is None or self.last_inbound_at is None:
            return None
        return self.last_inbound_at + timedelta(hours=hours)

    def is_service_window_open(self, now: datetime | None = None) -> bool:
        """Indica se mensagem livre é permitida. Canais sem janela (email, voz) retornam True."""
        if self.channel not in SERVICE_WINDOW_HOURS:
            return True
        expires_at = self.service_window_expires_at
        return expires_at is not None and (now or timezone.now()) < expires_at


class MessageDirection(models.TextChoices):
    INBOUND = "in", "Entrada"
    OUTBOUND = "out", "Saída"


class MessageStatus(models.TextChoices):
    RECEIVED = "received", "Recebida"
    QUEUED = "queued", "Na fila"
    SIMULATED = "simulated", "Simulada (dry-run)"
    SENT = "sent", "Enviada"
    DELIVERED = "delivered", "Entregue"
    READ = "read", "Lida"
    FAILED = "failed", "Falhou"


# Ordem dos status de saída: webhooks de status chegam fora de ordem e não podem regredir
_OUTBOUND_STATUS_RANK = {
    MessageStatus.QUEUED: 0,
    MessageStatus.SENT: 1,
    MessageStatus.DELIVERED: 2,
    MessageStatus.READ: 3,
}


class Message(models.Model):
    """Mensagem de entrada ou saída, com payload bruto e status de entrega."""

    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="messages", verbose_name="conversa"
    )
    channel = models.CharField("canal", max_length=20, choices=Channel.choices)
    direction = models.CharField("direção", max_length=3, choices=MessageDirection.choices)
    kind = models.CharField(
        "tipo",
        max_length=30,
        default="text",
        help_text="text, image, audio, template, interactive...",
    )
    body = models.TextField("conteúdo", blank=True)
    external_id = models.CharField("ID externo", max_length=255, blank=True)
    status = models.CharField("status", max_length=20, choices=MessageStatus.choices)
    is_proactive = models.BooleanField(
        "iniciada pela empresa",
        default=False,
        help_text="Conta no limite LAB_MAX_PROACTIVE_PER_WEEK.",
    )
    raw_payload = models.JSONField("payload bruto", default=dict, blank=True)
    error = models.JSONField("erro", default=dict, blank=True)
    status_updated_at = models.DateTimeField("status atualizado em", null=True, blank=True)
    created_at = models.DateTimeField("criada em", default=timezone.now, db_index=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name = "mensagem"
        verbose_name_plural = "mensagens"
        constraints = [
            models.UniqueConstraint(
                fields=["channel", "external_id"],
                condition=~Q(external_id=""),
                name="core_message_unique_external",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.get_direction_display()} · {self.kind} · {self.body[:40]}"

    def advance_status(self, new_status: str, at: datetime | None = None) -> bool:
        """Atualiza o status de uma mensagem de saída sem regredir. Retorna se mudou.

        Falha só é aceita antes da entrega; status repetidos ou atrasados são ignorados.
        """
        current_rank = _OUTBOUND_STATUS_RANK.get(self.status)
        if current_rank is None:
            return False
        if new_status == MessageStatus.FAILED:
            accepted = current_rank < _OUTBOUND_STATUS_RANK[MessageStatus.DELIVERED]
        else:
            new_rank = _OUTBOUND_STATUS_RANK.get(new_status)
            accepted = new_rank is not None and new_rank > current_rank
        if accepted:
            self.status = new_status
            self.status_updated_at = at or timezone.now()
        return accepted


class Event(models.Model):
    """Linha do tempo genérica: comentário, clique, ligação concluída, lead criado etc."""

    contact = models.ForeignKey(
        Contact,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="events",
        verbose_name="contato",
    )
    channel = models.CharField("canal", max_length=20, choices=Channel.choices, blank=True)
    event_type = models.CharField(
        "tipo",
        max_length=60,
        db_index=True,
        help_text="Ex.: comment.created, email.clicked, call.completed, lead.created.",
    )
    external_id = models.CharField("ID externo", max_length=255, blank=True)
    occurred_at = models.DateTimeField("ocorrido em", default=timezone.now, db_index=True)
    summary = models.CharField("resumo", max_length=255, blank=True)
    data = models.JSONField("dados", default=dict, blank=True)
    created_at = models.DateTimeField("registrado em", auto_now_add=True)

    class Meta:
        ordering = ["-occurred_at"]
        verbose_name = "evento"
        verbose_name_plural = "eventos"
        constraints = [
            models.UniqueConstraint(
                fields=["channel", "event_type", "external_id"],
                condition=~Q(external_id=""),
                name="core_event_unique_external",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.event_type} · {self.summary or self.external_id}"
