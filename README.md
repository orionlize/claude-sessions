# Claude Sessions

DankMaterialShell 状态栏组件：实时显示 Claude Code 会话状态，在需要权限或选择时弹窗让你处理。

- 运行中：图标和圆点呼吸；每个会话对应一个圆点，最多 6 个
- 思考中：`psychology` 图标、主题主色，文字显示「项目 · 思考中」
- 调用工具中：`build` 图标、主题第三色，文字显示「项目 · 工具名」；有工具未结束（并行调用、子代理）时不会回到思考中
- 等待权限或选择：变为警告色，快速闪烁，并自动弹窗
- 弹窗不抢键盘，也不拦截窗口外的点击，指针移入弹窗后才接管键盘
- 弹窗底色是混入 15% 主题主色的表面，不透明度为「浮动窗口透明度」的 0.5 倍，并开启 blur；内部卡片和按钮是主题主色的半透明层，边框、圆角、阴影跟随 DMS 主题
- 终端仍可照常回答，先答的一方生效，弹窗随后自动收起
- 刚启动、还没输入过提示词的会话不显示：进入 Claude Code 的 dashboard 后前台那个会话不会再被用到，后台 daemon 也会预热备用会话，它们都只有一个 SessionStart。`--resume`、`/clear` 后的会话照常显示，其他会话有了第一条提示词就会出现
- 在 dashboard 里回复后台任务时，dashboard 进程会显示这个任务的会话，同时由它派生的后台进程用 `--fork-session` 分叉出新会话来干活，两者在同一个窗口里。这时只列出分叉出来的会话，原会话的提示词转给它
- 点击弹窗里的会话，会切到它所在的 tmux 窗口和 pane，并聚焦对应的 foot 窗口（目前只支持 niri）；该 tmux 会话没有终端连着时，会新开一个 foot 连上去（可用环境变量 `CLAUDE_SESSIONS_TERMINAL` 换成别的终端）
- 后台任务（`claude --bg`，或推到后台的会话）由 Claude 的 daemon 托管，没有自己的终端：点击时先找正在显示它的终端（agent view 或 `claude attach` 打开任务时，窗口标题就是任务名）并聚焦，其次是还在运行 `claude attach <id>` 的终端，都没有才新开一个终端执行 `claude attach <id>`（命令优先用环境变量 `CLAUDE_SESSIONS_CLAUDE`，其次是 PATH 里的 wrapper `claude-hl`，都没有才用 `claude` 本体；shell 里的 alias 对插件不可见），沿用该任务的 `CLAUDE_CONFIG_DIR` 和工作目录
- `Mod+Tab` 打开会话切换器，在插件设置的「会话切换器」里选样式：
  - **Spotlight**：居中的搜索框，输入关键字筛选项目、标题、提示词和路径，↑↓ / Tab / Ctrl+N/P 选择，回车切换，Esc 关闭
  - **平铺**：像窗口切换一样把会话铺成网格。会话在 tmux 里时，卡片显示该 pane 的快照（`tmux capture-pane -e`，带颜色，按 pane 尺寸等比缩小），打开期间每 1.5 秒刷新；不在 tmux 里时显示最近几轮对话（读 transcript；不截终端窗口，因为 niri 的截图每次都会弹系统通知并占用剪贴板）。像 Alt+Tab 一样：按住 Mod 时每按一次 Tab 选下一个，松开 Mod 就切过去并隐藏。也可以用方向键 / hjkl / Tab 选择，数字键 1–9 直接切换，回车或空格切换，Esc 只关闭不切换
  - 不看设置、直接指定样式：`dms ipc call claudeSessions tiles` / `dms ipc call claudeSessions spotlight`

## 快速启动

仿 Claude Desktop 的全局输入框：`dms ipc call claudeSessions launch` 弹出，输入提示词按回车，在全局唯一的 tmux 会话 `claude-quick` 里新开一个窗口运行 `claude "<提示词>"`，在所选文件夹里启动。整个过程静默：不弹终端、不切换当前 tmux 客户端。会话第一次启动时自动创建，之后每次都只加一个窗口。这些会话在 tmux 里，所以会出现在会话列表里，点击可以跳转；没有终端连着时，点击会按上面的规则新开一个 foot 连上去。

