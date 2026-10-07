# v1.1.1

本次更新包含一项影响启动成功率的修复，以及一次面向使用者的文档整理。

## 一、修复「EFMI 加载失败：无法检测到游戏进程 Endfield.exe 的窗口」

### 现象

游戏进程启动后 24~39 秒以 `0xC0000005`（访问违例）退出，`Player.log` 在

```
Forcing GfxDevice: Direct3D 11
GfxDevice: creating device client; threaded=1; jobified=0
1Crash!!!
```

处中断；Windows 错误报告的故障模块为 `ACE-Base64.dll`。XXMI 等待游戏窗口 60 秒超时，弹出「EFMI 加载失败：无法检测到游戏进程 Endfield.exe 的窗口」。此前同一环境的失败形态不同：进程极早期退出、退出码 `0xC0000135`（DLL 未找到）。

### 根因

XXMI 配置中的

```json
"Importers": { "EFMI": { "Importer": {
    "importer_folder": "C:/Users/…/Downloads/library"
} } }
```

被指向了 **Mod 库**（该目录里存在某个 Mod 附带的同名 `d3d11.dll`，且没有 `d3dx.ini`）。由此产生两份不同的 D3D11 loader 同时进入游戏进程：

| 来源 | 路径 |
|---|---|
| XXMI 自己（按 `importer_folder` 注入） | `…\Downloads\library\d3d11.dll` |
| 注入库（`extra_libraries` 第二条） | `…\runtime\builtin\XXMI\EFMI\d3d11.dll` |

证据：崩溃报告 `LoadedModule[16]` 与 `LoadedModule[61]` 分别为上述两个文件；XXMI 自身日志同时出现 `Successfully injected DLL … library\d3d11.dll` 与 `缺少关键文件：d3dx.ini！文件 '…\library\d3dx.ini' 不存在！`。两份 loader 抢同一套 D3D11 hook，游戏在创建 D3D11 设备阶段即崩溃。

### 修复

- **自动纠正该配置字段**：启动自检读取 `importer_folder`，若它落在这个 XXMI 自己的目录之外（或目录内没有 loader），改写回该 XXMI 自己的 EFMI 目录。写入绝对路径，改前备份为 `XXMI Launcher Config.json.mc-before-importer-folder-<时间戳>.bak`，其余字段一个不动，重复运行不重复改写。
- **顺序修正**：先纠正该字段、再重新读取配置，之后才写入 `extra_libraries`（避免旧副本覆盖刚写好的值）。
- **降级保护**：配置无法改写时，**不再叠加第二条 loader**（宁可少列一条，也不让两份 loader 同时进入进程）。
- **取证增强**：注入现场时间线按**路径**统计同名 loader（`d3d11.dll` / `d3d12.dll` / `dxgi.dll`），出现两份时在时间线与日志中显式标注；诊断包的「XXMI 注入链摘要」新增该字段现状（原值、解析路径、是否在这个 XXMI 内、有没有 `d3dx.ini`）以及"两侧 loader 是否同一份"的判据。

### 与前两次修复的关系

v1.0.10（注入顺序）与 v1.0.29（不再把 Mod 库里的同名 dll 列为 loader）修改的都是「注入库列哪一份」，而 XXMI 依据 `importer_folder` 自行注入的那一份始终未变 —— 症状因此从"单份假 loader（`0xC0000135`）"变为"两份 loader（`0xC0000005`）"。本次的判据换成了该配置字段本身。

`importer_folder` 只影响 XXMI 自身，程序不删除、不移动 Mod 库中任何文件。

## 二、文档整理

- 两份 README 重写为面向使用者：保留定位、工作原理、各页面用法、目录结构、逐项排查；开发相关内容（模块职责、发布流程、历史决策）移入 `CONTRIBUTING.md` 与 `docs/dev/`；详细版由 752 行精简至 440 行。
- `docs/` 目录归位：开发与历史档案收进 `docs/dev/`（12 个文件），根下只保留面向使用者的详细文档与自动生成产物；`docs/README.md` 索引页重写为「面向使用者 / 开发档案 / 自动生成」三栏。
- 修正 `CONTRIBUTING.md` 中关于前端的过时描述（现为 Vue 3 + Vite）。

## 三、注释与文案审计

按"不留过时与误导内容"逐处核对源码注释、文档串与界面上会出现的文案，共处理 5 处，其中 4 处改写：`configure_dlss5_injection()` 的文档串与动作文案不再自称「DLSS5 注入」（它负责的是 DLSS4 / DLSS5 / 第一人称 / 游戏内面板共用的注入底座）、`api` 中同类日志、`initialize` 里 `_check_dlss5_nrstyle` 前的注释（原写「自动改回 0」，而该动作早已移除，实际只报告不改动）。

## 四、验证

- 新增回归测试 `tests/test_efmi_importer_folder.py` 16 项，覆盖：指向 Mod 库时被纠正、正常绝对路径 / 相对路径 / 外部 XXMI 布局一律不改动、重复运行幂等、配置改不动时不写入且不叠加第二条 loader、注入现场时间线与诊断包的取证判据。
- 三项修复点分别临时退回，对应测试分别变红 2 / 4 / 2 项，恢复后全部通过。
- 全量测试 `python -m pytest tests -q -n 4`：1174 passed。
