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
    msg, state = agent.generate_next_message(UserMessage(role="user", content="help"), state)
    assert "run_speed_test" in msg.content and calls.count("handoff_review") == 1
    assert "check roaming" in state.system_messages[1].content        # note reaches the agent as an instruction
    assert [type(m).__name__ for m in state.messages] == ["UserMessage", "AssistantMessage"]   # draft discarded


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


# ---- line check ------------------------------------------------------------------------------

from tau2.data_model.message import ToolMessage


def call(name, **args):
    return AssistantMessage(role="assistant", cost=0.02, tool_calls=[ToolCall(id=f"c-{name}-{args.get('id', args.get('line_id', ''))}", name=name, arguments=args)])


def result(msg, content):
    return ToolMessage(id=msg.tool_calls[0].id, role="tool", requestor="assistant", content=content)


CUSTOMER = '{"customer_id": "C1", "line_ids": ["L1", "L2"]}'
L1 = '{"line_id": "L1", "phone_number": "555-000-0001", "roaming_enabled": false}'
L2 = '{"line_id": "L2", "phone_number": "555-000-0002", "roaming_enabled": false}'


def run_script(monkeypatch, replies, tool_results, **kw):
    agent, state, calls = make(monkeypatch, replies, [], guard=False, **kw)
    out, state = agent.generate_next_message(UserMessage(role="user", content="My number is 555-000-0002"), state)
    sent = [out]
    for r in tool_results:
        out, state = agent.generate_next_message(result(out, r), state)
        sent.append(out)
    return sent, state


def test_action_on_another_line_is_withheld(monkeypatch):
    lookup, wrong = call("get_customer_by_phone", phone_number="555-000-0002"), call("get_details_by_id", id="L1")
    sent, state = run_script(monkeypatch, [lookup, wrong, call("enable_roaming", customer_id="C1", line_id="L1"),
                                           call("get_details_by_id", id="L2")], [CUSTOMER, L1])
    assert sent[-1].tool_calls[0].arguments == {"id": "L2"}          # the roaming change never left the agent
    assert state.line_blocks == 1
    assert "555-000-0001" in state.messages[-2].content and "L2" in state.messages[-2].content


def test_action_on_the_matching_line_goes_through(monkeypatch):
    lookup = call("get_customer_by_phone", phone_number="555-000-0002")
    sent, state = run_script(monkeypatch, [lookup, call("get_details_by_id", id="L2"),
                                           call("enable_roaming", customer_id="C1", line_id="L2")], [CUSTOMER, L2])
    assert sent[-1].tool_calls[0].name == "enable_roaming" and state.line_blocks == 0


def test_line_that_was_never_looked_up_is_withheld(monkeypatch):
    lookup = call("get_customer_by_phone", phone_number="555-000-0002")
    sent, state = run_script(monkeypatch, [lookup, call("refuel_data", customer_id="C1", line_id="L1", gb_amount=2.0),
                                           call("get_details_by_id", id="L1")], [CUSTOMER])
    assert sent[-1].tool_calls[0].name == "get_details_by_id" and state.line_blocks == 1


def test_line_check_can_be_switched_off(monkeypatch):
    lookup = call("get_customer_by_phone", phone_number="555-000-0002")
    sent, state = run_script(monkeypatch, [lookup, call("refuel_data", customer_id="C1", line_id="L1", gb_amount=2.0)],
                             [CUSTOMER], line_check=False)
    assert sent[-1].tool_calls[0].name == "refuel_data"


# ---- case notes ------------------------------------------------------------------------------

POLICY = "The current time is 2025-02-25 12:08:00 EST."


def notes_agent(monkeypatch):
    agent, state, _ = make(monkeypatch, [], [])
    agent.today = "2025-02-25"
    state.caller_phone = "555-000-0002"
    return agent, state


def test_note_marks_the_wrong_line(monkeypatch):
    agent, state = notes_agent(monkeypatch)
    assert "NOT the customer's line" in agent._case_note(state, {"line_id": "L1", "phone_number": "555-000-0001"})


def test_note_flags_a_contract_that_has_ended(monkeypatch):
    agent, state = notes_agent(monkeypatch)
    note = agent._case_note(state, {"line_id": "L2", "phone_number": "555-000-0002", "status": "Suspended",
                                    "contract_end_date": "2024-12-31", "roaming_enabled": True})
    assert "must not be resumed" in note and "Roaming is enabled" in note
    assert "check_network_status" in note                      # the phone's own roaming switch still needs checking


def test_note_for_a_suspension_that_can_be_lifted(monkeypatch):
    agent, state = notes_agent(monkeypatch)
    note = agent._case_note(state, {"line_id": "L2", "phone_number": "555-000-0002", "status": "Suspended",
                                    "contract_end_date": "2026-12-31", "roaming_enabled": False})
    assert "overdue bill" in note and "NOT enabled" in note


def test_note_detects_a_used_up_allowance(monkeypatch):
    agent, state = notes_agent(monkeypatch)
    state.line_phone["L2"] = "555-000-0002"
    usage = {"line_id": "L2", "data_used_gb": "15.1", "data_limit_gb": "15.0", "data_refueling_gb": "0.0"}
    assert "used up" in agent._case_note(state, usage) and state.usage_checked
    usage["data_refueling_gb"] = "2.0"
    assert "is fine" in agent._case_note(state, usage)


def test_usage_on_another_line_is_ignored(monkeypatch):
    agent, state = notes_agent(monkeypatch)
    state.line_phone["L1"] = "555-000-0001"
    assert agent._case_note(state, {"line_id": "L1", "data_used_gb": "9", "data_limit_gb": "5"}) is None
    assert not state.usage_checked


def test_case_note_is_added_to_a_copy_not_the_original(monkeypatch):
    lookup = call("get_customer_by_phone", phone_number="555-000-0002")
    agent, state, _ = make(monkeypatch, [lookup, call("get_details_by_id", id="L1"), say("ok")], [], guard=False)
    out, state = agent.generate_next_message(UserMessage(role="user", content="My number is 555-000-0002"), state)
    out, state = agent.generate_next_message(result(out, CUSTOMER), state)
    original = result(out, L1)
    agent.generate_next_message(original, state)
    assert "[case note]" not in original.content
    assert "[case note] This is NOT the customer's line" in state.messages[-2].content
