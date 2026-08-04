from __future__ import annotations

from typing import Any


def load_gemini_client(api_key: str) -> Any:
    try:
        from google import genai  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "Gemini icin `google-genai` paketi gerekli. Kurulum: pip install google-genai"
        ) from exc
    return genai.Client(api_key=api_key)


def generate_text(
    api_key: str,
    model: str,
    system: str,
    user: str,
    temperature: float = 0.25,
    max_output_tokens: int = 1800,
    thinking_budget: int | None = 0,
) -> str:
    try:
        from google.genai import types  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "Gemini icin `google-genai` paketi gerekli. Kurulum: pip install google-genai"
        ) from exc

    client = load_gemini_client(api_key)
    config_kwargs: dict[str, Any] = {
        "system_instruction": system,
        "temperature": temperature,
        "max_output_tokens": max_output_tokens,
    }
    if thinking_budget is not None:
        config_kwargs["thinking_config"] = types.ThinkingConfig(
            thinking_budget=thinking_budget
        )

    response = client.models.generate_content(
        model=model,
        contents=user,
        config=types.GenerateContentConfig(**config_kwargs),
    )
    text = getattr(response, "text", None)
    if isinstance(text, str) and text.strip():
        return text.strip()
    candidates = getattr(response, "candidates", None) or []
    if candidates:
        content = getattr(candidates[0], "content", None)
        parts = getattr(content, "parts", None) or []
        joined = "".join(
            getattr(part, "text", "")
            for part in parts
            if getattr(part, "text", None)
        ).strip()
        if joined:
            return joined
    raise RuntimeError("Gemini response did not return text content.")
