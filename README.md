# LineAssist

A telecom customer-support agent, measured on the telecom domain of
[tau-bench](https://github.com/sierra-research/tau2-bench).

In this benchmark a simulated customer calls with a phone that has no service, broken mobile
data, or picture messages that will not send. The phone has between two and nine faults at
once. The agent can read and change the account, but it cannot touch the phone: it has to talk
the customer through each check and fix. A conversation passes only if the account and the
phone end up in the correct state. How the conversation sounded does not count.

**Reproduce:** `python reproduce.py` re-scores every saved run and checks each published number (no API key). Full steps, the frozen commit and the data are in [REPRODUCE.md](REPRODUCE.md). A 40-second demo video is on the site's Reproduce page.

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

**Escalation stays available.** The aim is no *unnecessary* hand-offs, not no hand-offs. In the 12 test
calls where policy requires a human (a contract that has ended, a SIM locked by PIN), the correct outcome is a
transfer: LineAssist handled these correctly, transfer included, in 33 of 36 attempts, and the standard agent in 33 of 36. The hand-off guard allows
transfers the playbook requires, overrules the agent at most three times per call, and fails open.

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
enforce the rule in code on the `resume_line` call, the same way the line check works. It was
not applied to the measured agent, because the test split had already been seen. It was added
afterwards (`lineassist_v2`) and tested on fresh calls, reported separately below.

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

## Checked after the test

Separate runs (`.github/workflows/extra-evals.yml`, scored by `scripts/analyze_extra.py` into
[results/extra_evals.json](results/extra_evals.json)). The held-out results above are unchanged. Cost: $1.45.

**The contract rule, on 8 fresh calls.** Every contract-end task in the benchmark's full set that is in neither the
development nor the test split. The right outcome is always: leave the line suspended and transfer to a human.

| | Solved | Transferred to a human | Lifted a suspension it must not |
|---|---|---|---|
| LineAssist as measured (`lineassist`) | 5 of 8 | 5 of 8 | 3 |
| **With the policy check (`lineassist_v2`)** | **8 of 8** | **8 of 8** | **0** |

The measured agent repeats its test failure on new calls (3 of 8), so the failure was not a one-off. The check
removes it and leaves escalation open: every call still reached a human.

**Difficult customers, a small probe** ([lineassist/difficult.py](lineassist/difficult.py)). Two held-out calls
LineAssist always solved, replayed with a customer who mixes up instructions, answers wrongly before checking, or goes
silent after two instructions. One attempt each, 12 calls.

| | Misunderstands | Contradicts | Goes silent | Transferred |
|---|---|---|---|---|
| Standard agent | 0 of 2 | 0 of 2 | 0 of 2 | 5 of 6 |
| **LineAssist** | **2 of 2** | **2 of 2** | **2 of 2** | **0 of 6** |

- **Read this as "not derailed", not as "handles confusion".** The simulated customer acted out its script in the
  standard agent's calls (looking at the wrong screen, giving a wrong first answer) but hardly at all in LineAssist's,
  whose instructions name the exact phone action and leave little room to misread. The standard agent solves one of
  these two calls with an ordinary customer and fails the other.
- **When the customer went silent,** both agents waited and asked again, made no change to the account and never said
  the problem was fixed. In LineAssist's two calls the silence came after the faults were already fixed, so the
  hardest moment (silence mid-fix) was not tested.
- **Escalation.** No unnecessary hand-offs from LineAssist in these calls, against five from the standard agent, none
  of them needed. With the 8 fresh contract calls, the agent with the policy check transferred every time a transfer
  was required and never when it was not.

**Ablation: each layer removed in turn** (the 7 held-out calls with the most faults, one attempt each; the full
agent's and the standard agent's figures are their frozen test runs on the same 7 calls, three attempts each).

| | Solved | Unneeded hand-offs |
|---|---|---|
| Standard agent (test run) | 0 of 21 | 14 |
| **LineAssist, all layers (test run)** | **21 of 21** | **0** |
| without the hand-off guard | 16 of 19 (6 of 7, then 10 of 12 in a second run) | see results/extra_evals.json |
| without the line check | 7 of 7 | 0 |
| without the case notes | 6 of 7 | 0 |
| without the playbook | 5 of 7 | 2 |

The playbook matters most; the line check made no difference on these calls (it guards against acting on the wrong
line, which these calls rarely tempt). No single removal brings the agent near the standard agent, so the gain comes
from the layers together. Seven calls and one attempt each: a one-call difference is within noise. Cost: $2.87.

**Scripted difficult customers** (`telecom_scripted`, `--user scripted_user` in [lineassist/difficult.py](lineassist/difficult.py)).
The first probe left the difficult behaviour to the simulator, which hardly acted it out against LineAssist. Here code
replaces the customer's reply at fixed points, so both agents meet the same mistakes: two misread instructions, a false
answer ("I already restarted the phone, and I'm not travelling"), and silence that starts before anything is fixed.

| Same 2 calls per customer | Misreads twice | False answer | Silent before the fix |
|---|---|---|---|
| Standard agent | 1 of 2 solved, 1 transfer | 1 of 2 solved, 1 transfer | waited; no account change; no claim it was fixed |
| **LineAssist** | **2 of 2 solved** | **2 of 2 solved** | **waited; no account change; no claim it was fixed** |

The misreads were delivered in all four of each agent's calls; the false answer fired in one call each (in the other,
the agent never asked a question at the scripted point). After the false answer, LineAssist kept to the account facts
and solved the call; the standard agent misread which line was the customer's and transferred. A silent call cannot be
solved, so what matters is the behaviour: neither agent changed the account or said the problem was fixed while nobody
answered, and LineAssist asked before sending a payment request it had no consent for. Cost: $0.35.

