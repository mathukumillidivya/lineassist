"""The escalation guard, tested with a scripted model so no API key is needed."""
import pytest

pytest.importorskip("tau2")

from tau2.data_model.message import AssistantMessage, ToolCall, UserMessage

import lineassist.agent as A


def scripted(agent_replies, review_replies, calls):
    agent_replies, review_replies = iter(agent_replies), iter(review_replies)

    def fake(model, messages, tools=None, call_name=None, **kw):
        calls.append(call_name)
        if call_name == "handoff_review":
            return AssistantMessage(role="assistant", content=next(review_replies), cost=0.01)
        return next(agent_replies)
    return fake


def transfer():
    return AssistantMessage(role="assistant", cost=0.02,
                            tool_calls=[ToolCall(id="t1", name="transfer_to_human_agents", arguments={"summary": "s"})])


def say(text):
    return AssistantMessage(role="assistant", content=text, cost=0.02)


def make(monkeypatch, agent_replies, review_replies, **kw):
    calls = []
    monkeypatch.setattr(A, "generate", scripted(agent_replies, review_replies, calls))
    agent = A.LineAssistAgent(tools=[], domain_policy="policy", llm="m", llm_args={}, **kw)
    return agent, agent.get_init_state(), calls


BLOCK = '{"allow": false, "reason": "roaming not checked", "remaining": ["check roaming"]}'
ALLOW = '{"allow": true, "reason": "SIM is locked", "remaining": []}'


def test_unjustified_transfer_is_withheld(monkeypatch):
    agent, state, calls = make(monkeypatch, [transfer(), say("Please run check_network_status")], [BLOCK])
    msg, state = agent.generate_next_message(UserMessage(role="user", content="help"), state)
    assert not msg.tool_calls and "check_network_status" in msg.content
    assert state.blocks == 1
    assert msg.cost == pytest.approx(0.02 + 0.02 + 0.01)       # withheld draft and review are counted


def test_justified_transfer_goes_through(monkeypatch):
    agent, state, _ = make(monkeypatch, [transfer()], [ALLOW])
    msg, state = agent.generate_next_message(UserMessage(role="user", content="help"), state)
    assert msg.tool_calls[0].name == "transfer_to_human_agents" and state.transferred


def test_text_that_announces_a_transfer_is_reviewed(monkeypatch):
    agent, state, calls = make(monkeypatch, [say("I will transfer you to a specialist."), say("Please run run_speed_test")], [BLOCK])
    msg, _ = agent.generate_next_message(UserMessage(role="user", content="help"), state)
    assert "run_speed_test" in msg.content and calls.count("handoff_review") == 1


def test_guard_gives_up_after_max_blocks(monkeypatch):
    agent, state, _ = make(monkeypatch, [transfer(), transfer(), transfer()], [BLOCK, BLOCK], max_blocks=2)
    msg, state = agent.generate_next_message(UserMessage(role="user", content="help"), state)
    assert msg.tool_calls and state.blocks == 2            # a real dead end still reaches a human


def test_unreadable_review_fails_open(monkeypatch):
    agent, state, _ = make(monkeypatch, [transfer()], ["not json"])
    msg, state = agent.generate_next_message(UserMessage(role="user", content="help"), state)
    assert msg.tool_calls and state.blocks == 0


def test_ordinary_messages_are_not_reviewed(monkeypatch):
    agent, state, calls = make(monkeypatch, [say("Please run check_status_bar")], [])
    agent.generate_next_message(UserMessage(role="user", content="help"), state)
    assert "handoff_review" not in calls


def test_guard_can_be_switched_off(monkeypatch):
    agent, state, calls = make(monkeypatch, [transfer()], [], guard=False)
    msg, _ = agent.generate_next_message(UserMessage(role="user", content="help"), state)
    assert msg.tool_calls and "handoff_review" not in calls
