import argparse
import logging
import platform
import random
import sys
from importlib import resources
from pathlib import Path

from slack_scheduler import paths
from slack_scheduler.auth import TokenExpiredError, TokenInvalidError
from slack_scheduler.logger import setup_logging
from slack_scheduler.sender import SlackAPIError

log = logging.getLogger(__name__)


def main():
    default_config = paths.config_dir() / "config.yaml"
    default_env = paths.data_dir() / "credentials.env"

    parser = argparse.ArgumentParser(
        prog="slack-scheduler",
        description="Schedule and send Slack messages using browser session tokens.",
    )

    # Global flags
    parser.add_argument(
        "--config", type=Path, default=default_config,
        help=f"Path to config.yaml (default: {default_config})",
    )
    parser.add_argument(
        "--env", type=Path, default=default_env,
        help=f"Path to credentials file (default: {default_env})",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview actions without sending anything",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Enable debug-level log output",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # init
    subparsers.add_parser(
        "init", help="Create config directories and example config file",
    )

    # send
    send_parser = subparsers.add_parser(
        "send", help="Send a message immediately",
    )
    send_parser.add_argument(
        "--channel", type=str, required=True,
        help="Target channel ID",
    )
    send_parser.add_argument(
        "--message", type=str, nargs="+",
        help="Message text (multiple for random selection)",
    )
    send_parser.add_argument(
        "--jitter", type=int, default=0,
        help="Random delay in minutes before sending (e.g. --jitter 15 waits 0-15 min)",
    )
    send_parser.add_argument(
        "--selection-mode", type=str, choices=["random", "cycle"],
        help="Message selection mode (overrides config)",
    )

    # run
    run_parser = subparsers.add_parser(
        "run", help="Start the daemon scheduler",
    )
    run_parser.add_argument(
        "--skip-holidays", type=str, default=None, metavar="COUNTRY",
        help='Skip country-specific bank holidays (e.g. "US", "NL", "DE-BY")',
    )

    # status
    status_parser = subparsers.add_parser(
        "status", help="Show upcoming scheduled messages",
    )
    status_parser.add_argument(
        "--count", type=int, default=5,
        help="Number of upcoming events to show per schedule (default: 5)",
    )
    status_parser.add_argument(
        "--skip-holidays", type=str, default=None, metavar="COUNTRY",
        help='Skip country-specific bank holidays (e.g. "US", "NL", "DE-BY")',
    )

    # validate
    subparsers.add_parser(
        "validate", help="Check that stored credentials are valid",
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    setup_logging(verbose=args.verbose)

    try:
        if args.command == "init":
            cmd_init(args)
        elif args.command == "send":
            cmd_send(args)
        elif args.command == "run":
            cmd_run(args)
        elif args.command == "status":
            cmd_status(args)
        elif args.command == "validate":
            cmd_validate(args)
    except TokenExpiredError as e:
        log.error(str(e))
        sys.exit(1)
    except TokenInvalidError as e:
        log.error(str(e))
        sys.exit(1)
    except SlackAPIError as e:
        log.error(str(e))
        sys.exit(1)
    except KeyboardInterrupt:
        log.info("Interrupted. Exiting.")
        sys.exit(0)
    except FileNotFoundError as e:
        log.error(str(e))
        sys.exit(1)
    except ValueError as e:
        log.error(str(e))
        log.debug("ValueError details:", exc_info=True)
        sys.exit(1)
    except Exception as e:
        log.exception(f"Unexpected error: {e}")
        sys.exit(1)


def cmd_init(args):
    config_dir = paths.config_dir()
    data_dir = paths.data_dir()
    log_dir = paths.log_dir()

    for d in [config_dir, data_dir, log_dir]:
        d.mkdir(parents=True, exist_ok=True)

    config_dest = config_dir / "config.yaml"
    if not config_dest.exists():
        try:
            ref = resources.files("slack_scheduler").joinpath("config.example.yaml")
            example_content = ref.read_text()
            config_dest.write_text(example_content)
            print(f"Example config copied to: {config_dest}")
        except (FileNotFoundError, AttributeError):
            print(f"Config directory created: {config_dir}")
            print("Create your config.yaml there to get started.")
    else:
        print(f"Config already exists: {config_dest}")

    env_dest = data_dir / "credentials.env"
    if not env_dest.exists():
        env_dest.write_text(
            "SLACK_XOXC_TOKEN=xoxc-your-token-here\n"
            "SLACK_D_COOKIE=xoxd-your-cookie-here\n"
        )
        if platform.system() != "Windows":
            env_dest.chmod(0o600)
        print(f"Credentials template created: {env_dest}")
    else:
        print(f"Credentials file already exists: {env_dest}")

    print(f"\nPaths:")
    print(f"  Config:      {config_dir}")
    print(f"  Credentials: {env_dest}")
    print(f"  Logs:        {log_dir}")


def cmd_send(args):
    import time
    from datetime import datetime

    from slack_scheduler.auth import validate_credentials
    from slack_scheduler.config import load_config, load_credentials
    from slack_scheduler.sender import send_message
    from slack_scheduler.templates import render

    credentials = load_credentials(args.env)

    config = load_config(args.config) if args.config.exists() else None

    validate_credentials(credentials)

    if args.message:
        selection_mode = args.selection_mode or (config.default_selection_mode if config else "random")
        if selection_mode == "cycle":
            from slack_scheduler.selector import pick_message
            message = pick_message(args.channel, args.message, "cycle")
        else:
            message = random.choice(args.message)
    elif config:
        channel_cfg = next((c for c in config.channels if c.id == args.channel), None)
        if channel_cfg and channel_cfg.messages:
            from slack_scheduler.selector import pick_message
            mode = args.selection_mode or channel_cfg.selection_mode
            message = pick_message(channel_cfg.name, channel_cfg.messages, mode)
        else:
            log.error("No --message provided and no messages in config for this channel.")
            sys.exit(1)
    else:
        log.error("No --message provided and no config file found.")
        sys.exit(1)

    message = render(message, datetime.now())

    if args.jitter > 0:
        delay = random.uniform(0, args.jitter * 60)
        log.info(f"Jitter: waiting {delay:.0f}s before sending")
        time.sleep(delay)

    result = send_message(
        channel_id=args.channel,
        message=message,
        credentials=credentials,
        dry_run=args.dry_run,
    )

    if result.ok:
        print(f"Message sent: {message!r}")
    else:
        log.error(f"Failed to send: {result.error_code}")
        sys.exit(1)


def cmd_run(args):
    from slack_scheduler.auth import validate_credentials
    from slack_scheduler.config import _validate_skip_holidays, load_config, load_credentials
    from slack_scheduler.scheduler import run_daemon

    config = load_config(args.config)
    credentials = load_credentials(args.env)
    validate_credentials(credentials)

    if args.skip_holidays is not None:
        _validate_skip_holidays(args.skip_holidays, "CLI --skip-holidays")
        config.skip_holidays = args.skip_holidays

    run_daemon(config, credentials, dry_run=args.dry_run)


def cmd_status(args):
    from slack_scheduler.config import _validate_skip_holidays, load_config
    from slack_scheduler.scheduler import print_upcoming

    config = load_config(args.config)

    if args.skip_holidays is not None:
        _validate_skip_holidays(args.skip_holidays, "CLI --skip-holidays")
        config.skip_holidays = args.skip_holidays

    print_upcoming(config, count=args.count)


def cmd_validate(args):
    from slack_scheduler.auth import validate_credentials
    from slack_scheduler.config import load_credentials

    credentials = load_credentials(args.env)
    validate_credentials(credentials)
    print("Credentials are valid.")


if __name__ == "__main__":
    main()
