"""Experiment entrypoint for running all routing methods with resume support."""

from __future__ import annotations

import argparse
import csv
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import yaml
from tqdm import tqdm

from .analyze_failures import generate_failure_analysis
from .baselines import cost_first_routing, random_routing, single_best_routing
from .datasets import Task, load_or_build_task_stream
from .eval_gsm8k import evaluate_gsm8k_response
from .eval_humaneval import humaneval_is_correct
from .openrouter_client import OpenRouterClient, WorkerConfig, compute_cost_fallback, load_workers_config
from .plotting import generate_plots
from .router import CapabilityRouter, TaskFeatures, build_decomp_prompt
from .stats_tests import generate_stats

METHODS = ["random", "cost_first", "single_best", "ours"]
SYSTEM_PROMPT = (
    "You are a careful problem solver.\n"
    "Rules:\n"
    "1. For GSM8K, the final line must be exactly `FINAL: <number>`.\n"
    "2. For HumanEval, output only raw Python code with no markdown and no explanation.\n"
    "3. Do not mention hidden reasoning.\n"
)
_PERTURBATION_WARNED_WORKERS: set[str] = set()


@dataclass
class RunRow:
    """One aggregated task-level log row."""

    t: int
    task_id: str
    task_type: str
    method: str
    worker_id: str
    model_id: str
    request_id: str
    success: int
    failure_reason: str
    format_ok: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_ms: int
    cost_usd: float
    cost_source: str
    cost_exact_usd: Optional[float]
    cost_fallback_usd: float
    decomp_used: int
    decomp_request_id: str
    raw_output_path: str
    planner_raw_output_path: str
    timestamp: int


ROW_FIELDNAMES = list(RunRow.__annotations__.keys())


def load_config(path: str) -> Dict[str, Any]:
    """Load experiment configuration from YAML."""

    with open(path, "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def ensure_paths(config: Dict[str, Any]) -> None:
    """Prepare output and cache directories and export local cache env vars."""

    paths = config["paths"]
    for key in (
        "hf_cache",
        "st_cache",
        "mpl_cache",
        "outputs_logs",
        "outputs_figs",
        "outputs_stats",
        "outputs_analysis",
        "outputs_raw",
    ):
        os.makedirs(paths[key], exist_ok=True)
    os.makedirs(os.path.join(paths["repo_root"], ".cache", "humaneval"), exist_ok=True)
    os.environ.setdefault("HF_HOME", paths["hf_cache"])
    os.environ.setdefault("SENTENCE_TRANSFORMERS_HOME", paths["st_cache"])
    os.environ.setdefault("MPLCONFIGDIR", paths["mpl_cache"])


def safe_name(value: str) -> str:
    """Sanitize a string for use in filenames."""

    return "".join(char if char.isalnum() or char in ("-", "_") else "_" for char in value)


def make_user_prompt(task: Task, plan_text: str = "") -> str:
    """Build the solver prompt for one task."""

    plan_section = f"\n\nPLAN:\n{plan_text.strip()}\n" if plan_text.strip() else ""
    if task.task_type == "gsm8k":
        return (
            "Solve the following math word problem.\n"
            "You may reason internally, but the last line must be exactly `FINAL: <number>`.\n\n"
            f"Question:\n{task.prompt}{plan_section}"
        )
    return (
        "Complete the following Python function.\n"
        "Output only valid Python code.\n\n"
        f"{task.prompt}{plan_section}"
    )


def build_messages(task: Task, plan_text: str = "") -> List[Dict[str, str]]:
    """Create chat messages for one task."""

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": make_user_prompt(task, plan_text=plan_text)},
    ]


def apply_perturbation_if_needed(
    t: int,
    workers: Dict[str, WorkerConfig],
    router: Optional[CapabilityRouter],
    config: Dict[str, Any],
) -> None:
    """Apply the single mid-run worker perturbation from the protocol."""

    perturbation = config["perturbation"]
    if not perturbation.get("enabled", True):
        return
    if t != int(perturbation["trigger_t"]):
        return

    target_worker = workers[perturbation["target_worker"]]
    target_worker.params["max_tokens"] = int(perturbation["max_tokens_after"])
    target_worker.params["reasoning"] = sanitize_reasoning_override(
        worker=target_worker,
        reasoning_override=perturbation["reasoning_after"],
    )
    if router is not None:
        router.forget_decay = float(perturbation["router_forget_decay_after"])


