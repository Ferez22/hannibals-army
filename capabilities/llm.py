"""Unified LLM interface — Ollama (local) + OpenAI (cloud) behind one call.

Routing decided by caller. No magic, no fallback chain. Caller passes a model
string; we dispatch:
  - "openai" → OpenAI chat completion using config.OPENAI_MODEL
  - anything else → Ollama generate with that model name

Caller checks `openai_available()` before requesting "openai" mode.
"""
from __future__ import annotations

import json as _json
import logging
from typing import Any

import config

log = logging.getLogger("hannibal.llm")


def openai_available() -> bool:
    return bool(config.OPENAI_API_KEY)


def generate(
    *,
    model: str,
    prompt: str,
    json_mode: bool = False,
    temperature: float = 0.0,
    max_tokens: int | None = None,
) -> str:
    """Single text completion. Returns raw text response. Never raises on LLM error;
    returns "" and logs."""
    try:
        if model == "openai":
            if not openai_available():
                log.warning("openai_requested_but_no_key")
                return ""
            return _openai_generate(prompt, json_mode=json_mode, temperature=temperature,
                                    max_tokens=max_tokens)
        return _ollama_generate(model=model, prompt=prompt, json_mode=json_mode,
                                temperature=temperature, max_tokens=max_tokens)
    except Exception as e:
        log.exception("llm_generate_failed", extra={"model": model, "error": str(e)})
        return ""


# ---------------------------------------------------------------------------
def _ollama_generate(*, model: str, prompt: str, json_mode: bool,
                     temperature: float, max_tokens: int | None) -> str:
    import ollama
    options: dict[str, Any] = {"temperature": temperature}
    if max_tokens is not None:
        options["num_predict"] = max_tokens
    kwargs: dict[str, Any] = {"model": model, "prompt": prompt, "options": options}
    if json_mode:
        kwargs["format"] = "json"
    resp = ollama.generate(**kwargs)
    return (resp.get("response") or "").strip()


def _openai_generate(prompt: str, *, json_mode: bool, temperature: float,
                     max_tokens: int | None) -> str:
    from openai import OpenAI
    client = OpenAI(api_key=config.OPENAI_API_KEY)
    kwargs: dict[str, Any] = {
        "model": config.OPENAI_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
    }
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    resp = client.chat.completions.create(**kwargs)
    return (resp.choices[0].message.content or "").strip()


# ---------------------------------------------------------------------------
def parse_json(raw: str) -> dict | None:
    """Tolerant JSON parser — strips markdown fences, recovers from extra prose."""
    import re
    if not raw:
        return None
    cleaned = raw.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return _json.loads(cleaned)
    except _json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            try:
                return _json.loads(match.group(0))
            except _json.JSONDecodeError:
                return None
        return None
