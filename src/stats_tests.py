"""Summary tables and statistical significance tests."""

from __future__ import annotations

import argparse
import json
import os
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd
from scipy.stats import wilcoxon
from statsmodels.stats.contingency_tables import mcnemar

METHOD_ORDER = ["random", "cost_first", "single_best", "ours"]
BASELINES = ["random", "cost_first", "single_best"]


def paired_bootstrap_diff(x: np.ndarray, y: np.ndarray, n_boot: int = 5000, seed: int = 0) -> Dict[str, Any]:
    """Paired bootstrap for the mean difference x - y."""

    rng = np.random.default_rng(seed)
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if x.shape != y.shape:
        raise ValueError("paired_bootstrap_diff expects arrays of identical shape")

    diffs = np.empty(n_boot, dtype=float)
    n = x.shape[0]
    for i in range(n_boot):
        idx = rng.integers(0, n, size=n)
        diffs[i] = float(np.mean(x[idx] - y[idx]))
    observed = float(np.mean(x - y))
    p_value = float(2.0 * min(np.mean(diffs <= 0.0), np.mean(diffs >= 0.0)))
    return {
        "observed_diff": observed,
        "ci_95": [float(np.quantile(diffs, 0.025)), float(np.quantile(diffs, 0.975))],
        "p_value": p_value,
        "n_boot": n_boot,
    }


def mcnemar_test(success_a: np.ndarray, success_b: np.ndarray) -> Dict[str, Any]:
    """Exact McNemar test on paired binary outcomes."""

    a = np.asarray(success_a, dtype=int)
    b = np.asarray(success_b, dtype=int)
    table = [
        [int(np.sum((a == 1) & (b == 1))), int(np.sum((a == 1) & (b == 0)))],
        [int(np.sum((a == 0) & (b == 1))), int(np.sum((a == 0) & (b == 0)))],
    ]
    result = mcnemar(table, exact=True)
    return {"table": table, "p_value": float(result.pvalue)}


def wilcoxon_test(metric_a: np.ndarray, metric_b: np.ndarray) -> Dict[str, Any]:
    """Two-sided paired Wilcoxon signed-rank test."""

    stat, p_value = wilcoxon(metric_a, metric_b, zero_method="wilcox", alternative="two-sided")
    return {"stat": float(stat), "p_value": float(p_value)}


def load_method_frames(logs_dir: str) -> Dict[str, pd.DataFrame]:
    """Load all available per-method run logs."""

    frames: Dict[str, pd.DataFrame] = {}
    for method in METHOD_ORDER:
        path = os.path.join(logs_dir, f"{method}_runs.csv")
        if os.path.exists(path):
            frames[method] = pd.read_csv(path).sort_values("task_id").reset_index(drop=True)
    return frames


def dataframe_to_markdown(frame: pd.DataFrame) -> str:
    """Render a simple Markdown table without requiring tabulate."""

    if frame.empty:
        return "_Empty table_"
    columns = list(frame.columns)
    header = "| " + " | ".join(columns) + " |"
    separator = "| " + " | ".join(["---"] * len(columns)) + " |"
    rows = []
    for _, record in frame.iterrows():
        rows.append("| " + " | ".join(str(record[column]) for column in columns) + " |")
    return "\n".join([header, separator, *rows])


def _aligned_pair(frames: Dict[str, pd.DataFrame], left: str, right: str) -> Tuple[pd.DataFrame, pd.DataFrame]:
    left_frame = frames[left].sort_values("task_id").reset_index(drop=True)
    right_frame = frames[right].sort_values("task_id").reset_index(drop=True)
    if list(left_frame["task_id"]) != list(right_frame["task_id"]):
        raise ValueError(f"Task alignment mismatch between {left} and {right}")
    return left_frame, right_frame