def sanitize_reasoning_override(worker: WorkerConfig, reasoning_override: Dict[str, Any]) -> Dict[str, Any]:
    """Avoid provider-invalid reasoning settings during the planned worker perturbation."""

    override = dict(reasoning_override or {})
    if (
        worker.worker_id == "deepseek_r1"
        and isinstance(override.get("enabled"), bool)
        and override["enabled"] is False
    ):
        override["enabled"] = True
        if worker.worker_id not in _PERTURBATION_WARNED_WORKERS:
            print(
                "[perturbation-warning] deepseek_r1 requires reasoning to stay enabled on OpenRouter; "
                "keeping reasoning.enabled=true and applying only the max_tokens reduction."
            )
            _PERTURBATION_WARNED_WORKERS.add(worker.worker_id)
    return override


def pick_worker(
    method: str,
    task: Task,
    t: int,
    rng: np.random.Generator,
    workers: Dict[str, WorkerConfig],
    router: Optional[CapabilityRouter],
    fixed_single_best_worker: str,
) -> Tuple[str, bool, Dict[str, float], Optional[TaskFeatures]]:
    """Select the execution worker for the given method."""

    if method == "ours":
        assert router is not None
        worker_id, need_decomp, scores, features = router.choose_worker(task=task, t=t, rng=rng)
        return worker_id, need_decomp, scores, features
    if method == "random":
        worker_id, need_decomp = random_routing(task, list(workers.keys()), rng)
        return worker_id, need_decomp, {}, None
    if method == "cost_first":
        worker_id, need_decomp = cost_first_routing(task, workers)
        return worker_id, need_decomp, {}, None
    if method == "single_best":
        worker_id, need_decomp = single_best_routing(fixed_single_best_worker)
        return worker_id, need_decomp, {}, None
    raise ValueError(f"Unknown method: {method}")


def usage_from_sources(
    response_usage: Dict[str, Any],
    generation_usage: Dict[str, Any],
) -> Dict[str, int]:
    """Prefer precise usage from generation stats and fall back to response usage."""

    usage = dict(response_usage or {})
    if generation_usage:
        usage.update({key: int(value) for key, value in generation_usage.items() if isinstance(value, (int, float))})
    prompt_tokens = int(usage.get("prompt_tokens", 0))
    completion_tokens = int(usage.get("completion_tokens", 0))
    total_tokens = int(usage.get("total_tokens", prompt_tokens + completion_tokens))
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }


def execute_request(
    client: OpenRouterClient,
    worker: WorkerConfig,
    messages: List[Dict[str, str]],
) -> Dict[str, Any]:
    """Call one worker and return normalized usage and cost fields."""

    response = client.chat(model=worker.model, messages=messages, **worker.params)
    generation_stats = None
    precise_cost = None
    precise_usage: Dict[str, Any] = {}
    try:
        generation_stats = client.fetch_generation_stats(response.request_id)
        precise_cost, precise_usage = client.extract_cost_and_usage(generation_stats)
    except Exception:
        generation_stats = None

    usage = usage_from_sources(response.usage, precise_usage)
    fallback_cost = compute_cost_fallback(response.usage, worker)
    total_cost = float(precise_cost) if precise_cost is not None else float(fallback_cost)

    return {
        "response": response,
        "generation_stats": generation_stats,
        "usage": usage,
        "cost_usd": total_cost,
        "cost_source": "generation" if precise_cost is not None else "usage_estimate",
        "cost_exact_usd": float(precise_cost) if precise_cost is not None else None,
        "cost_fallback_usd": float(fallback_cost),
    }


