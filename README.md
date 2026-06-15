# The Fuck — Optimized for Python 3.12+ and WSL2

基于 [thefuck](https://github.com/nvbn/thefuck) v3.32 的优化版本，修复 Python 3.12 兼容性并大幅提升 WSL2 下的性能。

## 改动说明

### Python 3.12 兼容性
| 文件 | 问题 | 修复 |
|------|------|------|
| `thefuck/system/unix.py` | `distutils.spawn.find_executable` 在 3.12 中被移除 | 替换为 `shutil.which` |
| `thefuck/conf.py` | `imp.load_source` 在 3.12 中被移除 | 替换为 `importlib.util.spec_from_file_location` |
| `thefuck/types.py` | `imp.load_source` 在 3.12 中被移除 | 同上 |

### 性能优化
| 文件 | 优化 | 效果 |
|------|------|------|
| `thefuck/utils.py` | `which()`: 单次 PATH 扫描 + dict 缓存替代重复 `shutil.which()` 调用 | 消除 ~1943 次 stat() 调用（原 85% 耗时） |
| `thefuck/utils.py` | `get_all_executables()`: `os.scandir()` + PATH 去重 | 避免重复扫描，消除额外 stat |
| `thefuck/utils.py` | `_executable_cache` 线程安全锁（双检锁模式） | 防止并行规则加载时的竞态条件 |
| `thefuck/entrypoints/fix_command.py` | 规则加载与命令输出捕获并行化（`Thread`） | 两个最慢步骤并行执行 |
| `thefuck/corrector.py` | `ThreadPoolExecutor` 并行规则加载 + exec cache 预热 | 规则加载 ~2.1s → ~0.05s |

### WSL2 调优
| 文件 | 配置 | 目的 |
|------|------|------|
| `user-settings.py` | `excluded_search_path_prefixes = ['/mnt/']` | 跳过 Windows 挂载点的 PATH 扫描 |

## 性能数据 (WSL2)

| 阶段 | 优化前 | 优化后 |
|------|--------|--------|
| PATH 可执行文件扫描 | ~2.24s (1943 次 stat) | ~0.01s (单次 scandir) |
| 规则加载 | ~2.13s (顺序) | ~0.05s (并行 + 字节码缓存) |
| **总计** | **~2.64s** | **~0.25s** (~10x 提速) |

剩余 ~0.14s 为 WSL2 固有的 `fork+exec` 开销（重新执行失败命令以捕获输出）。

## 安装方法

### 方法 1：从本项目直接安装

```bash
# 克隆项目
git clone https://github.com/YOUR_USER/fuck.git ~/projects/fuck
cd ~/projects/fuck

# 方式 A：pipx 安装（推荐，隔离环境）
pipx install .

# 方式 B：pip 用户安装
pip install --user .

# 方式 C：开发模式安装（可修改源码即时生效）
pip install --user -e .
```

### 方法 2：替代已安装的 thefuck（覆盖 pipx 安装）

```bash
# 先通过 pipx 安装原始版本获取依赖
pipx install thefuck

# 然后用本项目源码覆盖
cp -r ~/projects/fuck/thefuck/* \
  ~/.local/share/pipx/venvs/thefuck/lib/python*/site-packages/thefuck/
```

### 安装后配置

```bash
# 1. 配置 shell 别名（必须）
echo 'eval "$(thefuck --alias)"' >> ~/.bashrc
source ~/.bashrc

# 2. 配置 WSL2 优化（跳过 Windows 挂载路径）
mkdir -p ~/.config/thefuck
cp user-settings.py ~/.config/thefuck/settings.py

# 3. 验证安装
fuck --version
```

## 依赖

- Python >= 3.7
- psutil
- colorama
- six
- decorator
- pyte

## License

MIT (同上游)
