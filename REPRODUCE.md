# Reproduce these results

## Check the published numbers (no API key, a few seconds)

```bash
python reproduce.py          # Python 3.10+, standard library only
```

`reproduce.py` re-scores every saved conversation with the same scoring code and compares each number with
the committed results. It prints `MATCH` or `DIFFERENT` per file.

## What each part is

| | Where |
|---|---|
| Agent frozen before the test split | commit `aac2c62` |
| Benchmark | tau2-bench (Sierra Research, MIT), telecom domain, test split, pinned at commit `4ce7c0397c1eb65c9bbe59aeacfe1ca44a1cd699` (see `.github/workflows/run-bench.yml`) |
| Raw conversations | `results/runs/test-baseline/` and `results/runs/test-lineassist/`: every message, tool call, benchmark check and cost, in `results.json.gz` |
| Scoring code | `scripts/compare.py` (pass rates, hand-offs, cost, task-level bootstrap), `scripts/analyze.py` (failure breakdown) |
| Published results | `results/test_comparison.json`, `results/runs/test-*/breakdown.json` |

## Re-run the conversations from scratch

Needs an Anthropic API key. The test split cost about $14 for both agents (120 conversations each).

```bash
git clone https://github.com/sierra-research/tau2-bench && git -C tau2-bench checkout 4ce7c0397c1eb65c9bbe59aeacfe1ca44a1cd699
cd tau2-bench && uv sync && cd ..
export ANTHROPIC_API_KEY=...      # never commit this
# In GitHub: Actions > run-bench > Run workflow, with split=test, num_trials=3, agent=llm_agent (standard)
# and again with agent=lineassist. The workflow pins the benchmark and saves each run under results/runs/.
cd scripts && python compare.py ../results/runs/<standard run> ../results/runs/<lineassist run>
```

The simulated customer is itself a model, so a fresh run lands close to, not exactly on, the published figures.

## Checks added after the test

These came after the frozen evaluation and do not change its numbers. In GitHub: Actions > extra-evals (needs the
`ANTHROPIC_API_KEY` secret, about $1.50). It runs the 8 fresh contract-end calls for `lineassist` and `lineassist_v2`
and the difficult-customer task set (`lineassist/difficult.py`) for `lineassist_v2` and the standard agent, then:

```bash
python scripts/analyze_extra.py \
  --contract lineassist=results/runs/fresh-contract-lineassist lineassist_v2=results/runs/fresh-contract-lineassist_v2 \
  --difficult lineassist_v2=results/runs/difficult-lineassist_v2 standard=results/runs/difficult-baseline \
  --out results/extra_evals.json      # re-scores the saved conversations, no API key
```
