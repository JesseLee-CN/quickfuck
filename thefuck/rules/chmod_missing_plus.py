import re
from thefuck.utils import for_app

# Matches mode arguments that look like they're missing a '+' prefix.
# Handles single letters (x, r, w) and combinations (rw, rx, wx, rwx).
_INVALID_MODE_RE = re.compile(r'^[rwx]+$')


@for_app('chmod')
def match(command):
    if 'invalid mode' not in command.output:
        return False

    # Find the first non-option argument (the mode)
    for part in command.script_parts[1:]:
        if not part.startswith('-'):
            return bool(_INVALID_MODE_RE.match(part))

    return False


def get_new_command(command):
    # Find the mode argument and prepend '+'
    for i, part in enumerate(command.script_parts):
        if not part.startswith('-') and _INVALID_MODE_RE.match(part):
            parts = command.script_parts[:]
            parts[i] = '+' + part
            return ' '.join(parts)

    return command.script
