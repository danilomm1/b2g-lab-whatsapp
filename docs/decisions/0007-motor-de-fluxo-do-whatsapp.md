# ADR 0007: Motor de fluxo do WhatsApp em código, com envio depois do commit

**Status:** aceito
**Data:** 2026-11-06

## Contexto

O CLAUDE.md pede um motor de fluxo conversacional com nós de mensagem, pergunta, condição, chamada de API e handoff humano. Ele é a base dos fluxos F01 a F17 e precisa:

- ser testável sem a Meta (todas as chamadas mockadas);
- respeitar as travas do laboratório (janela de 24h, consentimento, dry-run, allowlist e palavra de saída);
- nunca mandar mensagem real atrelada a um registro que ainda pode ser desfeito, já que o webhook é processado dentro de uma transação.

As opções eram fluxos guardados no banco, editáveis por tela, ou fluxos definidos em código.

## Decisão

- **Fluxos definidos em Python** (`apps/whatsapp/flows`), como grafos de nós com IDs. Tipos: `Say`, `Ask` (botões, lista ou texto validado), `Branch`, `Call` (serviço ou API, em savepoint), `Handoff` e `End`. O grafo é validado na criação: nó inexistente é erro.
- **Estado no banco:** `FlowRun` guarda o fluxo, o nó atual, as respostas e as tentativas. Uma restrição garante no máximo uma execução aberta (ativa ou com humano) por conversa.
- **Envio depois do commit:** o motor só decide o que dizer e põe numa caixa de saída. `transaction.on_commit` agenda a tarefa Huey `send_outbox`, sem novas tentativas automáticas (repetir pode duplicar), que envia em ordem por `send_message`.
- **Robustez:**
  - O motor roda num savepoint. Se falhar, a mensagem recebida continua gravada e a falha vira o evento `whatsapp.flow_error`.
  - Os IDs de botão levam o nó como prefixo, para que um toque em botão antigo não seja aceito como resposta.
- **Regras de conversa no motor, não em cada fluxo:** SAIR (cancela e confirma), MENU (recomeça e tira do handoff), silêncio durante o handoff, 12 horas sem recomeço automático depois de concluir, e validade de 24 horas para perguntas sem resposta.

## Consequências

- Mudar um texto ou caminho exige commit e deploy. É o custo da revisão e dos testes; no laboratório, compensa.
- Os fluxos são testados como qualquer código, pela esteira completa (webhook assinado, motor e tarefa de envio).
- A orquestração multicanal (Journey, JourneyStep e JourneyRun, Fase 8) pode iniciar fluxos do WhatsApp com `start_flow` sem duplicar o motor.
- Uma tela para editar fluxos sem deploy pode vir depois, gerando os mesmos grafos a partir do banco.
