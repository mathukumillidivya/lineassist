# LineAssist

A telecom customer-support agent, measured on the telecom domain of
[tau-bench](https://github.com/sierra-research/tau2-bench).

In this benchmark a simulated customer calls with a phone that has no service, broken mobile
data, or picture messages that will not send. The phone has between two and nine faults at
once. The agent can read and change the account, but it cannot touch the phone: it has to talk
the customer through each check and fix. A conversation passes only if the account and the
phone end up in the correct state. How the conversation sounded does not count.

## Result on held-out tasks

40 test tasks, 3 trials each (120 conversations per agent). Same model for both agents
(Claude Haiku 4.5), same simulated customer, same benchmark version.

| | Standard agent | LineAssist |
|---|---|---|
| Conversations solved | 56 / 120 (47%) | 117 / 120 (97.5%) |
| Tasks solved on all 3 trials | 18 / 40 (45%) | 39 / 40 (97.5%) |
| Handed to a human when a fix was available | 45 / 120 (38%) | 0 / 120 |
| Cost per conversation | $0.060 | $0.053 |
| Cost per solved conversation | $0.129 | $0.055 |
| Median conversation time | 60 s | 42 s |

The difference in pass rate is 51 points (95% interval 33 to 68, resampling tasks rather than
conversations). LineAssist did better on 22 tasks, worse on 1, the same on 17.

By number of faults on the phone:

| Faults | Standard agent | LineAssist |
|---|---|---|
| 2 | 17 / 30 | 30 / 30 |
| 3-4 | 33 / 51 | 51 / 51 |
| 5-6 | 6 / 21 | 18 / 21 |
| 7 or more | 0 / 18 | 18 / 18 |

The agent was frozen (commit `aac2c62`) before the test split was run, and the test split was
run once.

### The task it fails

All three LineAssist failures are the same task. The line was suspended because its contract
had ended, which policy says the agent must not lift. The agent took payment for an overdue
bill and resumed the line anyway, and then told the customer they were being transferred
without actually making the transfer. That is a policy violation, not a near miss. The case note
for that line states that the contract has ended and the line must not be resumed (see case
notes below), and the agent acted against it. The fix is to
enforce the rule in code on the `resume_line` call, the same way the line check works. It has
not been made, because the test split had already been seen.

## Why the standard agent fails

Read from the 74 development conversations, before anything was built:

1. **It gives up early.** 40 of 52 failures were hand-offs to a human while the fix was still
   available. The agent fixes one or two faults, sees the problem persist, and escalates.
2. **It works on the wrong line.** The account has three lines. In 39 of 52 failures the agent
   never looked at the line matching the customer's number, and in 26 it read or changed
   another line (for example, enabling roaming on someone else's line).
3. **It does not check the data allowance.** The single most missed step was the data
   top-up (34 of 38 tasks that needed it), because the agent never compared usage to the plan
   limit.
4. **It invents menus.** It describes screens and buttons it cannot see, and the customer
   then reports having done something that never happened on the phone.

## What LineAssist adds

Four layers on top of the same tool-calling agent. Code is in `lineassist/`.

| Layer | What it is | Kind |
|---|---|---|
| Playbook | The provider's own manual, restructured into one ordered checklist per problem, with a "keep going until the check passes" rule and rules for talking a customer through their phone | Prompt |
| Line check | A tool call that names a line is withheld unless that line's number is the number the customer gave | Code |
| Case notes | Facts that follow mechanically from account data (is this the customer's line, has the contract ended, is the allowance used up) are computed and written next to the tool result the agent reads | Code |
| Hand-off guard | Before a transfer goes out, a second model call lists checklist items not yet examined; if any remain, the transfer is withheld. It can overrule the agent three times at most, and fails open | Model call |

Development runs, 74 tasks, one trial each, layers added in this order:

| Version | Solved |
|---|---|
| Standard agent | 22 / 74 |
| + playbook | 42 / 74 |
| + hand-off guard | 43 / 74 |
| + line check | 53 / 74 |
| + case notes | 66 / 74 |
| + two wording fixes (phone-side roaming, no suggested top-up amount) | 69 / 74 |

These are single runs on the tasks the agent was designed against, so they overstate
performance and the steps are noisy. Two pilot runs of the same agent on the same 5 tasks each
failed a different task. The table shows where the gains came from; the held-out result above
is the claim.

## What this does not show

- **The hand-off guard has not earned its place.** It added one task in development, which is
  within run-to-run noise. Guard interventions are not logged in the saved results, so I
  cannot say how often it fired on the test split. The layers were added cumulatively and not
  removed one at a time, so the contribution of each is not isolated.
- **Held-out means new combinations, not new problems.** Test tasks combine the same fault
  types as development tasks in different sets, on the same customer account. The result says
  the agent handles unseen combinations of known faults. It says nothing about fault types
  that are absent from the manual.
- **Not comparable to the public leaderboard.** Both agents here talk to a customer simulated
  by Claude Haiku 4.5 to keep cost down; published results use a different simulator model.
  Only the comparison between the two agents is meaningful.
- **One model.** Everything was run with Claude Haiku 4.5. A stronger model would likely narrow
  the gap from the baseline side.
- **A simulated customer is not a real one.** The simulator always has its phone, always
  eventually cooperates, and never misreads a screen.
- **Three trials.** Enough to see that failures are consistent per task, not enough to
  estimate rare failures.

## Live demo

**https://lineassist-app.netlify.app**

`app/` holds a page where a visitor plays the customer: they get a phone with hidden faults,
talk to LineAssist, and tap checks and fixes on the phone as the agent asks for them.

- **The simulator is the benchmark's own.** The account tools, phone tools and data models
  are the benchmark's Python files, unmodified, running in the browser through Pyodide.
  A parity script compared 192 tool calls across the six demo scenarios against the
  benchmark's environment and found identical results.
- **The agent's layers run on the page**, as a JavaScript port of `lineassist/agent.py`, and
  each intervention is shown to the visitor as it happens.
- **One server function** (`app/netlify/functions/agent.mjs`) reaches the model. It holds the
  system prompt and tool definitions itself, accepts only a conversation from the browser,
  limits requests per visitor and per day, and fails closed if it cannot count them.
- **It includes a policy check that the measured agent did not have**: a `resume_line` call on
  a line whose contract has ended is withheld in code. This is the fix for the test failure
  described above. It is unit-tested but has not been run on the benchmark, so the reported
  results do not include it (`lineassist_v2` is the agent name that enables it).

The demo shows the agent working; it is not evidence of how well it works. The evidence is the
recorded test runs.

## Reproducing

Every run happens in GitHub Actions (`.github/workflows/run-bench.yml`) against a pinned
benchmark commit. Raw conversations are saved under `results/runs/<run_id>/results.json.gz`
next to a summary.

```
python scripts/analyze.py results/runs/test-baseline results/runs/test-lineassist
cd scripts && python compare.py ../results/runs/test-baseline ../results/runs/test-lineassist
pytest tests            # guard, line check and case notes, with a scripted model
```

Prompt caching is on for all runs. It cut the cost of a conversation from $0.23 to $0.06
without changing behaviour.

Benchmark: tau-bench (tau2-bench), Sierra Research, MIT licence.
