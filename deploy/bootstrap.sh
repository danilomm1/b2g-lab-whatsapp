#!/usr/bin/env bash
# Prepara a EC2 Amazon Linux 2023 do laboratório: Python 3.12, Caddy, certbot, usuário b2glab
# e venv.
# Idempotente: o deploy.py roda este script a cada publicação, como root no servidor.
set -euo pipefail

APP_USER=b2glab
ROOT=/srv/b2g-lab

dnf install -y -q python3.12 python3.12-pip rsync sqlite tar

# Caddy: binário oficial do GitHub, conferido pelo SHA-512 publicado na release
if ! command -v caddy >/dev/null 2>&1; then
	tag=$(curl -fsSL https://api.github.com/repos/caddyserver/caddy/releases/latest |
		python3 -c 'import json, sys; print(json.load(sys.stdin)["tag_name"])')
	version=${tag#v}
	asset="caddy_${version}_linux_amd64.tar.gz"
	base="https://github.com/caddyserver/caddy/releases/download/$tag"
	tmp=$(mktemp -d)
	curl -fsSL -o "$tmp/$asset" "$base/$asset"
	curl -fsSL -o "$tmp/checksums.txt" "$base/caddy_${version}_checksums.txt"
	(cd "$tmp" && grep " $asset\$" checksums.txt | sha512sum -c --quiet -)
	tar -xzf "$tmp/$asset" -C "$tmp" caddy
	install -m 755 "$tmp/caddy" /usr/bin/caddy
	rm -rf "$tmp"
	echo "Caddy $version instalado"
fi
getent group caddy >/dev/null || groupadd --system caddy
id -u caddy >/dev/null 2>&1 ||
	useradd --system --gid caddy --create-home --home-dir /var/lib/caddy --shell /sbin/nologin caddy
install -d -m 755 /etc/caddy
install -d -o caddy -g caddy -m 750 /var/log/caddy

# Certbot (Let's Encrypt) num venv próprio, pela instalação via pip documentada pelo projeto;
# o pacote do dnf é bem mais antigo. O desafio HTTP-01 usa /var/www/acme, servido pelo Caddy.
if [ ! -x /opt/certbot/bin/certbot ]; then
	python3.12 -m venv /opt/certbot
	/opt/certbot/bin/pip install -q --no-cache-dir --upgrade pip
	/opt/certbot/bin/pip install -q --no-cache-dir certbot
	ln -sf /opt/certbot/bin/certbot /usr/bin/certbot
	echo "$(/opt/certbot/bin/certbot --version) instalado"
fi
install -d -m 755 /var/www/acme

# Usuário sem login dono da aplicação; o Caddy entra no grupo só para ler os estáticos
id -u "$APP_USER" >/dev/null 2>&1 ||
	useradd --system --no-create-home --home-dir "$ROOT" --shell /sbin/nologin "$APP_USER"
usermod -aG "$APP_USER" caddy
install -d -o "$APP_USER" -g "$APP_USER" -m 750 "$ROOT" "$ROOT/app"
# Banco e fila: só o dono lê (o Caddy fica de fora)
install -d -o "$APP_USER" -g "$APP_USER" -m 700 "$ROOT/app/var"
[ -x "$ROOT/venv/bin/python" ] || sudo -u "$APP_USER" python3.12 -m venv "$ROOT/venv"
