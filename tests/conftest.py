"""Fixtures compartilhadas dos testes."""

import json
from collections.abc import Callable
from typing import Any

import pytest
from django.conf import settings
from django.http import HttpResponse
from django.test import Client

from apps.meta_business.webhook import SIGNATURE_HEADER as META_SIGNATURE_HEADER
from apps.webhooks.lab import SIGNATURE_HEADER
from apps.webhooks.signatures import sign_body

LabPost = Callable[..., HttpResponse]


@pytest.fixture
def lab_post(client: Client, django_capture_on_commit_callbacks: Any) -> LabPost:
    """Envia um webhook ao provedor lab, assinado e com os callbacks on_commit executados."""

    def post(payload: dict[str, Any], *, secret: str | None = None, **headers: str) -> HttpResponse:
        body = json.dumps(payload).encode()
        signature = sign_body(settings.LAB_WEBHOOK_SECRET if secret is None else secret, body)
        with django_capture_on_commit_callbacks(execute=True):
            return client.post(
                "/webhooks/lab/",
                data=body,
                content_type="application/json",
                headers={SIGNATURE_HEADER: signature, **headers},
            )

    return post


MetaPost = Callable[..., HttpResponse]


@pytest.fixture
def meta_post(client: Client, django_capture_on_commit_callbacks: Any) -> MetaPost:
    """Envia um webhook da Meta assinado com o App Secret, executando os callbacks on_commit."""

    def post(payload: dict[str, Any], *, secret: str | None = None) -> HttpResponse:
        body = json.dumps(payload).encode()
        signature = sign_body(settings.META_APP_SECRET if secret is None else secret, body)
        with django_capture_on_commit_callbacks(execute=True):
            return client.post(
                "/webhooks/meta/",
                data=body,
                content_type="application/json",
                headers={META_SIGNATURE_HEADER: signature},
            )

    return post
