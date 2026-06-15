# The Fuck — Optimized for Python 3.12+ and WSL2

This is a patched version of [thefuck](https://github.com/nvbn/thefuck) v3.32 with performance optimizations and Python 3.12 compatibility fixes.

## Fixes Applied

### Python 3.12 Compatibility
| File | Issue | Fix |
|------|-------|-----|
| `thefuck/system/unix.py` | `distutils.spawn.find_executable` removed in 3.12 | Replaced with `shutil.which` |
| `thefuck/conf.py` | `imp.load_source` removed in 3.12 | Replaced with `importlib.util.spec_from_file_location` |
| `thefuck/types.py` | `imp.load_source` removed in 3.12 | Same as above |

### Performance Optimizations
| File | Optimization | Impact |
|------|-------------|--------|
| `thefuck/utils.py` | `which()`: single PATH scan + dict cache instead of repeated `shutil.which()` calls | Eliminated ~1943 stat() calls (85% of runtime) |
| `thefuck/utils.py` | `get_all_executables()`: `os.scandir()` + PATH dedup | No extra stat per file; avoid duplicate scans |
| `thefuck/utils.py` | Thread-safe `_executable_cache` with double-checked locking | Prevent race conditions in parallel rule loading |
| `thefuck/entrypoints/fix_command.py` | Rule loading ∥ command output capture via `Thread` | Parallelized the two slowest sequential steps |
| `thefuck/corrector.py` | Parallel rule loading via `ThreadPoolExecutor` + exec cache pre-warming | Rule loading ~2.1s → ~0.05s |

### WSL2 Tuning
| File | Configuration | Purpose |
|------|--------------|---------|
| `user-settings.py` | `excluded_search_path_prefixes = ['/mnt/']` | Skip Windows mount points in PATH scanning |

## Performance Results (WSL2)

| Phase | Before | After |
|-------|--------|-------|
| PATH executable scanning | ~2.24s (1943 stat calls) | ~0.01s (single scandir pass) |
| Rule loading | ~2.13s (sequential) | ~0.05s (parallel + bytecode cached) |
| **Total** | **~2.64s** | **~0.25s** (~10x speedup) |

Remaining ~0.14s is inherent WSL2 `fork+exec` overhead for command output capture.

## Installation

```bash
pipx install --force --python python3.12 thefuck
# Then apply patches from this repo
```

## License

MIT (same as upstream)
