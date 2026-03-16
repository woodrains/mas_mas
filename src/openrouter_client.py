"""OpenRouter client helpers for the capability-aware routing experiment."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests
import yaml
from openai import APIConnectionError, APITimeoutError, BadRequestError, InternalServerError, OpenAI, RateLimitError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


@dataclass
class WorkerConfig:
    """Static configuration for one OpenRouter worker."""

    worker_id: str
    model: str
    role: str
    price_usd_per_m_input: float
    price_usd_per_m_output: float
    params: Dict[str, Any]


@dataclass
class OpenRouterResponse:
    """Normalized chat completion response."""

    request_id: str
    model: str
    content: str
    usage: Dict[str, Any]
    latency_ms: int
    raw: Dict[str, Any]
    request_params: Dict[str, Any]
    request_adjustments: List[str]


def load_workers_config(path: str) -> Dict[str, WorkerConfig]:
    """Load worker definitions from YAML and return a worker_id keyed mapping."""

    with open(path, "r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}

    workers: Dict[str, WorkerConfig] = {}
    for item in payload.get("workers", []):
        worker = WorkerConfig(
            worker_id=item["worker_id"],
            model=item["model"],
            role=item.get("role", ""),
            price_usd_per_m_input=float(item["price_usd_per_m_input"]),
            price_usd_per_m_output=float(item["price_usd_per_m_output"]),
            params=dict(item.get("params", {})),
        )
        workers[worker.worker_id] = worker
    return workers


def compute_cost_fallback(usage: Dict[str, Any], worker: WorkerConfig) -> float:
    """Estimate request cost from OpenAI-style usage when generation stats are unavailable."""

    prompt_tokens = float(usage.get("prompt_tokens", 0))
    completion_tokens = float(usage.get("completion_tokens", 0))
    return (
        (prompt_tokens / 1_000_000.0) * worker.price_usd_per_m_input
        + (completion_tokens / 1_000_000.0) * worker.price_usd_per_m_output
    )


class OpenRouterClient:
    """OpenRouter client using the OpenAI SDK compatibility layer."""

    def __init__(self) -> None:
        api_key = os.environ["OPENROUTER_API_KEY"]
        app_url = os.getenv("APP_URL", "http://localhost")
        app_title = os.getenv("APP_TITLE", "capability-router-exp")

        self.client = OpenAI(
            base_url=OPENROUTER_BASE_URL,
            api_key=api_key,
            default_headers={
                "HTTP-Referer": app_url,
                "X-Title": app_title,
            },
        )
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": app_url,
            "X-Title": app_title,
        }

    @retry(
        reraise=True,
        stop=stop_after_attempt(6),
        wait=wait_exponential(multiplier=0.8, min=1, max=30),
        retry=retry_if_exception_type(
            (requests.RequestException, TimeoutError, APIConnectionError, APITimeoutError, InternalServerError, RateLimitError)
        ),
    )
    def chat(self, model: str, messages: List[Dict[str, Any]], **params: Any) -> OpenRouterResponse:
        """Call the OpenRouter chat completion API and normalize the response."""

        request_params = self._normalize_request_params(params)
        request_adjustments: List[str] = []

        start = time.time()
        try:
            response = self.client.chat.completions.create(model=model, messages=messages, **request_params)
        except BadRequestError as exc:
            repaired = self._repair_bad_request(model=model, request_params=request_params, exc=exc)
            if repaired is None:
                raise
            request_params, adjustment = repaired
            request_adjustments.append(adjustment)
            response = self.client.chat.completions.create(model=model, messages=messages, **request_params)
        latency_ms = int((time.time() - start) * 1000)

        usage = getattr(response, "usage", None)
        usage_dict = usage.model_dump() if usage is not None else {}
        raw = response.model_dump()

        return OpenRouterResponse(
            request_id=response.id,
            model=response.model,
            content=self._flatten_message_content(response.choices[0].message.content),
            usage=usage_dict,
            latency_ms=latency_ms,
            raw=raw,
            request_params=request_params,
            request_adjustments=request_adjustments,
        )

    @staticmethod
    def _normalize_request_params(params: Dict[str, Any]) -> Dict[str, Any]:
        """Move provider-specific params into extra_body for the OpenAI-compatible SDK."""

        request_params = dict(params)
        extra_body = dict(request_params.pop("extra_body", {}) or {})
        if "reasoning" in request_params:
            extra_body["reasoning"] = request_params.pop("reasoning")
        if extra_body:
            request_params["extra_body"] = extra_body
        return request_params

    @staticmethod
    def _repair_bad_request(
        model: str,
        request_params: Dict[str, Any],
        exc: BadRequestError,
    ) -> Optional[Tuple[Dict[str, Any], str]]:
        """Repair a small class of provider-specific 400s without aborting the run."""

        message = str(exc)
        if "Reasoning is mandatory for this endpoint and cannot be disabled." not in message:
            return None

        extra_body = dict(request_params.get("extra_body", {}) or {})
        reasoning = dict(extra_body.get("reasoning", {}) or {})
        if reasoning.get("enabled") is not False:
            return None

        repaired_params = dict(request_params)
        reasoning["enabled"] = True
        extra_body["reasoning"] = reasoning
        repaired_params["extra_body"] = extra_body
        adjustment = f"forced reasoning.enabled=true for mandatory-reasoning model {model}"
        return repaired_params, adjustment

    @retry(
        reraise=True,
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=0.8, min=1, max=15),
        retry=retry_if_exception_type((requests.RequestException, TimeoutError)),
    )
    def fetch_generation_stats(self, request_id: str) -> Optional[Dict[str, Any]]:
        """Fetch generation-level cost and native token stats for a request id."""

        url = f"{OPENROUTER_BASE_URL}/generation"
        response = requests.get(url, params={"id": request_id}, headers=self._headers, timeout=30)
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else None

    def extract_cost_and_usage(self, generation_stats: Optional[Dict[str, Any]]) -> Tuple[Optional[float], Dict[str, Any]]:
        """Best-effort extraction of precise cost and native usage from generation stats."""

        if not generation_stats:
            return None, {}

        cost = self._find_first_numeric(generation_stats, {"cost"})
        usage = self._find_usage_block(generation_stats)
        if usage:
            return cost, usage

        prompt_native = self._find_first_numeric(generation_stats, {"native_prompt_tokens", "prompt_tokens", "input_tokens"})
        completion_native = self._find_first_numeric(
            generation_stats,
            {"native_completion_tokens", "completion_tokens", "output_tokens", "generated_tokens"},
        )
        total_native = self._find_first_numeric(generation_stats, {"native_total_tokens", "total_tokens"})
        fallback_usage: Dict[str, Any] = {}
        if prompt_native is not None:
            fallback_usage["prompt_tokens"] = int(prompt_native)
        if completion_native is not None:
            fallback_usage["completion_tokens"] = int(completion_native)
        if total_native is not None:
            fallback_usage["total_tokens"] = int(total_native)
        elif prompt_native is not None or completion_native is not None:
            fallback_usage["total_tokens"] = int((prompt_native or 0) + (completion_native or 0))
        return cost, fallback_usage

    @staticmethod
    def _flatten_message_content(content: Any) -> str:
        """Handle OpenAI-style string or content block responses."""

        if content is None:
            return ""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            chunks: List[str] = []
            for item in content:
                if isinstance(item, str):
                    chunks.append(item)
                elif isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str):
                        chunks.append(text)
            return "".join(chunks)
        return str(content)

    @classmethod
    def _find_first_numeric(cls, obj: Any, candidate_keys: Iterable[str]) -> Optional[float]:
        """Recursively search for the first numeric value under one of the candidate keys."""

        keys = set(candidate_keys)
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key in keys and isinstance(value, (int, float)):
                    return float(value)
            for value in obj.values():
                found = cls._find_first_numeric(value, keys)
                if found is not None:
                    return found
        elif isinstance(obj, list):
            for value in obj:
                found = cls._find_first_numeric(value, keys)
                if found is not None:
                    return found
        return None

    @classmethod
    def _find_usage_block(cls, obj: Any) -> Dict[str, Any]:
        """Recursively search for a dict that looks like a usage block."""

        if isinstance(obj, dict):
            if {"prompt_tokens", "completion_tokens"}.intersection(obj.keys()):
                return obj
            for value in obj.values():
                found = cls._find_usage_block(value)
                if found:
                    return found
        elif isinstance(obj, list):
            for value in obj:
                found = cls._find_usage_block(value)
                if found:
                    return found
        return {}
