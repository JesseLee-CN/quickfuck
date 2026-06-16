# quickfuck — Optimized for Python 3.12+ and WSL2

[中文文档](README_CN.md)

Based on [thefuck](https://github.com/nvbn/thefuck) v3.32 with Python 3.12 compatibility fixes,
~37x performance improvements for WSL2, structural refactoring, and a persistent daemon mode.

---

## What's Improved

### Python 3.12 Compatibility
| File | Issue | Fix |
|------|-------|-----|
| `thefuck/system/unix.py` | `distutils.spawn.find_executable` removed in 3.12 | Replaced with `shutil.which` |
| `thefuck/conf.py` | `imp.load_source` removed in 3.12 | Replaced with `importlib.util.spec_from_file_location` |
| `thefuck/types.py` | `imp.load_source` removed in 3.12 | Same as above |

### Performance Optimizations (13 items)
| Optimization | Location | Effect |
|-------------|----------|--------|
| Single-pass PATH scan + dict cache | `utils.py: which()` | Eliminates ~1943 stat() calls |
| Thread-safe double-checked locking | `cache.py` | Prevents race conditions |
| Parallel rule loading + output capture | `fix_command.py` + `corrector.py` | Two slowest steps run concurrently |
| Shell alias pre-captures output (`TF_LAST_OUTPUT`) | `shells/{bash,zsh,fish}.py` | Skips Popen re-execution (3.5x hot-path speedup) |
| **Persistent daemon mode (`thefuckd`)** | **`daemon.py`** | **Rules loaded once, responds in ~71ms** |
| Subprocess result caching | `fish.py`, `git_checkout.py` etc. | `@memoize` on subprocess helpers |
| Settings compilation cached | `conf.py` | `functools.lru_cache` |
| Lazy debug formatting | `logs.py` | `.format()` deferred until debug check |
| Wasted sorts removed | `corrector.py` | Removed unnecessary `sorted()` calls |
| Regex → `str.endswith` | `utils.py: replace_argument()` | No dynamic regex compilation |
| `split(' ', 1)` micro-optimizations | `shells/` | Single delimiter split |

### Bug Fixes (9 crash-level)
| Bug | File | Symptom |
|-----|------|---------|
| `brew_path_prefix` is `None` → `TypeError` | `brew_unknown_command.py`, `brew_install.py` | Crash when Homebrew not installed |
| `script_parts[2]` accessed with only 2 parts | `docker_not_command.py`, `git_fix_stash.py` | `IndexError` on short commands |
| `else` on `if` instead of `for` | `shell_logger.py: get_output()` | Only first command ever checked |
| `filename_index` uninitialized | `git_flag_after_filename.py` | `UnboundLocalError` with all-flag args |
| History commands hijacking fuzzy matches | `no_command.py` | `dcker`→`clear` instead of `docker` |
| `missing_space_before_subcommand` splits `print`→`pr int` | `missing_space_before_subcommand.py` | False positive on 2-char executables |
| Chinese locale errors not matched | `no_command.py`, shell aliases | `TF_LAST_OUTPUT` now uses `LC_ALL=C` |
| `chmod x` not corrected | *(new rule)* `chmod_missing_plus.py` | Missing rule added |
| C/Python function-call syntax in bash | *(new rule)* `function_call_syntax.py` | `printf("hello")`→`echo "hello"` |

### Structural Refactoring
| Change | Detail |
|--------|--------|
| `utils.py`: 386→218 lines | Extracted caching to `cache.py` (176 lines) |
| `logs.py`: 149→65 lines | Extracted UI rendering to `display.py` (94 lines) |
| Rules reorganized | 168 rules grouped into 34 domain subdirectories |
| Thread-safe `Settings` | `threading.RLock` on all mutation methods |
| Thread-safe `Cache` | `threading.Lock` protecting `_init_db()` |
| Cycle-free imports | `cache.py` independent of `logs`/`conf`/`utils` |
| `DEVNULL` fd leak fixed | Replaced with `subprocess.DEVNULL` |

## Project Structure

```
thefuck/
├── daemon.py             # Persistent daemon (thefuckd)
├── cache.py              # Memoization, persistent cache, state reset
├── conf.py               # Settings (thread-safe singleton)
├── const.py              # Constants & defaults
├── corrector.py          # Rule discovery & command correction engine
├── display.py            # Terminal UI rendering
├── exceptions.py         # Exception classes
├── logs.py               # Debug/warning/exception logging
├── types.py              # Domain models: Command, Rule, CorrectedCommand
├── ui.py                 # Interactive keyboard-driven command selector
├── utils.py              # PATH scanning, fuzzy matching, decorators, helpers
├── argument_parser.py
├── entrypoints/          # CLI entry points (main, fix_command, alias, etc.)
├── shells/               # Shell adapters (bash, zsh, fish, tcsh, powershell)
├── system/               # Platform abstraction (unix.py / win32.py)
├── output_readers/       # Command output capture strategies
├── specific/             # Tool-specific helpers (git, sudo, apt, brew, npm, ...)
├── rules/                # 168 correction rules in 34 domain directories
├── systemd/              # Systemd user service for auto-start
└── tests/                # Pytest test suite (109 tests)
```

## Benchmarks (WSL2)

| Mode | Latency | Notes |
|------|---------|-------|
| Original thefuck v3.32 | ~2640ms | Python 3.7, sequential |
| quickfuck (normal) | ~246ms | Popen + parallel rules |
| quickfuck + TF_LAST_OUTPUT | ~130ms | Shell alias pre-capture |
| **quickfuck + thefuckd daemon** | **~71ms** | **Rules pre-loaded, no Popen** |

**Total: ~37x faster than original, 109 tests passing.**

## Installation

```bash
# Clone
git clone https://github.com/JesseLee-CN/quickfuck.git ~/projects/fuck
cd ~/projects/fuck

# Install (recommended: pipx for isolated venv)
pipx install -e .

# Or: pip user install
pip install --user -e .

# Configure shell alias (MUST)
echo 'eval "$(thefuck --alias)"' >> ~/.bashrc
source ~/.bashrc

# WSL2 optimization (skip Windows mount points)
mkdir -p ~/.config/thefuck
cp user-settings.py ~/.config/thefuck/settings.py

# Verify
fuck --version
```

## Daemon Setup (sub-100ms mode)

```bash
# Option A: Auto-start on WSL login (add to ~/.bashrc)
thefuckd start &>/dev/null

# Option B: systemd user service (auto-start on boot, WSL2 with systemd)
mkdir -p ~/.config/systemd/user
cp systemd/thefuckd.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now thefuckd

# Verify
thefuckd status
# → thefuckd: running (pid 12345)
```

The daemon consumes ~26MB RAM and ~0% CPU when idle. The `thefuck` CLI
transparently detects and uses the daemon — no alias changes needed.

To disable the daemon temporarily: `TF_DAEMON_DISABLE=1 fuck`

## Dependencies

- Python >= 3.7
- psutil, colorama, pyte

## License

MIT (same as upstream)
