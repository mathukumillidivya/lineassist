"""LineAssist: a telecom support agent with a playbook and an escalation guard.

Two layers on top of a plain tool-calling agent:

1. Playbook. The provider's manual, restructured into ordered checklists with a
   verify-before-closing rule (see playbook.py).
2. Escalation guard. Handing a customer to a human is the expensive outcome and, on
   the baseline, the most common way to fail. Before a hand-off goes out, a second
   review call reads the conversation and lists the checklist items that have not been
   examined. If any remain, the hand-off is withheld and the agent is sent back with
   that list. The guard can overrule the agent a limited number of times, so a genuine
   dead end still reaches a human.

3. Line check. An account can hold several lines. Before any tool call that names a
   line, the agent must have seen that the line's number is the number the customer
   gave. This is plain code, not a model call: a call on an unverified or mismatched
   line is withheld and the agent is told which lines are left to look at.

4. Case notes. Facts that follow mechanically from the account data (is this the
   customer's line, has the contract ended, is the data allowance used up) are worked
   out in code and written next to the tool result the agent reads, instead of leaving
   date and number comparisons to the model.

Each layer can be switched on separately so its effect can be measured.
"""
from __future__ import annotations

import json
import re
from typing import Optional

from loguru import logger
from pydantic import BaseModel

from tau2.agent.base.llm_config import LLMConfigMixin
from tau2.agent.base_agent import HalfDuplexAgent, ValidAgentInputMessage
from tau2.data_model.message import (
    APICompatibleMessage, AssistantMessage, Message, MultiToolMessage, SystemMessage, ToolMessage, UserMessage,
)
from tau2.environment.tool import Tool
from tau2.registry import registry
from tau2.utils.llm_utils import generate

from lineassist.playbook import PLAYBOOK

INSTRUCTION = """You are a customer service agent that helps the user according to the <policy> provided below.
In each turn you can either:
- Send a message to the user.
- Make a tool call.
You cannot do both at the same time.
Try to be helpful and always follow the policy. Always make sure you generate valid JSON only."""

SYSTEM = "<instructions>\n{instruction}\n</instructions>\n<policy>\n{policy}\n</policy>"
SYSTEM_WITH_PLAYBOOK = SYSTEM + "\n<playbook>\n{playbook}\n</playbook>"

HANDOFF_WORDS = re.compile(
    r"transfer|escalat|specialist|human agent|technician|higher[- ]level|support team|visit (a|our|the) store|"
    r"unable to (resolve|fix)|beyond what i can", re.I)

REVIEW_SYSTEM = """You are a support supervisor. An agent wants to hand a customer to a human, or is \
telling the customer the problem cannot be fixed on this call. Decide whether that is justified.

<playbook>
{playbook}
</playbook>

Read the conversation. A checklist item counts as examined only if the conversation contains the \
result of its check (from an agent tool, or read out by the customer from their phone). An action the \
customer merely says they did, with no check result afterwards, is not confirmed. The computed facts \
below the conversation are reliable: anything they mark as not identified or not checked is a remaining item.

Reply with JSON only:
{{"allow": true or false,
  "reason": "one sentence",
  "remaining": ["each checklist item not yet examined or not yet confirmed, as an instruction to the agent"]}}

Allow the hand-off only if one of the playbook's transfer conditions is met. Otherwise set allow to \
false and list what remains, most likely cause first."""

BLOCKED = ("Hand-off not approved by the supervisor. {reason}\nBefore this customer can be transferred, "
           "do the following, one at a time, and confirm each result:\n{items}\n"
           "Continue helping the customer now. Do not mention this note or a transfer.")


WRONG_LINE = ("Line check failed: {line} {why} The customer's number is {phone}. Do not act on or quote details "
              "from a line until get_details_by_id shows its phone_number is {phone}.{todo}")
PHONE = re.compile(r"\b\d{3}[-. ]\d{3}[-. ]\d{4}\b")


class State(BaseModel):
    system_messages: list[SystemMessage]
    messages: list[APICompatibleMessage]
    blocks: int = 0
    caller_phone: Optional[str] = None
    line_ids: list[str] = []
    line_phone: dict[str, str] = {}
    line_blocks: int = 0
    usage_checked: bool = False
    facts: dict[str, str] = {}
    notes: list[str] = []
    transferred: bool = False
    reviews: list[dict] = []


def transcript(messages: list) -> str:
    out = []
    for m in messages:
        if isinstance(m, ToolMessage):
            out.append(f"[tool result] {m.content}")
            continue
        who = "AGENT" if isinstance(m, AssistantMessage) else "CUSTOMER"
        if m.content:
            out.append(f"{who}: {m.content}")
        for tc in (getattr(m, "tool_calls", None) or []):
            out.append(f"{who} [tool call] {tc.name}({json.dumps(tc.arguments)})")
    return "\n".join(out)


def parse_review(text: str) -> Optional[dict]:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        v = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(v.get("allow"), bool):
        return None
    v["remaining"] = [str(x) for x in (v.get("remaining") or [])][:8]
    return v


