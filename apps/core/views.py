"""Views do núcleo do laboratório."""

import logging
import os
from datetime import timedelta

from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Count
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils import timezone
from huey.contrib.djhuey import HUEY

from apps.credentials.models import CredentialStatus, IntegrationCredential
from apps.webhooks.models import DeliveryStatus, WebhookDelivery

from .integrations import integration_statuses
from .models import Contact, Conversation, ConversationStatus, Event, Message

logger = logging.getLogger(__name__)

RECENT_EVENTS_LIMIT = 15

DELIVERY_TONES = {
    DeliveryStatus.PROCESSED: "ok",
    DeliveryStatus.RECEIVED: "neutral",
    DeliveryStatus.IGNORED: "neutral",
    DeliveryStatus.FAILED: "danger",
    DeliveryStatus.REJECTED: "warn",
}

CREDENTIAL_TONES = {
    CredentialStatus.OK: "ok",
    CredentialStatus.EXPIRING: "warn",
    CredentialStatus.EXPIRED: "danger",
    CredentialStatus.INACTIVE: "neutral",
}


def _pending_tasks() -> int | None:
    """Tarefas na fila do Huey. Se o número só cresce, o consumidor não está rodando."""
    try:
        return HUEY.pending_count()
    except Exception:
        logger.exception("Não foi possível ler a fila do Huey")
        return None


@staff_member_required
def home(request: HttpRequest) -> HttpResponse:
    """Painel com segurança operacional, contadores, fila, credenciais e integrações."""
    since = timezone.now() - timedelta(hours=24)

    stats = [
        {"label": "Contatos", "value": Contact.objects.count()},
        {
            "label": "Conversas abertas",
            "value": Conversation.objects.exclude(status=ConversationStatus.CLOSED).count(),
        },
        {
            "label": "Mensagens (24h)",
            "value": Message.objects.filter(created_at__gte=since).count(),
        },
        {"label": "Eventos (24h)", "value": Event.objects.filter(occurred_at__gte=since).count()},
    ]

    delivery_counts = dict(
        WebhookDelivery.objects.filter(received_at__gte=since)
        .values_list("status")
        .annotate(total=Count("id"))
    )
    deliveries = [
        {"label": status.label, "total": delivery_counts.get(status.value, 0), "tone": tone}
        for status, tone in DELIVERY_TONES.items()
    ]

    credentials = []
    for credential in IntegrationCredential.objects.all():
        status = credential.status()
        credentials.append(
            {"obj": credential, "status": status.label, "tone": CREDENTIAL_TONES[status]}
        )

    context = {
        "stats": stats,
        "deliveries": deliveries,
        "pending_tasks": _pending_tasks(),
        "credentials": credentials,
        "integrations": integration_statuses(),
        "dry_run": settings.LAB_DRY_RUN,
        "allowed_recipients_count": len(settings.LAB_ALLOWED_RECIPIENTS),
        "max_proactive_per_week": settings.LAB_MAX_PROACTIVE_PER_WEEK,
        "settings_module": os.environ.get("DJANGO_SETTINGS_MODULE", ""),
        "debug": settings.DEBUG,
        "events": _recent_events(),
    }
    return render(request, "core/home.html", context)


@staff_member_required
def recent_events(request: HttpRequest) -> HttpResponse:
    """Parcial da linha do tempo, atualizada pelo HTMX a cada 15 segundos."""
    return render(request, "core/partials/recent_events.html", {"events": _recent_events()})


def _recent_events() -> list[Event]:
    return list(Event.objects.select_related("contact")[:RECENT_EVENTS_LIMIT])
