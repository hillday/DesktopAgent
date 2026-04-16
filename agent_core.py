from __future__ import annotations

import json
import platform
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from computer_control import execute_action, get_screen_state, screenshot_base64
from config import AppConfig
from llm_client import chat_with_tools, make_openai_client


def _extract_json_object(text: str) -> Dict[str, Any]:
    text = (text or "").strip()
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except Exception:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            data = json.loads(text[start : end + 1])
            return data if isinstance(data, dict) else {}
        except Exception:
            pass
    return {}


def _compact_action(action: Dict[str, Any]) -> str:
    safe = {
        "action": action.get("action"),
        "browser": action.get("browser"),
        "url": action.get("url"),
        "query": action.get("query"),
        "press_enter": action.get("press_enter"),
        "x": action.get("x"),
        "y": action.get("y"),
        "text": action.get("text"),
        "keys": action.get("keys"),
        "scrollX": action.get("scrollX"),
        "scrollY": action.get("scrollY"),
        "path": action.get("path"),
    }
    return json.dumps(safe, ensure_ascii=False)


def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))


def _provider_uses_normalized_coords(provider: str) -> bool:
    return (provider or "").strip().lower() == "doubao"


def _denormalize_xy(nx: Any, ny: Any, width: int, height: int) -> tuple[int, int]:
    width = max(1, int(width))
    height = max(1, int(height))
    x = int(round((float(nx) / 1000.0) * width))
    y = int(round((float(ny) / 1000.0) * height))
    return _clamp(x, 0, width - 1), _clamp(y, 0, height - 1)


def _map_action_to_physical_pixels(
    action: Dict[str, Any], width: int, height: int
) -> Dict[str, Any]:
    mapped = dict(action)

    if "x" in mapped and "y" in mapped:
        try:
            mapped["x"], mapped["y"] = _denormalize_xy(mapped["x"], mapped["y"], width, height)
        except Exception:
            pass

    path = mapped.get("path")
    if isinstance(path, list):
        new_path = []
        for pt in path:
            if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                try:
                    x, y = _denormalize_xy(pt[0], pt[1], width, height)
                    new_path.append([x, y])
                except Exception:
                    new_path.append(pt)
            else:
                new_path.append(pt)
        mapped["path"] = new_path

    return mapped


@dataclass
class LoopState:
    task: str
    plan: List[str]
    current_step_index: int = 0
    turns: int = 0
    status: str = "running"
    action_history: List[str] = field(default_factory=list)
    last_assistant_text: str = ""
    last_supervisor_message: str = ""
    last_verifier_message: str = ""
    # Cache the most recent "before/after" screenshots so planner/verifier can compare state changes.
    last_before_screenshot_b64: str = ""
    last_after_screenshot_b64: str = ""


