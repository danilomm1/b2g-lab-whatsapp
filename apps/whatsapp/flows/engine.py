"""Motor de fluxo conversacional do WhatsApp (ADR 0007).

Um fluxo é um grafo de nós definido em código: mensagem (Say), pergunta (Ask), condição
(Branch), chamada de API ou serviço (Call), passagem para humano (Handoff) e fim (End).
FlowRun guarda o nó atual e as respostas de cada conversa.

O motor roda dentro da transação do webhook e só decide o que dizer: as mensagens vão
para uma caixa de saída enviada pela tarefa send_outbox depois do commit. Assim um envio
real nunca fica atrelado a um registro que ainda pode ser desfeito.
"""

from __future__ import annotations

import logging
import unicodedata
from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import timedelta
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.core.models import Contact, Conversation, ConversationStatus, Message
from apps.core.safety import is_opt_out_message
from apps.core.services import record_event

from .. import payloads
from ..models import FlowRun, FlowRunStatus
from ..payloads import ListRow, ListSection, OutboundPayload

logger = logging.getLogger(__name__)

RUN_TTL = timedelta(hours=24)  # pergunta sem resposta há mais tempo: a execução expira
RESTART_COOLDOWN = timedelta(hours=12)  # depois de concluir, só recomeça sozinho após 12h
MAX_STEPS = 50  # trava contra ciclos no grafo
MENU_KEYWORDS = frozenset({"MENU", "INICIO", "COMECAR"})
OPT_OUT_CONFIRMATION = (
    "Pronto, você não vai mais receber mensagens da Brave2Grow por aqui. "
    "Se mudar de ideia, é só mandar uma mensagem."
)
_OPEN = (FlowRunStatus.ACTIVE, FlowRunStatus.HANDOFF)


def normalize(text: str) -> str:
    """Maiúsculas, sem acento e sem pontuação, para comparar respostas digitadas."""
    decomposed = unicodedata.normalize("NFKD", text)
    kept = "".join(ch for ch in decomposed if ch.isalnum() or ch.isspace())
    return " ".join(kept.upper().split())


@dataclass
class FlowContext:
    """O que um nó enxerga: a execução, a mensagem recebida e a caixa de saída."""

    run: FlowRun
    flow: Flow
    message: Message | None = None
    outbox: list[OutboundPayload] = field(default_factory=list)
    # Avisos para outras conversas (ex.: o Danilo no handoff), enviados depois da resposta
    notices: list[tuple[Conversation, OutboundPayload]] = field(default_factory=list)

    @property
    def contact(self) -> Contact:
        return self.run.contact

    @property
    def conversation(self) -> Conversation:
        return self.run.conversation

    @property
    def answers(self) -> dict[str, Any]:
        return self.run.state.setdefault("answers", {})

    def first_name(self) -> str:
        return (self.contact.name or "").split(" ")[0]

    def say(self, source: PayloadSource) -> None:
        payload = source(self) if callable(source) else source
        if isinstance(payload, str):
            payload = payloads.text(payload)
        self.outbox.append(payload)


TextSource = str | Callable[[FlowContext], str]
PayloadSource = str | OutboundPayload | Callable[[FlowContext], "str | OutboundPayload"]


def _text(source: TextSource, ctx: FlowContext) -> str:
    return source(ctx) if callable(source) else source


class Node:
    """Base dos nós. enter devolve o próximo nó, ou None para parar e esperar."""

    def __init__(self, node_id: str) -> None:
        self.id = node_id

    def enter(self, ctx: FlowContext) -> str | None:
        raise NotImplementedError

    def targets(self) -> Iterable[str]:
        return ()


class Waiting(Node):
    """Nó que para e espera a próxima mensagem do contato (pergunta ou formulário)."""

    def receive(self, ctx: FlowContext, message: Message) -> str | None:
        """Interpreta a resposta; devolve o próximo nó ou None para continuar esperando."""
        raise NotImplementedError


class Say(Node):
    """Envia uma mensagem e segue."""

    def __init__(self, node_id: str, message: PayloadSource, *, next: str) -> None:
        super().__init__(node_id)
        self.message = message
        self.next = next

    def enter(self, ctx: FlowContext) -> str | None:
        ctx.say(self.message)
        return self.next

    def targets(self) -> Iterable[str]:
        return (self.next,)


