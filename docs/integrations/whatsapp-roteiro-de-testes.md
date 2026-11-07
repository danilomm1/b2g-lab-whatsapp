# WhatsApp: roteiro de testes de ponta a ponta

Roteiro para conferir, no WhatsApp real, todas as mensagens que o laboratório envia e recebe, nos dois papéis da conversa:

- **Cliente:** o WhatsApp Web, na conversa com o número de teste.
- **Fornecedor:** a tela de conversa do laboratório (`/whatsapp/<id>/`), em nome da Brave2Grow.
- **Servidor:** conferência no banco do servidor de validação.
- **Simulado:** `whatsapp_simulate_reply`, para botões de templates ainda em análise.

Os testes automatizados (pytest) cobrem a mesma lógica com a Graph API mockada. Este roteiro confere o que só aparece na Meta e no aparelho: entrega, ordem, formatação, botões, listas, formulários e mídia.

## Antes de começar

- O servidor precisa de `LAB_DRY_RUN=False`, com o celular do cliente em `LAB_ALLOWED_RECIPIENTS` e em `OWNER_WHATSAPP_NUMBERS`.
- O formulário `b2g_cadastro` precisa estar criado (`whatsapp_forms list`).
- O WhatsApp Web precisa estar aberto na conversa com o número de teste, e a tela de conversa do laboratório aberta noutra aba.
- **Preparação no banco do servidor:**
  - apagar o evento `privacy.notice_shown` do contato, para o próximo MENU contar como primeiro contato;
  - zerar o email do contato, para o fluxo de agendamento perguntar o email.

## Inventário de mensagens

### Mensagens do assistente

| Mensagem | Como disparar | Esperado |
|---|---|---|
| Saudação com aviso de privacidade | MENU no primeiro contato | Nome do contato, aviso com o link https://brave2grow.com/privacidade/ e o lembrete do SAIR |
| Saudação sem aviso | MENU depois do primeiro contato | Só a saudação |
| Menu | Logo após a saudação | 3 botões: Conhecer serviços, Agendar conversa, Falar com o Danilo |
| Resposta inválida | Texto que não é opção | "Não entendi..." e o menu de novo |
| Opção digitada | "1" ou o título digitado | Vale como o botão |
| Serviços | Conhecer serviços | Apresentação e a pergunta de novidades, com 2 botões |
| Opt-in | Quero receber | "Combinado!..." e consentimento de marketing |
| Recusa | Agora não | "Sem problemas!..." |
| Pergunta de email | Agendar conversa, contato sem email | "Qual é o seu melhor email?..." |
| Email inválido | Texto que não é email | "Não reconheci esse email..." |
| Período | Email válido, ou contato que já tem email | 3 botões: Manhã, Tarde, Noite |
| Pedido de agendamento | Um período | "Anotado!... para o período da ..." |
| Handoff | Falar com o Danilo, ou duas respostas inválidas | "Certo! Vou avisar o Danilo..." |
| Aviso ao dono | Junto com o handoff | "Aviso do laboratório: ..." com telefone, motivo e respostas |
| Silêncio | Mensagem durante o handoff, ou "obrigado" logo depois de concluir | Nenhuma resposta |
| Convite do formulário | CADASTRO, ou o botão na tela | Texto e o botão "Preencher" |
| Formulário pendente | Texto no lugar do formulário | Pedido para tocar no botão e o convite de novo |
| Agradecimento do cadastro | Formulário enviado | "Obrigado, ...! Recebemos seu cadastro..." |
| Formulário não concluído | Duas mensagens no lugar do formulário | Handoff com o motivo "Cadastro pelo formulário não concluído" |
| Formulário indisponível | CADASTRO sem o formulário na Meta | "O formulário está indisponível agora..." |
| Respostas aos botões de template | Confirmo, Reagendar, Cancelar, Agora não, Sim, continuar | A resposta de cada botão; "Sim, continuar" abre o menu |
| Confirmação de saída | SAIR, PARAR ou STOP | "Pronto, você não vai mais receber..." |

