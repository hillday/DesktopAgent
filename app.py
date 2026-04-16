from __future__ import annotations

import base64
import json
import queue
import threading
import tkinter as tk
from io import BytesIO
from tkinter import messagebox, scrolledtext, ttk
from typing import Any, Dict, List, Optional

from agent_core import DesktopPlannerAgent
from config import (
    AppConfig,
    default_api_base_for_provider,
    default_api_key_env_for_provider,
    load_config,
    save_config,
)
from PIL import Image, ImageTk
from run_history import RunRecord, append_history, load_history, new_record


class ConfigDialog(tk.Toplevel):
    def __init__(self, parent: "DesktopAgentApp", cfg: AppConfig):
        super().__init__(parent.root)
        self.parent = parent
        self.cfg = cfg
        self.title("Agent Config")
        self.resizable(False, False)
        self.transient(parent.root)
        self.grab_set()

        self.vars: Dict[str, Any] = {
            "provider": tk.StringVar(value=cfg.provider),
            "model": tk.StringVar(value=cfg.model),
            "planner_model": tk.StringVar(value=cfg.planner_model),
            "executor_model": tk.StringVar(value=cfg.executor_model),
            "verifier_model": tk.StringVar(value=cfg.verifier_model),
            "api_key_env": tk.StringVar(value=cfg.api_key_env),
            "api_base": tk.StringVar(value=cfg.api_base),
            "openrouter_referer": tk.StringVar(value=cfg.openrouter_referer),
            "openrouter_title": tk.StringVar(value=cfg.openrouter_title),
            "max_turns": tk.StringVar(value=str(cfg.max_turns)),
            "screenshot_delay_ms": tk.StringVar(value=str(cfg.screenshot_delay_ms)),
            "hitl": tk.BooleanVar(value=cfg.hitl),
            "auto_minimize_on_send": tk.BooleanVar(
                value=getattr(cfg, "auto_minimize_on_send", True)
            ),
        }

        fields = [
            ("Default Model", "model"),
            ("Planner Model", "planner_model"),
            ("Executor Model", "executor_model"),
            ("Verifier Model", "verifier_model"),
            ("API Key Env", "api_key_env"),
            ("API Base", "api_base"),
            ("OpenRouter Referer", "openrouter_referer"),
            ("OpenRouter Title", "openrouter_title"),
            ("Max Turns", "max_turns"),
            ("Screenshot Delay (ms)", "screenshot_delay_ms"),
        ]

        body = ttk.Frame(self, padding=12)
        body.grid(row=0, column=0, sticky="nsew")

        ttk.Label(body, text="Provider").grid(row=0, column=0, sticky="w", pady=4)
        provider_combo = ttk.Combobox(
            body,
            textvariable=self.vars["provider"],
            values=["openai", "openrouter", "doubao"],
            state="readonly",
            width=45,
        )
        provider_combo.grid(row=0, column=1, sticky="ew", pady=4)
        provider_combo.bind("<<ComboboxSelected>>", self.on_provider_changed)

        for i, (label, key) in enumerate(fields, start=1):
            ttk.Label(body, text=label).grid(row=i, column=0, sticky="w", pady=4)
            ttk.Entry(body, textvariable=self.vars[key], width=48).grid(
                row=i, column=1, sticky="ew", pady=4
            )

        ttk.Checkbutton(body, text="Human-in-the-loop", variable=self.vars["hitl"]).grid(
            row=len(fields) + 1, column=0, columnspan=2, sticky="w", pady=(8, 4)
        )
        ttk.Checkbutton(
            body,
            text="Auto minimize on Send",
            variable=self.vars["auto_minimize_on_send"],
        ).grid(row=len(fields) + 2, column=0, columnspan=2, sticky="w", pady=(0, 4))

        btns = ttk.Frame(body)
        btns.grid(row=len(fields) + 3, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="right", padx=4)
        ttk.Button(btns, text="Save", command=self.on_save).pack(side="right", padx=4)

    def on_provider_changed(self, _event=None) -> None:
        provider = self.vars["provider"].get().strip() or "openrouter"

        current_api_base = self.vars["api_base"].get().strip()
        current_api_key_env = self.vars["api_key_env"].get().strip()
        known_bases = {
            "https://api.openai.com/v1",
            "https://openrouter.ai/api/v1",
            "https://ark.cn-beijing.volces.com/api/v3",
            "",
        }
        known_key_envs = {"OPENAI_API_KEY", "OPENROUTER_API_KEY", "ARK_API_KEY", ""}

        if current_api_base in known_bases:
            self.vars["api_base"].set(default_api_base_for_provider(provider))
        if current_api_key_env in known_key_envs:
            self.vars["api_key_env"].set(default_api_key_env_for_provider(provider))

    def on_save(self) -> None:
        self.cfg.provider = self.vars["provider"].get().strip() or "openrouter"
        self.cfg.model = self.vars["model"].get().strip() or "openai/gpt-5.4"
        self.cfg.planner_model = self.vars["planner_model"].get().strip()
        self.cfg.executor_model = self.vars["executor_model"].get().strip()
        self.cfg.verifier_model = self.vars["verifier_model"].get().strip()
        self.cfg.api_key_env = self.vars["api_key_env"].get().strip() or "OPENROUTER_API_KEY"
        self.cfg.api_base = self.vars["api_base"].get().strip()
        self.cfg.openrouter_referer = self.vars["openrouter_referer"].get().strip()
        self.cfg.openrouter_title = self.vars["openrouter_title"].get().strip()
        self.cfg.max_turns = max(1, int(self.vars["max_turns"].get().strip() or "40"))
        self.cfg.screenshot_delay_ms = max(
            0, int(self.vars["screenshot_delay_ms"].get().strip() or "500")
        )
        self.cfg.hitl = bool(self.vars["hitl"].get())
        self.cfg.auto_minimize_on_send = bool(self.vars["auto_minimize_on_send"].get())

        # Provider-aware defaults to reduce manual setup.
        if self.cfg.provider == "openai":
            if not self.cfg.api_base:
                self.cfg.api_base = default_api_base_for_provider(self.cfg.provider)
            if self.cfg.api_key_env == "OPENROUTER_API_KEY":
                self.cfg.api_key_env = default_api_key_env_for_provider(self.cfg.provider)
        elif self.cfg.provider == "openrouter":
            if not self.cfg.api_base:
                self.cfg.api_base = default_api_base_for_provider(self.cfg.provider)
            if self.cfg.api_key_env == "OPENAI_API_KEY":
                self.cfg.api_key_env = default_api_key_env_for_provider(self.cfg.provider)
        elif self.cfg.provider == "doubao":
            if not self.cfg.api_base:
                self.cfg.api_base = default_api_base_for_provider(self.cfg.provider)
            if self.cfg.api_key_env in ("OPENAI_API_KEY", "OPENROUTER_API_KEY"):
                self.cfg.api_key_env = default_api_key_env_for_provider(self.cfg.provider)

        save_config(self.cfg)
        self.parent.refresh_config_label()
        # If the user pasted a real key into the env-name field, warn once.
        if (
            any(x in self.cfg.api_key_env.lower() for x in ("sk-", "or_", "apikey", "api_key"))
            and " " not in self.cfg.api_key_env
        ):
            messagebox.showinfo(
                "API Key Tip",
                "`API Key Env` 这里建议填写环境变量名（例如 OPENAI_API_KEY / OPENROUTER_API_KEY），\n"
                "不要把 key 直接粘贴到这里。\n\n"
                "然后在系统环境变量里设置对应的 key 值即可。",
            )
        self.destroy()


