"""Tests for slack_scheduler.selector"""
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from slack_scheduler.selector import _load_state, _save_state, pick_message


# --- pick_message: guard clauses --------------------------------------------

def test_pick_message_raises_on_empty_messages():
    with pytest.raises(ValueError, match="No messages"):
        pick_message("C1", [])


def test_pick_message_single_message_returns_it():
    assert pick_message("C1", ["only one"]) == "only one"


# --- pick_message: random mode ----------------------------------------------

class TestPickMessageRandom:
    def test_random_mode_calls_random_choice(self):
        messages = ["a", "b", "c"]
        with patch("slack_scheduler.selector.random.choice", return_value="b") as mock:
            result = pick_message("C1", messages, mode="random")
        mock.assert_called_once_with(messages)
        assert result == "b"

    def test_default_mode_is_random(self):
        with patch("slack_scheduler.selector.random.choice", return_value="a"):
            assert pick_message("C1", ["a", "b"]) == "a"

    def test_unknown_mode_falls_back_to_random(self):
        with patch("slack_scheduler.selector.random.choice", return_value="x"):
            assert pick_message("C1", ["x", "y"], mode="unknown") == "x"


# --- pick_message: cycle mode -----------------------------------------------

class TestPickMessageCycle:
    def test_cycle_returns_all_messages_before_repeating(self, tmp_path):
        messages = ["a", "b", "c"]
        # Prevent shuffle so order is preserved and deterministic
        with patch("slack_scheduler.selector.random.shuffle"):
            results = [
                pick_message("C1", messages, mode="cycle", state_dir=tmp_path)
                for _ in range(3)
            ]
        # Each message exactly once, in original order (shuffle is no-op)
        assert results == messages

    def test_cycle_reshuffles_after_exhaustion(self, tmp_path):
        messages = ["a", "b"]
        with patch("slack_scheduler.selector.random.shuffle"):
            # Exhaust the cycle
            pick_message("C1", messages, mode="cycle", state_dir=tmp_path)
            pick_message("C1", messages, mode="cycle", state_dir=tmp_path)
            # This should trigger a reshuffle
            pick_message("C1", messages, mode="cycle", state_dir=tmp_path)
        state = json.loads((tmp_path / "C1.json").read_text())
        assert state["index"] == 1

    def test_cycle_uses_channel_specific_state_file(self, tmp_path):
        pick_message("C111", ["x", "y"], mode="cycle", state_dir=tmp_path)
        pick_message("C222", ["a", "b"], mode="cycle", state_dir=tmp_path)
        assert (tmp_path / "C111.json").exists()
        assert (tmp_path / "C222.json").exists()

    def test_cycle_reshuffles_when_messages_change(self, tmp_path):
        original = ["a", "b"]
        modified = ["a", "b", "c"]
        with patch("slack_scheduler.selector.random.shuffle"):
            pick_message("C1", original, mode="cycle", state_dir=tmp_path)
            pick_message("C1", modified, mode="cycle", state_dir=tmp_path)
        state = json.loads((tmp_path / "C1.json").read_text())
        assert sorted(state["shuffled"]) == sorted(modified)

    def test_cycle_creates_state_dir_if_missing(self, tmp_path):
        nested = tmp_path / "deep" / "nested"
        pick_message("C1", ["a", "b"], mode="cycle", state_dir=nested)
        assert nested.is_dir()

    def test_cycle_handles_corrupt_state_file(self, tmp_path):
        state_file = tmp_path / "C1.json"
        state_file.write_text("not valid json")
        result = pick_message("C1", ["a", "b"], mode="cycle", state_dir=tmp_path)
        assert result in ["a", "b"]

    def test_cycle_handles_state_missing_keys(self, tmp_path):
        state_file = tmp_path / "C1.json"
        state_file.write_text(json.dumps({"wrong_key": 1}))
        result = pick_message("C1", ["a", "b"], mode="cycle", state_dir=tmp_path)
        assert result in ["a", "b"]


# --- _load_state / _save_state ----------------------------------------------

class TestStateIO:
    def test_load_returns_none_for_missing_file(self, tmp_path):
        assert _load_state(tmp_path / "nonexistent.json") is None

    def test_load_returns_none_for_invalid_json(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("{ not json }")
        assert _load_state(p) is None

    def test_save_and_load_roundtrip(self, tmp_path):
        p = tmp_path / "state.json"
        state = {"shuffled": ["a", "b"], "index": 1}
        _save_state(p, state)
        assert _load_state(p) == state

    def test_save_is_atomic_no_leftover_files(self, tmp_path):
        p = tmp_path / "state.json"
        _save_state(p, {"shuffled": ["a"], "index": 0})
        assert len(list(tmp_path.iterdir())) == 1
        assert list(tmp_path.iterdir())[0] == p
