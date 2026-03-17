# Failure Analysis

- Ours mean success: 0.9300
- Ours total cost: 0.5283 USD
- Ours average latency: 11390.04 ms

## Worker Usage Distribution

| method | worker_id | usage_ratio |
| --- | --- | --- |
| random | deepseek_r1 | 0.244 |
| random | gemini25flash | 0.264 |
| random | haiku45 | 0.258 |
| random | qwen3_235b | 0.234 |
| cost_first | qwen3_235b | 1.0 |
| single_best | gemini25flash | 1.0 |
| ours | deepseek_r1 | 0.004 |
| ours | gemini25flash | 0.256 |
| ours | haiku45 | 0.12 |
| ours | qwen3_235b | 0.62 |

## Per-Task-Type Performance

| method | task_type | mean_success | avg_cost_usd | avg_latency_ms |
| --- | --- | --- | --- | --- |
| random | gsm8k | 0.9285714285714286 | 0.0015502650535714096 | 16053.458333333334 |
| random | humaneval | 0.7865853658536586 | 0.0026339368414633954 | 17456.969512195123 |
| cost_first | gsm8k | 0.9226190476190477 | 2.958538095238095e-05 | 7275.818452380952 |
| cost_first | humaneval | 0.8902439024390244 | 2.6778676829268294e-05 | 5859.207317073171 |
| single_best | gsm8k | 0.9404761904761905 | 0.0013161154761904565 | 4137.898809523809 |
| single_best | humaneval | 0.8902439024390244 | 0.002524321951219495 | 6571.8109756097565 |
| ours | gsm8k | 0.9345238095238095 | 0.00019824689583333247 | 13895.21130952381 |
| ours | humaneval | 0.9207317073170732 | 0.0028149409573170617 | 6257.506097560976 |

## Decomposition Usage

```json
{
  "trigger_rate": 0.048,
  "used_count": 24,
  "used_success": 0.9166666666666666,
  "used_avg_cost_usd": 0.0018767469166666624,
  "used_avg_latency_ms": 13628.375,
  "unused_success": 0.930672268907563,
  "unused_avg_cost_usd": 0.0010151666974789872,
  "unused_avg_latency_ms": 11277.186974789916
}
```

## Perturbation Before/After

| method | before_success | after_success | before_cost_usd | after_cost_usd | before_latency_ms | after_latency_ms | recovery_steps_to_95pct_pre |
| --- | --- | --- | --- | --- | --- | --- | --- |
| random | 0.896 | 0.868 | 0.0018691802879999787 | 0.0019422385119999832 | 16477.216 | 16550.404 | 50 |
| cost_first | 0.896 | 0.928 | 2.9266328e-05 | 2.8063236e-05 | 8102.692 | 5519.648 | 50 |
| single_best | 0.94 | 0.908 | 0.0016057655999999817 | 0.001819048799999981 | 4901.504 | 4970.94 | 63 |
| ours | 0.944 | 0.916 | 0.0010009314239999964 | 0.0011121136719999948 | 10029.564 | 12750.524 | 50 |

## Error Buckets

| method | task_type | failure_reason | count |
| --- | --- | --- | --- |
| random | gsm8k | parse_failure | 4 |
| random | gsm8k | wrong_answer | 20 |
| random | humaneval | runtime_error | 12 |
| random | humaneval | syntax_error | 15 |
| random | humaneval | wrong_answer | 8 |
| cost_first | gsm8k | parse_failure | 1 |
| cost_first | gsm8k | wrong_answer | 25 |
| cost_first | humaneval | runtime_error | 5 |
| cost_first | humaneval | syntax_error | 4 |
| cost_first | humaneval | wrong_answer | 9 |
| single_best | gsm8k | wrong_answer | 20 |
| single_best | humaneval | runtime_error | 7 |
| single_best | humaneval | syntax_error | 3 |
| single_best | humaneval | wrong_answer | 8 |
| ours | gsm8k | parse_failure | 1 |
| ours | gsm8k | wrong_answer | 21 |
| ours | humaneval | runtime_error | 4 |
| ours | humaneval | syntax_error | 2 |
| ours | humaneval | wrong_answer | 7 |

## Most Likely Reasons

- Ours improved over the baselines on the available metrics; no dominant failure pattern was detected.
