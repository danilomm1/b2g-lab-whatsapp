# ADR 0004: Criptografia dos tokens em IntegrationCredential

**Status:** aceito
**Data:** 2026-11-03

## Contexto

O CLAUDE.md exige tokens criptografados em repouso. O `.env.example` já previa `FIELD_ENCRYPTION_KEY`. As bibliotecas prontas de campos criptografados para Django estão paradas ou sem suporte claro ao Django 5.2.

## Decisão

- Campo próprio `EncryptedTextField` (`apps/credentials/fields.py`), com Fernet da biblioteca `cryptography`: criptografa em `get_prep_value` e descriptografa em `from_db_value`.
- `FIELD_ENCRYPTION_KEY` aceita uma lista separada por vírgula, usada com `MultiFernet`: a primeira chave criptografa, todas descriptografam.
- Sem chave configurada, ou com chave errada, o sistema falha com `ImproperlyConfigured` e mensagem clara, nunca trata o valor como vazio.
- O admin nunca exibe o token: mostra só os 4 últimos caracteres, e os campos de token são de escrita (vazio mantém o atual).

## Rotação de chave

1. `python manage.py generate_encryption_key`
2. No `.env`: `FIELD_ENCRYPTION_KEY=<nova>,<antiga>`
3. `python manage.py reencrypt_credentials`
4. Remover a chave antiga do `.env`.

## Consequências

- Fernet não é determinístico: não dá para filtrar credenciais pelo valor do token, só por vazio.
- Perder a chave significa perder os tokens gravados; eles terão de ser gerados de novo nas plataformas. Guardar a chave fora do servidor (gerenciador de senhas).
