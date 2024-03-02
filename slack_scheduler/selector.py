import json
import logging
import os
import random
import tempfile
from pathlib import Path

from slack_scheduler import paths

log = logging.getLogger(__name__)

STATE_DIR = paths.state_dir()


def pick_message(
    channel_id: str,
    messages: list[str],
    mode: str = "random",
    state_dir: Path | None = None,
) -> str:
    if not messages:
        raise ValueError(f"No messages configured for channel {channel_id}")

    if len(messages) == 1:
        return messages[0]

    if mode == "cycle":
        return _pick_cycle(channel_id, messages, state_dir or STATE_DIR)
    return random.choice(messages)


def _pick_cycle(channel_id: str, messages: list[str], state_dir: Path) -> str:
    state_dir.mkdir(parents=True, exist_ok=True)
    state_file = state_dir / f"{channel_id}.json"

    state = _load_state(state_file)

    # Reshuffle if state is stale, exhausted, or messages changed
    if (
        state is None
        or state["index"] >= len(state["shuffled"])
        or sorted(state["shuffled"]) != sorted(messages)
    ):
        shuffled = messages.copy()
        random.shuffle(shuffled)
        state = {"shuffled": shuffled, "index": 0}

    message = state["shuffled"][state["index"]]
    state["index"] += 1
    _save_state(state_file, state)
    return message


def _load_state(state_file: Path) -> dict | None:
    try:
        with open(state_file) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _save_state(state_file: Path, state: dict) -> None:
    tmp_fd, tmp_path = tempfile.mkstemp(dir=state_file.parent)
    try:
        with os.fdopen(tmp_fd, "w") as f:
            json.dump(state, f)
        os.replace(tmp_path, state_file)
    except Exception:
        os.unlink(tmp_path)
        raise
