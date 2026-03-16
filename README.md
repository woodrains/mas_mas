# Capability-Aware Router Quick Validation

This repository implements the small-scale rapid validation experiment specified in the local research reports. It evaluates a capability-aware router against `random`, `cost-first`, and `single-best` baselines on a fixed 500-task stream built from GSM8K and HumanEval, with one mid-run worker perturbation.

Execution is token-safe by default:

- requests are sent one task at a time, not as a single 500-task batch
- each finished task is appended immediately to CSV/JSONL logs
- reruns resume from existing per-method logs instead of repeating finished tasks
- consecutive request failures trigger an early stop so a broken run does not keep burning API budget
- raw model outputs and OpenRouter payloads are archived under `outputs/raw/`

## Environment

Use the `mas` conda environment and keep all generated files inside this repository.

```bash
conda activate mas
export HF_HOME=/disk0/home/gaohaoyu/multi-agent-sys_2/.cache/huggingface
export SENTENCE_TRANSFORMERS_HOME=/disk0/home/gaohaoyu/multi-agent-sys_2/.cache/sentence_transformers
export MPLCONFIGDIR=/disk0/home/gaohaoyu/multi-agent-sys_2/.cache/matplotlib
python -m pip install -r requirements.txt
```

If `orjson` is unavailable, the code falls back to the standard `json` module, but installing all requirements is recommended.

## OpenRouter API Key

Copy `.env.example` to `.env` or export the variables directly:

```bash
export OPENROUTER_API_KEY="sk-or-..."
export APP_URL="http://localhost:8000"
export APP_TITLE="capability-router-exp"
```

The experiment requires a valid OpenRouter key for real runs.

## Reproduce The Experiment

1. Build the fixed task stream:

```bash
conda run -n mas python -m src.datasets --config configs/experiment.yaml --save
```

2. Run all methods:

```bash
conda run -n mas python -m src.run_experiment --config configs/experiment.yaml --workers configs/workers.yaml --method all
```

If the process is interrupted, rerun the same command. The runner resumes from the last completed task for each method.

3. Generate figures:

```bash
conda run -n mas python -m src.plotting --logs-dir outputs/logs --out-dir outputs/figs
```

4. Run statistical tests and summary tables:

```bash
conda run -n mas python -m src.stats_tests --logs-dir outputs/logs --out-dir outputs/stats
```

5. Generate failure analysis:

```bash
conda run -n mas python -m src.analyze_failures --logs-dir outputs/logs --stats-dir outputs/stats --out-dir outputs/analysis
```

## Single Command Flow

You can also run the full pipeline from the experiment runner:

```bash
conda run -n mas python -m src.run_experiment \
  --config configs/experiment.yaml \
  --workers configs/workers.yaml \
  --method all \
  --build-reports
```

## Results

Expected outputs:

- Logs: `outputs/logs/runs.csv`, `outputs/logs/runs.jsonl`, and per-method `*_runs.csv/jsonl`
- Raw responses: `outputs/raw/<method>/...json`
- Figures:
  - `outputs/figs/recovery_curve.png`
  - `outputs/figs/cost_quality_pareto.png`
  - `outputs/figs/baseline_compare.png`
- Stats:
  - `outputs/stats/summary.csv`
  - `outputs/stats/summary.md`
  - `outputs/stats/significance_tests.json`
  - `outputs/stats/significance_tests.md`
- Failure analysis:
  - `outputs/analysis/failure_analysis.md`
  - supporting CSV/JSON files under `outputs/analysis/`

## Experiment Controls

- Disable decomposition: set `experiment.enable_decomposition: false` in [configs/experiment.yaml](/disk0/home/gaohaoyu/multi-agent-sys_2/configs/experiment.yaml).
- Change perturbation settings: edit the `perturbation` block in [configs/experiment.yaml](/disk0/home/gaohaoyu/multi-agent-sys_2/configs/experiment.yaml).
- Change the fixed worker for `single-best`: edit `fixed_single_best_worker` in [configs/experiment.yaml](/disk0/home/gaohaoyu/multi-agent-sys_2/configs/experiment.yaml).
- Change resume / chunk / failure guard behavior: edit the `execution` block in [configs/experiment.yaml](/disk0/home/gaohaoyu/multi-agent-sys_2/configs/experiment.yaml).

## HumanEval Safety

HumanEval executes model-generated Python code. The default executor uses Docker with:

- `--network none`
- `--read-only`
- CPU / memory / PID limits
- timeout enforcement

If Docker is unavailable, the evaluator falls back to a local subprocess sandbox and emits a warning. Docker is strongly recommended.
