---
name: emc-structure-closeout
description: 改完 EndfieldModController 源码后的收尾流程——跑测试、重建前端产物、结构树（normify）四步收尾与镜像同步、构建 exe 并放进 modtest。仅在处理 D:\zmdmod\modecontroller 这个项目时使用。
---

# EndfieldModController 改完之后的收尾

## 第零步：先确认收尾对象（否则整条流程都是空转）

1. 先跑 `git status --short` 与 `git diff --stat`。报告的**第一行**必须是：
   「本次改动 = <文件列表>；影响面 = <前端 / 后端 / 配置 / 测试 / 无>」。
2. **影响面必须落在一个枚举值上**：`前端` / `后端` / `配置` / `测试` / `无`。
   工作区干净 → 写「无」；只动了 `endfieldmodcontroller/config.py` 这类 → 写「配置」；动了 `frontend/` → 写「前端」。
   「未能确认」「无法判定」不算答案：要么给结论，要么给出你查过的命令与输出、说明为什么给不出。
3. **工作区干净、但用户说「我改了东西」**：这是矛盾，不是能补脑的细节。立刻回报：
   「`git status` 显示没有未提交改动，你说的这处改动我没看到 —— 可能已经提交（可看 `git log -1 --stat`）、
   在另一个检出、或者没保存」，然后请用户确认收尾对象。**不许假设它存在，然后对着空气排一遍流程。**
4. 一旦确认了改动对象，**必须按 ①→⑤ 逐步列出每步的验证字段**，不许一句「一路做到 ⑤」带过：
   ① 测试 = 通过/失败条数；② 前端产物 = 产物 mtime 对比 `frontend\src` 最新 mtime；
   ③ 结构树 = change id + 状态 + 镜像同步结果；④ 构建 = exe 完整路径 + SHA256；
   ⑤ 点验 = TESTING.md 条目编号 + modtest 目标目录。
5. 改动涉及**产品默认值**时，主动提示：依赖旧默认值的测试 fixture 会变红，
   应在这些 fixture 的构造里显式写出前提，而不是回去改逻辑。
6. 任何一步没做成，报告里标「未执行 + 原因」，并给出用户能自己跑一遍的验证命令；
   **不许写「已通过」「已完成」，也不许用计划冒充结果。**
项目：`D:\zmdmod\modecontroller`。**改了源码就要走完这几步**，漏一步用户拿到的就是"产物是新的、源码/文档是旧的"。

## 一、顺序

```
① 跑测试（必须全绿）
② 改了 frontend/ ⇒ 重建产物
③ 改了后端 ⇒ 结构树四步 + 同步镜像
④ 构建 exe（会自动放进 modtest）
⑤ 要用户点验的 ⇒ TESTING.md 末尾追加编号条目
```

### ① 测试

```powershell
cd D:\zmdmod\modecontroller
python -m pytest tests -q          # 必须 0 failed
```

- 修过的 bug **要有测试钉住**，并做**反向验证**（把修复退回去 ⇒ 测试确实变红）。
- 改产品默认值时特别小心：会有若干测试的 fixture 依赖旧默认值而变红。**那是测试假设要更新**（在它们的 `AppConfig(...)` 构造里显式写出前提），不是逻辑错。
  ⚠️ `AppConfig` 是 dataclass，`__init__` 的默认值写在函数签名里 ⇒ **改类属性无效**，只能逐个构造点显式传参。
- 单跑通过、全量失败 ⇒ 是测试间隔离问题（`AppConfig()` 裸构造没关总闸之类），同样用"显式写前提"修。

### ② 前端产物（改了 `frontend/` 就必须做）

```powershell
cd D:\zmdmod\modecontroller\frontend
node node_modules\vite\bin\vite.js build      # ⇒ ..\web\dist\index.html
```
**程序实际加载的是产物、不是源码**；`build_release.py` 的静态检查会校验"产物不得比 `frontend/src` 旧"。

### ③ 结构树（normify）

- 插件：**`@dsh-external/dsh-normify`** —— 仓库 **https://github.com/yan-mc/dsh-normify**（作者 yan-mc）。
  DSH profile 里的包位置：`C:\Users\Administrator\.dsh\profiles\desktop\node_modules\@dsh-external\dsh-normify`。
