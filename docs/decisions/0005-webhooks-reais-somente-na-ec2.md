# ADR 0005: Webhooks reais somente na EC2, sem túneis

**Status:** aceito
**Data:** 2026-11-06

## Contexto

A Meta (e depois Twilio, ElevenLabs, SNS e o site) só entrega webhooks para um endereço HTTPS público com certificado válido. Na Fase 1, a validação foi feita com o túnel rápido do cloudflared (`trycloudflare.com`) apontando para o runserver da porta 8602. Funcionou, mas:

- enquanto o túnel está no ar, o servidor de desenvolvimento inteiro fica público, incluindo o admin e as páginas de erro do `DEBUG=True`;
- a Cloudflare termina o TLS e enxerga o conteúdo dos webhooks, o que inclui dados pessoais de contatos (LGPD);
- a URL muda a cada execução e o túnel caiu com a VPN ligada.

## Decisão

- Não usar túneis (cloudflared, ngrok ou similares) para expor a máquina local.
- Webhooks reais chegam somente no servidor de validação: a EC2 `b2g-labs-meta` (Amazon Linux 2023) com Gunicorn, Caddy, Huey como serviço e `config.settings.prod` (`DEBUG=False`). O servidor atende só o seu domínio (de início foi um nome provisório do sslip.io; os valores ficam no `deploy.py` local, fora do Git), com certificado Let's Encrypt emitido e renovado pelo certbot. Deploy pelo `deploy.py` (docs/deploy/ec2.md).
- Localmente, o fluxo de webhooks é testado com eventos simulados e assinados (testes automatizados e o comando `send_test_webhook`).
- Isso adianta a parte de webhooks da Fase 16 do roadmap.

## Consequências

- O callback cadastrado na Meta passa a ser fixo e não precisa ser recadastrado.
- Testar um webhook real exige publicar o código no servidor.
- O servidor guarda segredos (App Secret, token do System User, chave de criptografia): `.env` só no servidor, com permissão 600, e SSH só por chave. A porta 22 ficou aberta para qualquer IP; restringir ao IP do Danilo é recomendado.
- O painel e o admin no servidor exigem login de staff; avaliar limitar o acesso por IP no Caddy.
