"""Re-score LineAssist's published conversations and check every number against the committed results.

No API key and no benchmark checkout needed; it takes a few seconds. Every conversation is saved in
results/runs/test-*/results.json.gz, the scoring code is scripts/compare.py and scripts/analyze.py, and
the agent was frozen at commit aac2c62 before the test split was run. To re-run the conversations
themselves against the pinned tau2-bench commit, see REPRODUCE.md.

Usage: python reproduce.py
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TMP = Path(tempfile.mkdtemp(prefix="reproduce-"))


def run(*args, cwd=None):
    """Run one of the repository's own scripts with this Python, quietly."""
    subprocess.run([sys.executable, *map(str, args)], cwd=cwd or ROOT, check=True, stdout=subprocess.DEVNULL)


def differences(a, b, path=""):
    """Every place two JSON values differ, allowing for rounding in the last decimal places."""
    if isinstance(a, dict) and isinstance(b, dict):
        out = [f"{path}/{k}: only in one file" for k in set(a) ^ set(b)]
        return out + [d for k in set(a) & set(b) for d in differences(a[k], b[k], f"{path}/{k}")]
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return [f"{path}: {len(a)} items against {len(b)}"]
        return [d for i, (x, y) in enumerate(zip(a, b)) for d in differences(x, y, f"{path}[{i}]")]
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        return [] if abs(a - b) <= 1e-3 else [f"{path}: {a} against {b}"]
    return [] if a == b else [f"{path}: {str(a)[:40]} against {str(b)[:40]}"]


def check(name, recomputed, published):
    diff = differences(recomputed, published)
    print(f"  {'MATCH    ' if not diff else 'DIFFERENT'} {name}")
    for d in diff[:5]:
        print(f"             {d}")
    return not diff


def rerun_in_place(name, files, *args, cwd=None):
    """For scripts that write next to the published files: run, compare with what was there, then put it back."""
    before = {f: (ROOT / f).read_text() for f in files}
    try:
        run(*args, cwd=cwd)
        return all([check(f"{name}: {f}", json.loads((ROOT / f).read_text()), json.loads(before[f])) for f in files])
    finally:
        for f, text in before.items():
            (ROOT / f).write_text(text)


def main():
    print("LineAssist: re-scoring the 120 held-out conversations per agent with the repository's own scoring code.\n")
    run("compare.py", "../results/runs/test-baseline", "../results/runs/test-lineassist", "--out", TMP / "test.json", cwd=ROOT / "scripts")
    r = json.loads((TMP / "test.json").read_text())
    ok = check("pass rates, hand-offs, cost and the task-level bootstrap (results/test_comparison.json)", r,
               json.loads((ROOT / "results/test_comparison.json").read_text()))
    ok &= rerun_in_place("failure breakdown", ["results/runs/test-baseline/breakdown.json", "results/runs/test-lineassist/breakdown.json"],
                         "scripts/analyze.py", "results/runs/test-baseline", "results/runs/test-lineassist")
    b, c = r["baseline"], r["candidate"]
    print(f"\n  Conversations solved   LineAssist {c['pass_rate']:.1%}   standard agent {b['pass_rate']:.1%}")
    print(f"  Hand-offs while a fix was available   LineAssist {c['unneeded_handoffs']:.1%}   standard agent {b['unneeded_handoffs']:.1%}")
    print("\nEvery number matches the published results." if ok else "\nSome numbers differ; see above.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
