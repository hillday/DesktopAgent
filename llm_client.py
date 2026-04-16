from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from config import AppConfig, get_api_key, make_default_headers
from openai import OpenAI


@dataclass
class ToolCall:
    name: str
    arguments: Dict[str, Any]
    tool_call_id: str


@dataclass
class LLMResult:
    assistant_text: str
    tool_calls: List[ToolCall]


def make_openai_client(cfg: AppConfig) -> OpenAI:
    api_key = get_api_key(cfg)
    if not api_key:
        raise RuntimeError(f"Missing API key in env var: {cfg.api_key_env}")

    base_url = None
    provider = (cfg.provider or "").lower().strip()
    if provider == "openrouter":
        base_url = cfg.api_base or "https://openrouter.ai/api/v1"
    elif provider == "openai":
        base_url = cfg.api_base or "https://api.openai.com/v1"
    elif provider == "doubao":
        # Volcengine Ark OpenAI-compatible endpoint
        base_url = cfg.api_base or "https://ark.cn-beijing.volces.com/api/v3"
    else:
        base_url = cfg.api_base or "https://api.openai.com/v1"

    headers = make_default_headers(cfg)
    return OpenAI(api_key=api_key, base_url=base_url, default_headers=headers)


def chat_with_tools(
    client: OpenAI,
    model: str,
    messages: List[Dict[str, Any]],
    tools: List[Dict[str, Any]],
) -> LLMResult:
    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        tools=tools,
    )
    msg = resp.choices[0].message

    assistant_text = msg.content or ""
    tool_calls: List[ToolCall] = []
    if msg.tool_calls:
        for tc in msg.tool_calls:
            name = tc.function.name
            raw_args = tc.function.arguments or "{}"
            try:
                args = json.loads(raw_args)
            except Exception:
                args = {"_raw": raw_args}
            tool_calls.append(ToolCall(name=name, arguments=args, tool_call_id=tc.id))

    return LLMResult(assistant_text=assistant_text, tool_calls=tool_calls)
