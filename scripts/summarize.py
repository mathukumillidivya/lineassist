"""Turn a tau2 results.json into a small summary that is easy to read and compare.

Usage: python scripts/summarize.py <results.json> <out_dir>
Writes summary.json (headline numbers) and per_task.csv (one row per conversation).
"""
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path


def main(src: str, out_dir: str) -> None:
    data = json.loads(Path(src).read_text())
    sims = data.get("simulations", [])
    rows = []
    for s in sims:
        reward = (s.get("reward_info") or {}).get("reward")
        msgs = s.get("messages") or []
        rows.append({
            "task_id": s.get("task_id"), "trial": s.get("trial"),
            "passed": int(reward is not None and reward >= 1.0 - 1e-6),
            "reward": reward, "termination": s.get("termination_reason"),
            "duration_s": round(s.get("duration") or 0, 1),
            "agent_cost": s.get("agent_cost") or 0.0, "user_cost": s.get("user_cost") or 0.0,
            "messages": len(msgs),
            "tool_calls": sum(len(m.get("tool_calls") or []) for m in msgs if m.get("role") == "assistant"),
        })
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    if rows:
        with open(out / "per_task.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)

    by_task = defaultdict(list)
    for r in rows:
        by_task[r["task_id"]].append(r["passed"])
    n = len(rows)
    trials = max((len(v) for v in by_task.values()), default=0)
    summary = {
        "conversations": n, "tasks": len(by_task), "trials_per_task": trials,
        "pass_rate": round(sum(r["passed"] for r in rows) / n, 4) if n else None,
        # share of tasks solved on every trial: the number that matters for a deployed agent
        "pass_all_trials": round(sum(all(v) for v in by_task.values()) / len(by_task), 4) if by_task else None,
        "agent_cost_total": round(sum(r["agent_cost"] for r in rows), 4),
        "user_cost_total": round(sum(r["user_cost"] for r in rows), 4),
        "cost_per_conversation": round(sum(r["agent_cost"] + r["user_cost"] for r in rows) / n, 4) if n else None,
        "median_duration_s": sorted(r["duration_s"] for r in rows)[n // 2] if n else None,
        "mean_tool_calls": round(sum(r["tool_calls"] for r in rows) / n, 1) if n else None,
        "terminations": dict(Counter(str(r["termination"]) for r in rows)),
        "config": {k: (data.get("info") or {}).get(k) for k in ("agent_info", "user_info", "num_trials", "seed")},
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    print(json.dumps({k: v for k, v in summary.items() if k != "config"}, indent=2))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
