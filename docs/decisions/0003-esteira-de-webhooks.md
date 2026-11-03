# ADR 0003: Esteira única de entrada de webhooks

**Status:** aceito
**Data:** 2026-11-03

## Contexto

Meta (WhatsApp, Instagram, Facebook), Twilio, ElevenLabs, SNS e o site vão chamar o laboratório por webhook. O CLAUDE.md exige: validar a assinatura de toda chamada, guardar o payload bruto, responder rápido e processar na fila, de forma idempotente.

## Decisão

- Endpoint único `POST /webhooks/<provedor>/` (app `webhooks`). `GET` no mesmo endereço é repassado ao `handshake()` do provedor (para o `hub.challenge` da Meta na Fase 1).
- Cada provedor é uma subclasse de `WebhookProvider` com: `verify_signature`, `handshake`, `parse_payload` (JSON ou formulário), `dedupe_key` e `route_key`. Os apps de canal registram o provedor e os handlers no `ready()` do AppConfig, por exemplo `@registry.handler("meta", "whatsapp_business_account")`. Assim o roteamento pelo campo `object` da Meta vira só um `route_key`.
- Toda chamada vira um `WebhookDelivery` com cabeçalhos (sem `Authorization` e `Cookie`), corpo bruto e payload. Assinatura inválida: grava como `rejected` e responde 403. Válida: grava, responde 200 e enfileira `process_delivery` no Huey depois do commit.
- Deduplicação por `(provedor, dedupe_key)`, que é o ID do evento quando o provedor informa um, ou o SHA-256 do corpo. A restrição única vale só para entregas com assinatura válida, para que uma chamada falsificada não bloqueie a verdadeira.
- Processamento: sem handler para a rota, a entrega fica `ignored`; erro em handler marca `failed`, guarda o traceback e o Huey tenta de novo (3 vezes, a cada 30 s). Entregas finalizadas são puladas, e o admin tem a ação "Reprocessar".
- Provedor `lab` embutido, assinado como a Meta (HMAC-SHA256, prefixo `sha256=`) com `LAB_WEBHOOK_SECRET`, para testar a esteira sem plataforma externa: `python manage.py send_test_webhook`.

## Consequências

- A Fase 1 só precisa de um `MetaProvider` (assinatura `X-Hub-Signature-256` com `META_APP_SECRET`, handshake e `route_key = payload["object"]`); `verify_hmac_sha256` já cobre o cálculo.
- Um POST da Meta pode trazer várias mensagens; a deduplicação fina continua nos IDs externos únicos de `Message` e `Event`.
- Entregas rejeitadas também ocupam espaço no banco. No deploy público, avaliar limpeza periódica.
