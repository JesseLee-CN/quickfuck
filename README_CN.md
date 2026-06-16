# quickfuck — Python 3.12+ 和 WSL2 深度优化版

[English](README.md)

基于 [thefuck](https://github.com/nvbn/thefuck) v3.32，修复 Python 3.12 兼容性，
WSL2 下性能提升约 37 倍，完成结构化重构，并支持常驻后台 daemon 模式。

---

## 改进总览

### Python 3.12 兼容性
| 文件 | 问题 | 修复 |
|------|------|------|
| `thefuck/system/unix.py` | `distutils.spawn.find_executable` 在 3.12 中移除 | 替换为 `shutil.which` |
| `thefuck/conf.py` | `imp.load_source` 在 3.12 中移除 | 替换为 `importlib.util.spec_from_file_location` |
| `thefuck/types.py` | 同上 | 同上 |

### 性能优化（13 项）
| 优化 | 位置 | 效果 |
|------|------|------|
| 单次 PATH 扫描 + dict 缓存 | `utils.py: which()` | 消除 ~1943 次 stat() 调用 |
| 线程安全双检锁 | `cache.py` | 防止并行规则加载时的竞态条件 |
| 规则加载与输出捕获并行 | `fix_command.py` + `corrector.py` | Thread + ThreadPoolExecutor 并行 |
| Shell alias 预捕获输出 | `shells/{bash,zsh,fish}.py` | `TF_LAST_OUTPUT` 跳过 Python Popen 重执行 |
| **常驻后台 daemon (`thefuckd`)** | **`daemon.py`** | **规则预加载，单次响应 ~71ms** |
| 子进程结果缓存 | `fish.py`, `git_checkout.py` 等 4 处 | `@memoize` 避免重复 subprocess |
| 用户配置编译缓存 | `conf.py` | `functools.lru_cache` |
| 惰性 debug 格式化 | `logs.py` | debug 关闭时不执行 `.format()` |
| 消除无效排序 | `corrector.py` | 移除被 set 构造丢弃的 `sorted()` |
| 正则 → `str.endswith` | `utils.py: replace_argument()` | 消除动态正则编译 |
| `split(' ', 1)` 微优化 | `shells/` | 只切分第一个空格 |

### Bug 修复（9 个崩溃级）
| Bug | 文件 | 症状 |
|-----|------|------|
| `brew_path_prefix` 为 `None` → `TypeError` | `brew_unknown_command.py`, `brew_install.py` | Homebrew 未安装时崩溃 |
| `script_parts[2]` 仅 2 个元素时访问 | `docker_not_command.py`, `git_fix_stash.py` | 短命令触发 `IndexError` |
| `else` 错挂在 `if` 而非 `for` | `shell_logger.py: get_output()` | 只检查第一条命令即返回 |
| `filename_index` 未初始化 | `git_flag_after_filename.py` | 全 flag 参数时 `UnboundLocalError` |
| 历史命令劫持模糊匹配 | `no_command.py` | `dcker`→`clear` 而非 `docker` |
| `missing_space_before_subcommand` 误拆 `print` | `missing_space_before_subcommand.py` | `print`→`pr int` 误判 |
| 中文 locale 错误不匹配 | `no_command.py`, shell alias | `TF_LAST_OUTPUT` 加 `LC_ALL=C` |
| `chmod x` 无法纠正 | *(新规则)* `chmod_missing_plus.py` | 新增规则 |
| C/Python 函数调用语法 | *(新规则)* `function_call_syntax.py` | `printf("hello")`→`echo "hello"` |

### 工程重构
| 变更 | 详情 |
|------|------|
| `utils.py`: 386→218 行 | 拆分出 `cache.py`（176 行），打破循环导入 |
| `logs.py`: 149→65 行 | 拆分出 `display.py`（94 行），UI 渲染独立 |
| 规则重组 | 168 个规则按 34 个领域分目录 |
| `Settings` 线程安全 | 所有写操作加 `threading.RLock` |
| `Cache` 线程安全 | `_init_db()` 加锁保护 |
| 循环导入消除 | `cache.py` 不依赖 `logs`/`conf`/`utils` |
| `DEVNULL` fd 泄露修复 | 替换为 `subprocess.DEVNULL` |

## 项目结构

```
thefuck/
├── daemon.py             # 常驻后台 daemon（thefuckd）
├── cache.py              # 缓存系统（memoize, Cache, reset_state）
├── conf.py               # 配置（线程安全单例）
├── const.py              # 常量与默认值
├── corrector.py          # 规则发现与命令修正引擎
├── display.py            # 终端 UI 渲染
├── exceptions.py         # 异常类
├── logs.py               # 日志系统
├── types.py              # 领域模型
├── ui.py                 # 交互式键盘选择器
├── utils.py              # PATH 扫描、模糊匹配、装饰器、辅助函数
├── entrypoints/          # CLI 入口（5 个文件）
├── shells/               # Shell 适配器（6 种 shell）
├── system/               # 平台抽象（unix / win32）
├── output_readers/       # 输出捕获策略（3 种）
├── specific/             # 工具特定辅助（11 个模块）
├── rules/                # 168 条修正规则（34 个子目录）
├── systemd/              # systemd 用户服务（开机自启）
└── tests/                # Pytest 测试套件（109 个测试）
```

## 性能数据 (WSL2)

| 模式 | 延迟 | 说明 |
|------|------|------|
| 原始 thefuck v3.32 | ~2640ms | Python 3.7，顺序加载 |
| quickfuck（正常） | ~246ms | Popen + 并行规则 |
| quickfuck + TF_LAST_OUTPUT | ~130ms | Shell alias 预捕获输出 |
| **quickfuck + thefuckd daemon** | **~71ms** | **规则预加载，跳过 Popen** |

**累计提速约 37 倍，109 个测试全部通过。**

## 安装方法

```bash
# 克隆项目
git clone https://github.com/JesseLee-CN/quickfuck.git ~/projects/fuck
cd ~/projects/fuck

# 安装（推荐 pipx，隔离虚拟环境）
pipx install -e .

# 或 pip 用户安装
pip install --user -e .

# 配置 shell 别名（必须）
echo 'eval "$(thefuck --alias)"' >> ~/.bashrc
source ~/.bashrc

# WSL2 优化（跳过 Windows 挂载路径）
mkdir -p ~/.config/thefuck
cp user-settings.py ~/.config/thefuck/settings.py

# 验证
fuck --version
```

## Daemon 配置（百毫秒内极速模式）

```bash
# 方式 A：登录时自动启动（加入 ~/.bashrc）
thefuckd start &>/dev/null

# 方式 B：systemd 用户服务（WSL2 开机自启，需 systemd）
mkdir -p ~/.config/systemd/user
cp systemd/thefuckd.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now thefuckd

# 验证
thefuckd status
# → thefuckd: running (pid 12345)
```

Daemon 空闲时占用约 26MB 内存，CPU 接近 0%。`thefuck` 命令会自动检测并使用
daemon，无需修改 alias。

临时禁用 daemon：`TF_DAEMON_DISABLE=1 fuck`

## 依赖

- Python >= 3.7
- psutil, colorama, pyte

## License

MIT（同上游）
