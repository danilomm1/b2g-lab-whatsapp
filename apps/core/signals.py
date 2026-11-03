"""Sinais do núcleo, para que outros apps reajam sem acoplamento direto."""

from django.dispatch import Signal

# Disparado quando um contato usa a palavra de saída (SAIR, PARAR, STOP) em um canal.
# Argumentos: contact, channel, source. O orchestrator (Fase 8) encerra as jornadas ativas.
contact_opted_out = Signal()
