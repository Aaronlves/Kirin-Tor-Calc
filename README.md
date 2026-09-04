# Kirin Tor

Kirin Tor 是一个面向攻略与理论计算作者的本地结构化数学工作台。它把数据、公式、假设、参数方案和有界动态过程写进可审查的 `.kirin` 源码，再从同一份源码生成结果、图表、解释和可重放记录。

Kirin Tor 不内置任何游戏、职业或技能数据，也不会从自然语言规则自动补全模型。作者负责事实和假设；Kirin Tor 负责校验并计算明确写下来的模型。

## 安装

Kirin Tor 支持 Python 3.12 或更新版本。推荐使用 [`uv`](https://docs.astral.sh/uv/getting-started/installation/)；它会维护独立环境，不需要手动激活虚拟环境。

Windows 推荐通过 WinGet 安装 `uv`：

```powershell
winget install --id=astral-sh.uv -e
```

macOS 和 Linux 请按 [`uv` 官方说明](https://docs.astral.sh/uv/getting-started/installation/)安装。`uv` 可用后，安装 Kirin Tor，并把工具目录加入 shell 的 `PATH`：

```bash
uv tool install kirin-tor-cli
uv tool update-shell
```

完全退出并重新打开终端，然后验证：

```bash
kt version
```

如果 Windows 提示无法识别 `kt`，再次运行 `uv tool update-shell`，退出所有 PowerShell、Windows Terminal 和 VS Code 终端后重试；必要时注销或重启 Windows。诊断命令是：

```powershell
uv tool list
uv tool dir --bin
where.exe kt
```

不需要为了重新运行 `kt` 而反复执行 `uv` 的在线安装脚本。

### 升级与卸载

`kt web` 当前不会自动更新。升级和卸载由 `uv` 管理：

```bash
uv tool upgrade kirin-tor-cli
uv tool uninstall kirin-tor-cli
```

也可以从 [GitHub Releases](https://github.com/Aaronlves/Kirin-Tor-Calc/releases) 下载 wheel，安装到自行管理的 Python 环境。

## 五分钟开始

创建工作区并启动浏览器工作台：

```bash
kt init my-math
cd my-math
kt web
```

`kt web` 会启动只监听本机回环地址的服务，并自动打开默认浏览器。保持终端进程运行；按 `Ctrl+C` 停止工作台。

Kirin Tor 会记住最近使用的工作区。运行中的浏览器工作台可以从“设置 → 当前工作区”
直接打开另一个已有工作区；有未保存草稿时会先明确保留到原工作区的恢复缓存。
也可以在启动前使用：

```bash
kt web --choose
```

空工作区会直接提供新建文档、语法参考和 Agent 协作入口；新文档先成为未保存草稿，只有执行“保存全部”才会写入工作区。

## `.kirin` 源码

工作区中唯一可编辑的计算权威是 `entries/**/*.kirin`。浏览器里的结果、图表、公式解释、诊断、关系图和索引都是源码的派生投影，不会形成第二套计算定义。预览区可以对结果依赖的输入做仅存于当前会话的临时试算；只有显式生成 preset 草稿并保存，才会改变权威源码。

一份最小模型如下：

```text
@kirin 2
@entry basic_model "基础公式"

input unit_price "单价": number[dimensionless] = 12 in 0..*
input quantity "数量": number[dimensionless] = 5 in 0..100 integer
input discount "折扣": probability = 10%

field subtotal "小计": dimensionless = unit_price * quantity
output total "折后总价": dimensionless = subtotal * (1 - discount)
display total = number digits 2
```

保存为 `entries/basic_model.kirin` 后，可以从工作台查看结果，也可以使用 CLI：

```bash
kt check
kt eval basic_model.total
```

结果是精确值 `54`。十进制会先转换为精确有理数，而不是直接进入二进制浮点计算。

## 工作台与 CLI

浏览器工作台提供源码编辑、补全、诊断、原子保存、结果试算、多图排列与导出、公式解释、关系导航、外部修改检测和有界 Process Analysis。Agent 或其他本地编辑器可以直接修改 `.kirin` 文件；也可以通过 `kt mcp WORKSPACE` 使用只暴露资源、校验、解释、静态求值、有界 Process Analysis 和单文件校验写入的薄 MCP。工作台会重新加载没有未保存草稿的文档，并在发生并发修改时保留冲突供作者处理。

CLI 与工作台使用同一个工作区、解析器和计算服务。常用入口是：

```bash
kt web
kt mcp /absolute/path/to/workspace
kt check
kt eval ENTRY.OUTPUT
kt analyze ENTRY.ANALYSIS
kt --help
```

完整命令及参数以 `kt COMMAND --help` 为准。

## 能力边界

Kirin Tor 支持精确数值、用户声明的量纲和单位、参数方案、查表、有限分布、符号计算、扫描与图表，以及作者明确声明并受边界约束的 Process 场景和分析。

它不是完整战斗模拟器：没有内置游戏语义，不会从技能说明推导事件顺序、优先级 APL、Boss 时间线或目标函数，也不会把未证明的有限搜索称为全局最优。完整范围见[游戏机制计算能力边界](docs/game-mechanics-capability-audit.md)。

## 文档

- [Kirin Tor source syntax v2](docs/kirin-syntax.md)：源码语法与示例。
- [结构模型、表达式与安全边界](docs/schema-and-expressions.md)：数学语义、求值规则和固定限制。
- [有界 Process 模型](docs/bounded-process-model.md)：动态机制、运行语义和分析边界。
- [浏览器工作台规范](docs/web-workbench.md)：界面、保存、冲突、Agent 协作和安全边界。
- [MCP server](docs/mcp-server.md)：Agent 资源、工具、stdio 配置、哈希写入和权威边界。
- [Community Package protocol v2](docs/package-system-v2.md)：只含数据的依赖、接口、锁定与缓存协议。
- [Workbench Extension Plugin protocol v2](docs/workbench-plugin-system-v2.md)：沙箱扩展、模型目录、权限和安全模式。
- [可规模化游戏插件平台提案](docs/scalable-game-plugin-platform-proposal.md)：Package、Catalog、Plugin API、SDK、可信呈现和验收路线；Phase 0–1 已实现，其余阶段仍是提案。
- [游戏机制计算能力边界](docs/game-mechanics-capability-audit.md)：适用问题与明确非目标。
- [Changelog](CHANGELOG.md)：版本历史和破坏性变更。

发生冲突时，以当前实现和测试为行为证据；语法、数学、工作台、Package 与 Plugin 的正式合同分别由对应规范文档定义。

## 开发

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
pytest
```

浏览器前端的构建、测试和打包资产同步方式见 [frontend/README.md](frontend/README.md)。
