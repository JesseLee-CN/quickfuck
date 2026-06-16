"""Configuration module for thefuck.

.. note::

    ``settings`` is a module-level global (module singleton pattern).
    This is an intentional design choice to avoid threading a
    configuration object through every function signature in the
    ~127 rule files. Tests should call ``settings.init(...)`` to
    configure, or monkey-patch ``conf.settings`` in test setup.
"""

from __future__ import annotations

import importlib.util


def _load_source(name: str, path: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

import os
import sys
import threading
from collections.abc import Iterator
from typing import Any
from warnings import warn
from . import const
from .system import Path


def _load_settings_from(settings_path: str) -> dict[str, Any]:
    """Loads and returns settings dict from settings.py.

    Cached with ``memoize`` below to avoid recompiling on every invocation.
    """
    settings = _load_source('settings', settings_path)
    return {key: getattr(settings, key)
            for key in const.DEFAULT_SETTINGS.keys()
            if hasattr(settings, key)}


class Settings(dict):
    def __init__(self, *args, **kwargs):
        # Bypass __setattr__ to avoid _lock not-yet-existing error
        dict.__setitem__(self, '_lock', threading.RLock())
        super().__init__(*args, **kwargs)

    def __getattr__(self, item: str) -> Any:
        return self.get(item)

    def __setattr__(self, key: str, value: Any) -> None:
        with self._lock:
            self[key] = value

    def update(self, *args, **kwargs) -> None:  # type: ignore[override]
        with self._lock:
            super().update(*args, **kwargs)

    def setdefault(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return super().setdefault(key, default)

    def init(self, args: Any = None) -> None:
        """Fills `settings` with values from `settings.py` and env."""
        with self._lock:
            from .logs import exception

            self._setup_user_dir()
            self._init_settings_file()

            try:
                self.update(self._settings_from_file())
            except Exception:
                exception("Can't load settings from file", sys.exc_info())

            try:
                self.update(self._settings_from_env())
            except Exception:
                exception("Can't load settings from env", sys.exc_info())

            self.update(self._settings_from_args(args))

    def _init_settings_file(self) -> None:
        settings_path = self.user_dir.joinpath('settings.py')
        if not settings_path.is_file():
            with settings_path.open(mode='w') as settings_file:
                settings_file.write(const.SETTINGS_HEADER)
                for setting in const.DEFAULT_SETTINGS.items():
                    settings_file.write(u'# {} = {}\n'.format(*setting))

    def _get_user_dir_path(self) -> Path:
        """Returns Path object representing the user config resource"""
        xdg_config_home = os.environ.get('XDG_CONFIG_HOME', '~/.config')
        user_dir = Path(xdg_config_home, 'thefuck').expanduser()
        legacy_user_dir = Path('~', '.thefuck').expanduser()

        # For backward compatibility use legacy '~/.thefuck' if it exists:
        if legacy_user_dir.is_dir():
            warn(u'Config path {} is deprecated. Please move to {}'.format(
                legacy_user_dir, user_dir))
            return legacy_user_dir
        else:
            return user_dir

    def _setup_user_dir(self) -> None:
        """Returns user config dir, create it when it doesn't exist."""
        user_dir = self._get_user_dir_path()

        rules_dir = user_dir.joinpath('rules')
        if not rules_dir.is_dir():
            rules_dir.mkdir(parents=True)
        self.user_dir = user_dir

    def _settings_from_file(self) -> dict[str, Any]:
        """Loads settings from file."""
        return _load_settings_from(str(self.user_dir.joinpath('settings.py')))

    def _rules_from_env(self, val: str) -> list[str]:
        """Transforms rules list from env-string to python."""
        val = val.split(':')
        if 'DEFAULT_RULES' in val:
            val = const.DEFAULT_RULES + [rule for rule in val if rule != 'DEFAULT_RULES']
        return val

    def _priority_from_env(self, val: str) -> Iterator[tuple[str, int]]:
        """Gets priority pairs from env."""
        for part in val.split(':'):
            try:
                rule, priority = part.split('=')
                yield rule, int(priority)
            except ValueError:
                continue

    def _val_from_env(self, env: str, attr: str) -> Any:
        """Transforms env-strings to python."""
        val = os.environ[env]
        if attr in ('rules', 'exclude_rules'):
            return self._rules_from_env(val)
        elif attr == 'priority':
            return dict(self._priority_from_env(val))
        elif attr in ('wait_command', 'history_limit', 'wait_slow_command',
                      'num_close_matches'):
            return int(val)
        elif attr in ('require_confirmation', 'no_colors', 'debug',
                      'alter_history', 'instant_mode'):
            return val.lower() == 'true'
        elif attr in ('slow_commands', 'excluded_search_path_prefixes'):
            return val.split(':')
        else:
            return val

    def _settings_from_env(self) -> dict[str, Any]:
        """Loads settings from env."""
        return {attr: self._val_from_env(env, attr)
                for env, attr in const.ENV_TO_ATTR.items()
                if env in os.environ}

    def _settings_from_args(self, args: Any) -> dict[str, Any]:
        """Loads settings from args."""
        if not args:
            return {}

        from_args = {}
        if args.yes:
            from_args['require_confirmation'] = not args.yes
        if args.debug:
            from_args['debug'] = args.debug
        if args.repeat:
            from_args['repeat'] = args.repeat
        return from_args


settings: Settings = Settings(const.DEFAULT_SETTINGS)

from functools import lru_cache  # noqa: E402
_load_settings_from = lru_cache(maxsize=1)(_load_settings_from)
