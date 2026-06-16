from thefuck.cache import memoize
from thefuck.utils import get_all_executables


@memoize
def _get_executable(script_part):
    for executable in get_all_executables():
        # Require executable to be at least 3 chars to avoid false positives
        # like splitting 'print' into 'pr' + 'int' (pr is a valid command)
        if len(executable) >= 3 and script_part.startswith(executable):
            suffix = script_part[len(executable):]
            # Require the remaining suffix to be at least 2 lowercase letters
            # so we don't split single chars or random suffixes
            if len(suffix) >= 2 and suffix.isalpha() and suffix.islower():
                return executable
    return None


def match(command):
    return (not command.script_parts[0] in get_all_executables()
            and _get_executable(command.script_parts[0]))


def get_new_command(command):
    executable = _get_executable(command.script_parts[0])
    return command.script.replace(executable, u'{} '.format(executable), 1)


priority = 4000
