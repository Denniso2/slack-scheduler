"""Tests for slack_scheduler.paths"""
from pathlib import Path
from unittest.mock import patch

from slack_scheduler import paths


class TestPaths:
    def test_config_dir_returns_path(self):
        assert isinstance(paths.config_dir(), Path)

    def test_data_dir_returns_path(self):
        assert isinstance(paths.data_dir(), Path)

    def test_log_dir_is_subdirectory_of_data_dir(self):
        with patch("slack_scheduler.paths.user_data_dir", return_value="/tmp/test-data"):
            assert paths.log_dir() == Path("/tmp/test-data/logs")

    def test_state_dir_is_subdirectory_of_data_dir(self):
        with patch("slack_scheduler.paths.user_data_dir", return_value="/tmp/test-data"):
            assert paths.state_dir() == Path("/tmp/test-data/state")

    def test_config_dir_uses_app_name(self):
        with patch("slack_scheduler.paths.user_config_dir") as mock:
            mock.return_value = "/fake"
            paths.config_dir()
        mock.assert_called_once_with("slack-scheduler")

    def test_data_dir_uses_app_name(self):
        with patch("slack_scheduler.paths.user_data_dir") as mock:
            mock.return_value = "/fake"
            paths.data_dir()
        mock.assert_called_once_with("slack-scheduler")

    def test_log_and_state_dirs_differ(self):
        with patch("slack_scheduler.paths.user_data_dir", return_value="/tmp/test"):
            assert paths.log_dir() != paths.state_dir()
