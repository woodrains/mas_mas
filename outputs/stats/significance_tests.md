# Experiment Summary

| method | mean_success | total_cost_usd | avg_latency_ms | vs_random_success_abs | vs_random_success_rel | vs_random_cost_abs | vs_random_cost_rel | vs_random_latency_abs | vs_random_latency_rel | vs_cost_first_success_abs | vs_cost_first_success_rel | vs_cost_first_cost_abs | vs_cost_first_cost_rel | vs_cost_first_latency_abs | vs_cost_first_latency_rel | vs_single_best_success_abs | vs_single_best_success_rel | vs_single_best_cost_abs | vs_single_best_cost_rel | vs_single_best_latency_abs | vs_single_best_latency_rel |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| random | 0.882 | 0.9528546999999905 | 16513.81 | nan | nan | nan | nan | nan | nan | nan | nan | nan | nan | nan | nan | nan | nan | nan | nan | nan | nan |
| cost_first | 0.912 | 0.014332391 | 6811.17 | nan | nan | nan | nan | nan | nan | nan | nan | nan | nan | nan | nan | nan | nan | nan | nan | nan | nan |
| single_best | 0.924 | 0.8562035999999905 | 4936.222 | nan | nan | nan | nan | nan | nan | nan | nan | nan | nan | nan | nan | nan | nan | nan | nan | nan | nan |
| ours | 0.93 | 0.5282612739999978 | 11390.044 | 0.04800000000000004 | 0.05442176870748304 | 0.4245934259999927 | 0.4456014395479153 | 5123.766000000001 | 0.3102715848129536 | 0.018000000000000016 | 0.019736842105263174 | -0.5139288829999977 | -35.857860910995086 | -4578.874 | -0.6722595383759324 | 0.006000000000000005 | 0.006493506493506499 | 0.32794232599999273 | 0.3830190926550605 | -6453.822 | -1.3074416020997435 |

# Significance Tests

## ours_vs_random

```json
{
  "success_bootstrap": {
    "observed_diff": 0.048,
    "ci_95": [
      0.02,
      0.078
    ],
    "p_value": 0.0012,
    "n_boot": 5000
  },
  "mcnemar": {
    "table": [
      [
        427,
        38
      ],
      [
        14,
        21
      ]
    ],
    "p_value": 0.0011951203200073481
  },
  "cost_wilcoxon": {
    "stat": 28024.0,
    "p_value": 3.327824015695394e-24
  },
  "latency_wilcoxon": {
    "stat": 54138.5,
    "p_value": 0.00865197603427223
  }
}
```

## ours_vs_cost_first

```json
{
  "success_bootstrap": {
    "observed_diff": 0.018,
    "ci_95": [
      -0.004049999999999983,
      0.04
    ],
    "p_value": 0.1388,
    "n_boot": 5000
  },
  "mcnemar": {
    "table": [
      [
        444,
        21
      ],
      [
        12,
        23
      ]
    ],
    "p_value": 0.16275565745308995
  },
  "cost_wilcoxon": {
    "stat": 18830.5,
    "p_value": 5.7944562533178085e-34
  },
  "latency_wilcoxon": {
    "stat": 46452.5,
    "p_value": 5.63390701223193e-07
  }
}
```

## ours_vs_single_best

```json
{
  "success_bootstrap": {
    "observed_diff": 0.006,
    "ci_95": [
      -0.014,
      0.028
    ],
    "p_value": 0.6348,
    "n_boot": 5000
  },
  "mcnemar": {
    "table": [
      [
        449,
        16
      ],
      [
        13,
        22
      ]
    ],
    "p_value": 0.711071103811264
  },
  "cost_wilcoxon": {
    "stat": 22381.0,
    "p_value": 1.0371266309676785e-34
  },
  "latency_wilcoxon": {
    "stat": 37537.5,
    "p_value": 8.397218818924446e-15
  }
}
```