def evaluate_task(
    task: Task,
    response_text: str,
    humaneval_cfg: Dict[str, Any],
) -> Tuple[bool, str, bool]:
    """Evaluate one model response against benchmark-specific logic."""

    if task.task_type == "gsm8k":
        success, failure_reason, format_ok, _, _ = evaluate_gsm8k_response(response_text, task.meta["answer_full"])
        return success, failure_reason, format_ok

    temp_root = str(humaneval_cfg["tmp_dir"])
    if not os.path.isabs(temp_root):
        temp_root = os.path.abspath(temp_root)
    success, failure_reason, format_ok, _ = humaneval_is_correct(
        code=response_text,
        test_code=task.meta["test"],
        entry_point=task.meta["entry_point"],
        timeout_s=int(humaneval_cfg["timeout_s"]),
        executor=str(humaneval_cfg["executor"]),
        docker_image=str(humaneval_cfg["docker_image"]),
        temp_root=temp_root,
        memory=str(humaneval_cfg["memory"]),
        cpus=str(humaneval_cfg["cpus"]),
        pids_limit=int(humaneval_cfg["pids_limit"]),
    )
    return success, failure_reason, format_ok


def aggregate_usage(parts: Sequence[Dict[str, int]]) -> Dict[str, int]:
    """Sum token usage across planner and solver calls."""

    return {
        "prompt_tokens": int(sum(part.get("prompt_tokens", 0) for part in parts)),
        "completion_tokens": int(sum(part.get("completion_tokens", 0) for part in parts)),
        "total_tokens": int(sum(part.get("total_tokens", 0) for part in parts)),
    }


def resolve_method_log_paths(logs_dir: str, method: str) -> Tuple[str, str]:
    """Return CSV and JSONL log paths for one method."""

    return (
        os.path.join(logs_dir, f"{method}_runs.csv"),
        os.path.join(logs_dir, f"{method}_runs.jsonl"),
    )


