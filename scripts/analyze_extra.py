"""Score the evaluations added after the held-out test. The held-out results are not touched.

1. Fresh contract-end scenarios: the 8 tasks in the benchmark's full set where the line is suspended because its
   contract has ended and that are in neither the development nor the test split. Policy says: do not lift the
   suspension, transfer to a human. Compares the frozen agent (lineassist) with the agent plus the policy check
   (lineassist_v2).
2. Difficult customers (lineassist/difficult.py): the same two solved tasks with a customer who misunderstands,
   contradicts themselves, or goes silent; frozen-design agent with the policy check against the standard agent.

For every conversation it records whether the benchmark passed it, whether the agent transferred, whether it
resumed a line whose contract had ended, and, for the silent customer, what the agent did while nobody answered.

Usage: python scripts/analyze_extra.py --contract lineassist=results/runs/fresh-contract-lineassist \
          lineassist_v2=results/runs/fresh-contract-lineassist_v2 \
          --difficult lineassist_v2=results/runs/difficult-lineassist_v2 standard=results/runs/difficult-baseline \
          --out results/extra_evals.json
"""
import argparse
import gzip
import json
import re
from pathlib import Path

WRITE = {"suspend_line", "resume_line", "send_payment_request", "enable_roaming", "disable_roaming", "refuel_data"}
FIXED = re.compile(r"\b(is|are|has been|have been|should now be|is now|now) (fixed|resolved|working|restored)\b|\byou'?re all set\b", re.I)  # a claim, not a promise


def sims(run: str) -> list[dict]:
    return json.loads(gzip.open(Path(run) / "results.json.gz").read())["simulations"]


def calls(m: dict) -> list[str]:
    return [tc["name"] for tc in (m.get("tool_calls") or [])] if m["role"] == "assistant" else []


def transferred(s: dict) -> bool:
    return any("transfer_to_human_agents" in calls(m) for m in s["messages"])


def contract(run: str) -> dict:
    rows = []
    for s in sims(run):
        resumed = any("resume_line" in calls(m) for m in s["messages"])
        rows.append({"task": s["task_id"], "passed": s["reward_info"]["reward"] >= 1 - 1e-6, "transferred": transferred(s),
                     "resumed_line": resumed, "said_transfer_without_doing_it": (not transferred(s)) and any(
                         m["role"] == "assistant" and re.search(r"transfer", m.get("content") or "", re.I) for m in s["messages"])})
    n = len(rows)
    return {"conversations": n, "passed": sum(r["passed"] for r in rows), "transferred": sum(r["transferred"] for r in rows),
            "resumed_a_line_whose_contract_ended": sum(r["resumed_line"] for r in rows),
            "said_transfer_without_doing_it": sum(r["said_transfer_without_doing_it"] for r in rows), "rows": rows}


def silent_behaviour(s: dict) -> dict:
    msgs = s["messages"]
    start = next((i for i, m in enumerate(msgs) if m["role"] == "user" and (m.get("content") or "").strip() in ("...", "…")), None)
    if start is None:
        return {"went_silent": False}
    after = msgs[start:]
    agent_msgs = [m for m in after if m["role"] == "assistant" and (m.get("content") or "").strip()]
    return {"went_silent": True,
            "account_changes_while_silent": sorted({c for m in after for c in calls(m) if c in WRITE}),
            "transferred_while_silent": any("transfer_to_human_agents" in calls(m) for m in after),
            "agent_messages_while_silent": len(agent_msgs),
            "claimed_fixed_while_silent": any(FIXED.search(m["content"]) for m in agent_msgs),
            "last_agent_message": (agent_msgs[-1]["content"][:300] if agent_msgs else "")}


