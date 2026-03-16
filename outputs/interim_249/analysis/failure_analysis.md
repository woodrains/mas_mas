# Failure Analysis

## Worker Usage Distribution

| method | worker_id | usage_ratio |
| --- | --- | --- |
| random | deepseek_r1 | 0.2289156626506024 |
| random | gemini25flash | 0.26104417670682734 |
| random | haiku45 | 0.26104417670682734 |
| random | qwen3_235b | 0.24899598393574296 |
| cost_first | qwen3_235b | 1.0 |

## Per-Task-Type Performance

| method | task_type | mean_success | avg_cost_usd | avg_latency_ms |
| --- | --- | --- | --- | --- |
| random | gsm8k | 0.9322033898305084 | 0.00150545249717512 | 15299.316384180791 |
| random | humaneval | 0.8055555555555556 | 0.0027662184722222014 | 19295.277777777777 |
| cost_first | gsm8k | 0.8421052631578947 | 3.383902631578947e-05 | 15734.236842105263 |
| cost_first | humaneval | 0.7391304347826086 | 2.4127173913043476e-05 | 7426.130434782609 |

## Decomposition Usage

No decomposition data available.

## Perturbation Before/After

| method | before_success | after_success | before_cost_usd | after_cost_usd | before_latency_ms | after_latency_ms | recovery_steps_to_95pct_pre |
| --- | --- | --- | --- | --- | --- | --- | --- |
| random | 0.8955823293172691 | nan | 0.0018700113333333123 | nan | 16454.775100401606 | nan | None |
| cost_first | 0.8032786885245902 | nan | 3.017718032786885e-05 | nan | 12601.672131147541 | nan | None |

## Error Buckets

| method | task_type | failure_reason | count |
| --- | --- | --- | --- |
| random | gsm8k | parse_failure | 1 |
| random | gsm8k | wrong_answer | 11 |
| random | humaneval | runtime_error | 4 |
| random | humaneval | syntax_error | 7 |
| random | humaneval | wrong_answer | 3 |
| cost_first | gsm8k | parse_failure | 1 |
| cost_first | gsm8k | wrong_answer | 5 |
| cost_first | humaneval | runtime_error | 2 |
| cost_first | humaneval | syntax_error | 3 |
| cost_first | humaneval | wrong_answer | 1 |

## Most Likely Reasons

- No `ours` run was found, so failure analysis for the router could not be completed.
