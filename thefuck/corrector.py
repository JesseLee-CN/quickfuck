from __future__ import annotations
import os
import sys
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING
from .conf import settings
from .types import Command, CorrectedCommand, Rule
from .system import Path
from . import logs

if TYPE_CHECKING:
    from .system import Path
    from .types import Command, CorrectedCommand, Rule


def get_loaded_rules(rules_paths: list[Path]) -> list[Rule]:
    """Returns all available rules.

    :type rules_paths: [Path]
    :rtype: [Rule]

    """
    # Pre-warm the executable cache in a single thread to avoid
    # race conditions when multiple threads call which() concurrently.
    from .utils import which
    which('')

    paths = [p for p in rules_paths if p.name != '__init__.py']
    max_workers = min(32, (os.cpu_count() or 1) + 4)
    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_path = {
            executor.submit(Rule.from_path, path): path
            for path in paths}
        for future in as_completed(future_to_path):
            try:
                rule = future.result()
                if rule and rule.is_enabled:
                    results.append(rule)
            except Exception as e:
                logs.debug(u'Error loading rule from {}: {}'.format(
                    future_to_path[future], e))
    return results


def get_rules_import_paths() -> Iterable[Path]:
    """Yields all rules import paths.

    :rtype: Iterable[Path]

    """
    # Bundled rules:
    yield Path(__file__).parent.joinpath('rules')
    # Rules defined by user:
    yield settings.user_dir.joinpath('rules')
    # Packages with third-party rules:
    for path in sys.path:
        for contrib_module in Path(path).glob('thefuck_contrib_*'):
            contrib_rules = contrib_module.joinpath('rules')
            if contrib_rules.is_dir():
                yield contrib_rules


def get_rules() -> list[Rule]:
    """Returns all enabled rules.

    :rtype: [Rule]

    """
    paths = [rule_path for path in get_rules_import_paths()
             for rule_path in path.glob('*.py')]
    return sorted(get_loaded_rules(paths),
                  key=lambda rule: rule.priority)


def organize_commands(corrected_commands: Iterable[CorrectedCommand]) -> Iterable[CorrectedCommand]:
    """Yields sorted commands without duplicates.

    :type corrected_commands: Iterable[thefuck.types.CorrectedCommand]
    :rtype: Iterable[thefuck.types.CorrectedCommand]

    """
    try:
        first_command = next(corrected_commands)
        yield first_command
    except StopIteration:
        return

    without_duplicates = {
        command for command in corrected_commands
        if command != first_command}

    sorted_commands = sorted(
        without_duplicates,
        key=lambda corrected_command: corrected_command.priority)

    logs.debug(u'Corrected commands: {}',
               ', '.join(u'{}'.format(cmd) for cmd in [first_command] + sorted_commands))

    for command in sorted_commands:
        yield command


def get_corrected_commands(command: Command) -> Iterable[CorrectedCommand]:
    """Returns generator with sorted and unique corrected commands.

    :type command: thefuck.types.Command
    :rtype: Iterable[thefuck.types.CorrectedCommand]

    """
    corrected_commands = (
        corrected for rule in get_rules()
        if rule.is_match(command)
        for corrected in rule.get_corrected_commands(command))
    return organize_commands(corrected_commands)
