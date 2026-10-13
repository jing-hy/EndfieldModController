---
name: emc-structure-closeout
description: 改完 EndfieldModController 源码后的收尾流程——跑测试、重建前端产物、结构树（normify）四步收尾与镜像同步、构建 exe 并放进 modtest。仅在处理 D:\zmdmod\modecontroller 这个项目时使用。
---

# EndfieldModController 改完之后的收尾

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
