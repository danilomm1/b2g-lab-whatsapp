"""Fluxos da Brave2Grow no WhatsApp.

boas_vindas: primeiro contato com aviso de privacidade (CLAUDE.md, seção 13), menu e três
caminhos: conhecer serviços (com opt-in de novidades), pedir agendamento (email e
período) e falar com o Danilo (handoff). O agendamento de verdade, com Google Calendar,
é o F01 da Fase 10; aqui o pedido vira evento e etiqueta para o Danilo agir.
"""

from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_email

from apps.core.models import (
    Channel,
    ConsentPurpose,
    Contact,
    Event,
    Message,
    Tag,
)
from apps.core.services import grant_consent, record_event

from .. import payloads
from ..payloads import OutboundPayload
from .engine import (
    QUICK_REPLY_HANDLERS,
    Ask,
    Branch,
    Call,
    End,
    Flow,
    FlowContext,
    Handoff,
    Option,
    Say,
    register,
)

PRIVACY_EVENT = "privacy.notice_shown"
LEAD_TAG = "lead-whatsapp"
NEWS_QUESTION = (
    "Quer receber novidades e conteúdos da Brave2Grow por aqui? "
    "Você pode cancelar quando quiser enviando SAIR."
)
PERIODS = {"manha": "manhã", "tarde": "tarde", "noite": "noite"}


def welcome(ctx: FlowContext) -> str:
    """Saudação; no primeiro contato, inclui o aviso de privacidade e registra que foi dado."""
    name = ctx.first_name()
    text = f"Olá{', ' + name if name else ''}! Aqui é o assistente automático da Brave2Grow."
    already_shown = Event.objects.filter(
        contact=ctx.contact, channel=Channel.WHATSAPP, event_type=PRIVACY_EVENT
    ).exists()
    if not already_shown:
        notice = (
            "Para personalizar seu atendimento, a Brave2Grow conecta as suas interações "
            "nos nossos canais."
        )
        if settings.PRIVACY_POLICY_URL:
            notice += f" Política de privacidade: {settings.PRIVACY_POLICY_URL}"
        text += f"\n\n{notice}\nPara não receber mais mensagens, envie SAIR a qualquer momento."
        record_event(
            PRIVACY_EVENT,
            contact=ctx.contact,
            channel=Channel.WHATSAPP,
            external_id=f"whatsapp-{ctx.contact.pk}",
            summary="Aviso de privacidade no primeiro contato pelo WhatsApp",
        )
    return text


def parse_email(text: str) -> str | None:
    candidate = text.strip().lower()
    try:
        validate_email(candidate)
    except ValidationError:
        return None
    return candidate


def grant_news_consent(ctx: FlowContext) -> bool:
    """Registra o opt-in de marketing no WhatsApp com o texto aceito e a mensagem como prova."""
    grant_consent(
        ctx.contact,
        Channel.WHATSAPP,
        ConsentPurpose.MARKETING,
        source="whatsapp_flow",
        consent_text=f"{NEWS_QUESTION} Resposta: Quero receber.",
        evidence={
            "flow": ctx.flow.key,
            "run_id": ctx.run.pk,
            "message_id": ctx.message.external_id if ctx.message else "",
        },
    )
    return True


def save_email(ctx: FlowContext) -> bool:
    """Grava o email no contato se ele ainda não tem um e nenhum outro contato o usa."""
    email = ctx.answers.get("email", "")
    contact = ctx.contact
    if not email or contact.email:
        return False
    if Contact.objects.filter(email=email).exclude(pk=contact.pk).exists():
        return False
    contact.email = email
    contact.save()
    return True


def register_scheduling_request(ctx: FlowContext) -> str:
    """Registra o pedido de agendamento para o Danilo (o F01 automatiza na Fase 10)."""
    period = PERIODS.get(ctx.answers.get("periodo", ""), "")
    tag, _ = Tag.objects.get_or_create(name=LEAD_TAG)
    ctx.contact.tags.add(tag)
    record_event(
        "lead.scheduling_requested",
        contact=ctx.contact,
        channel=Channel.WHATSAPP,
        summary=f"Pedido de conversa pelo WhatsApp, período: {period or 'não informado'}",
        data={"answers": ctx.answers, "run_id": ctx.run.pk},
    )
    return period


def scheduling_done(ctx: FlowContext) -> str:
    period = PERIODS.get(ctx.answers.get("periodo", ""), "")
    when = f" para o período da {period}" if period else ""
    return f"Anotado! O Danilo vai te enviar opções de horário{when}. Obrigado pelo contato!"


