#!/usr/bin/env bash
# Hook de deploy do certbot: entrega o certificado ao Caddy, que roda como usuário caddy e não
# lê /etc/letsencrypt (só root). Instalado em /etc/letsencrypt/renewal-hooks/deploy/, roda a
# cada renovação; o deploy.py também o chama depois da primeira emissão.
# O certbot informa a pasta do certificado em RENEWED_LINEAGE (/etc/letsencrypt/live/<domínio>).
set -euo pipefail

dest=/etc/caddy/certs/$(basename "$RENEWED_LINEAGE")
install -d -o caddy -g caddy -m 700 "$dest"
install -o caddy -g caddy -m 644 "$RENEWED_LINEAGE/fullchain.pem" "$dest/fullchain.pem"
install -o caddy -g caddy -m 600 "$RENEWED_LINEAGE/privkey.pem" "$dest/privkey.pem"
# O Caddy só relê os arquivos do certificado ao recarregar a configuração
systemctl reload-or-restart caddy