- **真实数据在**：`C:\Users\Administrator\.dsh\profiles\desktop\normify-modecontroller\`；
  仓库里的 `docs\structure\` 是它的**镜像**（由 `scripts\sync_structure.py` 同步，`push.py` 也会自动调）。
- 项目 slug = **`modecontroller`**（调 normify 工具时传 `project="modecontroller"` + `repoRoot="D:\zmdmod\modecontroller"`；
  ⚠️ 别传 `dir=docs\structure`，工具要求目录名以 `normify-` 开头）。

四步：

```powershell
python scripts\normify_realign.py --apply     # ① 按 git diff 平移 source 行号（改完代码必跑）
```
```
② normify_module_refresh(project="modecontroller", repoRoot="D:\zmdmod\modecontroller", all=true)
③ normify_validate(...)      # 必须 0 error（warning 可接受）
④ normify_build(...) → normify_render(...)
```
```powershell
python scripts\sync_structure.py              # 把产物同步回仓库 docs\structure\
```

- **新增模块**：先 `normify_module_upsert`（`state=planned` + `fingerprint=pending` 也行，落地后 `normify_module_refresh(activate=true)` 转 active）；`uid` 要 8 位小写 hex 且全项目唯一（`modecontroller.backend.game.*` 已用到 `b1d10001`…`b1d1000b`）。
- `deps` 的 `label.en` **不得超过 30 字符**（超了 upsert 直接报错拒写）。
- **父层 layout 要一起维护**：往某层加子模块后跑 `normify_layout_get`，把新 id 补进 `order`/`groups`（否则 warning `layout/order-incomplete`）。
- `normify_realign.py` **不是幂等的**：每跑一次都会按"结构树 revision → 当前工作区"的完整 diff 再平移一遍，别连跑。

### ④ 构建并送进测试目录

```powershell
cd D:\zmdmod\modecontroller
python scripts\build_release.py --no-push     # 静态检查 + 构建 + 同步 modtest（+ 带版本号副本）
```
- **默认会推 main**；用户没让推就加 `--no-push`。
- 它**只把 exe 同步进 `..\modtest\`**（其余文件一概不动），并核对 sha256。
- **离线包也要放进 modtest**（用户 2026-10-14：「以后离线包也放 modtest」）：
  跑 `python scripts\build_deps_bundle.py` 时**默认就同步一份** `deps-bundle.zip` + `.sha256`
  过去（`--skip-modtest` 可关）—— 在 modtest 里测"离线导入"时手边就有包。
  另注：该脚本产的包**不进 Release**，只在连不上 GitHub 时应急分发。
- 默认不跑测试（测试是独立入口 `scripts\run_tests.py`），要带着跑加 `--with-tests`。

### ⑤ 给用户的点验条目

`TESTING.md` 末尾按编号追加（新编号接末尾，老编号不动），格式：

```
| 编号 | 操作 | 预期结果 |
| --- | --- | --- |
| 541 ★★★ | 启动页打开「X」开关 | 依赖页出现…；目录里出现… |
```

## 二、modtest 的清理与重建（用户要"干净环境"时）

标准动作（2026-10-13 实操过一遍）：

1. **先确认没有进程占用**：`Endfield` / `XXMI Launcher` / `EndfieldModController` 都没在跑
   （`pythonw.exe` 可能是别的东西，先看它的 `CommandLine` 再判断）。
2. **大件移出去而不是删掉**（同盘 move 是秒级，省得重下）：
   - `mod-backup\`（实测 12.4 GB！）
   - `assets\`（250 MB 随包资产）—— 构建脚本只同步 exe，**不清空后搬回的话新 exe 首次启动要重下**
3. **用户调过的设置另存一份**：`config.json` + `runtime\` 下所有 <2 MB 的 `.json/.ini/.cfg/.txt/.log/.bak`，
   按相对路径保留结构（实测 1882 个文件；最要紧的是 `runtime\dlss5\ReShade.ini`、`ReShadePreset.ini`）。
4. 删除 `modtest` 下**除 `library\` 以外**的一切（`Remove-Item -Recurse -Force`，
   删前用 `Resolve-Path` 校验目标确实是 `D:\zmdmod\modtest`）。
5. 跑 `build_release.py`，exe 会自动放进去。

## 三、版本号与发版

- 版本号**三处必须一致**：`endfieldmodcontroller\version.py` + `README.md` + `docs\README.detailed.md`
  （`build_release.py` 第 0 步会校验，不一致直接 exit 1）。
- `RELEASE_NOTES.md` 只在**准备发版**时更新。
- **未经用户明确同意不要发 Release**；推 main ≠ 发版。
- 内置组件版本表 `endfieldmodcontroller\component_versions.json` 要随发版同步；
  `scripts\check_component_versions.py --strict` 是发版闸（过期会中止构建，除非显式 `--skip-version-table-check`）。

## 硬性验收（不满足即视为没做完）

这一节是按回测失败项写死的规则，比上面任何描述都优先：

1. **禁止用「（假设）」「应该」「理论上」代替执行。** 每一步都要真跑，并把命令与关键输出贴出来：
   测试给「X passed / Y failed」的条数；`git diff --stat` 贴原文；`normify_*` 贴返回的 id 与状态。
   工具不可用或目录不存在时，写「这一步没做成，原因是……」，**不许写成通过**。
2. **动工前先跑 `git status --short` 与 `git diff --stat`**，据此判断 `frontend/` 到底改没改。
   没改就声明「本次无前端改动，跳过重建」并附 diff 证据；改了就必须重建，不许跳过。
3. **修过的 bug 必须有钉住它的测试，并做反向验证**：把修复临时退回 → 该测试确实变红 → 再恢复。
   回复里写清测试名与两次运行结果（红/绿各一次）。
4. **产物新鲜度要有数字**：重建后给出产物文件 `LastWriteTime` 与 `frontend\src` 最新 mtime 的对比，
   不能只说「静态检查通过」。
5. **收尾报告逐条可点验**：测试条数、exe 完整路径 + SHA256、modtest 目标目录、
   normify change id 与状态、TESTING.md 新增条目编号。禁止用「已完成」三个字代替清单。