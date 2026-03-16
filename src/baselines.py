"""Baseline routing policies."""

from __future__ import annotations

from typing import Dict, List, Tuple

import numpy as np

from .datasets import Task
from .openrouter_client import WorkerConfig


def random_routing(task: Task, worker_ids: List[str], rng: np.random.Generator) -> Tuple[str, bool]:
    """Pick a worker uniformly at random."""

    del task
    return str(rng.choice(worker_ids)), False


def cost_first_routing(task: Task, workers: Dict[str, WorkerConfig]) -> Tuple[str, bool]:
    """Pick the cheapest worker, with one simple long-context exception for Gemini."""

    cheapest = min(
        workers.values(),
        key=lambda worker: worker.price_usd_per_m_input + worker.price_usd_per_m_output,
    )
    if len(task.prompt) > 6000 and "gemini25flash" in workers:
        return "gemini25flash", False
    return cheapest.worker_id, False


def single_best_routing(fixed_worker_id: str) -> Tuple[str, bool]:
    """Always use one configured worker."""

    return fixed_worker_id, False
