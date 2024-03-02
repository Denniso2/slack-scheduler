# slack-scheduler

Schedule and send Slack messages using browser session tokens — no Slack app or admin API approval required.

## Quick Start

```bash
pip install slack-scheduler
slack-scheduler init
# Edit your config and credentials (paths shown by init)
slack-scheduler validate
slack-scheduler run
```

## Getting Your Credentials

slack-scheduler authenticates using your browser session tokens (`xoxc` token + `d` cookie). Here's how to get them:

1. Open your Slack workspace in a browser (e.g. `https://your-company.slack.com`)
2. Open DevTools (F12)

**Get the `d` cookie:**

3. Go to **Application** > **Storage** > **Cookies** > `app.slack.com`
4. Find the cookie named `d` (its value starts with `xoxd-`)
5. Copy the full value

**Get the `xoxc` token:**

6. Go to the **Console** tab
7. If on chrome enable pasting by typing "allow pasting"
8. Run:
   ```javascript
   JSON.parse(localStorage.getItem('localConfig_v2')).teams[Object.keys(JSON.parse(localStorage.getItem('localConfig_v2')).teams)[0]].token
   ```
9. Copy the `xoxc-...` token

**Save them to your credentials file:**

```bash
slack-scheduler init  # creates the file with placeholders
```

Then edit the credentials file (path shown by `init`) and replace the placeholders:

```env
SLACK_XOXC_TOKEN=xoxc-your-actual-token
SLACK_D_COOKIE=xoxd-your-actual-cookie
```

> **Note:** These tokens expire (typically after ~1 year, shorter on workspaces with strict security policies). When they expire, repeat the steps above.

## Configuration

After running `slack-scheduler init`, edit the config file:

```yaml
workspace_url: "https://your-company.slack.com"

# Default message selection mode: "random" or "cycle"
default_selection_mode: "random"

# Dates to skip globally (YYYY-MM-DD)
skip_dates:
  - "2026-12-25"
  - "2026-01-01"

channels:
  - id: "C1234567890"        # Slack channel ID
    name: "standup"           # Human-readable label (for logs)

    messages:
      - "Good morning team! Ready for {day_of_week}."
      - "Morning all! Let's have a great {day_of_week}."
      - "Hey team, online and ready. Today is {date}."

    selection_mode: "cycle"   # Override default for this channel

    schedules:
      - cron: "0 9 * * 1-5"  # 9:00 AM, Monday-Friday
        jitter_minutes: 15    # Randomize ±15 min (sends between 8:45-9:15)
        skip_weekends: true

  - id: "C0987654321"
    name: "random-chat"

    messages:
      - "Anyone up for a virtual coffee?"
      - "Happy {day_of_week}!"

    schedules:
      - cron: "0 14 * * 3"   # 2:00 PM every Wednesday
        jitter_minutes: 30
```

> **Tip:** To find a channel's ID, right-click the channel name in Slack > "View channel details" > the ID is at the bottom.

## CLI Commands

### `init` — Set up config directories

```bash
slack-scheduler init
```

Creates config directories and template files at the OS-appropriate locations.

### `send` — Send a message now

```bash
# Send a specific message
slack-scheduler send --channel C1234567890 --message "Good morning!"

# Pick randomly from multiple messages
slack-scheduler send --channel C1234567890 --message "Hello!" "Hey there!" "Morning!"

# Cycle through messages (no repeats until all are used)
slack-scheduler send --channel C1234567890 --message "Hello!" "Hey!" "Morning!" --selection-mode cycle

# Use messages from config file
slack-scheduler send --channel C1234567890

# Add a random delay before sending (useful with cron)
slack-scheduler send --channel C1234567890 --message "Good morning!" --jitter 15

# Override workspace URL
slack-scheduler send --channel C1234567890 --message "Hi" --workspace https://other.slack.com

# Preview without sending
slack-scheduler --dry-run send --channel C1234567890 --message "Test"
```

