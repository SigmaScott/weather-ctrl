# Weather Control CLI — Implementation Plan

## TL;DR

> **Quick Summary**: Build a single-file Python CLI (`weather-ctrl.py`) that controls a remote device via telnet — enabling/disabling ports with timed passthrough, override, and stop functions. Includes INI config, per-port rate limiting, retry logic, status verification, and logging.
>
> **Deliverables**:
> - `weather-ctrl.py` — main CLI program
> - `weather-ctrl.conf.example` — example INI config file
> - Mock telnet server script for testing (`.sisyphus/test_server.py`)
>
> **Estimated Effort**: Medium
> **Parallel Execution**: NO — sequential (single file, each task builds on prior)
> **Critical Path**: Task 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9

---

## Context

### Original Request
Python CLI program that controls a remote application via telnet. Supports 4 functions: Passthrough (timed enable/disable), Override (enable-only), Stop all ports, Stop one port. Uses INI config, per-port rate limiting, connection retry, status verification, and file-based logging.

### Metis Review
**Identified Gaps** (addressed):
- **Python version**: Confirmed 3.10.12 — `telnetlib` available, no deprecation concern
- **Telnet response format**: Assumed line-based with `\r\n` terminator. Status command `s` returns JSON. Read with timeout to avoid hanging.
- **State file race condition**: Accepted single-instance constraint (no file locking). Documented as known limitation.
- **Exit codes**: Defined as 0=success, 1=error, 2=rate-limited
- **stdout output**: Minimal — print status/errors to stderr, stay quiet on success
- **Status JSON format**: Confirmed actual format: `{"channels":[{"ch":0,"state":"idle"},{"ch":1,"state":"idle"},...]}`. States: `"idle"` = disabled/stopped, `"passthrough"` = enabled/on.
- **Testing without real device**: User will provide a real test endpoint. Mock server included as fallback.
- **Git commits**: Use existing git user config as-is. Do NOT modify git user.name, user.email, or add Co-authored-by / Signed-off-by trailers.

---

## Work Objectives

### Core Objective
Single-file Python CLI that sends telnet commands to a remote device to control 7 ports (0-6), with config-driven settings, rate limiting, and robust error handling.

### Concrete Deliverables
- `weather-ctrl.py` — complete CLI, stdlib only
- `weather-ctrl.conf.example` — documented example config
- Mock server for testing

### Definition of Done
- [ ] All 4 CLI functions work: `P <port>`, `O <port>`, `S`, `S <port>`
- [ ] Config loaded from `./weather-ctrl.conf` or `/etc/weather-ctrl.conf`
- [ ] Rate limiting prevents excess calls per port
- [ ] Connection retries 3×3s on failure
- [ ] Status verification retries 3× after enable/disable
- [ ] Ctrl+C cleanly disconnects
- [ ] Log file records all activity

### Must Have
- Python stdlib only (`telnetlib`, `configparser`, `argparse`, `logging`, `json`, `time`, `signal`, `sys`, `os`)
- Single file `weather-ctrl.py`
- INI config with search order: `./weather-ctrl.conf` → `/etc/weather-ctrl.conf`
- Per-port rate limit state in `./weather-ctrl.state.json`
- Logging to file (no rotation)

### Must NOT Have (Guardrails)
- No TUI, interactive mode, or daemon mode
- No generic retry decorator — keep retry logic inline per context
- No class hierarchy or over-abstraction — flat functions
- No third-party dependencies
- No config auto-generation or interactive setup wizard
- No log rotation or structured logging beyond basic FileHandler
- No file locking on state file (single-instance assumption)
- No excessive config validation — parse, default, fail on truly invalid

---

## Design Decisions

### File Structure
```
weather-ctrl/
├── weather-ctrl.py              # Main CLI (single file, all logic)
├── weather-ctrl.conf.example    # Example config with documentation
└── .sisyphus/
    └── test_server.py      # Mock telnet server for testing
```

At runtime, the program creates/uses:
```
./weather-ctrl.conf              # User's config (or /etc/weather-ctrl.conf)
./weather-ctrl.state.json        # Rate limit state
./weather-ctrl.log               # Default log location
```