BOAS_VINDAS = register(
    Flow(
        "boas_vindas",
        "Boas-vindas e qualificação",
        start="saudacao",
        nodes=[
            Say("saudacao", welcome, next="menu"),
            Ask(
                "menu",
                "Como posso te ajudar?",
                save_as="interesse",
                options=[
                    Option("servicos", "Conhecer serviços", "servicos"),
                    Option("agendar", "Agendar conversa", "tem_email"),
                    Option("danilo", "Falar com o Danilo", "handoff"),
                ],
                on_fail="handoff",
            ),
            Say(
                "servicos",
                "A Brave2Grow ajuda empresas a crescer com estratégia digital, conteúdo e "
                "automação de relacionamento. Veja mais em https://brave2grow.com",
                next="novidades",
            ),
            Ask(
                "novidades",
                NEWS_QUESTION,
                save_as="quer_novidades",
                options=[
                    Option("sim", "Quero receber", "registrar_consentimento"),
                    Option("nao", "Agora não", "fim_sem_novidades"),
                ],
                on_fail="fim_sem_novidades",
            ),
            Call(
                "registrar_consentimento",
                grant_news_consent,
                next="fim_novidades",
                on_error="handoff",
            ),
            End(
                "fim_novidades",
                "Combinado! Você vai receber nossas novidades por aqui. "
                "Para voltar ao início, envie MENU.",
            ),
            End("fim_sem_novidades", "Sem problemas! Se precisar de algo, é só enviar MENU."),
            Branch(
                "tem_email",
                lambda ctx: bool(ctx.contact.email),
                if_true="periodo",
                if_false="pedir_email",
            ),
            Ask(
                "pedir_email",
                "Qual é o seu melhor email? Vamos usá-lo para enviar o convite da conversa.",
                save_as="email",
                parse=parse_email,
                retry="Não reconheci esse email. Pode enviar de novo? Exemplo: nome@empresa.com",
                next="salvar_email",
                on_fail="periodo",
            ),
            Call("salvar_email", save_email, next="periodo", on_error="periodo"),
            Ask(
                "periodo",
                "Qual período é melhor para uma conversa de 30 minutos com o Danilo?",
                save_as="periodo",
                options=[
                    Option("manha", "Manhã", "registrar_pedido"),
                    Option("tarde", "Tarde", "registrar_pedido"),
                    Option("noite", "Noite", "registrar_pedido"),
                ],
                on_fail="handoff",
            ),
            Call(
                "registrar_pedido",
                register_scheduling_request,
                next="fim_agendar",
                on_error="handoff",
            ),
            End("fim_agendar", scheduling_done),
            Handoff(
                "handoff",
                "Certo! Vou avisar o Danilo, e ele continua a conversa por aqui assim que puder. "
                "Para voltar ao menu automático, envie MENU.",
                reason="Contato pediu para falar com o Danilo",
            ),
        ],
    )
)


def _meeting_reply(message: Message, outbox: list[OutboundPayload]) -> str | None:
    """Botões do template b2g_confirmacao_reuniao (base do F02, Fase 10)."""
    answer = str((message.raw_payload or {}).get("reply_id", "")).removeprefix("reuniao_")
    record_event(
        "meeting.response",
        contact=message.conversation.contact,
        channel=Channel.WHATSAPP,
        external_id=message.external_id,
        summary=f"Resposta à confirmação de reunião: {answer}",
        data={"answer": answer},
    )
    texts = {
        "confirmar": "Presença confirmada. Até lá!",
        "reagendar": "Sem problemas! O Danilo vai te enviar novas opções de horário.",
        "cancelar": "Reunião cancelada. Se quiser remarcar, é só enviar MENU.",
    }
    outbox.append(payloads.text(texts.get(answer, "Recebido, obrigado!")))
    return None


def _resume_yes(message: Message, outbox: list[OutboundPayload]) -> str | None:
    return BOAS_VINDAS.key


def _resume_no(message: Message, outbox: list[OutboundPayload]) -> str | None:
    outbox.append(payloads.text("Tudo bem! Quando quiser retomar, é só enviar MENU."))
    return None


QUICK_REPLY_HANDLERS.update(
    {
        "retomar_sim": _resume_yes,
        "retomar_nao": _resume_no,
        "reuniao_confirmar": _meeting_reply,
        "reuniao_reagendar": _meeting_reply,
        "reuniao_cancelar": _meeting_reply,
    }
)
