"""Corrects C/Python-style function calls mistakenly used in bash.

e.g. ``printf("hello")`` → ``echo "hello"``
     ``print("hello")``  → ``echo "hello"``
"""
import re
from thefuck.utils import get_close_matches, get_all_executables, which


# Commands that look like function calls but are really print statements
_PRINT_LIKE = {'printf', 'print', 'println', 'puts', 'echo', 'fmt.Print',
               'console.log', 'System.out.println', 'printfn'}

# Patterns for shell syntax errors caused by function-call syntax.
# dash/sh says "Syntax error: word unexpected"
# bash says "syntax error near unexpected token"
# Chinese locale: 语法错误 / 未预期的记号
_SYNTAX_ERROR_PATTERNS = (
    'syntax error',
    '语法错误',
    '未预期的记号',
)


def _extract_command_name(script: str) -> str | None:
    """Extract the command name from a function-call style script.

    e.g. ``printf("hello")`` → ``printf``
         ``print ("world")`` → ``print``
    """
    if '(' not in script:
        return None
    return script.split('(')[0].strip().split()[0] if script.split('(')[0].strip() else None


def _extract_args(script: str) -> str:
    """Extract the arguments from inside the parentheses."""
    match = re.search(r'\((.+)\)', script, re.DOTALL)
    if match:
        return match.group(1).strip()
    return ''


def match(command):
    # Must be a shell syntax error (guard against None output)
    if not command.output:
        return False
    output_lower = command.output.lower()
    if not any(p in output_lower for p in _SYNTAX_ERROR_PATTERNS):
        return False

    # Must look like a function call: contains ( and )
    # Check both the raw script and the first script part (shlex may absorb parens)
    script = command.script
    if '(' not in script or ')' not in script:
        return False

    cmd_name = _extract_command_name(command.script)
    if not cmd_name:
        return False

    # The command might be valid (e.g. printf exists at /usr/bin/printf)
    # but the function-call syntax (parentheses) is wrong in bash.
    # We match if there are alternatives worth suggesting.
    is_print_like = cmd_name in _PRINT_LIKE
    is_builtin = bool(which(cmd_name))

    if is_print_like:
        return True

    # For non-print commands that DO exist: suggest removing parentheses
    if is_builtin:
        return True

    # For non-existent commands: suggest closest executable matches
    return bool(get_close_matches(cmd_name, get_all_executables()))


def get_new_command(command):
    cmd_name = _extract_command_name(command.script)
    args = _extract_args(command.script)

    # For print-like commands, suggest echo
    if cmd_name in _PRINT_LIKE:
        if args:
            return ['echo ' + args]
        return ['echo']

    # For existing commands used with wrong syntax: remove parentheses
    if which(cmd_name):
        if args:
            return [cmd_name + ' ' + args]
        return [cmd_name]

    # For non-existent commands: find the closest match
    matches = get_close_matches(cmd_name, get_all_executables())
    if matches:
        if args:
            return [matches[0] + ' ' + args]
        return [matches[0]]

    # Fallback: remove parentheses
    if args:
        return [cmd_name + ' ' + args]
    return [cmd_name]


priority = 2900  # Higher than no_command (3000), so syntax errors are caught first
