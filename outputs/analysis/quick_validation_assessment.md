# Quick Validation Assessment

## Goal Alignment

The original small-scale goal was to verify whether the router can learn task-specific worker preferences and improve the quality-cost tradeoff against `random`, `cost_first`, and `single_best`, while the stronger dynamic claim requires clearer recovery advantages after perturbation.

- Research-plan criterion: the router should route different task types to more suitable workers and improve accuracy without cost exploding.
- Min-plan criterion: the method should win on a quality-cost tradeoff and the figures should highlight recovery and Pareto behavior rather than static averages alone.

## Final Outcome

This run **partially validates** the idea, but it does **not fully validate** the stronger dynamic-adaptation claim.

### What worked

- `ours` achieved the best overall success: `0.930`, above `single_best` (`0.924`), `cost_first` (`0.912`), and `random` (`0.882`).
- `ours` strongly dominated `random` on all three top-line metrics:
  - success `+4.8` points
  - total cost `-44.6%`
  - average latency `-31.0%`
- `ours` improved the quality-cost tradeoff relative to `single_best`:
  - success `+0.6` points
  - total cost `-38.3%`
  - but latency was worse
- The router learned a nontrivial task split:
  - GSM8K: `91.7%` of tasks were routed to `qwen3_235b`
  - HumanEval: `72.6%` to `gemini25flash`, `26.2%` to `haiku45`
  - `deepseek_r1` was nearly abandoned
- The gain mostly came from code tasks:
  - HumanEval success: `ours 0.9207` vs `single_best 0.8902` vs `random 0.7866`
  - GSM8K stayed close to the best static baseline while being much cheaper than `single_best`

### What did not get validated

- The perturbation/recovery claim is weakly supported at best.
- `ours` did not show a clear recovery-speed advantage over all baselines.
- The perturbation hit `deepseek_r1`, but `ours` had already stopped relying on it:
  - pre-perturbation `deepseek_r1` usage: `0.8%`
  - post-perturbation `deepseek_r1` usage: `0%`
- `cost_first` and `single_best` were also largely unaffected by that perturbation because they never used `deepseek_r1`.
- As a result, the recovery plot is not a strong stress test of dynamic adaptation; it is mostly measuring noise plus the effect on `random`.

## Why The Idea Looks Promising

- The worker pool was meaningfully heterogeneous.
- In `random`, worker success differed sharply:
  - `haiku45`: `0.9845`
  - `qwen3_235b`: `0.9060`
  - `gemini25flash`: `0.8939`
  - `deepseek_r1`: `0.7377`
- On HumanEval in `random`, `deepseek_r1` was especially weak (`0.4250`), while `haiku45` was strongest (`0.9792`).
- The router exploited this structure instead of collapsing to a single worker:
  - overall routing entropy: `1.3298` bits
  - dominant worker ratio: `0.62`

## Why The Stronger Claim Is Not Yet Proven

- `ours` vs `cost_first` was not a Pareto win:
  - success improved by `1.8` points
  - but cost and latency were much higher
- `ours` vs `single_best` did not show statistically significant success improvement.
- The decomposition mechanism was not validated:
  - trigger rate: `4.8%`
  - decomposition success: `0.9167`
  - non-decomposition success: `0.9307`
- The requested internal ablations (`No-update`, `Scalar-only`, `No-decomp`) were not run, so the current experiment does not isolate whether the gains came from:
  - online updating
  - multidimensional capability modeling
  - decomposition

## Bottom Line

The small-scale run supports the claim that **capability-aware routing can learn useful task-worker specialization and deliver a better cost-quality tradeoff than naive or fixed routing baselines**. It does **not** yet support the stronger claim that the method has a clear **dynamic worker-pool adaptation advantage** under perturbation, because the perturbation mostly targeted a worker that the router had already learned to avoid.
