"""Compare two runs on the same tasks: pass rate, reliability across trials, cost and time.

Usage: python scripts/compare.py results/runs/<baseline> results/runs/<candidate> [--out file.json]

Confidence intervals resample TASKS, not conversations: three trials of one task are
not three independent pieces of evidence.
"""
import argparse
import json
import random
import statistics
from collections import defaultdict

from analyze import load


def by_task(rows):
    out = defaultdict(list)
    for r in rows:
        out[r["task"]].append(r)
    return out


def describe(rows):
    tasks = by_task(rows)
    k = min(len(v) for v in tasks.values())
    return {
        "tasks": len(tasks), "trials": k, "conversations": len(rows),
        "pass_rate": sum(r["passed"] for r in rows) / len(rows),
        "solved_every_trial": sum(all(r["passed"] for r in v) for v in tasks.values()) / len(tasks),
        "solved_at_least_once": sum(any(r["passed"] for r in v) for v in tasks.values()) / len(tasks),
        "unneeded_handoffs": sum(r["handoff"] and not r["handoff_expected"] for r in rows) / len(rows),
        "cost_per_conversation": sum(r["cost"] for r in rows) / len(rows),
        "agent_cost_per_conversation": sum(r["agent_cost"] for r in rows) / len(rows),
        "cost_per_solved": sum(r["cost"] for r in rows) / max(1, sum(r["passed"] for r in rows)),
        "median_seconds": statistics.median(r["duration"] for r in rows),
        "median_messages": statistics.median(r["messages"] for r in rows),
    }


def bootstrap(a_rows, b_rows, n=10000, seed=7):
    a, b = by_task(a_rows), by_task(b_rows)
    tasks = sorted(set(a) & set(b))
    rate = lambda d, t: sum(r["passed"] for r in d[t]) / len(d[t])
    allk = lambda d, t: float(all(r["passed"] for r in d[t]))
    rng = random.Random(seed)
    stats = {"a_pass": [], "b_pass": [], "diff_pass": [], "a_all": [], "b_all": [], "diff_all": []}
    for _ in range(n):
        s = [rng.choice(tasks) for _ in tasks]
        ap, bp = sum(rate(a, t) for t in s) / len(s), sum(rate(b, t) for t in s) / len(s)
        aa, ba = sum(allk(a, t) for t in s) / len(s), sum(allk(b, t) for t in s) / len(s)
        for key, v in zip(stats, (ap, bp, bp - ap, aa, ba, ba - aa)):
            stats[key].append(v)
    ci = lambda v: [round(sorted(v)[int(0.025 * n)], 4), round(sorted(v)[int(0.975 * n)], 4)]
    better = sum(rate(b, t) > rate(a, t) for t in tasks)
    worse = sum(rate(b, t) < rate(a, t) for t in tasks)
    return {"shared_tasks": len(tasks), **{k + "_ci95": ci(v) for k, v in stats.items()},
            "tasks_candidate_better": better, "tasks_candidate_worse": worse,
            "tasks_same": len(tasks) - better - worse}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("baseline")
    ap.add_argument("candidate")
    ap.add_argument("--out")
    args = ap.parse_args()
    a, b = load(args.baseline), load(args.candidate)
    report = {"baseline": {"run": args.baseline, **describe(a)}, "candidate": {"run": args.candidate, **describe(b)},
              "comparison": bootstrap(a, b)}
    text = json.dumps(report, indent=2, default=lambda x: round(x, 4))
    print(json.dumps(json.loads(text), indent=2))
    if args.out:
        open(args.out, "w").write(text)


if __name__ == "__main__":
    main()