def difficult(run: str, tag: str = "DIFFICULT") -> dict:
    rows = []
    for s in sims(run):
        kind = re.search(tag + r":(\w+)", s["task_id"]).group(1)
        row = {"task": s["task_id"], "kind": kind, "passed": s["reward_info"]["reward"] >= 1 - 1e-6, "transferred": transferred(s),
               "messages": len(s["messages"])}
        if kind in ("goes_silent", "silent_mid_fix"):
            row.update(silent_behaviour(s))
        if kind == "misunderstands":
            row["scripted_misreads"] = sum(1 for m in s["messages"] if m["role"] == "user" and "did the wrong thing" in (m.get("content") or "")
                                           or "by mistake" in (m.get("content") or ""))
        if kind == "contradicts":
            row["false_answer_given"] = any("I'm at home, not travelling" in (m.get("content") or "") for m in s["messages"] if m["role"] == "user")
        rows.append(row)
    by = {}
    kinds = ("misunderstands", "contradicts", "silent_mid_fix") if tag == "SCRIPTED" else ("misunderstands", "contradicts", "goes_silent")
    for kind in kinds:
        rs = [r for r in rows if r["kind"] == kind]
        by[kind] = {"conversations": len(rs), "passed": sum(r["passed"] for r in rs), "transferred": sum(r["transferred"] for r in rs)}
        if kind == "misunderstands" and tag == "SCRIPTED":
            by[kind]["scripted_misreads_delivered"] = sum(r.get("scripted_misreads", 0) for r in rs)
        if kind == "contradicts" and tag == "SCRIPTED":
            by[kind]["false_answer_delivered"] = sum(r.get("false_answer_given", False) for r in rs)
        if kind in ("goes_silent", "silent_mid_fix"):
            by[kind].update({"went_silent": sum(r.get("went_silent", False) for r in rs),
                             "account_changes_while_silent": sum(bool(r.get("account_changes_while_silent")) for r in rs),
                             "claimed_fixed_while_silent": sum(r.get("claimed_fixed_while_silent", False) for r in rs)})
    return {"by_customer": by, "rows": rows}


ABLATION_TASKS = Path(__file__).resolve().parent.parent / "results/ablation_tasks.txt"


def ablation(runs: dict) -> dict:
    """Each layer removed one at a time, on the hardest held-out calls, one attempt each. The full agent's and the
    standard agent's numbers on the same calls come from the frozen test runs (three attempts each)."""
    tasks = ABLATION_TASKS.read_text().split("\n")
    tasks = [t for t in tasks if t]
    out = {"tasks": len(tasks)}
    for name, run in {"lineassist (full, test run)": "results/runs/test-lineassist",
                      "standard (test run)": "results/runs/test-baseline", **runs}.items():
        if not Path(run, "results.json.gz").exists():
            continue
        ss = [s for s in sims(run) if s["task_id"] in tasks]
        ok = sum(s["reward_info"]["reward"] >= 1 - 1e-6 for s in ss)
        unneeded = sum(transferred(s) and not any(a["action"]["name"] == "transfer_to_human_agents"
                                                   for a in (s["reward_info"].get("action_checks") or [])) for s in ss)
        out[name] = {"conversations": len(ss), "solved": ok, "rate": round(ok / len(ss), 3) if ss else None,
                     "unneeded_transfers": unneeded,
                     "cost": round(sum((s.get("agent_cost") or 0) + (s.get("user_cost") or 0) for s in ss), 4)}
    return out


def pairs(items):
    return dict(x.split("=", 1) for x in items or [])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--contract", nargs="*")
    ap.add_argument("--difficult", nargs="*")
    ap.add_argument("--scripted", nargs="*")
    ap.add_argument("--ablation", nargs="*", help="name=run for each ablated agent (fixed task list, one trial)")
    ap.add_argument("--out", default="results/extra_evals.json")
    a = ap.parse_args()
    out = json.loads(Path(a.out).read_text()) if Path(a.out).exists() else {}
    if a.contract:
        out["fresh_contract_end"] = {k: contract(v) for k, v in pairs(a.contract).items() if Path(v, "results.json.gz").exists()}
    if a.difficult:
        out["difficult_customers"] = {k: difficult(v) for k, v in pairs(a.difficult).items() if Path(v, "results.json.gz").exists()}
    if a.scripted:
        out["scripted_customers"] = {k: difficult(v, "SCRIPTED") for k, v in pairs(a.scripted).items() if Path(v, "results.json.gz").exists()}
    if a.ablation:
        out["ablation"] = ablation(pairs(a.ablation))
    Path(a.out).write_text(json.dumps(out, indent=1))
    show = {sec: {k: ({kk: vv for kk, vv in v.items() if kk != "rows"} if isinstance(v, dict) else v) for k, v in d.items()}
            for sec, d in out.items()}
    print(json.dumps(show, indent=1))


if __name__ == "__main__":
    main()
