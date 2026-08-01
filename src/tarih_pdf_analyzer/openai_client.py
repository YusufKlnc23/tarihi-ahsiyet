from __future__ import annotations

import json
from typing import Any


def load_openai_client(api_key: str) -> Any:
    try:
        from openai import OpenAI  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError("OpenAI package is required. Install with: pip install openai") from exc

    try:
        return OpenAI(api_key=api_key)
    except TypeError:
        import openai

        openai.api_key = api_key
        return openai


def create_chat_completion(client: Any, **kwargs: Any) -> Any:
    chat = getattr(client, "chat", None)
    if chat is not None and getattr(chat, "completions", None) is not None:
        return chat.completions.create(**kwargs)

    if getattr(client, "ChatCompletion", None) is not None:
        return client.ChatCompletion.create(**kwargs)

    raise RuntimeError(
        "OpenAI client does not expose a supported chat completion API. "
        "Install a compatible openai package version."
    )


def parse_chat_content(response: Any) -> dict[str, Any] | list[Any]:
    if not response or not getattr(response, "choices", None):
        raise RuntimeError("OpenAI response has no choices.")

    choice = response.choices[0]
    message = choice if isinstance(choice, dict) else getattr(choice, "message", None)
    if isinstance(message, dict):
        content = message.get("content")
    else:
        content = getattr(message, "content", None)

    if content is None:
        content = getattr(response, "output_parsed", None)

    if isinstance(content, (dict, list)):
        return content

    if isinstance(content, str):
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"OpenAI returned invalid JSON response: {exc}; content={content!r}"
            ) from exc

    raise RuntimeError(
        f"Unexpected OpenAI response content type: {type(content).__name__}"
    )
