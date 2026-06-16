from __future__ import annotations
import atexit
import os
import pickle
import re
import shelve
import sys
import subprocess
import threading
from collections.abc import Callable, Iterable, Iterator
from difflib import get_close_matches as difflib_get_close_matches
from functools import wraps
from typing import Any, TYPE_CHECKING
from .logs import warn, exception
from .conf import settings
from .system import Path
if TYPE_CHECKING:
    from .types import Command

DEVNULL = subprocess.DEVNULL

import dbm
shelve_open_error = dbm.error


def memoize(fn: Callable) -> Callable:
    """Caches previous calls to the function."""
    memo = {}

    @wraps(fn)
    def wrapper(*args, **kwargs) -> Any:
        if not memoize.disabled:
            key = pickle.dumps((args, kwargs))
            if key not in memo:
                memo[key] = fn(*args, **kwargs)
            value = memo[key]
        else:
            # Memoize is disabled, call the function
            value = fn(*args, **kwargs)

        return value

    return wrapper


memoize.disabled = False


_executable_cache = None
_executable_cache_lock = threading.Lock()


def _build_executable_cache():
    """Build a {name: path} cache of all executables found in PATH."""
    global _executable_cache
    _executable_cache = {}
    paths = list(dict.fromkeys(os.environ.get('PATH', '').split(os.pathsep)))
    for path in paths:
        if not include_path_in_search(path):
            continue
        try:
            with os.scandir(path) as entries:
                for entry in entries:
                    if not entry.is_dir() and entry.name not in _executable_cache:
                        _executable_cache[entry.name] = os.path.join(path, entry.name)
        except OSError:
            pass


def which(program: str) -> str | None:
    """Returns the full path to `program` or `None`."""
    global _executable_cache
    if _executable_cache is None:
        with _executable_cache_lock:
            # Double-checked locking: another thread might have built
            # the cache while we were waiting for the lock.
            if _executable_cache is None:
                _build_executable_cache()
    return _executable_cache.get(program)


def default_settings(params: dict) -> Callable:
    """Adds default values to settings if it not presented.

    Usage:

        @default_settings({'apt': '/usr/bin/apt'})
        def match(command):
            print(settings.apt)

    """
    def _default_settings(fn):
        @wraps(fn)
        def wrapper(command, *args, **kwargs):
            for k, w in params.items():
                settings.setdefault(k, w)
            return fn(command, *args, **kwargs)
        return wrapper
    return _default_settings


def get_closest(word: str, possibilities: Iterable[str], cutoff: float = 0.6, fallback_to_first: bool = True) -> str | None:
    """Returns closest match or just first from possibilities."""
    possibilities = list(possibilities)
    try:
        return difflib_get_close_matches(word, possibilities, 1, cutoff)[0]
    except IndexError:
        if fallback_to_first:
            return possibilities[0]


def get_close_matches(word: str, possibilities: Iterable[str], n: int | None = None, cutoff: float = 0.6) -> list[str]:
    """Overrides `difflib.get_close_match` to control argument `n`."""
    if n is None:
        n = settings.num_close_matches
    return difflib_get_close_matches(word, possibilities, n, cutoff)


def include_path_in_search(path: str) -> bool:
    return not any(path.startswith(x) for x in settings.excluded_search_path_prefixes)


@memoize
def get_all_executables() -> list[str]:
    """Returns list of all available executables and aliases."""
    if _executable_cache is None:
        with _executable_cache_lock:
            if _executable_cache is None:
                _build_executable_cache()
    from thefuck.shells import shell
    tf_alias = get_alias()
    tf_entry_points = ['thefuck', 'fuck']
    aliases = [alias for alias in shell.get_aliases() if alias != tf_alias]
    return [name for name in _executable_cache
            if name not in tf_entry_points] + aliases


def replace_argument(script: str, from_: str, to: str) -> str:
    """Replaces command line argument."""
    if script.endswith(' ' + from_):
        return script[:-len(from_)] + to
    else:
        return script.replace(
            u' {} '.format(from_), u' {} '.format(to), 1)