class LineAssistAgent(LLMConfigMixin, HalfDuplexAgent[State]):
    def __init__(self, tools: list[Tool], domain_policy: str, llm: str, llm_args: Optional[dict] = None,
                 playbook: bool = True, guard: bool = True, line_check: bool = True, case_notes: bool = True,
                 max_blocks: int = 3):
        super().__init__(tools=tools, domain_policy=domain_policy, llm=llm, llm_args=llm_args)
        self.use_playbook, self.use_guard, self.max_blocks = playbook, guard, max_blocks
        self.use_line_check, self.use_case_notes = line_check, case_notes
        m = re.search(r"current time is (\d{4}-\d{2}-\d{2})", domain_policy)
        self.today = m.group(1) if m else None

    @property
    def system_prompt(self) -> str:
        if self.use_playbook:
            return SYSTEM_WITH_PLAYBOOK.format(instruction=INSTRUCTION, policy=self.domain_policy, playbook=PLAYBOOK)
        return SYSTEM.format(instruction=INSTRUCTION, policy=self.domain_policy)

    def get_init_state(self, message_history: Optional[list[Message]] = None) -> State:
        return State(system_messages=[SystemMessage(role="system", content=self.system_prompt)],
                     messages=list(message_history or []))

    def _call(self, state: State) -> AssistantMessage:
        return generate(model=self.llm, tools=self.tools, messages=state.system_messages + state.messages,
                        call_name="agent_response", **self.llm_args)

    # ---- line check -------------------------------------------------------------------------
    def _observe(self, state: State, incoming: list) -> list:
        """Record which phone number the customer gave and which number each line has.

        Returns the messages to store in the agent's own history. Tool results that get a
        case note are copied first, so the benchmark's record of the conversation is untouched."""
        incoming = list(incoming)
        calls = {}
        for m in reversed(state.messages):
            if isinstance(m, AssistantMessage) and m.tool_calls:
                calls = {tc.id: tc for tc in m.tool_calls}
                break
        for i, m in enumerate(incoming):
            if isinstance(m, UserMessage) and m.content and state.caller_phone is None:
                found = PHONE.findall(m.content)
                if found:
                    state.caller_phone = re.sub(r"[. ]", "-", found[-1])
            if not isinstance(m, ToolMessage) or m.error:
                continue
            tc = calls.get(m.id)
            if tc is not None and tc.name == "get_customer_by_phone":
                state.caller_phone = str(tc.arguments.get("phone_number"))
            try:
                data = json.loads(m.content or "")
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(data, dict):
                continue
            if isinstance(data.get("line_ids"), list):
                state.line_ids = [str(x) for x in data["line_ids"]]
            if data.get("line_id") and data.get("phone_number"):
                state.line_phone[str(data["line_id"])] = str(data["phone_number"])
            note = self._case_note(state, data) if self.use_case_notes else None
            if note:
                incoming[i] = m.model_copy(update={"content": f"{m.content}\n[case note] {note}"})
        return incoming

    def _case_note(self, state: State, data: dict) -> Optional[str]:
        """Facts that follow mechanically from a tool result."""
        phone = state.caller_phone
        if data.get("line_id") and data.get("phone_number") and phone:
            if str(data["phone_number"]) != phone:
                return f"This is NOT the customer's line. The customer's number is {phone}. Ignore these details."
            parts = [f"This IS the customer's line ({phone})."]
            status, end = str(data.get("status", "")), str(data.get("contract_end_date") or "")
            ended = bool(self.today and end and end < self.today)
            if status.lower() == "suspended":
                parts.append(f"The line is suspended. Its contract ended on {end}, before today ({self.today}): it must not "
                             "be resumed, and the customer has to be transferred once the phone itself has been checked."
                             if ended else
                             "The line is suspended and its contract is still running: look for an overdue bill.")
            parts.append("Roaming is enabled on the line." if data.get("roaming_enabled")
                         else "Roaming is NOT enabled on the line: enable it if the customer is abroad.")
            if not state.usage_checked:
                parts.append("Data allowance not checked yet: call get_data_usage for this line.")
            state.facts["line"] = " ".join(parts)
            return state.facts["line"]
        if data.get("line_id") and "data_limit_gb" in data and "data_used_gb" in data:
            if state.line_phone.get(str(data["line_id"])) != phone:
                return None
            try:
                used, limit = float(data["data_used_gb"]), float(data["data_limit_gb"])
                extra = float(data.get("data_refueling_gb") or 0)
            except (TypeError, ValueError):
                return None
            state.usage_checked = True
            if used >= limit + extra:
                note = (f"Data allowance used up: {used:g} GB used against {limit + extra:g} GB available. Mobile data "
                        "will not work until the customer refuels data or changes plan. Ask how much they want to "
                        "refuel, confirm the price, then apply exactly that amount.")
            else:
                note = f"Data allowance is fine: {used:g} GB used of {limit + extra:g} GB available."
            state.facts["data"] = note
            return note
        return None

    def _wrong_line(self, state: State, reply: AssistantMessage) -> Optional[str]:
        if state.caller_phone is None:
            return None
        for tc in (reply.tool_calls or []):
            line = tc.arguments.get("line_id")
            if not line:
                continue
            seen = state.line_phone.get(str(line))
            if seen == state.caller_phone:
                continue
            why = f"has the number {seen}." if seen else "has not been looked up yet."
            left = [x for x in state.line_ids if x not in state.line_phone]
            match = [k for k, v in state.line_phone.items() if v == state.caller_phone]
            todo = (f" The matching line is {match[0]}." if match else
                    f" Lines not yet looked up: {', '.join(left)}." if left else "")
            return WRONG_LINE.format(line=line, why=why, phone=state.caller_phone, todo=todo)
        return None

    def _facts(self, state: State) -> str:
        lines = [f"Customer's number: {state.caller_phone or 'not known'}",
                 state.facts.get("line", "The customer's line has NOT been identified yet."),
                 state.facts.get("data", "Data allowance has NOT been checked (get_data_usage on the customer's line).")]
        return "\n".join(lines)

    def _is_handoff(self, msg: AssistantMessage) -> bool:
        if any(tc.name == "transfer_to_human_agents" for tc in (msg.tool_calls or [])):
            return True
        return bool(msg.content and HANDOFF_WORDS.search(msg.content))

    def _review(self, state: State, draft: AssistantMessage) -> tuple[Optional[dict], float]:
        convo = transcript(state.messages + [draft])
        args = {k: v for k, v in self.llm_args.items() if k != "cache_control_injection_points"}
        reply = generate(model=self.llm, call_name="handoff_review", messages=[
            SystemMessage(role="system", content=REVIEW_SYSTEM.format(playbook=PLAYBOOK)),
            UserMessage(role="user", content=f"<conversation>\n{convo}\n</conversation>\n\n"
                                              f"<computed_facts>\n{self._facts(state)}\n</computed_facts>\n\n"
                                              "Is the hand-off justified?"),
        ], **args)
        return parse_review(reply.content), reply.cost or 0.0

    def generate_next_message(self, message: ValidAgentInputMessage, state: State) -> tuple[AssistantMessage, State]:
        incoming = message.tool_messages if isinstance(message, MultiToolMessage) else [message]
        state.messages.extend(self._observe(state, incoming))

        reply = self._call(state)
        hidden_cost = 0.0
        while self.use_line_check and state.line_blocks < 4:
            problem = self._wrong_line(state, reply)
            if problem is None:
                break
            state.line_blocks += 1
            hidden_cost += reply.cost or 0.0
            logger.info(f"[line check] call withheld: {problem}")
            state.messages.append(reply)
            for tc in reply.tool_calls:
                state.messages.append(ToolMessage(id=tc.id, role="tool", requestor="assistant", content=problem))
            reply = self._call(state)
        while (self.use_guard and not state.transferred and state.blocks < self.max_blocks
               and len(state.reviews) < 2 * self.max_blocks and self._is_handoff(reply)):
            verdict, cost = self._review(state, reply)
            hidden_cost += cost
            state.reviews.append({"turn": len(state.messages), "verdict": verdict})
            if verdict is None or verdict["allow"] or not verdict["remaining"]:
                break                                   # fail open: an unreadable review never traps a customer
            state.blocks += 1
            hidden_cost += reply.cost or 0.0
            note = BLOCKED.format(reason=verdict.get("reason", ""),
                                  items="\n".join(f"- {x}" for x in verdict["remaining"]))
            logger.info(f"[guard] hand-off withheld ({state.blocks}/{self.max_blocks}): {verdict['remaining']}")
            # The withheld draft and the note live only in the agent's private history.
            if reply.tool_calls:
                state.messages.append(reply)
                for tc in reply.tool_calls:
                    state.messages.append(ToolMessage(id=tc.id, role="tool", requestor="assistant", content=note))
            else:
                # The draft is discarded and the note is added to the agent's instructions.
                state.notes.append(note)
                state.system_messages = state.system_messages[:1] + [SystemMessage(
                    role="system", content="<supervisor_notes>\n" + "\n\n".join(state.notes) + "\n</supervisor_notes>")]
            reply = self._call(state)

        if any(tc.name == "transfer_to_human_agents" for tc in (reply.tool_calls or [])):
            state.transferred = True
        if hidden_cost:
            reply.cost = (reply.cost or 0.0) + hidden_cost     # review calls are part of what the agent costs
        state.messages.append(reply)
        return reply, state


def _factory(**fixed):
    def make(tools, domain_policy, llm=None, llm_args=None, **_):
        return LineAssistAgent(tools=tools, domain_policy=domain_policy, llm=llm, llm_args=llm_args, **fixed)
    return make


registry.register_agent_factory(_factory(), "lineassist")
registry.register_agent_factory(_factory(guard=False, line_check=False, case_notes=False), "lineassist_playbook")
registry.register_agent_factory(_factory(guard=False), "lineassist_no_guard")
registry.register_agent_factory(_factory(case_notes=False), "lineassist_no_case_notes")
registry.register_agent_factory(_factory(playbook=False), "lineassist_no_playbook")
