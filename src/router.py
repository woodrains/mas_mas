"""Capability-aware online router."""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional, Tuple

import numpy as np

from .datasets import Task

try:
    from sentence_transformers import SentenceTransformer
except Exception:  # pragma: no cover - runtime fallback
    SentenceTransformer = None  # type: ignore


@dataclass
class BetaPosterior:
    """Beta posterior for binary success outcomes."""

    alpha: float = 1.0
    beta: float = 1.0

    def mean(self) -> float:
        return self.alpha / (self.alpha + self.beta)

    def var(self) -> float:
        total = self.alpha + self.beta
        return (self.alpha * self.beta) / ((total ** 2) * (total + 1.0))

    def decay_towards_prior(self, decay: float) -> None:
        if decay >= 1.0:
            return
        self.alpha = 1.0 + decay * (self.alpha - 1.0)
        self.beta = 1.0 + decay * (self.beta - 1.0)

    def update(self, success: bool, decay: float = 1.0) -> None:
        self.decay_towards_prior(decay)
        if success:
            self.alpha += 1.0
        else:
            self.beta += 1.0


@dataclass
class TaskFeatures:
    """Task representation used by the router."""

    task_type: str
    prompt_length: int
    prompt_length_bin: str
    difficulty: str
    needs_strict_instruction: int
    line_count: int
    digit_count: int
    code_keyword_count: int
    math_keyword_count: int
    embedding: Optional[np.ndarray] = None

    @property
    def bucket_key(self) -> str:
        return f"{self.task_type}|{self.difficulty}|{self.prompt_length_bin}|{self.needs_strict_instruction}"


@dataclass
class WorkerState:
    """Online worker capability estimates."""

    ema_cost: float = 0.0
    ema_latency: float = 0.0
    ema_format: float = 0.5
    ema_decay: float = 0.95
    task_posteriors: Dict[str, BetaPosterior] = field(
        default_factory=lambda: {"gsm8k": BetaPosterior(), "humaneval": BetaPosterior()}
    )
    bucket_posteriors: Dict[str, BetaPosterior] = field(default_factory=dict)
    recent_success: Deque[int] = field(default_factory=lambda: deque(maxlen=50))
    success_embedding_centroid: Optional[np.ndarray] = None
    success_embedding_count: int = 0

    def get_bucket_posterior(self, bucket_key: str) -> BetaPosterior:
        if bucket_key not in self.bucket_posteriors:
            self.bucket_posteriors[bucket_key] = BetaPosterior()
        return self.bucket_posteriors[bucket_key]

    def update(
        self,
        task_type: str,
        bucket_key: str,
        success: bool,
        cost: float,
        latency_ms: float,
        format_ok: bool,
        decay: float,
        embedding: Optional[np.ndarray],
    ) -> None:
        self.task_posteriors[task_type].update(success=success, decay=decay)
        self.get_bucket_posterior(bucket_key).update(success=success, decay=decay)

        d = self.ema_decay
        self.ema_cost = d * self.ema_cost + (1.0 - d) * cost
        self.ema_latency = d * self.ema_latency + (1.0 - d) * latency_ms
        self.ema_format = d * self.ema_format + (1.0 - d) * float(format_ok)
        self.recent_success.append(1 if success else 0)

        if success and embedding is not None:
            if self.success_embedding_centroid is None:
                self.success_embedding_centroid = embedding.astype(np.float32)
                self.success_embedding_count = 1
            else:
                count = float(self.success_embedding_count)
                self.success_embedding_centroid = (
                    (count * self.success_embedding_centroid + embedding) / (count + 1.0)
                ).astype(np.float32)
                self.success_embedding_count += 1

    def stability(self) -> float:
        if len(self.recent_success) < 5:
            return 0.5
        return float(1.0 - np.var(np.asarray(self.recent_success, dtype=np.float32)))