### Config File Format (INI)
```ini
[remote]
host = 192.168.1.100
port = 5555

[timer]
duration = 300

[logging]
file = /var/log/weather-ctrl.log

[ratelimit]
max_calls = 5
window_seconds = 60
```

- `[remote]` host/port — required
- `[timer]` duration — seconds, required for P function
- `[logging]` file — optional, defaults to `./weather-ctrl.log`
- `[ratelimit]` max_calls / window_seconds — required

### State File Format (JSON)
```json
{
  "0": [1721300000.0, 1721300100.0],
  "1": [],
  "2": [1721300050.0]
}
```
- Keys: port numbers as strings
- Values: list of Unix timestamps of recent P calls
- On read: prune timestamps older than `window_seconds`
- On P call: append current timestamp, check if len > `max_calls`

### Status JSON Format (from remote device)
```json
{
  "channels": [
    {"ch": 0, "state": "idle"},
    {"ch": 1, "state": "passthrough"},
    {"ch": 2, "state": "idle"},
    {"ch": 3, "state": "idle"},
    {"ch": 4, "state": "idle"},
    {"ch": 5, "state": "idle"},
    {"ch": 6, "state": "idle"}
  ]
}
```
- `"idle"` = port is disabled/stopped
- `"passthrough"` = port is enabled/on
- Verification checks: disabled → `"idle"`, enabled → `"passthrough"`

### Module Breakdown (functions in `weather-ctrl.py`)
```
main()                      # argparse + dispatch
load_config(path)           # configparser → dict
─────────────────────────────────
connect(host, port)         # telnetlib connect with 3×3s retry
send_command(tn, cmd)       # write command, read response
disconnect(tn)              # send 'q', close
─────────────────────────────────
get_status(tn)              # send 's', parse JSON
verify_port(tn, port, expected_state)  # check + 3× retry
─────────────────────────────────
check_rate_limit(port, config) # read state, prune, check
record_call(port)           # append timestamp to state
─────────────────────────────────
do_passthrough(port, config)  # P function
do_override(port, config)    # O function
do_stop(port, config)        # S function (one or all)
─────────────────────────────────
setup_logging(config)       # logging.FileHandler
signal_handler(sig, frame)  # Ctrl+C → clean disconnect
```

### Error Handling Strategy
| Scenario | Action |
|----------|--------|
| Config not found | Exit 1, print error to stderr |
| Config missing required field | Exit 1, print which field |
| Port out of range (0-6) | Exit 1, print usage |
| Rate limit exceeded (P only) | Log, exit 2 |
| Connection failed after 3 retries | Log, exit 1 |
| Command send fails | Log error, attempt reconnect |
| Status verify fails after 3 retries | Log, exit 1 |
| Disconnect during P timer | Reconnect, complete disable |
| Ctrl+C | Send `q`, close connection, exit 130 |

### Telnet Protocol Details
- Use `telnetlib.Telnet` with timeout on connect and reads
- Line terminator: `\r\n` (standard telnet)
- After sending command, `read_until(b"\n", timeout=5)` to get response
- For `s` (status), read until valid JSON is captured (may be multi-line)
- Consume any welcome banner on connect by reading with short timeout

---

## Verification Strategy

> **UNIVERSAL RULE: ZERO HUMAN INTERVENTION**
> All verification by agent using mock telnet server + tool execution.

