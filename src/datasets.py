"""Dataset loading and fixed task stream construction."""

from __future__ import annotations

import argparse
import json
import os
import random
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Literal, Optional

import yaml
from datasets import load_dataset

TaskType = Literal["gsm8k", "humaneval"]


@dataclass
class Task:
    """One task in the mixed benchmark stream."""

    task_id: str
    task_type: TaskType
    prompt: str
    meta: Dict[str, Any]


def load_experiment_config(path: str) -> Dict[str, Any]:
    """Load the experiment YAML and return its raw dictionary."""

    with open(path, "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _gsm8k_to_task(row: Dict[str, Any], source_index: int) -> Task:
    prompt = row["question"].strip()
    return Task(
        task_id=f"gsm8k_{source_index}",
        task_type="gsm8k",
        prompt=prompt,
        meta={
            "answer_full": row["answer"],
            "source_index": source_index,
        },
    )


def _humaneval_to_task(row: Dict[str, Any], source_index: int) -> Task:
    return Task(
        task_id=f"humaneval_{row['task_id']}",
        task_type="humaneval",
        prompt=row["prompt"],
        meta={
            "test": row["test"],
            "entry_point": row["entry_point"],
            "source_index": source_index,
            "dataset_task_id": row["task_id"],
        },
    )


def build_task_stream(
    seed: int,
    total_tasks: int,
    n_humaneval: int,
    n_gsm8k: int,
    cache_dir: Optional[str] = None,
) -> List[Task]:
    """Build the fixed mixed benchmark stream from GSM8K and HumanEval."""

    if n_humaneval + n_gsm8k != total_tasks:
        raise ValueError("n_humaneval + n_gsm8k must equal total_tasks")

    rng = random.Random(seed)

    gsm8k = load_dataset("openai/gsm8k", "main", cache_dir=cache_dir)
    gsm_test = list(gsm8k["test"])
    indexed_gsm = list(enumerate(gsm_test))
    rng.shuffle(indexed_gsm)
    gsm_pick = indexed_gsm[:n_gsm8k]
    gsm_tasks = [_gsm8k_to_task(row, source_index) for source_index, row in gsm_pick]

    humaneval = load_dataset("openai/openai_humaneval", cache_dir=cache_dir)
    humaneval_rows = list(enumerate(humaneval["test"]))
    humaneval_tasks = [_humaneval_to_task(row, source_index) for source_index, row in humaneval_rows]
    if n_humaneval < len(humaneval_tasks):
        rng.shuffle(humaneval_tasks)
        humaneval_tasks = humaneval_tasks[:n_humaneval]

    tasks = gsm_tasks + humaneval_tasks
    rng.shuffle(tasks)
    return tasks


def save_task_stream(tasks: List[Task], path: str) -> None:
    """Persist the task stream as JSONL."""

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        for task in tasks:
            handle.write(json.dumps(asdict(task), ensure_ascii=False) + "\n")


def load_task_stream(path: str) -> List[Task]:
    """Load the task stream from JSONL."""

    tasks: List[Task] = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            payload = json.loads(line)
            tasks.append(Task(**payload))
    return tasks


def load_or_build_task_stream(config: Dict[str, Any], save: bool = True) -> List[Task]:
    """Load the persisted task stream if present, otherwise build and optionally save it."""

    experiment = config["experiment"]
    paths = config["paths"]
    task_stream_path = experiment["task_stream_path"]
    if not os.path.isabs(task_stream_path):
        task_stream_path = os.path.join(paths["repo_root"], task_stream_path)

    if os.path.exists(task_stream_path):
        return load_task_stream(task_stream_path)

    tasks = build_task_stream(
        seed=int(experiment["seed"]),
        total_tasks=int(experiment["total_tasks"]),
        n_humaneval=int(experiment["n_humaneval"]),
        n_gsm8k=int(experiment["n_gsm8k"]),
        cache_dir=paths.get("hf_cache"),
    )
    if save:
        save_task_stream(tasks, task_stream_path)
    return tasks


def main() -> None:
    """CLI for creating or previewing the task stream."""

    parser = argparse.ArgumentParser(description="Build the fixed 500-task stream.")
    parser.add_argument("--config", default="configs/experiment.yaml")
    parser.add_argument("--save", action="store_true", help="Persist the task stream JSONL.")
    parser.add_argument("--preview", type=int, default=5, help="Preview the first N tasks.")
    args = parser.parse_args()

    config = load_experiment_config(args.config)
    tasks = load_or_build_task_stream(config, save=args.save)

    print(f"Loaded {len(tasks)} tasks.")
    for task in tasks[: args.preview]:
        print(json.dumps(asdict(task), ensure_ascii=False)[:600])


if __name__ == "__main__":
    main()
