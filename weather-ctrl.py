#!/usr/bin/env python3

import argparse
import configparser
import logging
import json
import time
import signal
import sys
import os
import socket


def load_config():
    """Load configuration from ./weather-ctrl.conf or /etc/weather-ctrl.conf"""
    config_paths = [
        "./weather-ctrl.conf",
        "/etc/weather-ctrl.conf"
    ]
    
    config = configparser.ConfigParser()
    
    for path in config_paths:
        if os.path.exists(path):
            config.read(path)
            break
    else:
        sys.stderr.write("Error: No configuration file found at ./weather-ctrl.conf or /etc/weather-ctrl.conf\n")
        sys.exit(1)
    
    # Ensure required sections exist
    if not config.has_section("remote"):
        sys.stderr.write("Error: [remote] section not found in config\n")
        sys.exit(1)
    
    if not config.has_option("remote", "host"):
        sys.stderr.write("Error: [remote] host not found in config\n")
        sys.exit(1)
    
    if not config.has_section("timer"):
        sys.stderr.write("Error: [timer] section not found in config\n")
        sys.exit(1)
    
    if not config.has_option("timer", "duration"):
        sys.stderr.write("Error: [timer] duration not found in config\n")
        sys.exit(1)
    
    if not config.has_section("ratelimit"):
        sys.stderr.write("Error: [ratelimit] section not found in config\n")
        sys.exit(1)
    
    if not config.has_option("ratelimit", "max_calls"):
        sys.stderr.write("Error: [ratelimit] max_calls not found in config\n")
        sys.exit(1)
    
    if not config.has_option("ratelimit", "window_seconds"):
        sys.stderr.write("Error: [ratelimit] window_seconds not found in config\n")
        sys.exit(1)
    
    # Build config dict with defaults
    config_dict = {
        "remote": {
            "host": config.get("remote", "host"),
            "port": config.getint("remote", "port") if config.has_option("remote", "port") else 5555,
            "cmd_delay": config.getfloat("remote", "cmd_delay") if config.has_option("remote", "cmd_delay") else 3.0,
        },
        "timer": {
            "duration": config.getint("timer", "duration"),
        },
        "logging": {
            "file": config.get("logging", "file") if config.has_option("logging", "file") else "./weather-ctrl.log",
        },
        "ratelimit": {
            "max_calls": config.getint("ratelimit", "max_calls"),
            "window_seconds": config.getint("ratelimit", "window_seconds"),
        }
    }
    
    return config_dict


def setup_logging(config):
    """Configure logging with file handler and stderr error handler"""
    log_path = config["logging"]["file"]
    
    # Create logger
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    
    # File handler
    file_handler = logging.FileHandler(log_path)
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)
    
    # Stderr handler for ERROR level
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(logging.ERROR)
    stderr_formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    stderr_handler.setFormatter(stderr_formatter)
    logger.addHandler(stderr_handler)


_sock = None  # Module-level socket connection for signal handler access
_cmd_delay = 3.0  # Delay in seconds between commands


def connect(host, port):
    """Connect to remote device via TCP socket with retry logic"""
    global _sock
    logger = logging.getLogger()

    for attempt in range(1, 4):
        try:
            logger.info(f"Attempting connection to {host}:{port} (attempt {attempt}/3)")
            sock = socket.create_connection((host, port), timeout=5)
            sock.settimeout(10)
            _sock = sock
            logger.info(f"Successfully connected to {host}:{port}")

            # Consume any welcome banner
            try:
                time.sleep(0.5)
                sock.setblocking(False)
                try:
                    sock.recv(4096)
                except BlockingIOError:
                    pass
                sock.setblocking(True)
                sock.settimeout(10)
            except Exception:
                pass

            return sock
        except Exception as e:
            logger.warning(f"Connection attempt {attempt} failed: {e}")
            if attempt < 3:
                time.sleep(3)

    logger.error(f"Failed to connect to {host}:{port} after 3 attempts")
    sys.exit(1)


def disconnect(sock):
    """Disconnect from remote device"""
    global _sock
    logger = logging.getLogger()

    try:
        try:
            sock.sendall(b"q\r\n")
            time.sleep(1)
        except Exception:
            pass
        try:
            sock.close()
        except Exception:
            pass
        _sock = None
        logger.info("Disconnected from remote server")
    except Exception as e:
        logger.warning(f"Error during disconnect: {e}")