### Test Decision
- **Infrastructure exists**: NO (greenfield)
- **Automated tests**: None (user didn't request)
- **Agent-Executed QA**: Primary verification via mock server + CLI execution

### Mock Telnet Server
A simple Python script (`.sisyphus/test_server.py`) that:
- Listens on configurable port
- Tracks 7 ports state (0/1)
- Responds to `p N 0`, `p N 1` with `OK\r\n`
- Responds to `s` with JSON status
- Responds to `q` by closing connection
- Supports simulating: connection drops, delayed responses

---

## Execution Strategy

### Sequential Build Order
All tasks are sequential — each builds on the prior function in a single file.

```
Task 1: Scaffold + config + logging
Task 2: Telnet connection layer
Task 3: Command send + status parsing
Task 4: Status verification with retry
Task 5: Rate limiting
Task 6: do_stop (S function)
Task 7: do_override (O function)
Task 8: do_passthrough (P function)  
Task 9: Signal handling + integration QA
```

### Dependency Matrix
| Task | Depends On | Blocks |
|------|------------|--------|
| 1 | None | 2-9 |
| 2 | 1 | 3-9 |
| 3 | 2 | 4-9 |
| 4 | 3 | 6-8 |
| 5 | 1 | 8 |
| 6 | 4 | 9 |
| 7 | 4 | 9 |
| 8 | 4, 5 | 9 |
| 9 | 6, 7, 8 | None |

---

## TODOs

- [ ] 1. Scaffold weather-ctrl.py + config loading + logging setup + mock server

  **What to do**:
  - Create `weather-ctrl.py` with `#!/usr/bin/env python3`, imports, `main()` with argparse
  - argparse: positional `function` (choices: P, O, S), optional `port` (int, 0-6)
  - Validate: P and O require port; S port is optional
  - `load_config()`: search `./weather-ctrl.conf` then `/etc/weather-ctrl.conf`, return dict
  - `setup_logging()`: FileHandler to configured path, format: `%(asctime)s %(levelname)s %(message)s`
  - Create `weather-ctrl.conf.example` with all settings documented
  - Create `.sisyphus/test_server.py` mock telnet server

  **Must NOT do**:
  - No config auto-generation
  - No log rotation setup
  - No class-based structure

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Sequential
  - **Blocks**: All subsequent tasks
  - **Blocked By**: None

  **References**:
  - Python `configparser` docs: https://docs.python.org/3.10/library/configparser.html
  - Python `argparse` docs: https://docs.python.org/3.10/library/argparse.html

  **Acceptance Criteria**:
  - [ ] `python3 weather-ctrl.py --help` shows usage with P, O, S functions
  - [ ] `python3 weather-ctrl.py P` (no port) → exits non-zero with error
  - [ ] `python3 weather-ctrl.py S` (no port) → accepted (exits, doesn't crash on missing config yet)
  - [ ] `python3 weather-ctrl.py X` → argparse error for invalid function
  - [ ] `weather-ctrl.conf.example` exists with all documented fields
  - [ ] Mock server starts and accepts telnet connections

  **Agent-Executed QA Scenarios**:
  ```
  Scenario: Help output shows all functions
    Tool: Bash
    Steps:
      1. python3 weather-ctrl.py --help
      2. Assert: stdout contains "P", "O", "S"
      3. Assert: exit code 0

  Scenario: P without port fails
    Tool: Bash
    Steps:
      1. python3 weather-ctrl.py P 2>&1
      2. Assert: exit code non-zero
      3. Assert: stderr mentions "port"

  Scenario: Mock server accepts connection
    Tool: Bash
    Steps:
      1. Start mock server: python3 .sisyphus/test_server.py 9999 &
      2. sleep 1
      3. echo "q" | python3 -c "import telnetlib; t=telnetlib.Telnet('127.0.0.1', 9999, timeout=3); t.write(b'q\r\n'); t.close()"
      4. Assert: no connection error
      5. Kill mock server
  ```

  **Commit**: YES
  - Message: `feat: scaffold CLI with argparse, config loading, logging, mock server`
  - Files: `weather-ctrl.py`, `weather-ctrl.conf.example`, `.sisyphus/test_server.py`

---

- [ ] 2. Telnet connection layer with retry

  **What to do**:
  - `connect(host, port)`: `telnetlib.Telnet(host, port, timeout=5)` with 3 retries, 3s between
  - Consume any welcome banner on connect: `tn.read_very_eager()` with short delay
  - `disconnect(tn)`: send `q\r\n`, then `tn.close()`
  - Store `tn` (telnet connection) as a module-level variable so signal handler can access it
  - Return telnet object on success, exit 1 after 3 failures

  **Must NOT do**:
  - No generic retry decorator
  - No connection pooling
  - No async/threading

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Blocked By**: Task 1

  **References**:
  - Python `telnetlib` docs: https://docs.python.org/3.10/library/telnetlib.html
  - Task 1's `weather-ctrl.py` for existing structure

  **Acceptance Criteria**:
  - [ ] With mock server running: `connect()` returns telnet object
  - [ ] With no server: `connect()` retries 3 times (visible in log), exits 1
  - [ ] `disconnect()` sends `q` before closing

  **Agent-Executed QA Scenarios**:
  ```
  Scenario: Successful connection to mock server
    Tool: Bash
    Steps:
      1. Start mock server on port 9999
      2. Create test script that calls connect('127.0.0.1', 9999) and prints "OK"
      3. Run test script
      4. Assert: prints "OK", exit 0
      5. Kill mock server

  Scenario: Connection failure retries 3 times
    Tool: Bash
    Steps:
      1. No server running on port 9998
      2. Create test script that calls connect('127.0.0.1', 9998)
      3. Run with timeout 15s
      4. Assert: exit code 1
      5. Assert: log file contains 3 retry messages
  ```

  **Commit**: YES
  - Message: `feat: telnet connection with 3x retry and clean disconnect`
  - Files: `weather-ctrl.py`

---

- [ ] 3. Command sending and status JSON parsing

  **What to do**:
  - `send_command(tn, cmd)`: write `cmd\r\n`, read response with timeout, log command+response, return response string
  - `get_status(tn)`: send `s`, parse JSON response into dict, return it
  - Handle read timeout (log warning, return None)
  - Status JSON format: `{"channels":[{"ch":N,"state":"idle"|"passthrough"},...]}`
  - Helper to extract port state: find entry where `ch == port`, return `state`

  **Must NOT do**:
  - No command queuing
  - No response validation beyond JSON parse

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Blocked By**: Task 2

  **References**:
  - Task 2's `connect()`/`disconnect()` functions
  - Mock server's response format

  **Acceptance Criteria**:
  - [ ] `send_command(tn, "p 1 1")` returns response string, logs command
  - [ ] `get_status(tn)` returns parsed dict with port states
  - [ ] Timeout produces warning log, returns None

  **Agent-Executed QA Scenarios**:
  ```
  Scenario: Send enable command and get response
    Tool: Bash
    Steps:
      1. Start mock server
      2. Script: connect, send_command("p 1 1"), print response, disconnect
      3. Assert: response is "OK" or similar
      4. Assert: log contains "p 1 1"

  Scenario: Get status returns parsed JSON
    Tool: Bash
    Steps:
      1. Start mock server
      2. Script: connect, get_status(), print result, disconnect
      3. Assert: result is dict with keys "0" through "6"
  ```

  **Commit**: YES
  - Message: `feat: command sending and status JSON parsing`
  - Files: `weather-ctrl.py`

---

- [ ] 4. Status verification with retry logic

  **What to do**:
  - `verify_port(tn, port, expected_state)`: call `get_status()`, check if port matches expected (`"idle"` or `"passthrough"`)
  - If mismatch: retry up to 3 times with 1s delay between
  - If still mismatched after 3 retries: log error, return False
  - On success: log confirmation, return True

  **Must NOT do**:
  - No generic retry wrapper — inline the loop

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Blocked By**: Task 3

  **References**:
  - Task 3's `get_status()` function

  **Acceptance Criteria**:
  - [ ] After `p 1 1`, `verify_port(tn, 1, 1)` returns True
  - [ ] If mock returns wrong state, retries 3 times then returns False
  - [ ] Log shows verification attempts

  **Agent-Executed QA Scenarios**:
  ```
  Scenario: Verify port state matches
    Tool: Bash
    Steps:
      1. Start mock server
      2. Script: connect, send "p 1 1", verify_port(tn, 1, 1), print result
      3. Assert: result is True

  Scenario: Verify detects mismatch and retries
    Tool: Bash
    Steps:
      1. Start mock server (configured to return wrong state for port 2)
      2. Script: connect, verify_port(tn, 2, 1), print result
      3. Assert: result is False
      4. Assert: log shows 3 retry attempts
  ```

  **Commit**: YES
  - Message: `feat: port status verification with 3x retry`
  - Files: `weather-ctrl.py`

---

- [ ] 5. Per-port rate limiting

  **What to do**:
  - `check_rate_limit(port, max_calls, window_seconds)`:
    - Read `./weather-ctrl.state.json` (create if missing, default `{}`)
    - Get timestamps list for port, prune entries older than `window_seconds`
    - Return True if len >= `max_calls` (rate limited), False otherwise
  - `record_call(port)`:
    - Read state, append `time.time()` to port's list, write back
  - Both functions use port as string key
  - Handle corrupt/missing state file gracefully (reset to `{}`)

  **Must NOT do**:
  - No file locking
  - No database
  - No global (cross-port) rate limit — per-port only

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Blocked By**: Task 1 (config for thresholds)

  **References**:
  - State file format defined in Design Decisions section above

  **Acceptance Criteria**:
  - [ ] First call to `check_rate_limit(1, 3, 60)` returns False (not limited)
  - [ ] After 3 `record_call(1)` calls, `check_rate_limit(1, 3, 60)` returns True
  - [ ] Different ports have independent counters
  - [ ] Old timestamps are pruned correctly
  - [ ] Corrupt state file → reset to `{}`

  **Agent-Executed QA Scenarios**:
  ```
  Scenario: Rate limit triggers after max_calls
    Tool: Bash
    Steps:
      1. Remove weather-ctrl.state.json if exists
      2. Script: record 3 calls for port 1, then check → True
      3. Check port 2 → False (independent)
      4. Assert: state file exists with correct structure

  Scenario: Corrupt state file handled
    Tool: Bash
    Steps:
      1. echo "garbage" > weather-ctrl.state.json
      2. Script: check_rate_limit(0, 5, 60)
      3. Assert: returns False (reset, not crash)
      4. Assert: state file is valid JSON now
  ```

  **Commit**: YES
  - Message: `feat: per-port rate limiting with state file`
  - Files: `weather-ctrl.py`

---

- [ ] 6. Implement S (Stop) function

  **What to do**:
  - `do_stop(port, config)`:
    - If port is None: loop ports 0-6, send `p N 0` for each
    - If port given: send `p <port> 0`
    - After all disable commands: verify each disabled port via `verify_port()`
    - If any verification fails after retries: log error, exit 1
    - Send `q`, disconnect, exit 0

  **Must NOT do**:
  - No parallel port disabling — sequential is fine

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Blocked By**: Task 4

  **References**:
  - Task 4's `verify_port()` function
  - Task 2's `connect()`/`disconnect()` functions
  - Task 3's `send_command()` function

  **Acceptance Criteria**:
  - [ ] `weather-ctrl.py S` → disables all 7 ports, verifies, disconnects
  - [ ] `weather-ctrl.py S 3` → disables port 3 only, verifies, disconnects
  - [ ] Log shows each `p N 0` command and verification result
  - [ ] Exit 0 on success, exit 1 if verification fails

  **Agent-Executed QA Scenarios**:
  ```
  Scenario: Stop all ports
    Tool: Bash
    Steps:
      1. Start mock server, enable some ports manually
      2. Create weather-ctrl.conf with mock server host/port
      3. python3 weather-ctrl.py S
      4. Assert: exit 0
      5. Assert: log contains "p 0 0" through "p 6 0"
      6. Assert: log contains verification success for all ports

  Scenario: Stop single port
    Tool: Bash
    Steps:
      1. Start mock server
      2. python3 weather-ctrl.py S 3
      3. Assert: exit 0
      4. Assert: log contains "p 3 0" but NOT "p 0 0" or "p 6 0"
  ```

  **Commit**: YES
  - Message: `feat: implement S (stop) function for single and all ports`
  - Files: `weather-ctrl.py`

---

- [ ] 7. Implement O (Override) function

  **What to do**:
  - `do_override(port, config)`:
    - Connect to remote
    - Send `p <port> 1` to enable
    - Verify status with `verify_port(tn, port, 1)`
    - If verification fails after retries: log error, exit 1
    - Send `q`, disconnect, exit 0

  **Must NOT do**:
  - No timer
  - No rate limiting (O is not rate-limited, only P is)

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Blocked By**: Task 4

  **References**:
  - Task 4's `verify_port()` for status check
  - Task 2/3 for connection and command functions

  **Acceptance Criteria**:
  - [ ] `weather-ctrl.py O 5` → enables port 5, verifies, disconnects, exit 0
  - [ ] Log shows `p 5 1` command and verification success
  - [ ] If verification fails → exit 1

  **Agent-Executed QA Scenarios**:
  ```
  Scenario: Override enables port
    Tool: Bash
    Steps:
      1. Start mock server
      2. python3 weather-ctrl.py O 5
      3. Assert: exit 0
      4. Assert: log contains "p 5 1"
      5. Assert: log contains verification success for port 5

  Scenario: Override on already-enabled port still works
    Tool: Bash
    Steps:
      1. Start mock server, pre-enable port 5
      2. python3 weather-ctrl.py O 5
      3. Assert: exit 0 (no error for already-enabled)
  ```

  **Commit**: YES
  - Message: `feat: implement O (override) function`
  - Files: `weather-ctrl.py`

---

- [ ] 8. Implement P (Passthrough) function

  **What to do**:
  - `do_passthrough(port, config)`:
    - Check rate limit: if exceeded, log and exit 2
    - Record call in state file
    - Connect to remote
    - Send `p <port> 1` to enable
    - Verify enable with `verify_port(tn, port, 1)`
    - Start timer: `time.sleep(duration)` — keep connection open
    - During sleep, if connection drops: reconnect to complete disable
    - After timer: send `p <port> 0` to disable
    - Verify disable with `verify_port(tn, port, 0)`
    - Send `q`, disconnect, exit 0
  - Timer reconnection strategy:
    - Wrap the timer wait in a try/except
    - After timer expires, if connection lost: call `connect()` again
    - Then proceed with disable + verify

  **Must NOT do**:
  - No threading for timer — simple `time.sleep()`
  - No background process or daemon

  **Recommended Agent Profile**:
  - **Category**: `unspecified-low`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Blocked By**: Tasks 4, 5

  **References**:
  - Task 5's `check_rate_limit()` and `record_call()` functions
  - Task 4's `verify_port()` function
  - Config `[timer] duration` value

  **Acceptance Criteria**:
  - [ ] `weather-ctrl.py P 1` → enables, waits timer duration, disables, verifies, disconnects
  - [ ] Rate limit: after N calls within window, next call exits 2
  - [ ] Log shows enable → timer start → timer end → disable → verify sequence
  - [ ] Already-enabled port: still runs normal flow (re-enable + timer + disable)

  **Agent-Executed QA Scenarios**:
  ```
  Scenario: Passthrough full cycle (use short timer for test)
    Tool: Bash
    Preconditions: weather-ctrl.conf with duration=3 (3 seconds for fast test)
    Steps:
      1. Start mock server
      2. python3 weather-ctrl.py P 1
      3. Assert: exit 0
      4. Assert: log contains "p 1 1" then "p 1 0"
      5. Assert: log contains verification for both states
      6. Assert: weather-ctrl.state.json contains timestamp for port 1

  Scenario: Rate limit blocks P call
    Tool: Bash
    Preconditions: weather-ctrl.conf with max_calls=2, window_seconds=60, duration=2
    Steps:
      1. Start mock server
      2. python3 weather-ctrl.py P 1 && python3 weather-ctrl.py P 1 (wait for each)
      3. python3 weather-ctrl.py P 1
      4. Assert: third call exits 2
      5. Assert: log contains "rate limit" message

  Scenario: P on already-enabled port works normally
    Tool: Bash
    Steps:
      1. Start mock server, pre-enable port 1
      2. python3 weather-ctrl.py P 1 (with duration=2)
      3. Assert: exit 0 (normal flow, no error)
  ```

  **Commit**: YES
  - Message: `feat: implement P (passthrough) function with timer and rate limit`
  - Files: `weather-ctrl.py`

---

- [ ] 9. Signal handling (Ctrl+C) + final integration QA

  **What to do**:
  - `signal_handler(sig, frame)`:
    - Access module-level telnet connection variable
    - If connected: send `q`, close connection
    - Log "interrupted by user"
    - `sys.exit(130)`
  - Register with `signal.signal(signal.SIGINT, signal_handler)`
  - Wire up the `main()` dispatch: P → `do_passthrough`, O → `do_override`, S → `do_stop`
  - End-to-end integration test of all functions

  **Must NOT do**:
  - No SIGTERM handling (only SIGINT/Ctrl+C)
  - No graceful shutdown beyond disconnect

  **Recommended Agent Profile**:
  - **Category**: `unspecified-low`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Blocked By**: Tasks 6, 7, 8

  **References**:
  - Python `signal` module: https://docs.python.org/3.10/library/signal.html
  - All prior task functions

  **Acceptance Criteria**:
  - [ ] Ctrl+C during P timer → log shows "interrupted", clean disconnect
  - [ ] All 4 functions dispatch correctly from main()
  - [ ] Invalid port (7, -1) rejected by argparse
  - [ ] Missing config → clear error, exit 1

  **Agent-Executed QA Scenarios**:
  ```
  Scenario: Ctrl+C during passthrough timer
    Tool: Bash
    Preconditions: weather-ctrl.conf with duration=30
    Steps:
      1. Start mock server
      2. python3 weather-ctrl.py P 1 &
      3. PID=$!
      4. sleep 2
      5. kill -INT $PID
      6. wait $PID; echo $?
      7. Assert: exit code 130
      8. Assert: log contains "interrupted"
      9. Assert: log contains "q" disconnect command

  Scenario: Full integration — all functions
    Tool: Bash
    Preconditions: weather-ctrl.conf with duration=2, max_calls=10
    Steps:
      1. Start mock server
      2. python3 weather-ctrl.py O 3 → exit 0
      3. python3 weather-ctrl.py P 1 → exit 0 (waits 2s)
      4. python3 weather-ctrl.py S 3 → exit 0
      5. python3 weather-ctrl.py S → exit 0
      6. Assert: log contains all operations in order
      7. Kill mock server

  Scenario: Invalid inputs
    Tool: Bash
    Steps:
      1. python3 weather-ctrl.py P 7 → exit non-zero (port out of range)
      2. python3 weather-ctrl.py O → exit non-zero (missing port)
      3. python3 weather-ctrl.py Z → exit non-zero (invalid function)
  ```

  **Commit**: YES
  - Message: `feat: signal handling and main dispatch wiring`
  - Files: `weather-ctrl.py`

---

## Commit Strategy

| After Task | Message | Files | Verification |
|------------|---------|-------|--------------|
| 1 | `feat: scaffold CLI with argparse, config loading, logging, mock server` | weather-ctrl.py, weather-ctrl.conf.example, .sisyphus/test_server.py | --help works |
| 2 | `feat: telnet connection with 3x retry and clean disconnect` | weather-ctrl.py | connect/disconnect with mock |
| 3 | `feat: command sending and status JSON parsing` | weather-ctrl.py | send + parse with mock |
| 4 | `feat: port status verification with 3x retry` | weather-ctrl.py | verify with mock |
| 5 | `feat: per-port rate limiting with state file` | weather-ctrl.py | rate limit logic |
| 6 | `feat: implement S (stop) function` | weather-ctrl.py | S and S N work |
| 7 | `feat: implement O (override) function` | weather-ctrl.py | O N works |
| 8 | `feat: implement P (passthrough) function with timer and rate limit` | weather-ctrl.py | P N full cycle |
| 9 | `feat: signal handling and main dispatch wiring` | weather-ctrl.py | Ctrl+C + integration |

---

## Success Criteria

### Verification Commands
```bash
# All functions work end-to-end with mock server
python3 .sisyphus/test_server.py 9999 &
python3 weather-ctrl.py O 3     # Enable port 3 → exit 0
python3 weather-ctrl.py P 1     # Enable, wait, disable port 1 → exit 0
python3 weather-ctrl.py S 3     # Stop port 3 → exit 0
python3 weather-ctrl.py S       # Stop all → exit 0
kill %1                    # Stop mock server
```

### Final Checklist
- [ ] All 4 CLI functions work (P, O, S, S+port)
- [ ] Config loaded from ./weather-ctrl.conf or /etc/weather-ctrl.conf
- [ ] Rate limiting prevents excess P calls per port
- [ ] Connection retries 3×3s on failure
- [ ] Status verification retries 3× after enable/disable
- [ ] Ctrl+C cleanly disconnects
- [ ] Log file records all activity
- [ ] Exit codes: 0=success, 1=error, 2=rate-limited
- [ ] Single file, stdlib only