| Flag | Description |
|---|---|
| `--channel` (required) | Target channel ID |
| `--message` | One or more messages (random selection by default) |
| `--workspace` | Workspace URL (overrides config) |
| `--jitter <minutes>` | Random delay of 0 to N minutes before sending |
| `--selection-mode` | `random` or `cycle` (overrides config) |

### `run` — Start the scheduler daemon

```bash
slack-scheduler run

# Preview mode (logs what would be sent)
slack-scheduler --dry-run run
```

Runs continuously and sends messages according to your config schedules. Stop with `Ctrl-C`.

### `status` — Show upcoming messages

```bash
slack-scheduler status

# Show next 10 per schedule
slack-scheduler status --count 10
```

### `validate` — Check credentials

```bash
slack-scheduler validate
```

### Global Flags

| Flag | Description |
|---|---|
| `--config <path>` | Path to config.yaml (overrides default) |
| `--env <path>` | Path to credentials file (overrides default) |
| `--dry-run` | Preview actions without sending |
| `--verbose` | Enable debug logging |

## Message Templates

Messages support variable substitution:

| Variable | Example Output |
|---|---|
| `{date}` | `2026-03-04` |
| `{day_of_week}` | `Monday` |
| `{time}` | `09:15` |

```yaml
messages:
  - "Good morning! Today is {day_of_week}, {date}."
  - "Online and ready at {time}."
```

Unknown variables are left as-is (e.g. `{foo}` stays `{foo}`).

## Message Selection Modes

### Random (default)

Picks a random message from the pool each time.

### Cycle

Shuffles the message pool, then sends each message once before reshuffling. Guarantees every message is used before any repeats. State is persisted across restarts.

```yaml
selection_mode: "cycle"
```

## Scheduling

### Cron Format

Standard 5-field cron syntax: `minute hour day month weekday`

```
0 9 * * 1-5     # 9:00 AM, Monday-Friday
30 8 * * *      # 8:30 AM, every day
0 14 * * 3      # 2:00 PM, Wednesdays
0 9,14 * * 1-5  # 9:00 AM and 2:00 PM, weekdays
```

### Jitter

Adds a random offset to the scheduled time so messages don't arrive at exactly the same second every day.

```yaml
jitter_minutes: 15  # Sends anywhere in a ±15 minute window
```

A schedule at `09:00` with `jitter_minutes: 15` will fire between `08:45` and `09:15`.

### Skip Rules

```yaml
# Skip weekends
skip_weekends: true

# Skip specific dates (per-schedule, merged with global skip_dates)
skip_dates:
  - "2026-12-24"
```

## File Locations

After running `slack-scheduler init`:

| | Linux | macOS | Windows |
|---|---|---|---|
| Config | `~/.config/slack-scheduler/` | `~/Library/Application Support/slack-scheduler/` | `%APPDATA%\slack-scheduler\` |
| Credentials | `~/.local/share/slack-scheduler/` | `~/Library/Application Support/slack-scheduler/` | `%APPDATA%\slack-scheduler\` |
| Logs | `~/.local/share/slack-scheduler/logs/` | `~/Library/Application Support/slack-scheduler/logs/` | `%APPDATA%\slack-scheduler\logs\` |

All paths are overridable with `--config` and `--env` flags.

## Running as a Service

### systemd (Linux)

Create `~/.config/systemd/user/slack-scheduler.service`:

```ini
[Unit]
Description=Slack Scheduler

[Service]
ExecStart=slack-scheduler run
Restart=on-failure
RestartSec=30

[Install]
WantedBy=default.target
```

```bash
systemctl --user enable --now slack-scheduler
```

### cron (alternative)

Instead of the daemon, use cron to call `send` directly:

```bash
# crontab -e
0 9 * * 1-5 slack-scheduler send --channel C1234567890 --message "Good morning!" --jitter 15
```