@dataclass(frozen=True)
class Option:
    id: str
    title: str
    next: str
    description: str = ""


class Ask(Waiting):
    """Pergunta e espera a resposta: por opções (botões ou lista) ou texto livre validado.

    Opções viram botões (até 3) ou lista (até 10). O ID enviado leva o nó como prefixo,
    para que um botão antigo tocado fora de hora não seja aceito como resposta. Também
    valem o título digitado e o número da opção. Depois de max_attempts respostas
    inválidas, segue para on_fail.
    """

    def __init__(
        self,
        node_id: str,
        text: TextSource,
        *,
        save_as: str,
        options: Sequence[Option] = (),
        parse: Callable[[str], Any] | None = None,
        next: str | None = None,
        retry: str = "Não entendi. Pode escolher uma das opções?",
        max_attempts: int = 2,
        on_fail: str,
        list_button: str = "Ver opções",
    ) -> None:
        super().__init__(node_id)
        if bool(options) == bool(parse):
            raise ValueError(f"{node_id}: use opções ou parse, não os dois")
        if parse and not next:
            raise ValueError(f"{node_id}: pergunta de texto precisa de next")
        self.text = text
        self.save_as = save_as
        self.options = tuple(options)
        self.parse = parse
        self.next = next
        self.retry = retry
        self.max_attempts = max_attempts
        self.on_fail = on_fail
        self.list_button = list_button

    def reply_id(self, option: Option) -> str:
        return f"{self.id}:{option.id}"

    def prompt(self, ctx: FlowContext) -> OutboundPayload:
        text = _text(self.text, ctx)
        if not self.options:
            return payloads.text(text)
        if len(self.options) <= payloads.MAX_BUTTONS:
            return payloads.buttons(text, [(self.reply_id(o), o.title) for o in self.options])
        rows = [ListRow(self.reply_id(o), o.title, o.description) for o in self.options]
        return payloads.list_message(text, self.list_button, [ListSection("", rows)])

    def enter(self, ctx: FlowContext) -> str | None:
        ctx.say(self.prompt(ctx))
        return None

    def _match(self, message: Message) -> tuple[bool, Any, str | None]:
        payload = message.raw_payload if isinstance(message.raw_payload, dict) else {}
        if self.options:
            reply_id = str(payload.get("reply_id", ""))
            typed = normalize(message.body)
            for position, option in enumerate(self.options, start=1):
                if reply_id == self.reply_id(option) or (
                    not reply_id and typed in {normalize(option.title), str(position)}
                ):
                    return True, option.id, option.next
            return False, None, None
        value = self.parse(message.body) if message.kind == "text" else None
        return value is not None, value, self.next

    def receive(self, ctx: FlowContext, message: Message) -> str | None:
        matched, value, next_node = self._match(message)
        if matched:
            ctx.answers[self.save_as] = value
            return next_node
        ctx.run.attempts += 1
        if ctx.run.attempts >= self.max_attempts:
            return self.on_fail
        ctx.say(self.retry)
        if self.options:
            ctx.say(self.prompt(ctx))
        return None

    def targets(self) -> Iterable[str]:
        return [o.next for o in self.options] + [t for t in (self.next, self.on_fail) if t]


