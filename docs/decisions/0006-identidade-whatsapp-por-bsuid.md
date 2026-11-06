# ADR 0006: Identidade do WhatsApp pelo BSUID, telefone como dado do contato

**Status:** aceito
**Data:** 2026-11-06

## Contexto

Com os nomes de usuário do WhatsApp, a Meta passou a enviar nos webhooks, desde abril de 2026, o BSUID (business-scoped user ID, campo `user_id`). É um identificador por par portfólio e usuário, no formato `BR.13491208655302741918`, e é o único sempre presente. O telefone (`wa_id`, `from`, `recipient_id`) pode ser omitido quando a pessoa adotou um nome de usuário e não há interação recente com o número. O envio para um BSUID (campo `recipient`) é aceito desde julho de 2026.

Além disso, o `wa_id` de celulares brasileiros antigos chega sem o nono dígito (55 + DDD + 8 dígitos), e a biblioteca `phonenumbers` considera esse formato inválido.

## Decisão

- `ChannelIdentity` do WhatsApp usa `external_id` = BSUID e `account_id` = ID da WABA (`entry.id`). O nome de usuário, quando vem, vai para `handle`.
- O telefone vai para `Contact.phone` em E.164, só quando vier e só se nenhum outro contato já o usa. O nono dígito é inserido em celulares brasileiros antigos.
- Payloads sem BSUID (anteriores à mudança, ou o teste do painel) usam o `wa_id` como chave; quando o BSUID aparecer para o mesmo `wa_id`, a identidade é promovida.
- As mensagens de sistema `user_changed_number` e `user_changed_user_id` trocam o BSUID antigo (`previous_user_id`) pelo novo e atualizam o telefone.
- No envio, usa `to` com o telefone quando existe e `recipient` com o BSUID quando não existe.
- A conversa (`Conversation.account_id`) guarda o `phone_number_id` que recebeu, pois é por ele que se responde.

## Consequências

- Contatos que só têm nome de usuário continuam atendidos e ganham histórico, mas não aparecem por telefone na busca.
- A allowlist (`LAB_ALLOWED_RECIPIENTS`) aceita o BSUID para esses casos.
- Templates de autenticação não podem ir para um BSUID (erro 131062); quando forem usados, exigem o telefone.
- O BSUID muda se a pessoa troca de número; perder a mensagem de sistema cria uma identidade nova, que volta a se ligar ao contato quando o telefone aparecer.