def _flush_buffer(sock):
    """Drain any stale data from the socket buffer"""
    logger = logging.getLogger()
    try:
        sock.setblocking(False)
        while True:
            try:
                data = sock.recv(4096)
                if not data:
                    break
                logger.debug(f"Flushed stale data: {repr(data)}")
            except BlockingIOError:
                break
        sock.setblocking(True)
        sock.settimeout(10)
    except Exception:
        pass


def _recv_all_lines(sock, timeout=0.5):
    """Read all available lines from socket until silence"""
    sock.settimeout(timeout)
    buf = b""
    while True:
        try:
            chunk = sock.recv(4096)
            if not chunk:
                break
            buf += chunk
        except socket.timeout:
            break
    return buf.decode("ascii", errors="replace").strip()


def send_command(sock, cmd):
    """Send command to remote device and get response"""
    logger = logging.getLogger()

    try:
        raw_cmd = (cmd + "\r\n").encode("ascii")
        logger.debug(f"Sending raw bytes: {repr(raw_cmd)}")
        sock.sendall(raw_cmd)
        time.sleep(0.1)
        response_str = _recv_all_lines(sock)
        logger.info(f"Sent: {cmd} | Response: {response_str}")
        time.sleep(_cmd_delay)
        return response_str
    except Exception as e:
        logger.warning(f"Error sending command '{cmd}': {e}")
        return None


def get_status(sock):
    """Get status from remote device and parse JSON"""
    logger = logging.getLogger()

    try:
        _flush_buffer(sock)
        sock.sendall(b"s\r\n")
        time.sleep(0.1)
        response_str = _recv_all_lines(sock)
        status = json.loads(response_str)
        logger.info(f"Status: {response_str}")
        return status
    except json.JSONDecodeError as e:
        logger.warning(f"JSON parse error: {e}")
        return None
    except Exception as e:
        logger.warning(f"Error getting status: {e}")
        return None


def verify_port(tn, port, expected_state):
    """Verify port is in expected state"""
    logger = logging.getLogger()
    
    for attempt in range(1, 4):
        status = get_status(tn)
        
        if status is None:
            logger.warning(f"verify_port attempt {attempt}: Failed to get status")
            if attempt < 3:
                time.sleep(1)
            continue
        
        # Find channel with matching port
        for channel in status.get("channels", []):
            if channel.get("ch") == port:
                if channel.get("state") == expected_state:
                    logger.info(f"Port {port} verified in state '{expected_state}'")
                    return True
                else:
                    current_state = channel.get("state")
                    logger.warning(f"verify_port attempt {attempt}: Port {port} is '{current_state}', expected '{expected_state}'")
                    if attempt < 3:
                        time.sleep(1)
                    break
        else:
            logger.warning(f"verify_port attempt {attempt}: Port {port} not found in status")
            if attempt < 3:
                time.sleep(1)
    
    logger.error(f"Failed to verify port {port} in state '{expected_state}' after 3 attempts")
    return False


STATE_FILE = "./weather-ctrl.state.json"


def check_rate_limit(port, max_calls, window_seconds):
    """Check if port is rate limited"""
    logger = logging.getLogger()
    
    # Read state file
    state = {}
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                state = json.load(f)
        except (json.JSONDecodeError, IOError):
            state = {}
    
    # Get timestamps for this port
    port_key = str(port)
    timestamps = state.get(port_key, [])
    
    # Prune old entries
    now = time.time()
    cutoff = now - window_seconds
    timestamps = [ts for ts in timestamps if ts > cutoff]
    
    # Check if rate limited
    if len(timestamps) >= max_calls:
        logger.debug(f"Port {port} rate limited: {len(timestamps)} calls in last {window_seconds}s")
        return True
    
    return False


def record_call(port):
    """Record a call to the port in state file"""
    logger = logging.getLogger()
    
    # Read state file
    state = {}
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                state = json.load(f)
        except (json.JSONDecodeError, IOError):
            state = {}
    
    # Add timestamp
    port_key = str(port)
    if port_key not in state:
        state[port_key] = []
    state[port_key].append(time.time())
    
    # Write state file
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f)
        logger.debug(f"Recorded call for port {port}")
    except IOError as e:
        logger.warning(f"Failed to write state file: {e}")


