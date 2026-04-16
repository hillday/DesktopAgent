from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass
class AppConfig:
    provider: str = "openrouter"  # openai | openrouter | doubao
    model: str = "openai/gpt-5.4"
    planner_model: str = ""
    executor_model: str = ""
    verifier_model: str = ""
    api_key_env: str = "OPENROUTER_API_KEY"
    api_base: str = "https://openrouter.ai/api/v1"
    # Optional OpenRouter headers (safe defaults)
    openrouter_referer: str = ""
    openrouter_title: str = "desktop-agent-app"

    # Loop limits / timing
    max_turns: int = 40
    screenshot_delay_ms: int = 500

    # Safety: require confirmation for risky actions
    hitl: bool = False

    # UX: minimize the app window when running to avoid capturing itself in screenshots
    auto_minimize_on_send: bool = True


def normalize_provider(provider: str) -> str:
    return (provider or "").strip().lower() or "openrouter"


def default_api_base_for_provider(provider: str) -> str:
    p = normalize_provider(provider)
    if p == "openai":
        return "https://api.openai.com/v1"
    if p == "openrouter":
        return "https://openrouter.ai/api/v1"
    if p == "doubao":
        return "https://ark.cn-beijing.volces.com/api/v3"
    return "https://api.openai.com/v1"


def default_api_key_env_for_provider(provider: str) -> str:
    p = normalize_provider(provider)
    if p == "openai":
        return "OPENAI_API_KEY"
    if p == "openrouter":
        return "OPENROUTER_API_KEY"
    if p == "doubao":
        return "ARK_API_KEY"
    return "OPENAI_API_KEY"


def coordinate_mode_for_provider(provider: str) -> str:
    p = normalize_provider(provider)
    if p == "doubao":
        return "1000x1000 normalized"
    return "physical pixels"


def default_config_path() -> Path:
    # Store alongside this script (portable). Users can move the folder as a "project".
    return Path(__file__).resolve().parent / "config.json"


def load_config(path: Optional[Path] = None) -> AppConfig:
    path = path or default_config_path()
    if not path.exists():
        return AppConfig()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return AppConfig()
        cfg = AppConfig()
        for k, v in data.items():
            if hasattr(cfg, k):
                setattr(cfg, k, v)
        return cfg
    except Exception:
        return AppConfig()


def save_config(cfg: AppConfig, path: Optional[Path] = None) -> None:
    path = path or default_config_path()
    path.write_text(json.dumps(asdict(cfg), ensure_ascii=False, indent=2), encoding="utf-8")


def get_api_key(cfg: AppConfig) -> str:
    raw = (cfg.api_key_env or "").strip()
    # Support two modes:
    # 1) api_key_env is an env var name (recommended): OPENAI_API_KEY / OPENROUTER_API_KEY / ARK_API_KEY / ...
    # 2) api_key_env is the actual key pasted directly (works, but less secure)
    #
    # Heuristic: if it's ALL_CAPS_WITH_UNDERSCORES, treat as env var name; otherwise treat as key.
    if re.fullmatch(r"[A-Z0-9_]{2,64}", raw):
        return os.getenv(raw, "").strip()
    return raw


def make_default_headers(cfg: AppConfig) -> Dict[str, str]:
    headers: Dict[str, str] = {}
    if cfg.provider.lower() == "openrouter":
        if cfg.openrouter_referer:
            headers["HTTP-Referer"] = cfg.openrouter_referer
        if cfg.openrouter_title:
            headers["X-Title"] = cfg.openrouter_title
    return headers