### Mensagens do fornecedor (tela de conversa)

| Mensagem | Como disparar | Esperado |
|---|---|---|
| Texto | Responder como Brave2Grow | Chega no WhatsApp |
| Botões | Mensagem com botões | 3 botões; o toque volta com o ID `teste_*` |
| Lista | Mensagem com lista | Lista com duas seções; a escolha volta com o ID `teste_*` |
| Imagem | Imagem de teste | Imagem com legenda |
| Documento | Anexo na resposta | Documento com nome e legenda |
| Formulário | Formulário de cadastro | Convite do formulário |
| Devolver ao assistente | Botão durante o handoff | A próxima mensagem volta ao fluxo |

### Mensagens do cliente

| Mensagem | Esperado no laboratório |
|---|---|
| Texto, botão, lista, formulário | Gravadas com o ID escolhido ou as respostas do formulário |
| Foto e documento | Baixados para `var/media/whatsapp` e exibidos na tela |
| Reação com emoji | Gravada como `reaction`; o robô não responde e a pergunta aberta não muda |

### Templates

| Teste | Esperado |
|---|---|
| Template em análise | Barrado antes da Meta: "Envio bloqueado: Template ... está PENDING" |
| `hello_world` | Chega no WhatsApp |
| Botões dos templates próprios | Validados com `whatsapp_simulate_reply` enquanto a Meta não aprova |

## Resultado da rodada de 06 e 07/11/2026

O roteiro foi executado por um script que conduz o Chrome de depuração (porta 9997) nos dois papéis e confere o banco do servidor por SSH. São 54 passos, de 23:54 a 00:03 UTC, em sequência: a primeira parte parou no seletor de lista por um ajuste do script, e o complemento seguiu do mesmo ponto, no mesmo estado da conversa.

Resumo do servidor no fim da rodada: 121 mensagens enviadas e 121 lidas, nenhuma falha de envio, nenhum erro de fluxo e nenhum envio bloqueado.

