# Servidor de validação na EC2 (b2g-labs-meta)

Onde os webhooks reais chegam (ADR 0005). Amazon Linux 2023, Caddy na frente do Gunicorn com certificado emitido pelo certbot, Huey como serviço e `config.settings.prod` (`DEBUG=False`).

## O servidor

| Item | Valor |
|---|---|
| Nome | `b2g-labs-meta` |
| Região e tipo | `us-east-1`, `t3.micro` (913 MB de RAM, sem swap, disco de 8 GB) |
| Imagem | `ami-0c230065b91270bc6` (Amazon Linux 2023) |
| IP | público da instância; no `deploy.py` local (`HOST`) |
| Usuário SSH | `ec2-user`, só por chave (senha desligada no sshd) |
| Chave | `certificates/b2g-labs-meta.pem` (fora do Git; leitura só para o usuário do Windows) |
| Grupo de segurança | 22, 80 e 443 abertos para `0.0.0.0/0` |
| Domínio | registro A apontando para o IP; no `deploy.py` local (`DOMAIN`) |
| Certificado | Let's Encrypt, emitido pelo certbot com o email da conta no `deploy.py` local (`CERT_EMAIL`) |

IP, domínio e email da conta do certificado ficam só no `deploy.py` local, fora do Git, porque o repositório é público.

**Só o domínio é atendido.** A Meta exige HTTPS com certificado válido, e IP puro não recebe certificado. O servidor responde apenas ao domínio configurado:

- o Caddy encerra a conexão de qualquer outro nome na porta 80 e de qualquer outro `Host` na 443; pelo IP direto ou por um nome antigo (como o nome provisório do sslip.io usado no começo), o TLS nem completa, porque não há certificado para eles;
- o Django aceita só esse host (`DJANGO_ALLOWED_HOSTS`) e esse origin no CSRF.

Para trocar de domínio: criar o registro A apontando para o IP, mudar `DOMAIN` (e `CERT_EMAIL`, se for o caso) no `deploy.py` ou usar `--domain`/`--email`, publicar e trocar a URL de callback na Meta. O `deploy.py` ajusta o `.env` do servidor ao domínio e emite o certificado novo sozinho.

**Certificado (certbot):** o Caddy não emite certificado (`auto_https off`). O certbot, instalado via pip num venv próprio (`/opt/certbot`, versão atual; o pacote do `dnf` é de 2023), faz o desafio HTTP-01 pela porta 80: grava o arquivo em `/var/www/acme`, e o Caddy o serve em `/.well-known/acme-challenge/`. Como o Caddy roda como `caddy` e não lê `/etc/letsencrypt` (só root), o hook `deploy/certbot-caddy-hook.sh`, instalado em `/etc/letsencrypt/renewal-hooks/deploy/`, copia o certificado para `/etc/caddy/certs/<domínio>/` (chave com permissão 600, dono `caddy`) e recarrega o Caddy. A renovação roda pelo `certbot-renew.timer` (duas vezes por dia; o certbot só renova perto do vencimento). A Let's Encrypt não manda mais email de aviso de vencimento, então o timer é o que garante a renovação.

**Chave no Windows:** o OpenSSH recusa chave com permissão aberta. A proteção equivalente ao `chmod 400`:

```powershell
icacls certificates\b2g-labs-meta.pem /inheritance:r
icacls certificates\b2g-labs-meta.pem /grant:r "$env:USERNAME:(R)"
```

## Deploy

O `deploy.py` não é versionado (`.gitignore`), porque traz o IP, o domínio e o email da conta do certificado. Ele existe só na máquina de quem publica; guardar uma cópia fora do repositório. Os arquivos que ele envia ao servidor (`deploy/`) continuam versionados.

Na raiz do projeto, com tudo commitado:

```powershell
.\.venv\Scripts\python.exe deploy.py                # publicação normal
.\.venv\Scripts\python.exe deploy.py --replace-db   # troca o banco do servidor pelo local, sem backup
```

