"""Plotting utilities for experiment outputs."""

from __future__ import annotations

import argparse
import os
from typing import Dict, List

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

METHOD_ORDER = ["random", "cost_first", "single_best", "ours"]
METHOD_LABELS = {
    "random": "Random",
    "cost_first": "Cost-first",
    "single_best": "Single-best",
    "ours": "Ours",
}


def rolling_mean(values: np.ndarray, window: int = 50) -> np.ndarray:
    """Compute a trailing rolling mean with a fixed window."""

    return pd.Series(values).rolling(window=window, min_periods=window).mean().to_numpy()


def load_method_frames(logs_dir: str) -> Dict[str, pd.DataFrame]:
    """Load method CSVs from the logs directory."""

    frames: Dict[str, pd.DataFrame] = {}
    for method in METHOD_ORDER:
        path = os.path.join(logs_dir, f"{method}_runs.csv")
        if os.path.exists(path):
            frames[method] = pd.read_csv(path)
    return frames


def plot_recovery_curve(frames: Dict[str, pd.DataFrame], out_path: str, perturb_t: int = 250, window: int = 50) -> None:
    """Plot rolling success against task index with the perturbation marker."""

    plt.figure(figsize=(8.5, 5.0))
    for method in METHOD_ORDER:
        frame = frames.get(method)
        if frame is None:
            continue
        y = rolling_mean(frame["success"].to_numpy(), window=window)
        plt.plot(frame["t"].to_numpy(), y, label=METHOD_LABELS[method], linewidth=2.0)
    plt.axvline(perturb_t, color="black", linestyle="--", linewidth=1.5, label="Perturbation")
    plt.xlabel("Task index")
    plt.ylabel(f"Rolling success (window={window})")
    plt.title("Recovery Curve")
    plt.legend()
    plt.grid(alpha=0.25)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    plt.tight_layout()
    plt.savefig(out_path, dpi=220)
    plt.close()


def plot_cost_quality_pareto(frames: Dict[str, pd.DataFrame], out_path: str) -> None:
    """Plot total cost vs average success for each method."""

    plt.figure(figsize=(7.0, 5.0))
    for method in METHOD_ORDER:
        frame = frames.get(method)
        if frame is None:
            continue
        total_cost = float(frame["cost_usd"].sum())
        avg_success = float(frame["success"].mean())
        plt.scatter(total_cost, avg_success, s=90)
        plt.annotate(METHOD_LABELS[method], (total_cost, avg_success), textcoords="offset points", xytext=(6, 6))
    plt.xlabel("Total cost (USD)")
    plt.ylabel("Average success")
    plt.title("Cost-Quality Pareto")
    plt.grid(alpha=0.25)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    plt.tight_layout()
    plt.savefig(out_path, dpi=220)
    plt.close()


def plot_baseline_compare(frames: Dict[str, pd.DataFrame], out_path: str) -> None:
    """Plot success, total cost, and average latency side by side."""

    methods: List[str] = [method for method in METHOD_ORDER if method in frames]
    labels = [METHOD_LABELS[method] for method in methods]
    success = [float(frames[method]["success"].mean()) for method in methods]
    cost = [float(frames[method]["cost_usd"].sum()) for method in methods]
    latency = [float(frames[method]["latency_ms"].mean()) for method in methods]

    x = np.arange(len(methods))
    fig, axes = plt.subplots(1, 3, figsize=(13.0, 4.2))

    axes[0].bar(x, success, color="#2a9d8f")
    axes[0].set_title("Average Success")
    axes[0].set_xticks(x, labels, rotation=20)
    axes[0].set_ylim(0.0, 1.0)

    axes[1].bar(x, cost, color="#e9c46a")
    axes[1].set_title("Total Cost (USD)")
    axes[1].set_xticks(x, labels, rotation=20)

    axes[2].bar(x, latency, color="#e76f51")
    axes[2].set_title("Average Latency (ms)")
    axes[2].set_xticks(x, labels, rotation=20)

    fig.suptitle("Baseline Comparison")
    for axis in axes:
        axis.grid(axis="y", alpha=0.25)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    fig.tight_layout()
    fig.savefig(out_path, dpi=220)
    plt.close(fig)


def generate_plots(logs_dir: str, out_dir: str, perturb_t: int = 250, window: int = 50) -> None:
    """Generate all required figures."""

    frames = load_method_frames(logs_dir)
    if not frames:
        raise FileNotFoundError(f"No per-method CSV logs found in {logs_dir}")

    os.makedirs(out_dir, exist_ok=True)
    plot_recovery_curve(frames, os.path.join(out_dir, "recovery_curve.png"), perturb_t=perturb_t, window=window)
    plot_cost_quality_pareto(frames, os.path.join(out_dir, "cost_quality_pareto.png"))
    plot_baseline_compare(frames, os.path.join(out_dir, "baseline_compare.png"))


def main() -> None:
    """CLI entrypoint for figure generation."""

    parser = argparse.ArgumentParser(description="Generate experiment figures.")
    parser.add_argument("--logs-dir", default="outputs/logs")
    parser.add_argument("--out-dir", default="outputs/figs")
    parser.add_argument("--perturb-t", type=int, default=250)
    parser.add_argument("--window", type=int, default=50)
    args = parser.parse_args()
    generate_plots(logs_dir=args.logs_dir, out_dir=args.out_dir, perturb_t=args.perturb_t, window=args.window)


if __name__ == "__main__":
    main()
