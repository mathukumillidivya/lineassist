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

from tau2.data_model.tasks import Task
from tau2.registry import registry

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


try:
    registry.register_tasks(get_tasks, "telecom_difficult")
except ValueError:  # already registered (module imported twice)
    pass
