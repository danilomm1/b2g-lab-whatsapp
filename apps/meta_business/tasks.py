"""Tarefas Huey comuns ao Instagram e à Página."""

from huey.contrib.djhuey import db_task

from .profiles import fetch_profile


@db_task()  # sem novas tentativas: o perfil é um complemento
def fetch_user_profile(identity_id: int) -> None:
    """Completa nome e @ de um contato novo do Instagram ou do Messenger."""
    fetch_profile(identity_id)
