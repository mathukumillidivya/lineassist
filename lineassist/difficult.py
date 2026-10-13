"""Difficult customers: benchmark tasks re-run with a customer who is harder to help.

The benchmark's simulated customers follow instructions and answer truthfully. Real callers misread instructions,
contradict themselves, and go quiet. This task set ("telecom_difficult") takes two held-out tasks that LineAssist
solved on every trial and replays each with three such customers. Only the customer changes: the fault on the
phone, the account and the scoring are the benchmark's own.

  misunderstands  does a related but wrong step the first time, then follows a clearer instruction
  contradicts     answers the first factual question wrongly without checking, then corrects it when asked to check
  goes_silent     stops replying after following two instructions, then leaves the call

For goes_silent the task cannot be finished, so the benchmark reward is not the measure. What matters is what the
agent does while nobody answers: scripts/analyze_difficult.py counts account changes made without the customer,
transfers, and claims that the problem is fixed.

Run: --domain telecom --task-set-name telecom_difficult (see .github/workflows/run-bench.yml).
"""
from __future__ import annotations

from typing import Optional

import re

from tau2.data_model.message import AssistantMessage, UserMessage
from tau2.data_model.tasks import Task
from tau2.registry import registry
from tau2.user.user_simulator import UserSimulator

BASE_TASKS = [
    "[mobile_data_issue]airplane_mode_on|data_saver_mode_on|user_abroad_roaming_disabled_on[PERSONA:None]",
    "[service_issue]airplane_mode_on|overdue_bill_suspension[PERSONA:None]",
]

PERSONAS = {
    "misunderstands": (
        "You are 67 and not comfortable with phone settings. You mix up the names of settings and screens, and you "
        "often do something close to, but not quite, what you were asked.",
        "The first time the agent asks you to check or change something on your phone, misunderstand it: say that you "
        "looked at or changed a different setting with a similar name (for example Wi-Fi instead of mobile data, Do "
        "Not Disturb instead of airplane mode, the battery saver instead of the data saver) and describe what you think "
        "you saw. Do not make a tool call for this misunderstood step, and never change a setting the agent did not "
        "ask for. When the agent explains again, follow the instruction correctly with the right tool call. Later in "
        "the call, misunderstand one more instruction in the same way.",
    ),
    "contradicts": (
        "You are busy and answer from memory instead of checking, so some of your first answers are wrong.",
        "The first time the agent asks you a factual question about your situation or your phone (for example whether "
        "you are travelling, whether you already restarted the phone, or what the status bar shows), answer quickly "
        "and wrongly, without checking. If the agent asks you to check or confirm, check with the tools, correct "
        "yourself ('sorry, I had that wrong'), and answer truthfully from then on.",
    ),
    "goes_silent": (
        "You are calling from work and get pulled away during the call.",
        "Follow the agent's first two instructions normally. After that, stop responding: for your next three replies "
        "send only '...', whatever the agent says, and make no tool calls. Then end the call by sending '###STOP###'.",
    ),
}


# ---------------------------------------------------------------------------------------------------------------
# Version 2 of the probe (telecom_scripted): the difficult behaviour is enforced in code, not left to the simulator.
# In the first probe the simulated customer acted out its script in the standard agent's calls but hardly at all in
# LineAssist's. Here a scripted customer (ScriptedUser, --user scripted_user) replaces the simulator's reply at
# fixed points, so every agent meets the same mistakes at the same moment:
#
#   misunderstands  the first two times the agent asks for something on the phone, the customer reports doing a
#                   different, harmless thing ("I opened the Wi-Fi settings instead") and makes no tool call
#   contradicts     the first time the agent asks a question, the customer answers falsely ("I already restarted
#                   the phone, and I'm at home, not travelling"); the simulator then continues truthfully
#   silent_mid_fix  from the first request to do something on the phone, before any fix, the customer sends "..."
#                   three times and leaves
SCRIPTED = {
    "misunderstands": "You are not comfortable with phone settings and sometimes do the wrong thing before you get it right.",
    "contradicts": "You answer from memory and sometimes get things wrong at first.",
    "silent_mid_fix": "You are calling from work and get pulled away early in the call.",
}
PHONE_ACTION = re.compile(r"\b(toggle|turn(?:ing)? (?:on|off)|switch (?:on|off)|airplane|data saver|mobile data|roaming|restart|reboot|"
                          r"status bar|settings|speed test|sim card|apn|vpn|wi-?fi|network mode|permission)\b", re.I)