def do_stop(port, config):
    """Stop passthrough on port(s)"""
    logger = logging.getLogger()
    
    tn = connect(config["remote"]["host"], config["remote"]["port"])
    
    if port is None:
        for p in range(7):
            send_command(tn, f"p {p} 0")
    else:
        send_command(tn, f"p {port} 0")
    
    if port is None:
        for p in range(7):
            if not verify_port(tn, p, "idle"):
                logger.error(f"Failed to verify port {p} disabled")
                disconnect(tn)
                sys.exit(1)
    else:
        if not verify_port(tn, port, "idle"):
            logger.error(f"Failed to verify port {port} disabled")
            disconnect(tn)
            sys.exit(1)
    
    disconnect(tn)
    sys.exit(0)


def do_override(port, config):
    """Override port to passthrough"""
    logger = logging.getLogger()
    
    tn = connect(config["remote"]["host"], config["remote"]["port"])
    
    send_command(tn, f"p {port} 1")
    
    if not verify_port(tn, port, "passthrough"):
        logger.error(f"Failed to verify port {port} enabled")
        disconnect(tn)
        sys.exit(1)
    
    disconnect(tn)
    sys.exit(0)


def do_passthrough(port, config):
    """Enable passthrough with timer"""
    logger = logging.getLogger()
    
    if check_rate_limit(port, config["ratelimit"]["max_calls"], config["ratelimit"]["window_seconds"]):
        logger.warning(f"Rate limit exceeded for port {port}")
        sys.exit(2)
    
    record_call(port)
    
    tn = connect(config["remote"]["host"], config["remote"]["port"])
    
    send_command(tn, f"p {port} 1")
    
    if not verify_port(tn, port, "passthrough"):
        logger.error(f"Failed to verify port {port} enabled")
        disconnect(tn)
        sys.exit(1)
    
    duration = config["timer"]["duration"]
    logger.info(f"Starting timer for {duration} seconds on port {port}")
    time.sleep(duration)
    
    # Close stale connection and reconnect fresh before disabling
    disconnect(tn)
    time.sleep(_cmd_delay)
    tn = connect(config["remote"]["host"], config["remote"]["port"])

    response = send_command(tn, f"p {port} 0")
    
    if response and ("IDLE" in response.upper() or "OK" in response.upper()):
        logger.info(f"Port {port} confirmed disabled from command response")
    else:
        logger.warning(f"Port {port} disable response unclear: {response}")
    
    disconnect(tn)
    sys.exit(0)


def signal_handler(sig, frame):
    global _sock
    logger = logging.getLogger()
    logger.info("Interrupted by user (Ctrl+C)")
    if _sock is not None:
        disconnect(_sock)
    sys.exit(130)


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Weather control CLI for remote telnet device"
    )
    parser.add_argument(
        "function",
        choices=["P", "O", "S"],
        help="Function to execute: P (passthrough), O (override), S (stop)"
    )
    parser.add_argument(
        "port",
        nargs="?",
        type=int,
        help="Port number (0-6)"
    )
    
    args = parser.parse_args()
    
    # Validate port requirements
    if args.function in ["P", "O"]:
        if args.port is None:
            sys.stderr.write("Error: P and O functions require a port argument\n")
            sys.exit(1)
    
    # Validate port range if provided
    if args.port is not None:
        if args.port < 0 or args.port > 6:
            sys.stderr.write("Error: Port must be in range 0-6\n")
            sys.exit(1)
    
    # Load config and setup logging
    config = load_config()
    setup_logging(config)
    
    global _cmd_delay
    _cmd_delay = config["remote"]["cmd_delay"]
    
    logger = logging.getLogger()
    logger.info(f"Invoked with function={args.function}, port={args.port}")
    
    # Register signal handler
    signal.signal(signal.SIGINT, signal_handler)
    
    # Dispatch to function handlers
    if args.function == "P":
        do_passthrough(args.port, config)
    elif args.function == "O":
        do_override(args.port, config)
    elif args.function == "S":
        do_stop(args.port, config)


if __name__ == "__main__":
    main()
