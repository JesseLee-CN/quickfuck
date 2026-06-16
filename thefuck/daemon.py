"""Persistent daemon for sub-50ms command correction.

Protocol (Unix socket, JSON, newline-delimited)::

    → {"script": "...", "output": "..."}
    ← {"correction": "..."}

Start:  ``thefuckd``         (foreground) or ``thefuckd &`` (background)
Stop:   ``thefuckd --stop``
Query:  ``thefuckd query '{"script":"claer","output":"command not found"}'``
Status: ``thefuckd --status``
"""
from __future__ import annotations

import json
import os
import signal
import socket
import sys
import time
from typing import Any


SOCKET_PATH: str = os.path.expanduser("~/.cache/thefuck/daemon.sock")
PID_FILE: str = os.path.expanduser("~/.cache/thefuck/daemon.pid")
LOCK_FILE: str = os.path.expanduser("~/.cache/thefuck/daemon.lock")
BUFSIZE: int = 65536

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ensure_dir() -> None:
    os.makedirs(os.path.dirname(SOCKET_PATH), exist_ok=True)


def _read_pid() -> int | None:
    try:
        with open(PID_FILE) as fh:
            return int(fh.read().strip())
    except (FileNotFoundError, ValueError):
        return None


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _acquire_lock() -> bool:
    """Simple file-based lock to prevent double-start."""
    _ensure_dir()
    try:
        fd = os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o644)
        os.close(fd)
        return True
    except FileExistsError:
        return False


def _release_lock() -> None:
    try:
        os.unlink(LOCK_FILE)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Daemon server
# ---------------------------------------------------------------------------


def _load_rules():
    """Pre-load rules once.  Must be called before ``_handle``."""
    from .conf import settings
    settings.init()
    from .corrector import get_rules
    return get_rules()


def _handle(rules, raw: str) -> dict[str, Any]:
    """Process a single request, return a JSON-serialisable response."""
    try:
        req = json.loads(raw)
    except json.JSONDecodeError:
        return {"correction": None, "error": "invalid json"}

    script: str = req.get("script", "")
    output: str = req.get("output", "") or ""

    from .types import Command
    cmd = Command(script, output)

    corrections = []
    for rule in rules:
        try:
            if rule.is_match(cmd):
                for corr in rule.get_corrected_commands(cmd):
                    corrections.append(corr.script)
        except Exception:
            pass

    return {"correction": corrections[0] if corrections else None}


def _server_loop() -> None:
    """Accept connections forever."""
    # Write PID
    with open(PID_FILE, "w") as fh:
        fh.write(str(os.getpid()))

    # Remove stale socket
    try:
        os.unlink(SOCKET_PATH)
    except OSError:
        pass
    _ensure_dir()

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(SOCKET_PATH)
    server.listen(4)
    os.chmod(SOCKET_PATH, 0o600)

    # Signal-safe: close socket on SIGTERM/SIGINT
    def _cleanup(signum, frame):
        server.close()
        try:
            os.unlink(SOCKET_PATH)
        except OSError:
            pass
        try:
            os.unlink(PID_FILE)
        except OSError:
            pass
        _release_lock()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _cleanup)
    signal.signal(signal.SIGINT, _cleanup)

    # Pre-load rules (warm cache: the first request after this is instant)
    rules = _load_rules()

    while True:
        try:
            client, _addr = server.accept()
        except OSError:
            break  # server was closed by signal handler

        try:
            data = b""
            while True:
                chunk = client.recv(BUFSIZE)
                if not chunk:
                    break
                data += chunk
                if len(chunk) < BUFSIZE:
                    break
            response = _handle(rules, data.decode("utf-8"))
            client.sendall((json.dumps(response) + "\n").encode("utf-8"))
        except Exception:
            try:
                client.sendall(b'{"correction":null,"error":"internal"}\n')
            except OSError:
                pass
        finally:
            try:
                client.close()
            except OSError:
                pass


def start(foreground: bool = False) -> int:
    """Start the daemon.  Returns 0 on success, 1 if already running."""
    if not _acquire_lock():
        print("thefuckd: already running", file=sys.stderr)
        return 1

    pid = _read_pid()
    if pid and _pid_alive(pid):
        _release_lock()
        print("thefuckd: already running (pid {})".format(pid), file=sys.stderr)
        return 1

    if not foreground:
        # Double-fork to daemonise
        if os.fork() > 0:
            return 0
        os.setsid()
        if os.fork() > 0:
            os._exit(0)

        # Redirect stdin/stdout/stderr
        fd = os.open(os.devnull, os.O_RDWR)
        os.dup2(fd, 0)
        os.dup2(fd, 1)
        os.dup2(fd, 2)
        if fd > 2:
            os.close(fd)

    _server_loop()
    return 0


def stop() -> int:
    """Stop a running daemon.  Returns 0 on success."""
    pid = _read_pid()
    if pid and _pid_alive(pid):
        os.kill(pid, signal.SIGTERM)
        # Wait for it to exit
        for _ in range(50):
            if not _pid_alive(pid):
                break
            time.sleep(0.02)
        else:
            os.kill(pid, signal.SIGKILL)
        print("thefuckd: stopped (pid {})".format(pid), file=sys.stderr)
    else:
        print("thefuckd: not running", file=sys.stderr)
    _release_lock()
    try:
        os.unlink(PID_FILE)
    except OSError:
        pass
    try:
        os.unlink(SOCKET_PATH)
    except OSError:
        pass
    return 0


def status() -> int:
    """Print daemon status.  Exit 0 if running, 1 otherwise."""
    pid = _read_pid()
    if pid and _pid_alive(pid):
        print("thefuckd: running (pid {})".format(pid))
        return 0
    print("thefuckd: not running")
    return 1


def query(raw_json: str, timeout: float = 0.5) -> int:
    """Send a request to the daemon and print the response.

    Used by: ``thefuckd query '{"script":"claer","output":"..."}'``
    Also used internally by the shell client.
    """
    pid = _read_pid()
    if not pid or not _pid_alive(pid):
        # Daemon not running — fall through to print nothing
        print("", file=sys.stderr)
        return 1

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect(SOCKET_PATH)
        sock.sendall((raw_json.strip() + "\n").encode("utf-8"))
        data = b""
        while True:
            chunk = sock.recv(BUFSIZE)
            if not chunk:
                break
            data += chunk
            if len(chunk) < BUFSIZE:
                break
        response = json.loads(data.decode("utf-8"))
        correction = response.get("correction")
        if correction:
            print(correction, flush=True)
            return 0
        else:
            return 1
    except Exception:
        return 1
    finally:
        sock.close()


def ensure_running(max_wait: float = 1.0) -> bool:
    """Ensure the daemon is running, starting it if necessary.

    Returns True if a daemon is (now) available.
    """
    pid = _read_pid()
    if pid and _pid_alive(pid):
        return True

    # Try to start it
    start(foreground=False)
    deadline = time.time() + max_wait
    while time.time() < deadline:
        pid = _read_pid()
        if pid and _pid_alive(pid):
            return True
        time.sleep(0.05)
    return False


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] in ("--help", "-h"):
        print("usage: thefuckd [start|stop|status|query JSON]", file=sys.stderr)
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "start":
        sys.exit(start())
    elif cmd == "stop":
        sys.exit(stop())
    elif cmd == "status":
        sys.exit(status())
    elif cmd == "query":
        if len(sys.argv) < 3:
            print("usage: thefuckd query JSON", file=sys.stderr)
            sys.exit(1)
        sys.exit(query(sys.argv[2]))
    else:
        print("thefuckd: unknown command '{}'".format(cmd), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
