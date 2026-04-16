# Desktop Agent App (MVP)

Minimal macOS/Windows desktop agent app:

- GUI: `tkinter`
- Local computer control: `pyautogui` (mouse/keyboard + screenshots)
- Model: OpenAI-compatible API (OpenAI or OpenRouter)
- Model: OpenAI-compatible API (OpenAI / OpenRouter / Doubao Ark)
- Architecture: `planner -> execute step -> supervisor -> loop` (inspired by plan-and-execute)
  - Updated: `planner -> executor/supervisor (actions) -> verifier (step/task completion) -> loop`

## Install

```bash
cd desktop_agent_app
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Run

```bash
python .\app.py
```

Before first run, copy `config.example.json` to `config.json`, or open the app and fill the config in the `Config` dialog.

## What It Contains

- `app.py`: cross-platform desktop GUI (`tkinter`)
- `config.py`: config persistence (`config.json`)
- `computer_control.py`: local mouse/keyboard/screenshot layer via `pyautogui`
- `llm_client.py`: OpenAI-compatible API wrapper
- `agent_core.py`: independent `planner -> supervisor/executor -> loop`
- `run_history.py`: local task/run history persistence

## Browser Action Pack

The independent desktop agent now includes browser-oriented high-level actions:

- `open_browser`
- `focus_address_bar`
- `open_url`
- `search_text`
- `paste_text`

These reduce the amount of fragile low-level clicking/keypress planning the model must do.
Window maximize remains a normal screenshot-driven `click` decision by the model rather than a hardcoded action.

## Architecture

This project is intentionally independent from the existing repo's agent runtime.
It only uses:

- local GUI
- local screenshot + input control
- OpenAI-compatible model calls

Loop design:

1. `planner` generates a step list from the user task
2. each turn:
   - capture current screenshot
   - send task + plan + current step + recent action history + screenshot to the model
   - `executor/supervisor` chooses one of:
     - `computer(...)`: one UI action
     - `supervisor_update(...)`: control signal (replan/blocked/etc.)
   - after action/control, capture screenshot and run `verifier`:
     - verifier returns `continue | step_done | task_done | replan_required | blocked`
3. continue until the task completes

## Config

The repository includes `config.example.json` as a safe sample for open source publishing.
Keep your real `config.json` local and untracked.

In the app:

- Click `Config` and set:
  - `provider`: `openai` / `openrouter` / `doubao`
  - `model`: first version defaults to GPT models
  - `api_key_env`: env var name containing the key
  - `api_base` (optional): `https://openrouter.ai/api/v1` for OpenRouter

Provider notes:

- OpenAI:
  - `api_base`: `https://api.openai.com/v1`
  - `api_key_env`: usually `OPENAI_API_KEY`
- OpenRouter:
  - `api_base`: `https://openrouter.ai/api/v1`
  - `api_key_env`: usually `OPENROUTER_API_KEY`
- Doubao / Ark:
  - `api_base`: usually `https://ark.cn-beijing.volces.com/api/v3`
  - `api_key_env`: usually `ARK_API_KEY`

## UI Features

- task input box
- config dialog
- send / stop buttons
- live log output
- latest screenshot preview
- local run history list
- reload a previous task from history into the input box

## Three-Role Models (Optional)

You can set separate models for:

- planner
- executor
- verifier

If left empty, they fall back to the default model.

## Notes

- This MVP can control your real mouse/keyboard. Keep a hand on the mouse to interrupt.
- Start with safe tasks (open app, navigate, search, screenshot). Avoid irreversible actions.
- On macOS, you will likely need to grant Accessibility / Screen Recording permissions.
