from __future__ import annotations

import base64
import json
import platform
import time
from dataclasses import dataclass
from io import BytesIO
from typing import Any, Dict, List, Literal, Optional, Tuple

import pyautogui
import pyperclip
from PIL import Image

pyautogui.FAILSAFE = True  # move mouse to top-left to abort


ActionType = Literal[
    "screenshot",
    "click",
    "double_click",
    "right_click",
    "move",
    "scroll",
    "type",
    "keypress",
    "wait",
    "drag",
    "open_browser",
    "focus_address_bar",
    "open_url",
    "search_text",
    "paste_text",
]


@dataclass
class ComputerState:
    width: int
    height: int


def get_screen_state() -> ComputerState:
    w, h = pyautogui.size()
    return ComputerState(width=int(w), height=int(h))


def screenshot_base64(jpeg_quality: int = 85) -> str:
    img = pyautogui.screenshot()
    # Convert to RGB (JPEG does not support RGBA/palette modes).
    if img.mode != "RGB":
        img = img.convert("RGB")
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=jpeg_quality, optimize=True)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))


def _normalize_llm_string(value: Any) -> str:
    """
    Models sometimes emit JSON-string-literals or formatted strings like:
    - '"wait"'
    - '\n  "wait"\n'
    Normalize those into plain tokens like: wait
    """
    s = str(value or "").strip()
    if not s:
        return ""
    if s.startswith("`") and s.endswith("`") and len(s) >= 2:
        s = s[1:-1].strip()
    if s.startswith('"') and s.endswith('"') and len(s) >= 2:
        try:
            inner = json.loads(s)
            if isinstance(inner, str):
                s = inner.strip()
        except Exception:
            pass
    return s


def _apply_mouse_move(x: int, y: int) -> None:
    st = get_screen_state()
    x = _clamp(int(x), 0, st.width - 1)
    y = _clamp(int(y), 0, st.height - 1)
    pyautogui.moveTo(x, y, duration=0.05)


def _normalize_key(key: str) -> str:
    k = _normalize_llm_string(key).strip().lower()
    key_map = {
        "cmd": "command",
        "command": "command",
        "meta": "win",
        "windows": "win",
        "win": "win",
        "ctrl": "ctrl",
        "control": "ctrl",
        "alt": "alt",
        "option": "alt",
        "shift": "shift",
        "enter": "enter",
        "return": "enter",
        "esc": "esc",
        "escape": "esc",
        "space": "space",
        "tab": "tab",
        "backspace": "backspace",
        "delete": "delete",
        "del": "delete",
        "up": "up",
        "down": "down",
        "left": "left",
        "right": "right",
    }
    return key_map.get(k, k)


def _type_text(text: str, interval: float = 0.01) -> None:
    pyautogui.typewrite(str(text or ""), interval=interval)


def _paste_text(text: str) -> None:
    pyperclip.copy(str(text or ""))
    os_name = platform.system().lower()
    if "darwin" in os_name or "mac" in os_name:
        pyautogui.hotkey("command", "v")
    else:
        pyautogui.hotkey("ctrl", "v")


def _enter_text(text: str, prefer_paste: bool = True) -> str:
    """
    Use clipboard paste by default because it is more robust across IME states
    than simulated per-character typing. Fall back to typewrite if paste fails.
    Returns the method actually used: "paste" or "type".
    """
    text = str(text or "")
    if not text:
        return "paste" if prefer_paste else "type"
    if prefer_paste:
        try:
            _paste_text(text)
            return "paste"
        except Exception:
            pass
    _type_text(text)
    return "type"


def _press_enter() -> None:
    pyautogui.press("enter")


def _focus_address_bar() -> None:
    os_name = platform.system().lower()
    if "darwin" in os_name or "mac" in os_name:
        pyautogui.hotkey("command", "l")
    else:
        pyautogui.hotkey("ctrl", "l")


def _open_browser_app(browser_name: str) -> None:
    os_name = platform.system().lower()
    app_name = (browser_name or "chrome").strip() or "chrome"
    if "windows" in os_name:
        pyautogui.press("win")
        time.sleep(0.25)
        _type_text(app_name)
        time.sleep(0.15)
        _press_enter()
        return
    if "darwin" in os_name or "mac" in os_name:
        pyautogui.hotkey("command", "space")
        time.sleep(0.35)
        _type_text(app_name)
        time.sleep(0.15)
        _press_enter()
        return
    # Linux fallback
    pyautogui.press("win")
    time.sleep(0.25)
    _type_text(app_name)
    time.sleep(0.15)
    _press_enter()


