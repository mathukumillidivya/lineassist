# LineAssist

A customer-support agent for a telecom provider, measured on the telecom domain of
[tau-bench](https://github.com/sierra-research/tau2-bench): simulated customers with real
problems (no service, slow data, billing and roaming issues), a policy the agent must follow,
and a pass mark that checks the final state of the account and the phone, not how the
conversation sounded.

Status: setting up. Results will be reported here as they are measured.

## How results are produced

Every run happens in GitHub Actions against a pinned version of the benchmark, and the raw
conversations are saved under `results/runs/<run_id>/` next to a summary.

- Development uses the benchmark's `train` split (74 tasks).
- The `test` split (40 tasks) is held out and used only to report results.

Benchmark: Barres et al., tau2-bench (MIT licence).
