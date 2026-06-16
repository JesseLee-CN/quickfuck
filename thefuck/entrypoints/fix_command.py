from pprint import pformat
import os
import sys
from difflib import SequenceMatcher
from threading import Thread
from .. import logs, types, const
from ..conf import settings
from ..corrector import get_rules, organize_commands
from ..exceptions import EmptyCommand
from ..ui import select_command
from ..utils import get_alias, get_all_executables


def _get_raw_command(known_args):
    if known_args.force_command:
        return [known_args.force_command]
    elif not os.environ.get('TF_HISTORY'):
        return known_args.command
    else:
        history = os.environ['TF_HISTORY'].split('\n')[::-1]
        alias = get_alias()
        executables = get_all_executables()
        for command in history:
            diff = SequenceMatcher(a=alias, b=command).ratio()
            if diff < const.DIFF_WITH_ALIAS or command in executables:
                return [command]
    return []


def _try_daemon(script: str, output: str | None) -> str | None:
    """Try to get a correction from a running thefuckd daemon.

    Returns the corrected script, or ``None`` if the daemon is not
    available / returned no correction.
    """
    try:
        from ..daemon import SOCKET_PATH, BUFSIZE
        import json
        import socket
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(0.3)
        sock.connect(SOCKET_PATH)
        req = json.dumps({"script": script, "output": output or ""})
        sock.sendall(req.encode("utf-8"))
        data = b""
        while True:
            chunk = sock.recv(BUFSIZE)
            if not chunk:
                break
            data += chunk
            if len(chunk) < BUFSIZE:
                break
        sock.close()
        resp = json.loads(data.decode("utf-8"))
        return resp.get("correction")
    except Exception:
        return None


def fix_command(known_args):
    """Fixes previous command. Used when `thefuck` called without arguments."""
    settings.init(known_args)
    with logs.debug_time('Total'):
        logs.debug(u'Run with settings: {}'.format(pformat(settings)))
        raw_command = _get_raw_command(known_args)

        # ── daemon fast-path (skip Popen + rule loading entirely) ──
        pre_output = os.environ.get('TF_LAST_OUTPUT')
        if (pre_output is not None
                and raw_command
                and os.environ.get('TF_DAEMON_DISABLE', '').lower() not in ('1', 'true')):
            from ..utils import format_raw_script
            script = format_raw_script(raw_command)
            if script:
                correction = _try_daemon(script, pre_output)
                if correction:
                    from ..shells import shell
                    from ..types import CorrectedCommand
                    cmd = CorrectedCommand(
                        script=correction, side_effect=None, priority=0)
                    cmd.run(None)  # No old_cmd needed when just printing
                    return

        # ── normal (fully local) path ─────────────────────────────
        try:
            command = types.Command.from_raw_script(raw_command)
        except EmptyCommand:
            logs.debug('Empty command, nothing to do')
            return

        # Also try daemon with the captured output (slower path
        # because from_raw_script already did Popen, but still
        # saves rule loading time)
        if os.environ.get('TF_DAEMON_DISABLE', '').lower() not in ('1', 'true'):
            correction = _try_daemon(command.script, command.output)
            if correction:
                from ..types import CorrectedCommand
                cmd = CorrectedCommand(
                    script=correction, side_effect=None, priority=0)
                cmd.run(command)
                return

        # Pre-load rules in background while capturing command output
        rules_result = []
        rules_thread = Thread(target=lambda: rules_result.extend(get_rules()))
        rules_thread.start()

        rules_thread.join()
        rules = rules_result

        corrected_commands = (
            corrected for rule in rules
            if rule.is_match(command)
            for corrected in rule.get_corrected_commands(command))
        selected_command = select_command(
            organize_commands(corrected_commands))

        if selected_command:
            selected_command.run(command)
        else:
            sys.exit(1)