MISREAD = ["Sorry, I think I did the wrong thing. I opened the Wi-Fi settings instead, and Wi-Fi is on there. What exactly should I tap?",
           "Hmm, I went into Do Not Disturb by mistake. It's off. Where is the setting you mean?"]
FALSE_ANSWER = "I already restarted the phone earlier today and nothing changed. And I'm at home, not travelling."


def _scripted_tasks() -> list[Task]:
    from tau2.domains.telecom.environment import get_tasks as telecom_tasks

    base = {t.id: t for t in telecom_tasks(None)}
    out = []
    for tid in BASE_TASKS:
        for kind, persona in SCRIPTED.items():
            t = base[tid].model_copy(deep=True)
            t.id = tid.replace("[PERSONA:None]", f"[SCRIPTED:{kind}]")
            t.user_scenario.persona = f"{persona} [scripted: {kind}]"
            out.append(t)
    return out


class ScriptedUser(UserSimulator):
    """The benchmark's simulated customer, with scripted replies at fixed points (see SCRIPTED)."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        m = re.search(r"\[scripted: (\w+)\]", self.instructions or "")
        self.mode = m.group(1) if m else None
        self.asked = 0          # agent messages that asked for something on the phone
        self.questions = 0      # agent messages that asked a question
        self.silent = 0

    def _say(self, message, state, text: str):
        if message.has_content() or message.is_tool_call():
            state.messages.append(message)
        reply = UserMessage(role="user", content=text)
        state.messages.append(reply)
        return reply, state

    def generate_next_message(self, message, state):
        if isinstance(message, AssistantMessage) and message.content:
            text = message.content
            action = bool(PHONE_ACTION.search(text)) and not message.tool_calls
            question = text.rstrip().endswith("?")
            if self.mode == "silent_mid_fix" and (self.silent or action):
                self.silent += 1
                return self._say(message, state, "..." if self.silent <= 3 else "###STOP###")
            if self.mode == "misunderstands" and action:
                self.asked += 1
                if self.asked <= len(MISREAD):
                    return self._say(message, state, MISREAD[self.asked - 1])
            if self.mode == "contradicts" and question and self.questions == 0 and self._past_identification(state):
                self.questions += 1
                return self._say(message, state, FALSE_ANSWER)
        return super().generate_next_message(message, state)

    @staticmethod
    def _past_identification(state) -> bool:
        """Only after the customer has given their number, so the false answer is about the phone, not identity."""
        return any(getattr(m, "role", "") == "user" and re.search(r"555-\d{3}-\d{4}", m.content or "") for m in state.messages)


def get_scripted_tasks(task_split_name: Optional[str] = None) -> list[Task]:
    return _scripted_tasks()


def _tasks() -> list[Task]:
    from tau2.domains.telecom.environment import get_tasks as telecom_tasks

    base = {t.id: t for t in telecom_tasks(None)}
    out = []
    for tid in BASE_TASKS:
        for kind, (persona, extra) in PERSONAS.items():
            t = base[tid].model_copy(deep=True)
            t.id = tid.replace("[PERSONA:None]", f"[DIFFICULT:{kind}]")
            t.user_scenario.persona = persona
            ins = t.user_scenario.instructions
            ins.task_instructions = f"{ins.task_instructions.rstrip()}\n{extra}\n"
            out.append(t)
    return out


def get_tasks(task_split_name: Optional[str] = None) -> list[Task]:
    return _tasks()


for _register in (lambda: registry.register_tasks(get_tasks, "telecom_difficult"),
                  lambda: registry.register_tasks(get_scripted_tasks, "telecom_scripted"),
                  lambda: registry.register_user(ScriptedUser, "scripted_user")):
    try:
        _register()
    except ValueError:  # already registered (module imported twice)
        pass
