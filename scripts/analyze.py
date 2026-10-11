"""Break a run down by problem type, number of faults, customer persona and how it ended.

Usage: python scripts/analyze.py results/runs/<run_id> [results/runs/<other_run> ...]
"""
import gzip
import json
import re
import sys
from collections import defaultdict
from pathlib import Path


def load(run_dir: str) -> list[dict]:
    data = json.loads(gzip.open(Path(run_dir) / "results.json.gz").read())
    rows = []
    for s in data["simulations"]:
        name, ri = s["task_id"], s["reward_info"]
        faults = name.split("]")[1].split("[")[0].split("|")
        agent_calls = [tc["name"] for m in s["messages"] if m["role"] == "assistant" for tc in (m.get("tool_calls") or [])]
        expected = [a["action"]["name"] for a in (ri.get("action_checks") or [])]
        missed = [a["action"]["name"] for a in (ri.get("action_checks") or []) if not a["action_match"]]
        handed_off = "transfer_to_human_agents" in agent_calls or s["messages"][-1]["content"].strip().endswith("###TRANSFER###")
        rows.append({
            "task": name, "trial": s.get("trial"), "passed": ri["reward"] >= 1 - 1e-6,
            "issue": re.match(r"\[(\w+)\]", name).group(1), "persona": re.search(r"PERSONA:(\w+)", name).group(1),
            "faults": len(faults), "fault_names": faults, "missed": missed,
            "handoff": handed_off, "handoff_expected": "transfer_to_human_agents" in expected,
            "cost": (s.get("agent_cost") or 0) + (s.get("user_cost") or 0), "agent_cost": s.get("agent_cost") or 0,
            "duration": s.get("duration") or 0, "messages": len(s["messages"]),
        })
    return rows


def outcome(r: dict) -> str:
    if r["passed"]:
        return "solved"
    if r["handoff"] and not r["handoff_expected"]:
        return "handed to a human when the fix was available"
    return "customer left with the problem unresolved"


def table(rows: list[dict], key, title: str) -> dict:
    groups = defaultdict(list)
    for r in rows:
        groups[key(r)].append(r["passed"])
    print(f"\n{title}")
    out = {}
    for k in sorted(groups, key=str):
        v = groups[k]
        out[str(k)] = [sum(v), len(v)]
        print(f"  {str(k):48s} {sum(v):3d} / {len(v):3d}  ({100 * sum(v) / len(v):.0f}%)")
    return out


def bucket(n: int) -> str:
    return "2" if n <= 2 else "3-4" if n <= 4 else "5-6" if n <= 6 else "7+"


def main(run_dirs: list[str]) -> None:
    for d in run_dirs:
        rows = load(d)
        n = len(rows)
        print(f"\n===== {d}: {sum(r['passed'] for r in rows)}/{n} solved, "
              f"${sum(r['cost'] for r in rows) / n:.3f} per conversation =====")
        report = {
            "by_issue": table(rows, lambda r: r["issue"], "By problem type"),
            "by_faults": table(rows, lambda r: bucket(r["faults"]), "By number of faults on the phone"),
            "by_persona": table(rows, lambda r: r["persona"], "By customer persona"),
        }
        outcomes = defaultdict(int)
        for r in rows:
            outcomes[outcome(r)] += 1
        print("\nHow conversations ended")
        for k, v in sorted(outcomes.items(), key=lambda x: -x[1]):
            print(f"  {k:48s} {v:3d}")
        missed = defaultdict(int)
        for r in rows:
            for m in r["missed"]:
                missed[m] += 1
        print("\nRequired steps most often missed")
        for k, v in sorted(missed.items(), key=lambda x: -x[1])[:8]:
            print(f"  {k:48s} {v:3d}")
        report["outcomes"], report["missed_steps"] = dict(outcomes), dict(missed)
        (Path(d) / "breakdown.json").write_text(json.dumps(report, indent=2))


if __name__ == "__main__":
    main(sys.argv[1:])
