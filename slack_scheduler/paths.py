from pathlib import Path

from platformdirs import user_config_dir, user_data_dir

APP_NAME = "slack-scheduler"


def config_dir() -> Path:
    return Path(user_config_dir(APP_NAME))


def data_dir() -> Path:
    return Path(user_data_dir(APP_NAME))


def log_dir() -> Path:
    return data_dir() / "logs"


def state_dir() -> Path:
    return data_dir() / "state"
