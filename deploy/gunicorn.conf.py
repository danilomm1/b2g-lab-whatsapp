"""Configuração do Gunicorn no servidor de validação (deploy/systemd/b2g-lab-web.service).

O log de acesso grava só o caminho, sem a query string: a verificação de webhook da Meta
manda o hub.verify_token na URL, e outros provedores podem mandar dados na query.
"""

# Formato padrão do Gunicorn trocando %(r)s (linha da requisição, com a query) por método,
# caminho e protocolo, e sem o Referer, que também pode trazer query
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(m)s %(U)s %(H)s" %(s)s %(b)s "%(a)s"'
