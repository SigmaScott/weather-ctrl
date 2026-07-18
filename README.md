# weather-ctrl

Command-line tool to control a remote weather switching device over telnet. Manages 7 channels (0-6) with passthrough, override, and stop functions.

## Requirements

- Python 3.10+
- No third-party dependencies (stdlib only)

## Installation

1. Clone the repository:
   ```bash
   git clone git@github.com:SigmaScott/weather-ctrl.git
   cd weather-ctrl
   ```

2. Copy the example config and edit it:
   ```bash
   cp weather-ctrl.conf.example weather-ctrl.conf
   ```

3. Edit `weather-ctrl.conf` with your device's IP and port:
   ```ini
   [remote]
   host = 192.168.1.100
   port = 5555

   [timer]
   duration = 300

   [ratelimit]
   max_calls = 5
   window_seconds = 60
   ```

4. Make the script executable (optional):
   ```bash
   chmod +x weather-ctrl.py
   ```

## Configuration

The program looks for `weather-ctrl.conf` in the current working directory first, then falls back to `/etc/weather-ctrl.conf`.

| Section | Key | Required | Default | Description |
|---------|-----|----------|---------|-------------|
| `[remote]` | `host` | Yes | — | IP address or hostname of the remote device |
| `[remote]` | `port` | No | `5555` | TCP port on the remote device |
| `[timer]` | `duration` | Yes | — | Passthrough timer duration in seconds |
| `[logging]` | `file` | No | `./weather-ctrl.log` | Log file path |
| `[ratelimit]` | `max_calls` | Yes | — | Max passthrough (P) calls per channel within the time window |
| `[ratelimit]` | `window_seconds` | Yes | — | Rate limit time window in seconds |

## Usage

```
weather-ctrl.py <function> [channel]
```

### Functions

**P (Passthrough)** — Enable a channel for a timed duration, then automatically disable it.
```bash
python3 weather-ctrl.py P 3
```
Enables channel 3, waits for the configured timer duration, disables channel 3, verifies it stopped, then exits.

**O (Override)** — Enable a channel with no timer. The channel stays on until manually stopped.
```bash
python3 weather-ctrl.py O 3
```
Enables channel 3, verifies it is on, then exits. Use `S` to turn it off later.

**S (Stop)** — Disable a specific channel or all channels.
```bash
# Stop a single channel
python3 weather-ctrl.py S 3

# Stop all channels (0-6)
python3 weather-ctrl.py S
```

### Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Success |
| `1` | Error (connection failure, verification failure, bad config) |
| `2` | Rate limit exceeded (P function only) |
| `130` | Interrupted by Ctrl+C |

## Logging

All activity is logged to `./weather-ctrl.log` by default (configurable via the `[logging] file` setting). Each invocation and every command sent to the remote device is recorded. Errors are also printed to stderr.

## Rate Limiting

The P (passthrough) function is rate-limited per channel. If a channel is called more than `max_calls` times within `window_seconds`, the request is logged and the program exits with code 2. Rate limit state is tracked in `./weather-ctrl.state.json`.

Override (O) and Stop (S) are not rate-limited.

## Retry Behavior

- **Connection**: Retries 3 times with 3 seconds between attempts before giving up.
- **Verification**: After enabling or disabling a channel, the program checks the device status up to 3 times (1 second apart) to confirm the change took effect.
- **Reconnection**: If the connection drops during a passthrough timer, the program reconnects to complete the disable command.
