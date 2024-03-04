"""Tests for slack_scheduler.logger"""
import logging

import pytest

from slack_scheduler.logger import setup_logging


@pytest.fixture(autouse=True)
def reset_logger():
    """Ensure the slack_scheduler logger is clean before and after each test."""
    logger = logging.getLogger("slack_scheduler")
    yield
    logger.handlers.clear()


class TestSetupLogging:
    def test_creates_log_file(self, tmp_path):
        setup_logging(log_dir=tmp_path)
        assert (tmp_path / "slack_scheduler.log").exists()

    def test_attaches_exactly_two_handlers(self, tmp_path):
        setup_logging(log_dir=tmp_path)
        logger = logging.getLogger("slack_scheduler")
        assert len(logger.handlers) == 2

    def test_handlers_are_file_and_stream(self, tmp_path):
        setup_logging(log_dir=tmp_path)
        handler_types = {type(h) for h in logging.getLogger("slack_scheduler").handlers}
        assert logging.FileHandler in handler_types
        assert logging.StreamHandler in handler_types

    def test_verbose_false_console_level_info(self, tmp_path):
        setup_logging(verbose=False, log_dir=tmp_path)
        stream = [h for h in logging.getLogger("slack_scheduler").handlers
                  if type(h) is logging.StreamHandler]
        assert stream[0].level == logging.INFO

    def test_verbose_true_console_level_debug(self, tmp_path):
        setup_logging(verbose=True, log_dir=tmp_path)
        stream = [h for h in logging.getLogger("slack_scheduler").handlers
                  if type(h) is logging.StreamHandler]
        assert stream[0].level == logging.DEBUG

    def test_file_handler_always_debug(self, tmp_path):
        setup_logging(verbose=False, log_dir=tmp_path)
        file_h = [h for h in logging.getLogger("slack_scheduler").handlers
                  if isinstance(h, logging.FileHandler)]
        assert file_h[0].level == logging.DEBUG

    def test_repeated_calls_no_duplicate_handlers(self, tmp_path):
        setup_logging(log_dir=tmp_path)
        setup_logging(log_dir=tmp_path)
        assert len(logging.getLogger("slack_scheduler").handlers) == 2

    def test_creates_log_dir_if_missing(self, tmp_path):
        nested = tmp_path / "deep" / "logs"
        setup_logging(log_dir=nested)
        assert nested.is_dir()

    def test_root_logger_level_is_debug(self, tmp_path):
        setup_logging(log_dir=tmp_path)
        assert logging.getLogger("slack_scheduler").level == logging.DEBUG