class CapabilityRouter:
    """Minimal capability-aware router with contextual posteriors and decomposition trigger."""

    def __init__(
        self,
        worker_roles: Dict[str, str],
        use_sbert: bool = True,
        sbert_model: str = "sentence-transformers/all-MiniLM-L6-v2",
        warmup_steps: int = 40,
        epsilon_warmup: float = 0.20,
        epsilon_after: float = 0.10,
        alpha: float = 1.0,
        beta: float = 0.15,
        gamma: float = 0.05,
        delta: float = 0.10,
        ucb_k: float = 1.0,
        ema_decay: float = 0.95,
        stability_window: int = 50,
        decomp_threshold: float = 0.55,
        forget_decay: float = 1.0,
    ) -> None:
        self.worker_roles = dict(worker_roles)
        self.states: Dict[str, WorkerState] = {}
        for worker_id in worker_roles:
            state = WorkerState(ema_decay=ema_decay)
            state.recent_success = deque(maxlen=stability_window)
            self.states[worker_id] = state

        self.use_sbert = use_sbert and SentenceTransformer is not None
        self.encoder = SentenceTransformer(sbert_model) if self.use_sbert else None
        self.warmup_steps = warmup_steps
        self.epsilon_warmup = epsilon_warmup
        self.epsilon_after = epsilon_after
        self.alpha = alpha
        self.beta = beta
        self.gamma = gamma
        self.delta = delta
        self.ucb_k = ucb_k
        self.decomp_threshold = decomp_threshold
        self.forget_decay = forget_decay

    def featurize_task(self, task: Task) -> TaskFeatures:
        """Convert one task into the router's structured representation."""

        prompt = task.prompt
        prompt_length = len(prompt)
        line_count = prompt.count("\n") + 1
        digit_count = sum(char.isdigit() for char in prompt)
        code_keyword_count = sum(prompt.count(keyword) for keyword in ("def ", "return", "class ", "assert"))
        math_keyword_count = sum(prompt.lower().count(keyword) for keyword in ("sum", "total", "percent", "times", "each"))

        if prompt_length >= 2400:
            prompt_length_bin = "long"
        elif prompt_length >= 800:
            prompt_length_bin = "medium"
        else:
            prompt_length_bin = "short"

        if task.task_type == "gsm8k":
            difficulty_score = prompt_length / 120.0 + digit_count / 6.0 + math_keyword_count / 4.0
        else:
            test_size = len(str(task.meta.get("test", "")))
            difficulty_score = prompt_length / 180.0 + test_size / 600.0 + line_count / 10.0
        if difficulty_score >= 8.0:
            difficulty = "hard"
        elif difficulty_score >= 4.0:
            difficulty = "medium"
        else:
            difficulty = "easy"

        needs_strict_instruction = int(
            task.task_type == "humaneval" or "FINAL:" in prompt or "only output" in prompt.lower()
        )
        embedding = None
        if self.encoder is not None:
            embedding = np.asarray(self.encoder.encode([prompt], normalize_embeddings=True)[0], dtype=np.float32)

        return TaskFeatures(
            task_type=task.task_type,
            prompt_length=prompt_length,
            prompt_length_bin=prompt_length_bin,
            difficulty=difficulty,
            needs_strict_instruction=needs_strict_instruction,
            line_count=line_count,
            digit_count=digit_count,
            code_keyword_count=code_keyword_count,
            math_keyword_count=math_keyword_count,
            embedding=embedding,
        )

    def choose_worker(self, task: Task, t: int, rng: np.random.Generator) -> Tuple[str, bool, Dict[str, float], TaskFeatures]:
        """Select a worker and whether lightweight decomposition should be triggered."""

        features = self.featurize_task(task)
        epsilon = self.epsilon_warmup if t <= self.warmup_steps else self.epsilon_after
        if rng.random() < epsilon:
            worker_id = str(rng.choice(list(self.states.keys())))
            scores = {wid: self.score_worker(wid, features) for wid in self.states}
            mean_success = self.expected_success(worker_id, features)
            return worker_id, mean_success < self.decomp_threshold, scores, features

        scores = {wid: self.score_worker(wid, features) for wid in self.states}
        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        worker_id, _ = ranked[0]
        mean_success = self.expected_success(worker_id, features)
        need_decomp = mean_success < self.decomp_threshold
        return worker_id, need_decomp, scores, features

    def update(
        self,
        worker_id: str,
        features: TaskFeatures,
        success: bool,
        cost: float,
        latency_ms: float,
        format_ok: bool,
    ) -> None:
        """Update the selected worker's online capability state."""

        self.states[worker_id].update(
            task_type=features.task_type,
            bucket_key=features.bucket_key,
            success=success,
            cost=cost,
            latency_ms=latency_ms,
            format_ok=format_ok,
            decay=self.forget_decay,
            embedding=features.embedding,
        )

    def score_worker(self, worker_id: str, features: TaskFeatures) -> float:
        """Compute the multi-objective routing score."""

        state = self.states[worker_id]
        type_posterior = state.task_posteriors[features.task_type]
        bucket_posterior = state.get_bucket_posterior(features.bucket_key)
        heuristic_prior = self._heuristic_prior(worker_id, features)
        semantic_prior = self._semantic_similarity(state, features.embedding)

        expected_success = (
            0.55 * type_posterior.mean()
            + 0.20 * bucket_posterior.mean()
            + 0.15 * heuristic_prior
            + 0.10 * semantic_prior
        )
        uncertainty = 0.6 * type_posterior.var() + 0.4 * bucket_posterior.var()
        ucb_bonus = self.ucb_k * math.sqrt(max(uncertainty, 0.0))

        max_cost = max((worker_state.ema_cost for worker_state in self.states.values()), default=0.0)
        max_latency = max((worker_state.ema_latency for worker_state in self.states.values()), default=0.0)
        norm_cost = state.ema_cost / max_cost if max_cost > 0 else 0.0
        norm_latency = state.ema_latency / max_latency if max_latency > 0 else 0.0

        stability_bonus = self.delta * ((state.stability() + state.ema_format) / 2.0)
        return self.alpha * (expected_success + ucb_bonus) - self.beta * norm_cost - self.gamma * norm_latency + stability_bonus

    def expected_success(self, worker_id: str, features: TaskFeatures) -> float:
        """Return the current expected success without the exploration bonus."""

        state = self.states[worker_id]
        return (
            0.55 * state.task_posteriors[features.task_type].mean()
            + 0.20 * state.get_bucket_posterior(features.bucket_key).mean()
            + 0.15 * self._heuristic_prior(worker_id, features)
            + 0.10 * self._semantic_similarity(state, features.embedding)
        )

    def _semantic_similarity(self, state: WorkerState, embedding: Optional[np.ndarray]) -> float:
        if embedding is None or state.success_embedding_centroid is None:
            return 0.5
        centroid = state.success_embedding_centroid
        denom = np.linalg.norm(centroid) * np.linalg.norm(embedding)
        if denom == 0:
            return 0.5
        similarity = float(np.dot(centroid, embedding) / denom)
        return max(0.0, min(1.0, (similarity + 1.0) / 2.0))

    def _heuristic_prior(self, worker_id: str, features: TaskFeatures) -> float:
        role = self.worker_roles[worker_id]
        score = 0.5

        if features.task_type == "gsm8k":
            if role == "reasoning_specialist":
                score += 0.20 if features.difficulty == "hard" else 0.10
            if role == "long_context_workhorse" and features.prompt_length_bin == "long":
                score += 0.15
            if role == "low_cost_generalist" and features.difficulty == "easy":
                score += 0.10
            if role == "high_quality_generalist" and features.needs_strict_instruction:
                score += 0.05
        else:
            if role == "high_quality_generalist":
                score += 0.18
            if role == "long_context_workhorse" and features.prompt_length_bin != "short":
                score += 0.12
            if role == "low_cost_generalist" and features.difficulty == "easy":
                score += 0.08
            if role == "reasoning_specialist" and features.difficulty == "hard":
                score += 0.05

        if features.needs_strict_instruction and role == "high_quality_generalist":
            score += 0.08
        if features.prompt_length_bin == "long" and role == "long_context_workhorse":
            score += 0.10
        return max(0.0, min(1.0, score))


def build_decomp_prompt(task: Task) -> str:
    """Build the one-shot planner prompt used for lightweight decomposition."""

    if task.task_type == "gsm8k":
        return (
            "You are a concise problem planner.\n"
            "Output only a short plan with 3-6 numbered steps.\n"
            "Do not solve the problem. Do not give the final answer.\n\n"
            f"Problem:\n{task.prompt}\n"
        )
    return (
        "You are a concise coding planner.\n"
        "Output only three short sections: Algorithm, Edge Cases, Complexity.\n"
        "Do not write final code.\n\n"
        f"Task:\n{task.prompt}\n"
    )
