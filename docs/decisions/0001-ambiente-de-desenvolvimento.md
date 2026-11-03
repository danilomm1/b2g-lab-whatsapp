# ADR 0001: Ambiente de desenvolvimento no VS Code

**Status:** aceito
**Data:** 2026-11-03

## Contexto

O laboratório é desenvolvido localmente no Windows com VS Code. Queremos que, ao abrir o projeto, o servidor e o navegador de testes já estejam prontos, sem passos manuais. O Chrome precisa rodar com depuração remota para inspeção e automação (DevTools Protocol).

## Decisão

- O `runserver` roda sempre na porta **8602**.
- O Chrome de testes roda com `--remote-debugging-port=9997`.
- Ambos sobem por tarefas do VS Code com `runOn: folderOpen` (`.vscode/tasks.json`).
- O Chrome é aberto pelo script `scripts/dev/chrome_debug.ps1`, que espera o servidor responder, reaproveita uma instância já aberta na porta 9997 e usa um perfil dedicado em `%LOCALAPPDATA%\b2g-lab\chrome-debug-profile`.

## Motivos

- Desde o Chrome 136, `--remote-debugging-port` só funciona com um `--user-data-dir` diferente do perfil padrão. Um perfil dedicado também isola cookies e logins de teste (painéis da Meta, Google Cloud etc.) do perfil pessoal.
- O perfil fica fora do repositório para não pesar no Git nem no indexador do VS Code.
- Portas fixas e incomuns evitam conflito com outros projetos que usam 8000 e 9222.

## Consequências

- Na primeira abertura do Chrome de testes é preciso fazer login nos serviços usados no laboratório, pois o perfil começa vazio.
- Para depurar o Python com breakpoints é preciso parar a tarefa automática do `runserver` antes de iniciar a configuração "Django: depurar no 8602", porque as duas usam a mesma porta.
- Depende de `task.allowAutomaticTasks: "on"` nas configurações de usuário do VS Code.