def load_existing_rows(csv_path: str, limit: Optional[int] = None) -> List[Dict[str, str]]:
    """Load existing per-method rows for resume."""

    if not os.path.exists(csv_path):
        return []

    by_t: Dict[int, Dict[str, str]] = {}
    with open(csv_path, "r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if not row or not row.get("t"):
                continue
            t = int(row["t"])
            if limit is not None and t > limit:
                continue
            by_t[t] = row
    return [by_t[t] for t in sorted(by_t)]


def append_row_logs(row: RunRow, csv_path: str, jsonl_path: str) -> None:
    """Append one completed task row to CSV and JSONL, flushing immediately."""

    os.makedirs(os.path.dirname(csv_path), exist_ok=True)
    write_header = not os.path.exists(csv_path) or os.path.getsize(csv_path) == 0
    with open(csv_path, "a", encoding="utf-8", newline="") as csv_handle:
        writer = csv.DictWriter(csv_handle, fieldnames=ROW_FIELDNAMES)
        if write_header:
            writer.writeheader()
        writer.writerow(asdict(row))
        csv_handle.flush()
        os.fsync(csv_handle.fileno())

    with open(jsonl_path, "a", encoding="utf-8") as jsonl_handle:
        jsonl_handle.write(json.dumps(asdict(row), ensure_ascii=False) + "\n")
        jsonl_handle.flush()
        os.fsync(jsonl_handle.fileno())


def persist_raw_artifact(
    raw_root: str,
    method: str,
    stage: str,
    t: int,
    task: Task,
    payload: Dict[str, Any],
) -> str:
    """Persist raw request/response payloads for reproducibility and debugging."""

    method_dir = os.path.join(raw_root, method)
    os.makedirs(method_dir, exist_ok=True)
    filename = f"{t:04d}_{safe_name(task.task_id)}_{stage}.json"
    path = os.path.join(method_dir, filename)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    return path


def load_response_text_from_artifact(path: str) -> str:
    """Load the response text field from a raw artifact JSON."""

    if not path or not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return str(payload.get("response_text", ""))


def materialize_rows(records: Sequence[Dict[str, str]]) -> List[RunRow]:
    """Convert CSV record dictionaries back into RunRow dataclasses."""

    rows: List[RunRow] = []
    for record in records:
        rows.append(
            RunRow(
                t=int(record["t"]),
                task_id=record["task_id"],
                task_type=record["task_type"],
                method=record["method"],
                worker_id=record["worker_id"],
                model_id=record["model_id"],
                request_id=record["request_id"],
                success=int(record["success"]),
                failure_reason=record["failure_reason"],
                format_ok=int(record.get("format_ok", 0)),
                prompt_tokens=int(record["prompt_tokens"]),
                completion_tokens=int(record["completion_tokens"]),
                total_tokens=int(record["total_tokens"]),
                latency_ms=int(record["latency_ms"]),
                cost_usd=float(record["cost_usd"]),
                cost_source=record["cost_source"],
                cost_exact_usd=float(record["cost_exact_usd"]) if str(record.get("cost_exact_usd", "")).strip() not in ("", "None", "nan") else None,
                cost_fallback_usd=float(record["cost_fallback_usd"]),
                decomp_used=int(record["decomp_used"]),
                decomp_request_id=record["decomp_request_id"],
                raw_output_path=record.get("raw_output_path", ""),
                planner_raw_output_path=record.get("planner_raw_output_path", ""),
                timestamp=int(record["timestamp"]),
            )
        )
    return rows


def raw_payload_from_result(
    worker: WorkerConfig,
    task: Task,
    stage: str,
    messages: List[Dict[str, str]],
    result: Dict[str, Any],
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build the raw artifact payload for one OpenRouter request."""

    payload = {
        "stage": stage,
        "task_id": task.task_id,
        "task_type": task.task_type,
        "worker_id": worker.worker_id,
        "model": worker.model,
        "worker_role": worker.role,
        "worker_params": worker.params,
        "request_params": result["response"].request_params,
        "request_adjustments": result["response"].request_adjustments,
        "messages": messages,
        "request_id": result["response"].request_id,
        "response_text": result["response"].content,
        "usage": result["usage"],
        "latency_ms": result["response"].latency_ms,
        "cost_usd": result["cost_usd"],
        "cost_source": result["cost_source"],
        "cost_exact_usd": result["cost_exact_usd"],
        "cost_fallback_usd": result["cost_fallback_usd"],
        "raw_response": result["response"].raw,
        "generation_stats": result["generation_stats"],
    }
    if extra:
        payload.update(extra)
    return payload


def replay_completed_tasks(
    method: str,
    existing_records: Sequence[Dict[str, str]],
    tasks: Sequence[Task],
    workers: Dict[str, WorkerConfig],
    router: Optional[CapabilityRouter],
    rng: np.random.Generator,
    config: Dict[str, Any],
    fixed_single_best_worker: str,
) -> int:
    """Rebuild router and RNG state from existing logs so resume does not repeat API calls."""

    task_by_id = {task.task_id: task for task in tasks}
    last_completed_t = 0
    for record in existing_records:
        t = int(record["t"])
        task = task_by_id[record["task_id"]]
        last_completed_t = max(last_completed_t, t)
        apply_perturbation_if_needed(t=t, workers=workers, router=router, config=config)

        if method == "random":
            random_routing(task, list(workers.keys()), rng)
            continue
        if method in ("cost_first", "single_best"):
            continue
        if method != "ours" or router is None:
            continue

        final_features: Optional[TaskFeatures] = None
        _, _, _, final_features = pick_worker(
            method=method,
            task=task,
            t=t,
            rng=rng,
            workers=workers,
            router=router,
            fixed_single_best_worker=fixed_single_best_worker,
        )
        if int(record.get("decomp_used", 0)) == 1:
            plan_text = load_response_text_from_artifact(record.get("planner_raw_output_path", ""))
            if plan_text:
                planned_task = Task(
                    task_id=task.task_id,
                    task_type=task.task_type,
                    prompt=make_user_prompt(task, plan_text=plan_text),
                    meta=task.meta,
                )
                _, _, _, final_features = pick_worker(
                    method=method,
                    task=planned_task,
                    t=t,
                    rng=rng,
                    workers=workers,
                    router=router,
                    fixed_single_best_worker=fixed_single_best_worker,
                )
        if final_features is None:
            final_features = router.featurize_task(task)

        router.update(
            worker_id=record["worker_id"],
            features=final_features,
            success=bool(int(record["success"])),
            cost=float(record["cost_usd"]),
            latency_ms=float(record["latency_ms"]),
            format_ok=bool(int(record.get("format_ok", 0))),
        )
    return last_completed_t


def maybe_report_chunk_checkpoint(t: int, chunk_size: int, method: str) -> None:
    """Print a lightweight checkpoint marker every chunk_size tasks."""

    if chunk_size > 0 and t % chunk_size == 0:
        print(f"[checkpoint] method={method} completed_tasks={t}")


def run_method(
    method: str,
    tasks: Sequence[Task],
    workers_path: str,
    config: Dict[str, Any],
    limit: Optional[int] = None,
) -> List[RunRow]:
    """Run one routing method over the fixed task stream with append-only logs and resume."""

    experiment_cfg = config["experiment"]
    execution_cfg = config.get("execution", {})
    router_cfg = config["router"]
    humaneval_cfg = config["humaneval"]
    paths = config["paths"]

    workers = load_workers_config(workers_path)
    rng = np.random.default_rng(int(experiment_cfg["seed"]))
    selected_tasks = list(tasks[:limit]) if limit is not None else list(tasks)
    csv_path, jsonl_path = resolve_method_log_paths(paths["outputs_logs"], method)
    existing_records = load_existing_rows(csv_path, limit=len(selected_tasks))

    router = None
    if method == "ours":
        router = CapabilityRouter(
            worker_roles={worker_id: worker.role for worker_id, worker in workers.items()},
            use_sbert=bool(router_cfg["use_sbert"]),
            sbert_model=str(router_cfg["sbert_model"]),
            warmup_steps=int(router_cfg["warmup_steps"]),
            epsilon_warmup=float(router_cfg["epsilon_warmup"]),
            epsilon_after=float(router_cfg["epsilon_after"]),
            alpha=float(router_cfg["alpha"]),
            beta=float(router_cfg["beta"]),
            gamma=float(router_cfg["gamma"]),
            delta=float(router_cfg["delta"]),
            ucb_k=float(router_cfg["ucb_k"]),
            ema_decay=float(router_cfg["ema_decay"]),
            stability_window=int(router_cfg["stability_window"]),
            decomp_threshold=float(router_cfg["decomp_threshold"]),
            forget_decay=float(router_cfg["forget_decay"]),
        )

    resume_enabled = bool(execution_cfg.get("resume", True))
    fixed_single_best_worker = str(experiment_cfg["fixed_single_best_worker"])
    completed_tasks = 0
    if resume_enabled and existing_records:
        completed_tasks = replay_completed_tasks(
            method=method,
            existing_records=existing_records,
            tasks=selected_tasks,
            workers=workers,
            router=router,
            rng=rng,
            config=config,
            fixed_single_best_worker=fixed_single_best_worker,
        )
        print(f"[resume] method={method} completed_tasks={completed_tasks}")

    if completed_tasks >= len(selected_tasks):
        return materialize_rows(existing_records)

    client = OpenRouterClient()
    enable_decomposition = bool(experiment_cfg["enable_decomposition"])
    save_raw_outputs = bool(execution_cfg.get("save_raw_outputs", True))
    max_consecutive_failures = int(execution_cfg.get("max_consecutive_request_failures", 1))
    chunk_size = int(execution_cfg.get("chunk_size", 25))
    consecutive_request_failures = 0

    iterator = enumerate(selected_tasks[completed_tasks:], start=completed_tasks + 1)
    for t, task in tqdm(iterator, total=len(selected_tasks) - completed_tasks, desc=f"Running {method}", leave=False):
        apply_perturbation_if_needed(t=t, workers=workers, router=router, config=config)

        try:
            worker_id, need_decomp, _, features = pick_worker(
                method=method,
                task=task,
                t=t,
                rng=rng,
                workers=workers,
                router=router,
                fixed_single_best_worker=fixed_single_best_worker,
            )
            worker = workers[worker_id]

            planner_result: Optional[Dict[str, Any]] = None
            planner_raw_output_path = ""
            decomp_used = False
            plan_text = ""
            decomp_request_id = ""
            if method == "ours" and enable_decomposition and need_decomp:
                planner_worker = workers["qwen3_235b"]
                planner_messages = [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": build_decomp_prompt(task)},
                ]
                try:
                    planner_result = execute_request(client, planner_worker, planner_messages)
                    plan_text = planner_result["response"].content
                    decomp_request_id = planner_result["response"].request_id
                    decomp_used = True
                    if save_raw_outputs:
                        planner_raw_output_path = persist_raw_artifact(
                            raw_root=paths["outputs_raw"],
                            method=method,
                            stage="planner",
                            t=t,
                            task=task,
                            payload=raw_payload_from_result(
                                worker=planner_worker,
                                task=task,
                                stage="planner",
                                messages=planner_messages,
                                result=planner_result,
                                extra={"planner_prompt": planner_messages[-1]["content"]},
                            ),
                        )
                    planned_task = Task(
                        task_id=task.task_id,
                        task_type=task.task_type,
                        prompt=make_user_prompt(task, plan_text=plan_text),
                        meta=task.meta,
                    )
                    worker_id, _, _, features = pick_worker(
                        method=method,
                        task=planned_task,
                        t=t,
                        rng=rng,
                        workers=workers,
                        router=router,
                        fixed_single_best_worker=fixed_single_best_worker,
                    )
                    worker = workers[worker_id]
                except Exception as planner_exc:
                    planner_result = None
                    plan_text = ""
                    decomp_used = False
                    decomp_request_id = ""
                    print(f"[planner-warning] method={method} t={t} planner skipped after error: {planner_exc}")

            solver_messages = build_messages(task, plan_text=plan_text)
            solver_result = execute_request(client, worker, solver_messages)
            response = solver_result["response"]

            usage_parts = [solver_result["usage"]]
            total_latency = int(response.latency_ms)
            total_cost = float(solver_result["cost_usd"])
            exact_cost: Optional[float] = solver_result["cost_exact_usd"]
            fallback_cost = float(solver_result["cost_fallback_usd"])
            cost_source = str(solver_result["cost_source"])
            if planner_result is not None and decomp_used:
                usage_parts.insert(0, planner_result["usage"])
                total_latency += int(planner_result["response"].latency_ms)
                total_cost += float(planner_result["cost_usd"])
                fallback_cost += float(planner_result["cost_fallback_usd"])
                if exact_cost is not None and planner_result["cost_exact_usd"] is not None:
                    exact_cost += float(planner_result["cost_exact_usd"])
                    cost_source = "generation"
                else:
                    exact_cost = None
                    cost_source = "mixed"

            usage = aggregate_usage(usage_parts)
            success, failure_reason, format_ok = evaluate_task(
                task=task,
                response_text=response.content,
                humaneval_cfg=humaneval_cfg,
            )

            raw_output_path = ""
            if save_raw_outputs:
                raw_output_path = persist_raw_artifact(
                    raw_root=paths["outputs_raw"],
                    method=method,
                    stage="solver",
                    t=t,
                    task=task,
                    payload=raw_payload_from_result(
                        worker=worker,
                        task=task,
                        stage="solver",
                        messages=solver_messages,
                        result=solver_result,
                        extra={
                            "decomp_used": decomp_used,
                            "planner_raw_output_path": planner_raw_output_path,
                            "evaluation": {
                                "success": success,
                                "failure_reason": failure_reason,
                                "format_ok": format_ok,
                            },
                        },
                    ),
                )

            if method == "ours" and router is not None:
                if features is None:
                    features = router.featurize_task(task)
                router.update(
                    worker_id=worker_id,
                    features=features,
                    success=success,
                    cost=total_cost,
                    latency_ms=total_latency,
                    format_ok=format_ok,
                )

            row = RunRow(
                t=t,
                task_id=task.task_id,
                task_type=task.task_type,
                method=method,
                worker_id=worker_id,
                model_id=response.model,
                request_id=response.request_id,
                success=int(success),
                failure_reason=failure_reason,
                format_ok=int(format_ok),
                prompt_tokens=usage["prompt_tokens"],
                completion_tokens=usage["completion_tokens"],
                total_tokens=usage["total_tokens"],
                latency_ms=total_latency,
                cost_usd=total_cost,
                cost_source=cost_source,
                cost_exact_usd=exact_cost,
                cost_fallback_usd=fallback_cost,
                decomp_used=int(decomp_used),
                decomp_request_id=decomp_request_id,
                raw_output_path=raw_output_path,
                planner_raw_output_path=planner_raw_output_path,
                timestamp=int(datetime.now(tz=timezone.utc).timestamp()),
            )
            append_row_logs(row=row, csv_path=csv_path, jsonl_path=jsonl_path)
            existing_records.append({key: str(value) if value is not None else "" for key, value in asdict(row).items()})
            consecutive_request_failures = 0
            maybe_report_chunk_checkpoint(t=t, chunk_size=chunk_size, method=method)
        except Exception as exc:
            consecutive_request_failures += 1
            print(
                f"[stop] method={method} t={t} stopped after request failure to avoid wasting tokens: {exc}"
            )
            if consecutive_request_failures >= max_consecutive_failures:
                raise RuntimeError(
                    f"Stopping {method} at task {t} to protect OpenRouter budget. "
                    "Rerun the same command to resume from completed rows."
                ) from exc
            break

    return materialize_rows(load_existing_rows(csv_path, limit=len(selected_tasks)))


def rebuild_combined_logs(logs_dir: str, config: Dict[str, Any]) -> None:
    """Rebuild combined CSV and JSONL logs from per-method logs."""

    combined_rows: List[Dict[str, str]] = []
    for method in METHODS:
        csv_path, _ = resolve_method_log_paths(logs_dir, method)
        combined_rows.extend(load_existing_rows(csv_path))

    combined_rows.sort(key=lambda row: (row["method"], int(row["t"])))
    experiment_cfg = config["experiment"]
    repo_root = config["paths"]["repo_root"]
    combined_csv = experiment_cfg["combined_csv_path"]
    combined_jsonl = experiment_cfg["combined_jsonl_path"]
    if not os.path.isabs(combined_csv):
        combined_csv = os.path.join(repo_root, combined_csv)
    if not os.path.isabs(combined_jsonl):
        combined_jsonl = os.path.join(repo_root, combined_jsonl)

    os.makedirs(os.path.dirname(combined_csv), exist_ok=True)
    os.makedirs(os.path.dirname(combined_jsonl), exist_ok=True)
    with open(combined_csv, "w", encoding="utf-8", newline="") as csv_handle:
        writer = csv.DictWriter(csv_handle, fieldnames=ROW_FIELDNAMES)
        writer.writeheader()
        for row in combined_rows:
            writer.writerow(row)
    with open(combined_jsonl, "w", encoding="utf-8") as jsonl_handle:
        for row in combined_rows:
            jsonl_handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> None:
    """CLI entrypoint."""

    parser = argparse.ArgumentParser(description="Run the capability-aware routing experiment.")
    parser.add_argument("--config", default="configs/experiment.yaml")
    parser.add_argument("--workers", default="configs/workers.yaml")
    parser.add_argument("--method", default="all", choices=["all", *METHODS])
    parser.add_argument("--limit", type=int, default=None, help="Optional small smoke-run limit.")
    parser.add_argument("--build-reports", action="store_true", help="Generate plots, stats, and failure analysis after the run.")
    args = parser.parse_args()

    config = load_config(args.config)
    ensure_paths(config)
    tasks = load_or_build_task_stream(config, save=True)
    methods = METHODS if args.method == "all" else [args.method]
    logs_dir = config["paths"]["outputs_logs"]

    for method in methods:
        run_method(
            method=method,
            tasks=tasks,
            workers_path=args.workers,
            config=config,
            limit=args.limit,
        )

    rebuild_combined_logs(logs_dir=logs_dir, config=config)

    if args.build_reports:
        generate_plots(logs_dir=logs_dir, out_dir=config["paths"]["outputs_figs"])
        generate_stats(logs_dir=logs_dir, out_dir=config["paths"]["outputs_stats"])
        generate_failure_analysis(
            logs_dir=logs_dir,
            stats_dir=config["paths"]["outputs_stats"],
            out_dir=config["paths"]["outputs_analysis"],
        )


if __name__ == "__main__":
    main()
