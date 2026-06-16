from thefuck.utils import get_all_executables, get_close_matches, \
    get_valid_history_without_current, get_closest, which
from thefuck.specific.sudo import sudo_support
from difflib import SequenceMatcher


def _match_score(word: str, candidate: str) -> float:
    """Score a candidate match factoring in similarity and length.

    Pure difflib ratio can prefer longer words that contain the typo as a
    substring (e.g. ``eject`` over ``cat`` for ``ect``).  A small length
    penalty nudges toward candidates of similar length.
    """
    ratio = SequenceMatcher(None, word, candidate).ratio()
    length_penalty = abs(len(word) - len(candidate)) * 0.05
    return ratio - length_penalty


@sudo_support
def match(command):
    return (not which(command.script_parts[0])
            and ('not found' in command.output
                 or 'is not recognized as' in command.output)
            and bool(get_close_matches(command.script_parts[0],
                                       get_all_executables())))


def _get_used_executables(command):
    for script in get_valid_history_without_current(command):
        yield script.split(' ')[0]


@sudo_support
def get_new_command(command):
    old_command = command.script_parts[0]

    # Executable matches:
    executable_matches = get_close_matches(old_command, get_all_executables())

    # History match (may be None):
    already_used = get_closest(
        old_command, _get_used_executables(command),
        fallback_to_first=False)

    # Collect all candidates, score, and sort by combined score:
    candidates = list(executable_matches)
    if already_used and already_used not in candidates:
        candidates.append(already_used)

    candidates.sort(key=lambda c: _match_score(old_command, c), reverse=True)

    return [' '.join([new_cmd] + command.script_parts[1:])
            for new_cmd in candidates]


priority = 3000