class DesktopPlannerAgent:
    def __init__(
        self,
        cfg: AppConfig,
        on_log: Callable[[str], None],
        on_status: Optional[Callable[[str], None]] = None,
        on_screenshot: Optional[Callable[[str], None]] = None,
        confirm_action: Optional[Callable[[Dict[str, Any]], bool]] = None,
        should_stop: Optional[Callable[[], bool]] = None,
    ):
        self.cfg = cfg
        self.on_log = on_log
        self.on_status = on_status or (lambda _msg: None)
        self.on_screenshot = on_screenshot or (lambda _b64: None)
        self.confirm_action = confirm_action or (lambda _action: True)
        self.should_stop = should_stop or (lambda: False)
        self.client = make_openai_client(cfg)

    def _log(self, msg: str) -> None:
        self.on_log(msg.rstrip())

    def _model_for_role(self, role: str) -> str:
        if role == "planner" and self.cfg.planner_model.strip():
            return self.cfg.planner_model.strip()
        if role == "executor" and self.cfg.executor_model.strip():
            return self.cfg.executor_model.strip()
        if role == "verifier" and self.cfg.verifier_model.strip():
            return self.cfg.verifier_model.strip()
        return self.cfg.model

    def _plan(
        self,
        task: str,
        extra_context: str = "",
        before_screenshot_b64: Optional[str] = None,
        after_screenshot_b64: Optional[str] = None,
    ) -> List[str]:
        self.on_status("Planning")
        os_name = platform.system().strip() or "Unknown"
        prompt = (
            "You are a planner for a desktop UI agent.\n"
            'Return strict JSON only: {"steps": ["..."]}\n'
            "Rules:\n"
            "- 4 to 12 concise steps.\n"
            "- Steps must be observable and executable on a real desktop UI.\n"
            "- Prefer safe navigation/search/open/click/type/check steps.\n"
            "- When the task requires opening an application, prefer deterministic keyboard-first launch steps instead of guessing taskbar/dock icons.\n"
            "- After opening a browser or desktop app, inspect the screenshot. If the window is too small and a larger viewport would help, let the model visually identify the maximize control and click it with a normal click action.\n"
            "- All click coordinates must come from screenshot understanding, not hardcoded geometry.\n"
            "- Prefer browser-specific high-level actions when relevant: open_browser, focus_address_bar, open_url, search_text, paste_text.\n"
            "- For Chinese or other non-ASCII text, prefer paste-style input instead of letter-by-letter typing.\n"
            f"- Current OS: {os_name}.\n"
            "- On Windows, prefer Start/Win search or Win+R to open apps.\n"
            "- On macOS, prefer Spotlight (Cmd+Space) to open apps.\n"
            "- Do not include explanations outside JSON.\n\n"
            f"Task:\n{task}\n\n"
        )
        if extra_context:
            prompt += f"Extra context:\n{extra_context}\n"
        if before_screenshot_b64 and after_screenshot_b64:
            prompt += (
                "\nYou are given TWO screenshots:\n"
                "- Screenshot A: before the last action / decision\n"
                "- Screenshot B: after the last action / decision\n"
                "Use them to infer what changed and adjust the plan.\n"
            )

        user_content: Any
        if before_screenshot_b64 and after_screenshot_b64:
            user_content = [
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{before_screenshot_b64}",
                        "detail": "high",
                    },
                },
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{after_screenshot_b64}",
                        "detail": "high",
                    },
                },
            ]
        else:
            user_content = prompt

        resp = self.client.chat.completions.create(
            model=self._model_for_role("planner"),
            messages=[
                {"role": "system", "content": "You output only JSON."},
                {"role": "user", "content": user_content},
            ],
        )
        text = resp.choices[0].message.content or ""
        data = _extract_json_object(text)
        steps = data.get("steps")
        if isinstance(steps, list):
            normalized = [str(s).strip() for s in steps if str(s).strip()]
            if normalized:
                return normalized[:12]
        return ["Inspect the current screen", "Perform the task safely", "Verify the result"]

    def _decision_tools(self) -> List[Dict[str, Any]]:
        state = get_screen_state()
        use_normalized = _provider_uses_normalized_coords(self.cfg.provider)
        coord_desc = (
            "Use 0-1000 normalized screen coordinates for x/y."
            if use_normalized
            else f"Use physical screen pixel coordinates. Screen size is {state.width}x{state.height}."
        )
        computer_tool = {
            "type": "function",
            "function": {
                "name": "computer",
                "description": f"Control the user's real computer. {coord_desc}",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": [
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
                            ],
                        },
                        "browser": {"type": "string"},
                        "url": {"type": "string"},
                        "query": {"type": "string"},
                        "press_enter": {"type": "boolean"},
                        "x": {"type": "integer", "description": "X coordinate"},
                        "y": {"type": "integer", "description": "Y coordinate"},
                        "text": {"type": "string"},
                        "keys": {"type": "array", "items": {"type": "string"}},
                        "scrollX": {"type": "integer"},
                        "scrollY": {"type": "integer"},
                        "path": {
                            "type": "array",
                            "items": {"type": "array", "items": {"type": "integer"}},
                        },
                    },
                    "required": ["action"],
                },
            },
        }
        supervisor_tool = {
            "type": "function",
            "function": {
                "name": "supervisor_update",
                "description": (
                    "Use this when you want to mark the current step done, the task done, "
                    "the task blocked, or request replanning."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "status": {
                            "type": "string",
                            "enum": ["step_done", "task_done", "blocked", "replan_required"],
                        },
                        "message": {"type": "string"},
                    },
                    "required": ["status"],
                },
            },
        }
        return [computer_tool, supervisor_tool]

    def _decide(
        self,
        loop_state: LoopState,
        screenshot_b64: str,
    ):
        self.on_status(f"Running step {loop_state.current_step_index + 1}/{len(loop_state.plan)}")
        screen_state = get_screen_state()
        os_name = platform.system().strip() or "Unknown"
        use_normalized = _provider_uses_normalized_coords(self.cfg.provider)
        coord_instruction = (
            "Coordinate space: use integers in a 0-1000 normalized screen space for any x/y/path values."
            if use_normalized
            else f"Coordinate space: use physical pixel coordinates on a {screen_state.width}x{screen_state.height} screen."
        )
        current_step = (
            loop_state.plan[loop_state.current_step_index]
            if loop_state.current_step_index < len(loop_state.plan)
            else "(none)"
        )
        completed = loop_state.plan[: loop_state.current_step_index]
        remaining = loop_state.plan[loop_state.current_step_index :]
        history_text = (
            "\n".join(loop_state.action_history[-8:]) if loop_state.action_history else "(none)"
        )

        prompt_text = (
            "You are the supervisor/executor of a desktop UI agent.\n"
            "You must either:\n"
            "1. Call `computer` with exactly ONE next UI action, OR\n"
            "2. Call `supervisor_update` to mark step_done/task_done/blocked/replan_required.\n\n"
            "Guidelines:\n"
            "- Prefer screenshot-first reasoning when unsure.\n"
            "- Use small, verifiable actions.\n"
            "- Do not guess taskbar or dock icons when a keyboard-based app launch is more reliable.\n"
            f"- Current OS: {os_name}.\n"
            f"- {coord_instruction}\n"
            "- Prefer high-level browser actions over low-level key/mouse sequences whenever possible.\n"
            "- Use `open_browser` to launch Chrome/browser.\n"
            "- Use `focus_address_bar` before browser navigation if needed.\n"
            "- Use `open_url` to navigate directly to a URL.\n"
            "- Use `search_text` to enter a query into the currently focused search/input field and submit it.\n"
            "- For any text entry, prefer clipboard-style paste over per-character typing because IME/input-method state may be wrong.\n"
            "- Use `paste_text` when you need to enter Chinese or other non-ASCII text reliably.\n"
            "- If search/input entry fails because of IME or keyboard layout, keep using paste-style entry; do not retry fragile character-by-character `type` repeatedly.\n"
            "- If the browser window is too small, first determine from the screenshot whether it is already maximized. If not, visually identify the maximize control and use a normal `click` action on that UI element.\n"
            "- Never rely on hardcoded maximize coordinates or hidden window geometry assumptions.\n"
            "- If you need to open an app on Windows and high-level actions are not suitable, prefer keypress with ['win'] then type the app name, or use ['win','r'] then type a command, then ['enter'].\n"
            "- If you need to open an app on macOS and high-level actions are not suitable, prefer keypress with ['command','space'], then type the app name, then ['enter'].\n"
            "- `keypress` with multiple keys means a combo hotkey, not sequential presses.\n"
            "- After enough actions to finish the current step, call supervisor_update(step_done).\n"
            "- If the whole task is done, call supervisor_update(task_done).\n"
            "- If the current plan is wrong, call supervisor_update(replan_required).\n"
            "- If blocked with no safe next action, call supervisor_update(blocked).\n\n"
            f"Task:\n{loop_state.task}\n\n"
            f"Completed steps:\n{json.dumps(completed, ensure_ascii=False)}\n\n"
            f"Current step:\n{current_step}\n\n"
            f"Remaining steps:\n{json.dumps(remaining, ensure_ascii=False)}\n\n"
            f"Recent action history:\n{history_text}\n\n"
            f"Loop turn: {loop_state.turns}\n"
            f"Previous supervisor note: {loop_state.last_supervisor_message or '(none)'}\n"
            f"Previous assistant text: {loop_state.last_assistant_text or '(none)'}\n"
            f"Screen size: {screen_state.width}x{screen_state.height}\n"
        )

        return chat_with_tools(
            client=self.client,
            model=self._model_for_role("executor"),
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt_text},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{screenshot_b64}",
                                "detail": "high",
                            },
                        },
                    ],
                }
            ],
            tools=self._decision_tools(),
        )

    def _verify(
        self,
        loop_state: LoopState,
        before_screenshot_b64: str,
        after_screenshot_b64: str,
        last_event: str,
    ) -> Dict[str, str]:
        self.on_status(f"Verifying step {loop_state.current_step_index + 1}/{len(loop_state.plan)}")
        current_step = (
            loop_state.plan[loop_state.current_step_index]
            if loop_state.current_step_index < len(loop_state.plan)
            else "(none)"
        )
        prompt = (
            "You are the verifier of a desktop UI agent.\n"
            "Return strict JSON only in this shape:\n"
            '{"status":"continue|step_done|task_done|replan_required|blocked","message":"..."}\n\n'
            "Definitions:\n"
            "- continue: current step is not finished yet, keep acting\n"
            "- step_done: current step is complete, move to next step\n"
            "- task_done: whole task is complete\n"
            "- replan_required: plan is wrong or outdated\n"
            "- blocked: cannot continue safely\n\n"
            "- If the agent is still trying random taskbar/dock clicks to open an app, prefer replan_required so the planner can switch to a keyboard-first launch strategy.\n\n"
            "- If the app or browser is open but the viewport is too small for reliable control, prefer continue with a note suggesting the executor visually identify and click the maximize control.\n\n"
            "- If the current step is browser launch/navigation/search, prefer high-level browser actions such as `open_browser`, `open_url`, `focus_address_bar`, `search_text`, and `paste_text` over fragile low-level clicks.\n"
            "- If any text entry failed or appears garbled, prefer continue with a note suggesting paste-style entry (`paste_text` / `search_text`) instead of repeating `type`.\n\n"
            "You are given TWO screenshots:\n"
            "- Screenshot A: BEFORE the last action / decision\n"
            "- Screenshot B: AFTER the last action / decision\n"
            "Compare them to determine whether the action had the intended effect.\n\n"
            "Be conservative. Only return step_done/task_done if it is visible from the screenshot or strongly implied by the last event.\n\n"
            f"Task:\n{loop_state.task}\n\n"
            f"Current step:\n{current_step}\n\n"
            f"Whole plan:\n{json.dumps(loop_state.plan, ensure_ascii=False)}\n\n"
            f"Recent action history:\n{chr(10).join(loop_state.action_history[-8:]) if loop_state.action_history else '(none)'}\n\n"
            f"Previous verifier note:\n{loop_state.last_verifier_message or '(none)'}\n\n"
            f"Last event:\n{last_event}\n"
        )
        resp = self.client.chat.completions.create(
            model=self._model_for_role("verifier"),
            messages=[
                {"role": "system", "content": "You output only JSON."},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{before_screenshot_b64}",
                                "detail": "high",
                            },
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{after_screenshot_b64}",
                                "detail": "high",
                            },
                        },
                    ],
                },
            ],
        )
        text = resp.choices[0].message.content or ""
        data = _extract_json_object(text)
        status = str(data.get("status", "continue")).strip() or "continue"
        message = str(data.get("message", "")).strip()
        if status not in {"continue", "step_done", "task_done", "replan_required", "blocked"}:
            status = "continue"
        return {"status": status, "message": message}

    def _make_initial_state(self, task: str) -> LoopState:
        plan = self._plan(task)
        self._log("[planner] generated plan:")
        for i, step in enumerate(plan, start=1):
            self._log(f"  {i}. {step}")
        return LoopState(task=task, plan=plan)

    def _should_continue(self, loop_state: LoopState) -> bool:
        if self.should_stop():
            loop_state.status = "stopped"
            self._log("[system] stopped by user")
            return False
        if loop_state.current_step_index >= len(loop_state.plan):
            loop_state.status = "completed"
            self._log("[system] completed all planned steps")
            return False
        if loop_state.turns >= int(self.cfg.max_turns):
            loop_state.status = "max_turns"
            self._log("[system] reached max turns")
            return False
        return True

    def _replan(self, loop_state: LoopState) -> None:
        before_b64 = loop_state.last_before_screenshot_b64.strip() or None
        after_b64 = loop_state.last_after_screenshot_b64.strip() or before_b64
        if before_b64 and after_b64:
            self._log("[planner] replanning with before/after screenshots")
        replanned = self._plan(
            loop_state.task,
            extra_context=(
                f"Old plan: {json.dumps(loop_state.plan, ensure_ascii=False)}\n"
                f"Current step index: {loop_state.current_step_index}\n"
                f"Recent action history:\n" + "\n".join(loop_state.action_history[-8:])
            ),
            before_screenshot_b64=before_b64,
            after_screenshot_b64=after_b64,
        )
        loop_state.plan = replanned
        loop_state.current_step_index = 0
        self._log("[planner] replanned:")
        for i, step in enumerate(loop_state.plan, start=1):
            self._log(f"  {i}. {step}")

    def _handle_computer_tool_call(self, loop_state: LoopState, action: Dict[str, Any]) -> None:
        action_to_execute = action
        if _provider_uses_normalized_coords(self.cfg.provider):
            screen_state = get_screen_state()
            action_to_execute = _map_action_to_physical_pixels(
                action, screen_state.width, screen_state.height
            )
            self._log(f"[computer/raw] {_compact_action(action)}")
            self._log(f"[computer/mapped] {_compact_action(action_to_execute)}")
        else:
            self._log(f"[computer] {_compact_action(action)}")

        if self.cfg.hitl and not self.confirm_action(action_to_execute):
            self._log("[human] rejected action")
            loop_state.action_history.append(
                "Human rejected action: " + _compact_action(action_to_execute)
            )
            return

        try:
            result_obj = execute_action(action_to_execute)
            self._log(f"[computer-result] {json.dumps(result_obj, ensure_ascii=False)}")
            loop_state.action_history.append("Executed: " + _compact_action(action_to_execute))
            time.sleep(max(0.0, int(self.cfg.screenshot_delay_ms) / 1000.0))
        except Exception as e:
            self._log(f"[computer-error] {type(e).__name__}: {e}")
            loop_state.action_history.append(f"Action error: {type(e).__name__}: {e}")

    def _handle_supervisor_update(self, loop_state: LoopState, arguments: Dict[str, Any]) -> None:
        status = str(arguments.get("status", "blocked"))
        message = str(arguments.get("message", ""))
        loop_state.last_supervisor_message = message
        self._log(f"[supervisor] {status}: {message}")

        if status == "step_done":
            loop_state.current_step_index += 1
            return
        if status == "task_done":
            loop_state.status = "completed"
            self._log("[system] task completed")
            return
        if status == "replan_required":
            self._replan(loop_state)
            return

        loop_state.status = "blocked"
        self._log("[system] blocked")

    def _handle_verifier_update(self, loop_state: LoopState, verification: Dict[str, str]) -> None:
        status = verification.get("status", "continue")
        message = verification.get("message", "")
        loop_state.last_verifier_message = message
        self._log(f"[verifier] {status}: {message}")

        if status == "continue":
            return
        if status == "step_done":
            loop_state.current_step_index += 1
            return
        if status == "task_done":
            loop_state.status = "completed"
            self._log("[system] task completed")
            return
        if status == "replan_required":
            self._replan(loop_state)
            return
        loop_state.status = "blocked"
        self._log("[system] blocked by verifier")

    def _run_turn(self, loop_state: LoopState) -> None:
        loop_state.turns += 1
        self._log(
            f"[loop] turn={loop_state.turns} step={loop_state.current_step_index + 1}/{len(loop_state.plan)}"
        )
        self._log("[loop] observe")
        screen_b64 = screenshot_base64()
        loop_state.last_before_screenshot_b64 = screen_b64
        self.on_screenshot(screen_b64)

        self._log("[loop] decide")
        result = self._decide(loop_state=loop_state, screenshot_b64=screen_b64)
        loop_state.last_assistant_text = result.assistant_text or ""

        if result.assistant_text:
            self._log(f"[assistant] {result.assistant_text}")

        if not result.tool_calls:
            loop_state.status = "no_tool_call"
            self._log("[supervisor] no tool call returned, stopping")
            return

        for tc in result.tool_calls:
            if tc.name == "computer":
                action = tc.arguments if isinstance(tc.arguments, dict) else {}
                self._log("[loop] execute")
                self._handle_computer_tool_call(loop_state, action)
                if loop_state.status != "running":
                    return

                self._log("[loop] observe-after-action")
                screen_b64_after = screenshot_base64()
                loop_state.last_after_screenshot_b64 = screen_b64_after
                self.on_screenshot(screen_b64_after)
                self._log("[loop] verify")
                verification = self._verify(
                    loop_state=loop_state,
                    before_screenshot_b64=screen_b64,
                    after_screenshot_b64=screen_b64_after,
                    last_event="Executed action: " + _compact_action(action),
                )
                self._handle_verifier_update(loop_state, verification)
                return

            if tc.name == "supervisor_update":
                self._log("[loop] supervise")
                self._handle_supervisor_update(loop_state, tc.arguments)
                if loop_state.status != "running":
                    return

                # Keep a consistent before/after pair for verifier even if no local action was executed.
                screen_b64_after = screenshot_base64()
                loop_state.last_after_screenshot_b64 = screen_b64_after
                self.on_screenshot(screen_b64_after)
                self._log("[loop] verify")
                verification = self._verify(
                    loop_state=loop_state,
                    before_screenshot_b64=screen_b64,
                    after_screenshot_b64=screen_b64_after,
                    last_event=(
                        "Supervisor proposed: " + json.dumps(tc.arguments, ensure_ascii=False)
                    ),
                )
                self._handle_verifier_update(loop_state, verification)
                return

        loop_state.status = "blocked"
        self._log("[system] no supported tool call returned")

    def run(self, task: str) -> str:
        try:
            loop_state = self._make_initial_state(task)
            while self._should_continue(loop_state):
                self._run_turn(loop_state)
                if loop_state.status != "running":
                    break
            return loop_state.status
        except Exception:
            self._log("[fatal]\n" + traceback.format_exc())
            return "fatal"