def execute_action(action: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute a single local UI action via pyautogui.
    Returns a small JSON-serializable result for logging.
    """
    t = _normalize_llm_string(action.get("action"))
    out: Dict[str, Any] = {"ok": True, "action": t}

    if t == "screenshot":
        out["note"] = "screenshot_requested"
        return out

    if t == "open_browser":
        browser_name = str(action.get("browser") or action.get("app_name") or "chrome")
        _open_browser_app(browser_name)
        out["note"] = f"open_browser_requested:{browser_name}"
        return out

    if t == "focus_address_bar":
        _focus_address_bar()
        out["note"] = "focus_address_bar_requested"
        return out

    if t == "open_url":
        url = str(action.get("url") or "").strip()
        if not url:
            raise ValueError("open_url requires `url`")
        _focus_address_bar()
        time.sleep(0.08)
        method = _enter_text(url, prefer_paste=True)
        time.sleep(0.05)
        _press_enter()
        out["note"] = f"open_url_requested:{url}"
        out["input_method"] = method
        return out

    if t == "search_text":
        query = str(action.get("query") or action.get("text") or "").strip()
        if not query:
            raise ValueError("search_text requires `query` or `text`")
        method = _enter_text(query, prefer_paste=True)
        press_enter = action.get("press_enter", True)
        if bool(press_enter):
            time.sleep(0.05)
            _press_enter()
        out["note"] = f"search_text_requested:{query}"
        out["input_method"] = method
        return out

    if t == "paste_text":
        text = str(action.get("text", ""))
        _paste_text(text)
        out["note"] = "paste_text_requested"
        return out

    if t == "wait":
        ms = action.get("ms")
        seconds = action.get("seconds")
        if ms is None and seconds is None:
            seconds = 1.0
        if ms is not None:
            time.sleep(max(0.0, float(ms) / 1000.0))
        else:
            time.sleep(max(0.0, float(seconds)))
        return out

    if t in ("click", "double_click", "right_click", "move"):
        x = int(action.get("x", 0))
        y = int(action.get("y", 0))
        _apply_mouse_move(x, y)
        if t == "move":
            return out
        if t == "click":
            pyautogui.click()
            return out
        if t == "double_click":
            pyautogui.doubleClick()
            return out
        if t == "right_click":
            pyautogui.rightClick()
            return out

    if t == "scroll":
        # Agent semantics: positive scrollY means scroll down the page.
        # pyautogui.scroll uses the opposite sign on major desktop platforms.
        x = int(action.get("x", pyautogui.position().x))
        y = int(action.get("y", pyautogui.position().y))
        _apply_mouse_move(x, y)
        scroll_y = int(action.get("scrollY", action.get("scroll_y", 0)))
        pyautogui.scroll(-scroll_y)
        return out

    if t == "type":
        text = str(action.get("text", ""))
        method = _enter_text(text, prefer_paste=True)
        out["input_method"] = method
        return out

    if t == "keypress":
        keys = action.get("keys") or []
        if isinstance(keys, str):
            keys = [keys]
        if not isinstance(keys, list):
            raise ValueError("keys must be a list of strings")
        normalized = [_normalize_key(str(k)) for k in keys if str(k).strip()]
        if not normalized:
            return out
        # If multiple keys are provided, treat them as a hotkey combo.
        if len(normalized) == 1:
            pyautogui.press(normalized[0])
        else:
            pyautogui.hotkey(*normalized)
        return out

    if t == "drag":
        # Expect path: [[x1,y1],[x2,y2],...]
        path = action.get("path") or []
        if not isinstance(path, list) or len(path) < 2:
            raise ValueError("drag requires a path array with >=2 points")
        p0 = path[0]
        if not isinstance(p0, (list, tuple)) or len(p0) < 2:
            raise ValueError("drag path points must be [x,y]")
        _apply_mouse_move(int(p0[0]), int(p0[1]))
        pyautogui.mouseDown()
        try:
            for pt in path[1:]:
                if not isinstance(pt, (list, tuple)) or len(pt) < 2:
                    continue
                _apply_mouse_move(int(pt[0]), int(pt[1]))
        finally:
            pyautogui.mouseUp()
        return out

    raise ValueError(f"Unsupported action: {t}")