def eager(fn: Callable) -> Callable:
    """Converts a generator-returning function into a list-returning function."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        return list(fn(*args, **kwargs))
    return wrapper


@eager
def get_all_matched_commands(stderr: str, separator: str | list[str] = 'Did you mean') -> list[str]:
    if not isinstance(separator, list):
        separator = [separator]
    should_yield = False
    for line in stderr.split('\n'):
        for sep in separator:
            if sep in line:
                should_yield = True
                break
        else:
            if should_yield and line:
                yield line.strip()


def replace_command(command: Command, broken: str, matched: list[str]) -> list[str]:
    """Helper for *_no_command rules."""
    new_cmds = get_close_matches(broken, matched, cutoff=0.1)
    return [replace_argument(command.script, broken, new_cmd.strip())
            for new_cmd in new_cmds]


@memoize
def is_app(command: Command, *app_names: str, **kwargs: Any) -> bool:
    """Returns `True` if command is call to one of passed app names."""

    at_least = kwargs.pop('at_least', 0)
    if kwargs:
        raise TypeError("got an unexpected keyword argument '{}'".format(kwargs.keys()))

    if len(command.script_parts) > at_least:
        return os.path.basename(command.script_parts[0]) in app_names

    return False


def for_app(*app_names: str, **kwargs: Any) -> Callable:
    """Specifies that matching script is for one of app names."""
    def _for_app(fn):
        @wraps(fn)
        def wrapper(command, *args, **kwargs_inner):
            if is_app(command, *app_names, **kwargs):
                return fn(command, *args, **kwargs_inner)
            else:
                return False
        return wrapper
    return _for_app


class Cache(object):
    """Lazy read cache and save changes at exit."""

    def __init__(self) -> None:
        self._db: Any = None
        self._lock = threading.Lock()

    def _init_db(self) -> None:
        with self._lock:
            if self._db is not None:
                return
            try:
                self._setup_db()
            except Exception:
                exception("Unable to init cache", sys.exc_info())
                self._db = {}

    def _setup_db(self) -> None:
        cache_dir = self._get_cache_dir()
        cache_path = Path(cache_dir).joinpath('thefuck').as_posix()

        try:
            self._db = shelve.open(cache_path)
        except shelve_open_error + (ImportError,):
            # Caused when switching between Python versions
            warn("Removing possibly out-dated cache")
            os.remove(cache_path)
            self._db = shelve.open(cache_path)

        atexit.register(self._db.close)

    def _get_cache_dir(self) -> str:
        default_xdg_cache_dir = os.path.expanduser("~/.cache")
        cache_dir = os.getenv("XDG_CACHE_HOME", default_xdg_cache_dir)

        # Ensure the cache_path exists, Python 2 does not have the exist_ok
        # parameter
        try:
            os.makedirs(cache_dir)
        except OSError:
            if not os.path.isdir(cache_dir):
                raise

        return cache_dir

    def _get_mtime(self, path: str) -> str:
        try:
            return str(os.path.getmtime(path))
        except OSError:
            return '0'

    def _get_key(self, fn: Callable, depends_on: list[str], args: tuple, kwargs: dict) -> str:
        parts = (fn.__module__, repr(fn).split('at')[0],
                 depends_on, args, kwargs)
        return str(pickle.dumps(parts))

    def get_value(self, fn: Callable, depends_on: list[str], args: tuple, kwargs: dict) -> Any:
        if self._db is None:
            self._init_db()

        depends_on = [Path(name).expanduser().absolute().as_posix()
                      for name in depends_on]
        key = self._get_key(fn, depends_on, args, kwargs)
        etag = '.'.join(self._get_mtime(path) for path in depends_on)

        if self._db.get(key, {}).get('etag') == etag:
            return self._db[key]['value']
        else:
            value = fn(*args, **kwargs)
            self._db[key] = {'etag': etag, 'value': value}
            return value


_cache = Cache()


def cache(*depends_on: str) -> Callable:
    """Caches function result in temporary file.

    Cache will be expired when modification date of files from `depends_on`
    will be changed.

    Only functions should be wrapped in `cache`, not methods.

    """
    def cache_decorator(fn):
        @memoize
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if cache.disabled:
                return fn(*args, **kwargs)
            else:
                return _cache.get_value(fn, depends_on, args, kwargs)

        return wrapper

    return cache_decorator


cache.disabled = False


@memoize
def get_installation_version() -> str:
    try:
        from importlib.metadata import version

        return version('thefuck')
    except ImportError:
        import pkg_resources

        return pkg_resources.require('thefuck')[0].version


def get_alias() -> str:
    return os.environ.get('TF_ALIAS', 'fuck')


@memoize
def get_valid_history_without_current(command: Command) -> list[str]:
    def _not_corrected(history, tf_alias):
        """Returns all lines from history except that comes before `fuck`."""
        previous = None
        for line in history:
            if previous is not None and line != tf_alias:
                yield previous
            previous = line
        if history:
            yield history[-1]

    from thefuck.shells import shell
    history = shell.get_history()
    tf_alias = get_alias()
    executables = set(get_all_executables())\
        .union(shell.get_builtin_commands())

    return [line for line in _not_corrected(history, tf_alias)
            if not line.startswith(tf_alias) and not line == command.script
            and line.split(' ')[0] in executables]


def format_raw_script(raw_script: list[str]) -> str:
    """Creates single script from a list of script parts.

    :type raw_script: [basestring]
    :rtype: basestring

    """
    script = ' '.join(raw_script)
    return script


import contextlib  # noqa: E402


@contextlib.contextmanager
def disable_memoize() -> Iterator[None]:
    """Context manager to temporarily disable memoization (for testing)."""
    previous = memoize.disabled
    memoize.disabled = True
    try:
        yield
    finally:
        memoize.disabled = previous


@contextlib.contextmanager
def disable_cache() -> Iterator[None]:
    """Context manager to temporarily disable persistent cache (for testing)."""
    previous = cache.disabled
    cache.disabled = True
    try:
        yield
    finally:
        cache.disabled = previous


def reset_state() -> None:
    """Reset all module-level state. Intended for testing."""
    global _executable_cache
    _executable_cache = None
    memoize.disabled = False
    cache.disabled = False
