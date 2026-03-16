"""Failure analysis and diagnostic summaries."""

from __future__ import annotations

import argparse
import json
import os
from typing import Any, Dict, List

import numpy as np
import pandas as pd

METHOD_ORDER = ["random", "cost_first", "single_best", "ours"]


def load_method_frames(logs_dir: str) -> Dict[str, pd.DataFrame]:
    """Load all available per-method run logs."""

    frames: Dict[str, pd.DataFrame] = {}
    for method in METHOD_ORDER:
        path = os.path.join(logs_dir, f"{method}_runs.csv")
        if os.path.exists(path):
            frames[method] = pd.read_csv(path)
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


def worker_usage_distribution(frames: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Return worker usage ratios by method."""

    records: List[Dict[str, Any]] = []
    for method, frame in frames.items():
        counts = frame["worker_id"].value_counts(normalize=True).sort_index()
        for worker_id, ratio in counts.items():
            records.append({"method": method, "worker_id": worker_id, "usage_ratio": float(ratio)})
    return pd.DataFrame.from_records(records)


def per_task_type_performance(frames: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Return success, cost, and latency aggregated by task type."""

    records: List[Dict[str, Any]] = []
    for method, frame in frames.items():
        grouped = frame.groupby("task_type")
        for task_type, group in grouped:
            records.append(
                {
                    "method": method,
                    "task_type": task_type,
                    "mean_success": float(group["success"].mean()),
                    "avg_cost_usd": float(group["cost_usd"].mean()),
                    "avg_latency_ms": float(group["latency_ms"].mean()),
                }
            )
    return pd.DataFrame.from_records(records)


def decomposition_usage_analysis(frame: pd.DataFrame) -> Dict[str, Any]:
    """Summarize decomposition usage and outcomes for the router."""

    if frame.empty or "decomp_used" not in frame:
        return {}
    used = frame[frame["decomp_used"] == 1]
    skipped = frame[frame["decomp_used"] == 0]
    return {
        "trigger_rate": float(frame["decomp_used"].mean()),
        "used_count": int(len(used)),
        "used_success": float(used["success"].mean()) if not used.empty else None,
        "used_avg_cost_usd": float(used["cost_usd"].mean()) if not used.empty else None,
        "used_avg_latency_ms": float(used["latency_ms"].mean()) if not used.empty else None,
        "unused_success": float(skipped["success"].mean()) if not skipped.empty else None,
        "unused_avg_cost_usd": float(skipped["cost_usd"].mean()) if not skipped.empty else None,
        "unused_avg_latency_ms": float(skipped["latency_ms"].mean()) if not skipped.empty else None,
    }


def perturbation_comparison(frames: Dict[str, pd.DataFrame], trigger_t: int = 250) -> pd.DataFrame:
    """Compare performance before and after the perturbation."""

    records: List[Dict[str, Any]] = []
    for method, frame in frames.items():
        before = frame[frame["t"] <= trigger_t]
        after = frame[frame["t"] > trigger_t]
        target = float(before["success"].mean() * 0.95) if not before.empty else 0.0
        rolling = after["success"].rolling(window=50, min_periods=50).mean().to_numpy()
        recovery_idx = None
        if rolling.size:
            reached = np.where(rolling >= target)[0]
            if reached.size:
                recovery_idx = int(reached[0] + 1)
        records.append(
            {
                "method": method,
                "before_success": float(before["success"].mean()) if not before.empty else np.nan,
                "after_success": float(after["success"].mean()) if not after.empty else np.nan,
                "before_cost_usd": float(before["cost_usd"].mean()) if not before.empty else np.nan,
                "after_cost_usd": float(after["cost_usd"].mean()) if not after.empty else np.nan,
                "before_latency_ms": float(before["latency_ms"].mean()) if not before.empty else np.nan,
                "after_latency_ms": float(after["latency_ms"].mean()) if not after.empty else np.nan,
                "recovery_steps_to_95pct_pre": recovery_idx,
            }
        )
    return pd.DataFrame.from_records(records)


def error_bucket_analysis(frames: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Summarize failure reasons by method and task type."""

    records: List[Dict[str, Any]] = []
    for method, frame in frames.items():
        failures = frame[frame["success"] == 0]
        grouped = failures.groupby(["task_type", "failure_reason"])
        for (task_type, failure_reason), group in grouped:
            records.append(
                {
                    "method": method,
                    "task_type": task_type,
                    "failure_reason": failure_reason,
                    "count": int(len(group)),
                }
            )
    return pd.DataFrame.from_records(records)


def likely_failure_reasons(
    frames: Dict[str, pd.DataFrame],
    task_type_df: pd.DataFrame,
    perturb_df: pd.DataFrame,
    error_df: pd.DataFrame,
    decomp_summary: Dict[str, Any],
) -> List[str]:
    """Generate evidence-based likely failure reasons if ours does not improve."""

    reasons: List[str] = []
    if "ours" not in frames:
        return ["No `ours` run was found, so failure analysis for the router could not be completed."]

    ours = frames["ours"]
    best_baseline = None
    best_success = -1.0
    for method, frame in frames.items():
        if method == "ours":
            continue
        success = float(frame["success"].mean())
        if success > best_success:
            best_success = success
            best_baseline = method

    ours_success = float(ours["success"].mean())
    if best_baseline is not None and ours_success <= best_success:
        usage_ratio = float(ours["worker_id"].value_counts(normalize=True).iloc[0])
        if usage_ratio >= 0.65:
            dominant_worker = str(ours["worker_id"].value_counts(normalize=True).index[0])
            reasons.append(
                f"Router collapsed toward `{dominant_worker}` with usage ratio {usage_ratio:.2f}, which weakens the benefit of a heterogeneous worker pool."
            )

        ours_pert = perturb_df.loc[perturb_df["method"] == "ours"].iloc[0]
        best_pert = perturb_df.loc[perturb_df["method"] == best_baseline].iloc[0]
        if float(ours_pert["after_success"]) < float(best_pert["after_success"]):
            reasons.append(
                f"Post-perturbation success for `ours` ({float(ours_pert['after_success']):.3f}) lagged behind `{best_baseline}` ({float(best_pert['after_success']):.3f}), so adaptation after the DeepSeek drift was too slow."
            )

        if decomp_summary and decomp_summary.get("trigger_rate", 0.0) > 0.15:
            used_success = decomp_summary.get("used_success")
            unused_success = decomp_summary.get("unused_success")
            if used_success is not None and unused_success is not None and used_success <= unused_success:
                reasons.append(
                    f"Decomposition triggered on {decomp_summary['trigger_rate']:.2%} of tasks but its success ({used_success:.3f}) did not beat non-decomposition cases ({unused_success:.3f})."
                )

        ours_task = task_type_df[task_type_df["method"] == "ours"].set_index("task_type")
        best_task = task_type_df[task_type_df["method"] == best_baseline].set_index("task_type")
        for task_type in ("gsm8k", "humaneval"):
            if task_type in ours_task.index and task_type in best_task.index:
                diff = float(ours_task.loc[task_type, "mean_success"] - best_task.loc[task_type, "mean_success"])
                if diff < -0.03:
                    reasons.append(
                        f"`ours` underperformed `{best_baseline}` on `{task_type}` by {diff:.3f}, suggesting the router did not learn the right task-specific worker mapping."
                    )

        ours_errors = error_df[error_df["method"] == "ours"].sort_values("count", ascending=False)
        if not ours_errors.empty:
            top_error = ours_errors.iloc[0]
            reasons.append(
                f"The largest failure bucket for `ours` was `{top_error['failure_reason']}` on `{top_error['task_type']}` with {int(top_error['count'])} cases."
            )

    return reasons[:5]


def render_markdown(
    frames: Dict[str, pd.DataFrame],
    usage_df: pd.DataFrame,
    task_type_df: pd.DataFrame,
    perturb_df: pd.DataFrame,
    error_df: pd.DataFrame,
    decomp_summary: Dict[str, Any],
    reasons: List[str],
) -> str:
    """Build the final Markdown failure analysis report."""

    summary_lines: List[str] = ["# Failure Analysis", ""]
    if "ours" in frames:
        ours_success = float(frames["ours"]["success"].mean())
        summary_lines.append(f"- Ours mean success: {ours_success:.4f}")
        summary_lines.append(f"- Ours total cost: {float(frames['ours']['cost_usd'].sum()):.4f} USD")
        summary_lines.append(f"- Ours average latency: {float(frames['ours']['latency_ms'].mean()):.2f} ms")
        summary_lines.append("")

    summary_lines.append("## Worker Usage Distribution")
    summary_lines.append("")
    summary_lines.append(dataframe_to_markdown(usage_df) if not usage_df.empty else "No usage data available.")
    summary_lines.append("")

    summary_lines.append("## Per-Task-Type Performance")
    summary_lines.append("")
    summary_lines.append(dataframe_to_markdown(task_type_df) if not task_type_df.empty else "No task-type data available.")
    summary_lines.append("")

    summary_lines.append("## Decomposition Usage")
    summary_lines.append("")
    if decomp_summary:
        summary_lines.append("```json")
        summary_lines.append(json.dumps(decomp_summary, indent=2, ensure_ascii=False))
        summary_lines.append("```")
    else:
        summary_lines.append("No decomposition data available.")
    summary_lines.append("")

    summary_lines.append("## Perturbation Before/After")
    summary_lines.append("")
    summary_lines.append(dataframe_to_markdown(perturb_df) if not perturb_df.empty else "No perturbation comparison available.")
    summary_lines.append("")

    summary_lines.append("## Error Buckets")
    summary_lines.append("")
    summary_lines.append(dataframe_to_markdown(error_df) if not error_df.empty else "No failures recorded.")
    summary_lines.append("")

    summary_lines.append("## Most Likely Reasons")
    summary_lines.append("")
    if reasons:
        for reason in reasons:
            summary_lines.append(f"- {reason}")
    else:
        summary_lines.append("- Ours improved over the baselines on the available metrics; no dominant failure pattern was detected.")

    return "\n".join(summary_lines) + "\n"


def generate_failure_analysis(logs_dir: str, stats_dir: str, out_dir: str, trigger_t: int = 250) -> None:
    """Generate all failure-analysis artifacts."""

    del stats_dir
    os.makedirs(out_dir, exist_ok=True)
    frames = load_method_frames(logs_dir)
    if not frames:
        raise FileNotFoundError(f"No per-method CSV logs found in {logs_dir}")

    usage_df = worker_usage_distribution(frames)
    task_type_df = per_task_type_performance(frames)
    perturb_df = perturbation_comparison(frames, trigger_t=trigger_t)
    error_df = error_bucket_analysis(frames)
    decomp_summary = decomposition_usage_analysis(frames.get("ours", pd.DataFrame()))
    reasons = likely_failure_reasons(frames, task_type_df, perturb_df, error_df, decomp_summary)

    usage_df.to_csv(os.path.join(out_dir, "worker_usage_distribution.csv"), index=False)
    task_type_df.to_csv(os.path.join(out_dir, "per_task_type_performance.csv"), index=False)
    perturb_df.to_csv(os.path.join(out_dir, "perturbation_before_after.csv"), index=False)
    error_df.to_csv(os.path.join(out_dir, "error_buckets.csv"), index=False)
    with open(os.path.join(out_dir, "decomposition_usage.json"), "w", encoding="utf-8") as handle:
        json.dump(decomp_summary, handle, indent=2, ensure_ascii=False)
    with open(os.path.join(out_dir, "failure_analysis.md"), "w", encoding="utf-8") as handle:
        handle.write(render_markdown(frames, usage_df, task_type_df, perturb_df, error_df, decomp_summary, reasons))


def main() -> None:
    """CLI entrypoint for failure analysis."""

    parser = argparse.ArgumentParser(description="Generate failure analysis artifacts.")
    parser.add_argument("--logs-dir", default="outputs/logs")
    parser.add_argument("--stats-dir", default="outputs/stats")
    parser.add_argument("--out-dir", default="outputs/analysis")
    parser.add_argument("--perturb-t", type=int, default=250)
    args = parser.parse_args()
    generate_failure_analysis(
        logs_dir=args.logs_dir,
        stats_dir=args.stats_dir,
        out_dir=args.out_dir,
        trigger_t=args.perturb_t,
    )


if __name__ == "__main__":
    main()