class DesktopAgentApp:
    def __init__(self) -> None:
        self.cfg = load_config()
        self.history: List[RunRecord] = load_history()
        self.root = tk.Tk()
        self.root.title("Desktop Agent App")
        self.root.geometry("1180x780")

        self.events: "queue.Queue[tuple[str, Any]]" = queue.Queue()
        self.worker: Optional[threading.Thread] = None
        self.stop_flag = threading.Event()
        self.preview_image_ref = None
        self.current_logs: List[str] = []
        self.current_task: str = ""

        self._build_ui()
        self.refresh_config_label()
        self.refresh_history_list()
        self.root.after(100, self._drain_events)

    def _build_ui(self) -> None:
        root = self.root

        top = ttk.Frame(root, padding=10)
        top.pack(fill="x")

        # Two-zone header: left expands, right is fixed-width so buttons never get clipped.
        top_left = ttk.Frame(top)
        top_left.pack(side="left", fill="x", expand=True)
        top_right = ttk.Frame(top)
        top_right.pack(side="right")

        self.config_label = ttk.Label(top_left, text="", anchor="w")
        self.config_label.pack(side="left", fill="x", expand=True)

        ttk.Button(top_right, text="Config", command=self.open_config).pack(side="right", padx=4)
        self.stop_button = ttk.Button(
            top_right, text="Stop", command=self.stop_run, state="disabled"
        )
        self.stop_button.pack(side="right", padx=4)
        self.send_button = ttk.Button(top_right, text="Send", command=self.start_run)
        self.send_button.pack(side="right", padx=4)

        task_frame = ttk.LabelFrame(root, text="Task", padding=10)
        task_frame.pack(fill="x", padx=10, pady=(0, 10))
        self.task_text = tk.Text(task_frame, height=5, wrap="word")
        self.task_text.pack(fill="x")

        mid = ttk.Panedwindow(root, orient="horizontal")
        mid.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        left = ttk.Frame(mid)
        right = ttk.Frame(mid)
        mid.add(left, weight=2)
        mid.add(right, weight=1)

        log_frame = ttk.LabelFrame(left, text="Logs", padding=8)
        log_frame.pack(fill="both", expand=True)
        self.log_text = scrolledtext.ScrolledText(log_frame, wrap="word", state="disabled")
        self.log_text.pack(fill="both", expand=True)

        right_pane = ttk.Panedwindow(right, orient="vertical")
        right_pane.pack(fill="both", expand=True)

        preview_frame = ttk.LabelFrame(right_pane, text="Latest Screenshot", padding=8)
        self.preview_label = ttk.Label(preview_frame, text="No screenshot yet", anchor="center")
        self.preview_label.pack(fill="both", expand=True)
        right_pane.add(preview_frame, weight=2)

        history_frame = ttk.LabelFrame(right_pane, text="Run History", padding=8)
        history_toolbar = ttk.Frame(history_frame)
        history_toolbar.pack(fill="x", pady=(0, 6))
        ttk.Button(history_toolbar, text="Reload Task", command=self.reload_selected_task).pack(
            side="left"
        )
        ttk.Button(history_toolbar, text="Refresh", command=self.refresh_history_list).pack(
            side="left", padx=4
        )
        self.history_list = tk.Listbox(history_frame, height=10)
        self.history_list.pack(fill="both", expand=True)
        self.history_list.bind("<<ListboxSelect>>", lambda _e: self.show_selected_history())
        right_pane.add(history_frame, weight=1)

        bottom = ttk.Frame(root, padding=(10, 0, 10, 10))
        bottom.pack(fill="x")
        self.status_var = tk.StringVar(value="Idle")
        ttk.Label(bottom, textvariable=self.status_var).pack(side="left")

    def refresh_config_label(self) -> None:
        def _ellipsize(s: str, max_len: int) -> str:
            s = (s or "").strip()
            if len(s) <= max_len:
                return s
            return s[: max_len - 3] + "..."

        self.config_label.config(text=f"Provider: {_ellipsize(self.cfg.provider, 18)}")

    def open_config(self) -> None:
        ConfigDialog(self, self.cfg)

    def append_log(self, text: str) -> None:
        self.current_logs.append(text)
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def clear_logs(self) -> None:
        self.current_logs = []
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def update_preview(self, screenshot_b64: str) -> None:
        try:
            raw = base64.b64decode(screenshot_b64)
            img = Image.open(BytesIO(raw))
            img.thumbnail((420, 300))
            photo = ImageTk.PhotoImage(img)
            self.preview_image_ref = photo
            self.preview_label.config(image=photo, text="")
        except Exception as e:
            self.preview_label.config(text=f"Preview error: {e}", image="")

    def stop_run(self) -> None:
        self.stop_flag.set()
        self.status_var.set("Stopping...")

    def refresh_history_list(self) -> None:
        self.history = load_history()
        if not hasattr(self, "history_list"):
            return
        self.history_list.delete(0, "end")
        for item in self.history:
            title = item.task.replace("\n", " ").strip()
            if len(title) > 36:
                title = title[:36] + "..."
            self.history_list.insert("end", f"[{item.created_at}] ({item.status}) {title}")

    def selected_history(self) -> Optional[RunRecord]:
        if not hasattr(self, "history_list"):
            return None
        sel = self.history_list.curselection()
        if not sel:
            return None
        idx = int(sel[0])
        if idx < 0 or idx >= len(self.history):
            return None
        return self.history[idx]

    def show_selected_history(self) -> None:
        item = self.selected_history()
        if not item:
            return
        self.clear_logs()
        self.status_var.set(f"Viewing history: {item.status}")
        for line in item.logs:
            self.append_log(line)

    def reload_selected_task(self) -> None:
        item = self.selected_history()
        if not item:
            messagebox.showinfo("History", "Please select a history item first.")
            return
        self.task_text.delete("1.0", "end")
        self.task_text.insert("1.0", item.task)
        self.status_var.set("Task reloaded from history")

    def confirm_action(self, action: Dict[str, Any]) -> bool:
        # Worker thread requests a UI confirmation and waits.
        event = threading.Event()
        box: Dict[str, Any] = {"result": False}
        self.events.put(("confirm", (action, event, box)))
        event.wait()
        return bool(box["result"])

    def start_run(self) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("Busy", "Agent is already running.")
            return

        task = self.task_text.get("1.0", "end").strip()
        if not task:
            messagebox.showwarning("Task Required", "Please enter a task first.")
            return

        self.stop_flag.clear()
        self.current_task = task
        self.status_var.set("Starting...")
        self.send_button.config(state="disabled")
        self.stop_button.config(state="normal")
        self.clear_logs()
        self.append_log("=" * 60)
        self.append_log("[system] new run")

        if getattr(self.cfg, "auto_minimize_on_send", True):
            # Minimize to avoid capturing this UI in desktop screenshots.
            try:
                self.root.iconify()
                self.root.update_idletasks()
            except Exception:
                pass

        self.worker = threading.Thread(target=self._run_agent, args=(task,), daemon=True)
        self.worker.start()

    def _run_agent(self, task: str) -> None:
        def on_log(msg: str) -> None:
            self.events.put(("log", msg))

        def on_status(msg: str) -> None:
            self.events.put(("status", msg))

        def on_screenshot(b64: str) -> None:
            self.events.put(("screenshot", b64))

        try:
            runner = DesktopPlannerAgent(
                cfg=self.cfg,
                on_log=on_log,
                on_status=on_status,
                on_screenshot=on_screenshot,
                confirm_action=self.confirm_action,
                should_stop=lambda: self.stop_flag.is_set(),
            )
            final_status = runner.run(task)
            self.events.put(("done", final_status))
        except Exception as e:
            # Avoid crashing the background thread with an unhandled exception.
            self.events.put(("log", f"[config-error] {type(e).__name__}: {e}"))
            self.events.put(("done", "config_error"))

    def _drain_events(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "log":
                    self.append_log(str(payload))
                elif kind == "status":
                    self.status_var.set(str(payload))
                elif kind == "screenshot":
                    self.update_preview(str(payload))
                elif kind == "confirm":
                    action, event, box = payload
                    pretty = json.dumps(action, ensure_ascii=False, indent=2)
                    result = messagebox.askyesno(
                        "Confirm Action",
                        "Agent requests to execute the following local UI action:\n\n" + pretty,
                    )
                    box["result"] = result
                    event.set()
                elif kind == "done":
                    final_status = str(payload or "unknown")
                    self.status_var.set(f"Idle ({final_status})")
                    self.send_button.config(state="normal")
                    self.stop_button.config(state="disabled")
                    record = new_record(
                        task=self.current_task,
                        status=final_status,
                        provider=self.cfg.provider,
                        model=self.cfg.model,
                        logs=self.current_logs,
                    )
                    self.history = append_history(record)
                    self.refresh_history_list()
                    if getattr(self.cfg, "auto_minimize_on_send", True):
                        # Restore the window when the run completes.
                        try:
                            self.root.deiconify()
                            self.root.lift()
                            self.root.focus_force()
                        except Exception:
                            pass
        except queue.Empty:
            pass
        self.root.after(100, self._drain_events)

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    DesktopAgentApp().run()