class Form(Waiting):
    """Abre um WhatsApp Flow (formulário nativo) e espera o envio, que volta como nfm_reply.

    O flow_token liga a resposta à execução e ao nó. Se o formulário não existe na Meta,
    segue para unavailable. Uma mensagem que não é o envio do formulário conta como
    tentativa e reenvia o convite; depois de max_attempts, segue para on_fail.
    """

    def __init__(
        self,
        node_id: str,
        form_name: str,
        text: TextSource,
        *,
        cta: str,
        save_as: str,
        next: str,
        on_fail: str,
        unavailable: str,
        retry: str = "Para continuar, toque no botão abaixo e preencha o formulário.",
        max_attempts: int = 2,
    ) -> None:
        super().__init__(node_id)
        self.form_name = form_name
        self.text = text
        self.cta = cta
        self.save_as = save_as
        self.next = next
        self.on_fail = on_fail
        self.unavailable = unavailable
        self.retry = retry
        self.max_attempts = max_attempts

    def token(self, ctx: FlowContext) -> str:
        return f"{ctx.run.pk}:{self.id}"

    def enter(self, ctx: FlowContext) -> str | None:
        from ..forms_catalog import get_form
        from ..models import WhatsAppForm

        stored = WhatsAppForm.objects.filter(name=self.form_name).exclude(meta_id="").first()
        if stored is None or stored.status not in {"PUBLISHED", "DRAFT"}:
            logger.warning("Formulário %s indisponível na Meta", self.form_name)
            return self.unavailable
        ctx.say(
            payloads.form(
                _text(self.text, ctx),
                self.cta,
                flow_id=stored.meta_id,
                token=self.token(ctx),
                screen=get_form(self.form_name).first_screen,
                mode=stored.send_mode,
            )
        )
        return None

    def receive(self, ctx: FlowContext, message: Message) -> str | None:
        payload = message.raw_payload if isinstance(message.raw_payload, dict) else {}
        response = payload.get("form_response") or {}
        if response.get("flow_token") == self.token(ctx):
            ctx.answers[self.save_as] = {k: v for k, v in response.items() if k != "flow_token"}
            return self.next
        ctx.run.attempts += 1
        if ctx.run.attempts >= self.max_attempts:
            return self.on_fail
        ctx.say(self.retry)
        return self.enter(ctx)

    def targets(self) -> Iterable[str]:
        return (self.next, self.on_fail, self.unavailable)


class Branch(Node):
    """Condição: segue para if_true ou if_false."""

    def __init__(
        self,
        node_id: str,
        predicate: Callable[[FlowContext], bool],
        *,
        if_true: str,
        if_false: str,
    ) -> None:
        super().__init__(node_id)
        self.predicate = predicate
        self.if_true = if_true
        self.if_false = if_false

    def enter(self, ctx: FlowContext) -> str | None:
        return self.if_true if self.predicate(ctx) else self.if_false

    def targets(self) -> Iterable[str]:
        return (self.if_true, self.if_false)


class Call(Node):
    """Chama um serviço interno ou uma API externa; o resultado pode virar resposta salva.

    A chamada roda num savepoint: se falhar, o que ela gravou é desfeito, o erro vira
    evento e o fluxo segue para on_error.
    """

    def __init__(
        self,
        node_id: str,
        action: Callable[[FlowContext], Any],
        *,
        next: str,
        on_error: str,
        save_as: str = "",
    ) -> None:
        super().__init__(node_id)
        self.action = action
        self.next = next
        self.on_error = on_error
        self.save_as = save_as

    def enter(self, ctx: FlowContext) -> str | None:
        try:
            with transaction.atomic():
                result = self.action(ctx)
        except Exception as exc:
            logger.exception("Falha no nó %s do fluxo %s", self.id, ctx.flow.key)
            record_event(
                "whatsapp.flow_error",
                contact=ctx.contact,
                channel="whatsapp",
                summary=f"{ctx.flow.key}/{self.id}: {exc}"[:255],
                data={"run_id": ctx.run.pk, "node": self.id},
            )
            return self.on_error
        if self.save_as:
            ctx.answers[self.save_as] = result
        return self.next

    def targets(self) -> Iterable[str]:
        return (self.next, self.on_error)


class Handoff(Node):
    """Passa a conversa para um humano: o fluxo para até alguém devolver ou o contato pedir MENU."""

    def __init__(self, node_id: str, message: PayloadSource, *, reason: str = "") -> None:
        super().__init__(node_id)
        self.message = message
        self.reason = reason

    def enter(self, ctx: FlowContext) -> str | None:
        from ..services import owner_notifications

        ctx.say(self.message)
        ctx.run.status = FlowRunStatus.HANDOFF
        conversation = ctx.conversation
        conversation.status = ConversationStatus.HANDOFF
        conversation.save(update_fields=["status", "updated_at"])
        record_event(
            "whatsapp.handoff",
            contact=ctx.contact,
            channel="whatsapp",
            summary=self.reason or f"Pedido de atendimento humano ({ctx.flow.key})",
            data={"run_id": ctx.run.pk, "answers": ctx.answers},
        )
        ctx.notices.extend(
            owner_notifications(
                ctx.contact, self.reason or "pedido de atendimento humano", ctx.answers
            )
        )
        return None