def build_summary(frames: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Create the required summary table."""

    records: List[Dict[str, Any]] = []
    ours = frames.get("ours")
    for method in METHOD_ORDER:
        frame = frames.get(method)
        if frame is None:
            continue
        record: Dict[str, Any] = {
            "method": method,
            "mean_success": float(frame["success"].mean()),
            "total_cost_usd": float(frame["cost_usd"].sum()),
            "avg_latency_ms": float(frame["latency_ms"].mean()),
        }
        if ours is not None and method == "ours":
            for baseline in BASELINES:
                baseline_frame = frames.get(baseline)
                if baseline_frame is None:
                    continue
                ours_success = float(ours["success"].mean())
                baseline_success = float(baseline_frame["success"].mean())
                ours_cost = float(ours["cost_usd"].sum())
                baseline_cost = float(baseline_frame["cost_usd"].sum())
                ours_latency = float(ours["latency_ms"].mean())
                baseline_latency = float(baseline_frame["latency_ms"].mean())

                record[f"vs_{baseline}_success_abs"] = ours_success - baseline_success
                record[f"vs_{baseline}_success_rel"] = (
                    (ours_success - baseline_success) / baseline_success if baseline_success else np.nan
                )
                record[f"vs_{baseline}_cost_abs"] = baseline_cost - ours_cost
                record[f"vs_{baseline}_cost_rel"] = (
                    (baseline_cost - ours_cost) / baseline_cost if baseline_cost else np.nan
                )
                record[f"vs_{baseline}_latency_abs"] = baseline_latency - ours_latency
                record[f"vs_{baseline}_latency_rel"] = (
                    (baseline_latency - ours_latency) / baseline_latency if baseline_latency else np.nan
                )
        records.append(record)
    return pd.DataFrame.from_records(records)


def run_significance_tests(frames: Dict[str, pd.DataFrame]) -> Dict[str, Any]:
    """Run all required tests for ours vs each baseline."""

    if "ours" not in frames:
        return {}

    results: Dict[str, Any] = {}
    for baseline in BASELINES:
        if baseline not in frames:
            continue
        ours_frame, baseline_frame = _aligned_pair(frames, "ours", baseline)
        results[f"ours_vs_{baseline}"] = {
            "success_bootstrap": paired_bootstrap_diff(
                ours_frame["success"].to_numpy(),
                baseline_frame["success"].to_numpy(),
            ),
            "mcnemar": mcnemar_test(
                ours_frame["success"].to_numpy(),
                baseline_frame["success"].to_numpy(),
            ),
            "cost_wilcoxon": wilcoxon_test(
                ours_frame["cost_usd"].to_numpy(),
                baseline_frame["cost_usd"].to_numpy(),
            ),
            "latency_wilcoxon": wilcoxon_test(
                ours_frame["latency_ms"].to_numpy(),
                baseline_frame["latency_ms"].to_numpy(),
            ),
        }
    return results


def write_markdown_summary(summary: pd.DataFrame, significance: Dict[str, Any], path: str) -> None:
    """Write summary metrics and significance results in Markdown."""

    lines: List[str] = ["# Experiment Summary", "", dataframe_to_markdown(summary), "", "# Significance Tests", ""]
    if significance:
        for pair_name, payload in significance.items():
            lines.append(f"## {pair_name}")
            lines.append("")
            lines.append("```json")
            lines.append(json.dumps(payload, indent=2, ensure_ascii=False))
            lines.append("```")
            lines.append("")
    else:
        lines.append("No `ours` results were found, so pairwise significance tests were skipped.")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))


def generate_stats(logs_dir: str, out_dir: str) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Generate summary CSV/Markdown plus significance JSON/Markdown."""

    os.makedirs(out_dir, exist_ok=True)
    frames = load_method_frames(logs_dir)
    if not frames:
        raise FileNotFoundError(f"No per-method CSV logs found in {logs_dir}")

    summary = build_summary(frames)
    significance = run_significance_tests(frames)

    summary.to_csv(os.path.join(out_dir, "summary.csv"), index=False)
    with open(os.path.join(out_dir, "significance_tests.json"), "w", encoding="utf-8") as handle:
        json.dump(significance, handle, indent=2, ensure_ascii=False)
    write_markdown_summary(summary, significance, os.path.join(out_dir, "summary.md"))
    write_markdown_summary(summary, significance, os.path.join(out_dir, "significance_tests.md"))
    return summary, significance


def main() -> None:
    """CLI entrypoint for statistical reporting."""

    parser = argparse.ArgumentParser(description="Generate summary tables and statistical tests.")
    parser.add_argument("--logs-dir", default="outputs/logs")
    parser.add_argument("--out-dir", default="outputs/stats")
    args = parser.parse_args()
    generate_stats(logs_dir=args.logs_dir, out_dir=args.out_dir)


if __name__ == "__main__":
    main()