- 回车启动，Shift+回车换行，Esc 关闭；提示词留空则只启动 Claude
- 输入框下方是工作文件夹，和 Desktop 新会话界面的「项目文件夹」一样，默认沿用上次成功启动用的文件夹。点它或按 Tab 打开选择列表：
  - **新建临时文件夹**：每次新建一个 `/tmp/<UUID>`，互不相同（第一次用时的默认值）
  - 最近的文件夹：先列在这里启动过的（最多 8 个），再列正在运行的会话所在的目录，`/tmp/<UUID>` 不会列出
  - 输入关键字筛选；以 `/` 或 `~` 开头时按路径补全磁盘上的目录，Tab 把选中的目录填进输入框继续往下补，回车选定，Esc 回到提示词
- 启动失败（找不到 `claude`、目录不存在等）会弹 DMS 错误通知，这个文件夹也不会被记下

## 安装

```bash
ln -s ~/i/claude-sessions ~/.config/dms/plugins/claudeSessions
```

1. 在 设置 → 插件 中扫描并启用 **Claude Sessions**
2. 在插件设置中点 **安装 hooks**，或运行 `python3 scripts/install-hooks.py install`
3. 在 设置 → 状态栏部件 中手动添加组件（插件不会自己加到状态栏上）
4. 重启已在运行的 Claude Code 会话，hooks 才会生效
5. 快捷键需要手动添加，插件不提供。在 DMS 设置的快捷键（shortcut）里新增下面几条，动作选执行命令，命令按空格拆成参数填写：

   | 按键 | 命令 | 作用 |
   | --- | --- | --- |
   | `Mod+Tab` | `dms ipc call claudeSessions toggle` | 打开会话切换器（样式见插件设置） |
   | `Mod+Shift+Tab` | `dms ipc call claudeSessions tiles` | 固定打开平铺 |
   | `Mod+E` | `dms ipc call claudeSessions launch` | 快速启动 |

   不需要的可以不加。

卸载 hooks：`python3 scripts/install-hooks.py uninstall`。写入前会备份为 `~/.claude/settings.json.claude-sessions.bak`，其他 hooks 不受影响。

## 工作方式

```
Claude Code ── hook/claude-sessions-hook.py ── $XDG_RUNTIME_DIR/claude-sessions.sock ── ClaudeDaemon.qml ── ClaudeWidget.qml
```

- `ClaudeDaemon.qml` 全局唯一，持有所有状态；组件每个状态栏一个实例，只负责显示
- `PermissionRequest` hook 保持连接，直到组件回复。socket 不存在、插件被禁用、shell 重启时，hook 静默退出，由终端确认框接管
- 按 Esc 不触发任何 hook，所以 `scripts/sweep.py` 定期读 transcript 末尾判断打断，同时检查进程是否存活

## 已知限制

- 通过终端拒绝或按 Esc 后，弹窗最多延迟约 2 秒收起（等下一次扫描）
- 「始终允许」只保存规则和目录类授权，不会切换权限模式
- `MultiEdit`、MCP 等工具的详情按 JSON 或文件内容显示，超过 6000 字符会截断并标注 `[truncated]`
- MCP elicitation 对话框只显示等待状态，仍需在终端处理
- 终端窗口截图不会实时刷新：niri 没有按窗口实时捕获的协议，只能每次打开时截一张
- niri 截图一定会写进剪贴板。截完后插件通过 DMS 剪贴板历史删掉这些截图并恢复原来的内容；没开 DMS 剪贴板管理时，剪贴板会被截图覆盖
- 点击跳转时按 pid 找终端窗口，foot 服务端模式（footclient）下所有窗口共用一个 pid，可能跳到别的 foot 窗口

## 测试

```bash
node --test tests/test_model.mjs tests/test_folders.mjs
python3 tests/test_hook.py
```