O `deploy.py`:
1. gera o CSS do Tailwind localmente (o servidor não baixa o binário do Tailwind);
2. envia o último commit (`git archive`, com quebras de linha LF) e o CSS por SSH, sem chave do GitHub no servidor;
3. roda `deploy/bootstrap.sh` (idempotente): Python 3.12, rsync, sqlite, Caddy (binário oficial conferido pelo SHA-512), certbot (pip, `/opt/certbot`), usuários `b2glab` e `caddy`, venv;
4. na primeira vez, cria `/srv/b2g-lab/app/.env` a partir do `.env` local: `DEBUG=False`, hosts e CSRF do domínio, `DJANGO_SECRET_KEY` nova, `LAB_DRY_RUN=True`. A `FIELD_ENCRYPTION_KEY` é a mesma do local, para o banco copiado abrir as credenciais. Nos deploys seguintes, só troca `DJANGO_ALLOWED_HOSTS` e `DJANGO_CSRF_TRUSTED_ORIGINS` se o domínio mudou; o resto do `.env` do servidor não é tocado (a não ser com `--replace-env`). Editar lá com `sudoedit /srv/b2g-lab/app/.env`;
5. com `--replace-db`, para os serviços e troca `var/db.sqlite3` por uma cópia consistente do banco local (sem backup do anterior, para poupar o disco);
6. instala dependências (`.[prod]`, sem cache), migra, coleta estáticos, roda `check --deploy` e instala os serviços, o timer de renovação e o hook do certbot;
7. se ainda não existe certificado para o domínio, sobe o Caddy só com a porta 80 (`deploy/Caddyfile`) e roda `certbot certonly --webroot` (aceita os termos da Let's Encrypt, sem a newsletter da EFF);
8. monta o Caddyfile completo (`deploy/Caddyfile` + `deploy/Caddyfile.https`), valida como o usuário `caddy` e reinicia tudo;
9. confere `https://<domínio>/webhooks/meta/` e espera **HTTP 403** (a verificação sem parâmetros é recusada, o que prova que HTTPS, Caddy e Django estão de pé), e confere que `http://<ip>/` tem a conexão encerrada.

## Depois do primeiro deploy

- Na Meta, trocar a URL de callback para `https://<domínio>/webhooks/meta/` (caso de uso Messenger > Configurações da API do Messenger > 1. Configure webhooks > Verificar e salvar) e repetir o "Teste" do campo `messages`.
- Com `--replace-db`, o login do painel é o mesmo do ambiente local.

## Operação (no servidor: `ssh -i certificates/b2g-labs-meta.pem ec2-user@<IP>`)

| Tarefa | Comando |
|---|---|
| Logs do Django | `journalctl -u b2g-lab-web -f` |
| Logs da fila | `journalctl -u b2g-lab-huey -f` |
| Logs do Caddy | `journalctl -u caddy -f` |
| Logs de acesso | `sudo tail -f /var/log/caddy/b2g-lab.log` |
| Certificado e vencimento | `sudo certbot certificates` |
| Testar a renovação (staging da Let's Encrypt) | `sudo certbot renew --dry-run` |
| Próxima verificação de renovação | `systemctl list-timers certbot-renew.timer` |
| Logs do certbot | `journalctl -u certbot-renew` e `sudo less /var/log/letsencrypt/letsencrypt.log` |
| Reiniciar | `sudo systemctl restart b2g-lab-web b2g-lab-huey` |
| Estado | `systemctl status b2g-lab-web b2g-lab-huey caddy certbot-renew.timer` |
| Comandos do Django | `sudo -u b2glab env HOME=/srv/b2g-lab DJANGO_SETTINGS_MODULE=config.settings.prod bash -c 'cd /srv/b2g-lab/app && /srv/b2g-lab/venv/bin/python manage.py <comando>'` (a pasta só abre para o `b2glab`) |

## Segurança

- Serviços rodam como `b2glab`, sem login, com o sistema de arquivos em modo leitura exceto `var/`.
- `.env` com permissão 600; `var/` (SQLite e fila) com 700; o Caddy só lê os estáticos.
- Só o domínio configurado é atendido; outros nomes, outro `Host` e o IP direto têm a conexão encerrada (ver "O servidor").
- Chave privada do certificado: em `/etc/letsencrypt` (só root) e na cópia do Caddy em `/etc/caddy/certs/<domínio>/privkey.pem` (600, dono `caddy`).
- SSH só por chave. A porta 22 está aberta para qualquer IP: recomendável restringir ao IP do Danilo no grupo de segurança.

## Pendente

- Restringir o SSH por IP.
- Atualizações de segurança automáticas (`dnf-automatic` ou janela de manutenção).
- Avaliar restringir o painel e o admin por IP no Caddy.