| Passo | Lado | Ação | Resultado |
|---|---|---|---|
| P0 | servidor | Preparação (aviso de privacidade e email zerados) | OK |
| A1 | cliente | MENU no primeiro contato | OK: saudação com o link da política, lembrete do SAIR e menu |
| A2 | cliente | Resposta inválida no menu | OK: "Não entendi" e o menu de novo |
| A3 | cliente | Opção pelo número ("1") | OK: serviços e pergunta de novidades |
| A4 | cliente | Recusa de novidades | OK |
| A5 | cliente | "obrigado" logo depois de concluir | OK: robô quieto |
| A5b | cliente | O "obrigado" aparece como lida | OK: tique azul |
| A6 | cliente | MENU de novo | OK: saudação sem repetir o aviso |
| A7a, A7b | cliente | Conhecer serviços e Quero receber | OK |
| A7c | servidor | Consentimento de marketing ativo | OK (um ativo por finalidade; já existia o do formulário) |
| A8a a A8d | cliente | Agendar sem email: pergunta, email inválido, email válido, manhã | OK |
| A8e | servidor | Email gravado e pedido de agendamento | OK |
| A9a, A9b | cliente | Agendar com email conhecido: direto ao período, noite | OK |
| A10 | cliente | Duas respostas inválidas | OK: handoff e aviso ao dono |
| A11 | cliente | Mensagem durante o handoff | OK: robô quieto |
| A11b | cliente | A mensagem fica como entregue no handoff | OK |
| P1 | fornecedor | Resposta em texto pela tela | OK |
| P1b | cliente | Depois da resposta pela tela, a mensagem fica como lida | OK |
| P2a, P2b | fornecedor e cliente | Mensagem com botões e toque em "Talvez" | OK: ID `teste_talvez`, robô quieto |
| P3a, P3b | fornecedor e cliente | Lista com duas seções e escolha "Quarta, 15h" | OK: ID `teste_qua_15` |
| P4 | fornecedor | Imagem de teste | OK |
| P5 | fornecedor | PDF com legenda pelo anexo | OK |
| C1 | cliente | Foto | OK: `image/jpeg` baixada no servidor |
| C2 | cliente | Documento PDF | OK: `application/pdf` baixado no servidor |
| C3 | cliente | Reação 👍 | OK: gravada como `reaction`, robô quieto |
| P6 | fornecedor | Devolver ao assistente | OK pelo servidor: a execução com humano foi encerrada no clique; o script não leu o aviso da tela porque a atualização automática (5 s) já o tinha trocado |
| A12a, A12b | cliente | Falar com o Danilo e MENU durante o handoff | OK |
| B1a a B1d | cliente e servidor | CADASTRO, texto no lugar do formulário, formulário com opt-in | OK: convite reenviado, cadastro e consentimento `whatsapp_form` |
| B2a, B2b | fornecedor e cliente | Formulário pela tela, não concluído | OK: handoff com o motivo do formulário |
| B3 | cliente | Formulário indisponível | OK |
| T1 | servidor | Template em análise | OK: barrado antes da Meta (PENDING) |
| T2 | servidor | `hello_world` | OK |
| T3 | simulado | Confirmo, Reagendar, Cancelar, Agora não, Sim, continuar | OK: as cinco respostas |
| D1a, D1b | cliente e servidor | "Parar" | OK: confirmação e consentimentos revogados |
| D2 | cliente | MENU depois da saída | OK: a conversa segue ativa |
| F1 | cliente | Última mensagem do cliente lida | OK |
| F2 | servidor | Resumo da rodada | OK |

## Problemas encontrados e corrigidos durante as rodadas

| Problema | Correção |
|---|---|
| A mensagem do cliente ficava só como entregue quando o robô não respondia, inclusive no handoff depois de o fornecedor responder | O robô quieto (fora do handoff) marca como lida; no handoff, qualquer ação bem-sucedida na tela marca como lida a última mensagem recebida |
| Uma reação com emoji contava como resposta inválida e, sem fluxo aberto, iniciava o menu | O motor ignora reações e tipos não suportados |
| Não havia como enviar uma lista interativa para teste | A tela ganhou "Mensagem com lista", com duas seções |
| O toque num botão de template com um fluxo aberto virava "Não entendi" (rodada anterior) | O botão de template tem prioridade sobre a pergunta aberta |
| Figurinhas `webp` eram gravadas como `.bin` no servidor (rodada anterior) | Tabela própria de extensões |

## Notas para automatizar o WhatsApp Web

- O WhatsApp Web não marca mais a direção da mensagem no `data-id`. A direção vem do "rabicho" do balão (`data-icon="tail-in"` ou `tail-out`) na primeira mensagem de cada sequência; as seguintes herdam a direção. O `data-id` continua único por mensagem e serve de marca para "mensagens novas".
- O status da mensagem enviada aparece no `aria-label` ("Entregue", "Lida").
- Botões de resposta e o botão da lista são `button` com o texto como nome; as opções da lista são `radio` dentro de `[data-testid="confirm-popup"]`, e o botão de enviar da lista só aparece depois de marcar uma opção, sem rótulo.
- Foto: "Anexar" > "Fotos e vídeos" (o primeiro campo de arquivo `image/*` é o de figurinha). Documento: "Anexar" > "Documento".
- O formulário nativo abre num iframe lateral, mais largo que a janela; a caixa de opt-in é marcada clicando no texto dela.
- Reação: botão "Reagir" da própria mensagem e o emoji no seletor.
- Mensagens com o mesmo texto no mesmo minuto (ex.: o menu reenviado) não podem ser comparadas pelo texto.
