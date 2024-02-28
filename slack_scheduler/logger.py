import logging
from pathlib import Path


def setup_logging(verbose: bool = False, log_dir: Path | None = None) -> None:
    log_dir = log_dir or Path.home() / ".slack-scheduler"
    log_dir.mkdir(parents=True, exist_ok=True)

    log_file = log_dir / "slack_scheduler.log"
    level = logging.DEBUG if verbose else logging.INFO

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)

    root = logging.getLogger("slack_scheduler")
    root.setLevel(logging.DEBUG)
    root.addHandler(file_handler)
    root.addHandler(console_handler)