## What this does not show

- **No single layer carries the result.** The ablation below removed each layer in turn on the
  7 hardest calls, one attempt each: no removal dropped below 5 of 7, while the standard agent
  solved none of those calls. With 7 calls, a difference of one call is noise, so the share each
  layer contributes is still not measured precisely.
- **Held-out means new combinations, not new problems.** Test tasks combine the same fault
  types as development tasks in different sets, on the same customer account. The result says
  the agent handles unseen combinations of known faults. It says nothing about fault types
  that are absent from the manual.
- **Not comparable to the public leaderboard.** Both agents here talk to a customer simulated
  by Claude Haiku 4.5 to keep cost down; published results use a different simulator model.
  Only the comparison between the two agents is meaningful.
- **One model.** Everything was run with Claude Haiku 4.5. A stronger model would likely narrow
  the gap from the baseline side.
- **A simulated customer is not a real one.** In the test the simulator always has its phone,
  always eventually cooperates, and never misreads a screen. The difficult-customer probe above
  is small, and the simulator did not always act out its script.
- **Three trials.** Enough to see that failures are consistent per task, not enough to
  estimate rare failures.

## Live demo

**https://lineassist-app.onrender.com**

`app/` holds a page where a visitor plays the customer: they get a phone with hidden faults,
talk to LineAssist, and tap checks and fixes on the phone as the agent asks for them.

- **The simulator is the benchmark's own.** The account tools, phone tools and data models
  are the benchmark's Python files, unmodified, running in the browser through Pyodide.
  A parity script compared 192 tool calls across the six demo scenarios against the
  benchmark's environment and found identical results.
- **The agent's layers run on the page**, as a JavaScript port of `lineassist/agent.py`, and
  each intervention is shown to the visitor as it happens.
- **One small server** reaches the model (`app/server.mjs` on Render, wrapping the same rules as
  the Netlify function `app/netlify/functions/agent.mjs`). It holds the system prompt and tool
  definitions itself, accepts only a conversation from the demo page, and limits requests per
  visitor and per day. The free Render service sleeps when idle, so the first live call can take
  up to a minute to start.
- **It includes a policy check that the measured agent did not have**: a `resume_line` call on
  a line whose contract has ended is withheld in code. This is the fix for the test failure
  described above. The held-out results do not include it; it was tested afterwards on 8 fresh
  contract-end calls (see "Checked after the test"; `lineassist_v2` is the agent name).

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