class End(Node):
    """Encerra o fluxo, com uma mensagem final opcional."""

    def __init__(self, node_id: str, message: PayloadSource | None = None) -> None:
        super().__init__(node_id)
        self.message = message

    def enter(self, ctx: FlowContext) -> str | None:
        if self.message:
            ctx.say(self.message)
        ctx.run.finish(FlowRunStatus.COMPLETED)
        return None


class Flow:
    """Grafo de nós com um nó inicial; os destinos são conferidos na criação."""

    def __init__(self, key: str, name: str, start: str, nodes: Sequence[Node]) -> None:
        self.key = key
        self.name = name
        self.start = start
        self.nodes = {node.id: node for node in nodes}
        if len(self.nodes) != len(nodes):
            raise ValueError(f"Fluxo {key}: IDs de nó repetidos")
        missing = {t for node in nodes for t in node.targets() if t not in self.nodes}
        if start not in self.nodes:
            missing.add(start)
        if missing:
            raise ValueError(f"Fluxo {key}: nós inexistentes {sorted(missing)}")


FLOWS: dict[str, Flow] = {}
QuickReplyHandler = Callable[[Message, list[OutboundPayload]], "str | None"]
# Respostas a botões de template (fora de fluxo). O handler pode responder na caixa de
# saída e devolver a chave de um fluxo para iniciar.
QUICK_REPLY_HANDLERS: dict[str, QuickReplyHandler] = {}
# Palavras (normalizadas) que iniciam um fluxo específico, ex.: CADASTRO
KEYWORD_FLOWS: dict[str, str] = {}
DEFAULT_FLOW = "boas_vindas"


def register(flow: Flow) -> Flow:
    FLOWS[flow.key] = flow
    return flow


def _advance(ctx: FlowContext, node_id: str | None) -> None:
    steps = 0
    while node_id:
        steps += 1
        if steps > MAX_STEPS:
            logger.error("Fluxo %s passou de %d passos; encerrado", ctx.flow.key, MAX_STEPS)
            ctx.run.finish(FlowRunStatus.CANCELLED)
            return
        node = ctx.flow.nodes[node_id]
        ctx.run.node = node_id
        ctx.run.attempts = 0
        node_id = node.enter(ctx)


def start_flow(
    conversation: Conversation,
    key: str = DEFAULT_FLOW,
    *,
    message: Message | None = None,
    node: str | None = None,
    outbox: list[OutboundPayload] | None = None,
    notices: list[tuple[Conversation, OutboundPayload]] | None = None,
) -> FlowContext:
    """Cria a execução e anda até o primeiro ponto de espera."""
    flow = FLOWS[key]
    run = FlowRun.objects.create(
        conversation=conversation,
        contact=conversation.contact,
        flow_key=key,
        node=node or flow.start,
        state={"answers": {}},
    )
    ctx = FlowContext(
        run=run,
        flow=flow,
        message=message,
        outbox=outbox if outbox is not None else [],
        notices=notices if notices is not None else [],
    )
    _advance(ctx, node or flow.start)
    run.save()
    return ctx


def open_run(conversation: Conversation) -> FlowRun | None:
    return (
        FlowRun.objects.select_related("contact", "conversation")
        .filter(conversation=conversation, status__in=_OPEN)
        .first()
    )


def _close(run: FlowRun, status: str) -> None:
    run.finish(status)
    run.save()
    conversation = run.conversation
    if conversation.status == ConversationStatus.HANDOFF:
        conversation.status = ConversationStatus.OPEN
        conversation.save(update_fields=["status", "updated_at"])


