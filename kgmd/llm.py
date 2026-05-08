"""LiteLLM wrapper with structured output parsing, retries, and logging."""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import TypeVar

import litellm
from pydantic import BaseModel, ValidationError

logger = logging.getLogger("kgmd.llm")

T = TypeVar("T", bound=BaseModel)


def call_structured(
    model: str,
    system: str,
    user: str,
    response_model: type[T],
    max_retries: int = 2,
    temperature: float = 0.0,
    max_tokens: int = 4096,
    timeout: int = 120,
    log_path: Path | None = None,
) -> T:
    """Call litellm, expect JSON output, parse into the given Pydantic model.

    On JSONDecodeError or ValidationError, append a corrective message and retry.
    Raises after max_retries.
    """
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]

    # Try to use response_format for providers that support it
    kwargs: dict = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "timeout": timeout,
    }

    # Attempt response_format; fall back gracefully
    try:
        kwargs["response_format"] = {"type": "json_object"}
    except Exception:
        pass

    last_error = None
    for attempt in range(max_retries + 1):
        start = time.time()
        try:
            response = litellm.completion(**kwargs)
            elapsed = time.time() - start
            content = response.choices[0].message.content

            # Log the call
            _log_call(log_path, model, messages, content, elapsed, True)

            # Strip markdown code fences
            content = _strip_code_fences(content)

            # Parse JSON
            data = json.loads(content)
            result = response_model.model_validate(data)
            return result

        except (json.JSONDecodeError, ValidationError) as e:
            elapsed = time.time() - start
            last_error = e
            _log_call(log_path, model, messages, str(e), elapsed, False)

            if attempt < max_retries:
                # Detect truncation vs malformed JSON
                is_truncated = isinstance(e, json.JSONDecodeError) and (
                    "Unterminated" in str(e)
                    or "Expecting" in str(e)
                    or "end of" in str(e).lower()
                )
                if is_truncated:
                    correction = (
                        "Your previous JSON output was truncated (cut off before "
                        "completion). Please output a SHORTER, complete JSON response. "
                        "Extract only the most important entities and relations. "
                        "Keep the output well under the token limit."
                    )
                else:
                    correction = (
                        f"Your previous output was not valid. Error: {e}\n"
                        "Please output ONLY valid JSON matching the required schema. "
                        "No prose, no markdown fences."
                    )
                # Reset to original messages to avoid ballooning context
                messages = [
                    {"role": "system", "content": messages[0]["content"]},
                    {"role": "user", "content": messages[1]["content"]},
                    {"role": "user", "content": correction},
                ]
                kwargs["messages"] = messages

        except Exception as e:
            elapsed = time.time() - start
            _log_call(log_path, model, messages, str(e), elapsed, False)
            raise

    raise RuntimeError(
        f"LLM call failed after {max_retries + 1} attempts. Last error: {last_error}"
    )


def _strip_code_fences(text: str) -> str:
    """Remove markdown code fences from LLM output."""
    text = text.strip()
    # Remove ```json ... ``` or ``` ... ```
    if text.startswith("```"):
        # Remove opening fence
        text = re.sub(r"^```(?:json|yaml)?\s*\n?", "", text)
        # Remove closing fence
        text = re.sub(r"\n?```\s*$", "", text)
    return text.strip()


def _log_call(
    log_path: Path | None,
    model: str,
    messages: list[dict],
    response: str,
    elapsed: float,
    success: bool,
) -> None:
    """Append a log entry to the build log."""
    if not log_path:
        return
    try:
        prompt_chars = sum(len(m.get("content", "")) for m in messages)
        resp_chars = len(response) if response else 0
        entry = (
            f"[{'OK' if success else 'FAIL'}] model={model} "
            f"prompt_chars={prompt_chars} resp_chars={resp_chars} "
            f"elapsed={elapsed:.2f}s\n"
        )
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a") as f:
            f.write(entry)
    except Exception:
        pass