def release_handoff(conversation: Conversation) -> bool:
    """Devolve a conversa ao assistente: encerra a execução com humano. Retorna se havia uma."""
    run = open_run(conversation)
    if run is None or run.status != FlowRunStatus.HANDOFF:
        if conversation.status == ConversationStatus.HANDOFF:
            conversation.status = ConversationStatus.OPEN
            conversation.save(update_fields=["status", "updated_at"])
        return False
    _close(run, FlowRunStatus.COMPLETED)
    return True


def _may_auto_start(conversation: Conversation) -> bool:
    """Evita recomeçar o fluxo a cada "obrigado" logo depois de concluir."""
    last = (
        FlowRun.objects.filter(conversation=conversation, status=FlowRunStatus.COMPLETED)
        .order_by("-finished_at")
        .first()
    )
    return (
        last is None
        or last.finished_at is None
        or (timezone.now() - last.finished_at >= RESTART_COOLDOWN)
    )


def handle_inbound(message: Message) -> list[OutboundPayload]:
    """Decide a resposta a uma mensagem recebida e agenda o envio para depois do commit."""
    conversation = message.conversation
    outbox: list[OutboundPayload] = []
    notices: list[tuple[Conversation, OutboundPayload]] = []
    run = open_run(conversation)
    typed = normalize(message.body)
    keyword_flow = KEYWORD_FLOWS.get(typed) if message.kind == "text" else None

    def start(key: str = DEFAULT_FLOW, **kwargs: Any) -> None:
        start_flow(conversation, key, message=message, outbox=outbox, notices=notices, **kwargs)

    if message.kind in {"text", "button", "interactive"} and is_opt_out_message(message.body):
        if run:
            _close(run, FlowRunStatus.CANCELLED)
        outbox.append(payloads.text(OPT_OUT_CONFIRMATION))
    elif message.kind == "text" and (typed in MENU_KEYWORDS or keyword_flow):
        if run:
            _close(run, FlowRunStatus.CANCELLED)
        start(keyword_flow or DEFAULT_FLOW)
    elif run and run.status == FlowRunStatus.HANDOFF:
        pass  # um humano está atendendo
    elif run and timezone.now() - run.updated_at > RUN_TTL:
        _close(run, FlowRunStatus.EXPIRED)
        start()
    elif run:
        flow = FLOWS.get(run.flow_key)
        node = flow.nodes.get(run.node) if flow else None
        if not isinstance(node, Waiting):
            logger.warning("Execução %s parada num nó que não espera resposta", run.pk)
            _close(run, FlowRunStatus.CANCELLED)
        else:
            ctx = FlowContext(run=run, flow=flow, message=message, outbox=outbox, notices=notices)
            _advance(ctx, node.receive(ctx, message))
            run.save()
    else:
        reply_id = str((message.raw_payload or {}).get("reply_id", ""))
        handler = QUICK_REPLY_HANDLERS.get(reply_id) if message.kind == "button" else None
        if handler:
            key = handler(message, outbox)
            if key:
                start(key)
        elif _may_auto_start(conversation):
            start()

    if outbox:
        schedule_outbox(conversation, outbox, reply_to=message)
    for notice_conversation, notice in notices:
        schedule_outbox(notice_conversation, [notice], reply_to=None)
    return outbox


def start_by_agent(conversation: Conversation, key: str) -> list[OutboundPayload]:
    """Inicia um fluxo a pedido de quem atende (tela de conversa), encerrando o que houver."""
    run = open_run(conversation)
    if run:
        _close(run, FlowRunStatus.CANCELLED)
    outbox: list[OutboundPayload] = []
    notices: list[tuple[Conversation, OutboundPayload]] = []
    start_flow(conversation, key, outbox=outbox, notices=notices)
    if outbox:
        schedule_outbox(conversation, outbox, reply_to=None)
    for notice_conversation, notice in notices:
        schedule_outbox(notice_conversation, [notice], reply_to=None)
    return outbox


def schedule_outbox(
    conversation: Conversation, outbox: list[OutboundPayload], *, reply_to: Message | None
) -> None:
    """Agenda o envio (tarefa Huey) para depois do commit da transação atual."""
    from ..tasks import send_outbox

    items = [asdict(item) for item in outbox]
    reply_to_id = reply_to.pk if reply_to else None
    transaction.on_commit(lambda: send_outbox(conversation.pk, items, reply_to_id))
