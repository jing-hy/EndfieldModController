# 维护者指南 —— 提交前请照这份清单走

本仓库是《明日方舟：终末地》Mod 管理器 **EndfieldModController** 的源码。
这份文档写给**维护者 / 贡献者**：动手前先知道边界，提交前把该更新的产出一并更新。

> 面向**使用者**的说明在 [README.md](README.md)（简略）与 [docs/README.detailed.md](docs/README.detailed.md)（详细）。
> 面向**手测**的清单在 [TESTING.md](TESTING.md)（编号条目，用户按编号回话）。

### 用 AI 排查故障？

先读 **[AGENTS.md](AGENTS.md)** —— 那份专门写给 AI 助手：怎么用诊断包里的东西定位问题、
查明是**本程序**的问题就**自己改、自己测、交出一个能直接合并的修复**。
交付方式二选一：**有 GitHub 账号 → 提 PR**（说明写清「改了什么 / 为什么 / 怎么验证」）；
**没有 GitHub 账号 → 加 QQ 群**（群号 **1045239747**，加群验证答案 `jing_hy`）
把改动（diff / 补丁 / 说明）连同诊断包发出来。

---

## 一、改动边界（别越线）

1. **只改本仓库**：`endfieldmodcontroller/`（后端）、`frontend/`（Vue 源码）、`web/`（构建产物）、
   `scripts/`、`tests/`、文档。
2. **不动第三方依赖本体** —— XXMI Launcher / EFMI / ReShade / SecondaryMotion（乳摇）/
   Endfield Poser / OptiScaler 这些是别人维护的：改了别人也从 GitHub 重新拉，我们的改动会静默失效。
   发现它们的问题 → **去它自己的仓库提 issue**，我们这边只做"编排、自检、补齐"。
3. **用户数据红线**：`library/`（用户的 Mod 库）**只读** —— 不删、不移、不重命名、不换位置、不"整理"。
   唯一允许的删除入口是用户自己在卡片菜单点「移出 Mod 库」（移到 `runtime/backups/mod-trash/`，可找回）。
4. **改游戏目录之前先备份、并且可一键还原**；游戏正在运行时不要替换它占用的文件（先查进程）。

---

## 二、提交前必须做的检查（一条都不能省）

### 1. 跑测试（必须全绿）

```bash
python -m pytest tests -q
```

* 当前基线：**630 passed**（数字随版本增长）。
* **修 bug 要配回归测试**，否则它迟早复发；测试文件顶部写清"这钉住的是什么现象/哪次实测"。
* ⚠️ 不要在仓库根跑全量（`_tmp/` 会污染），始终 `python -m pytest tests -q`。
* 仓库里已有几条"防复发"的静态检查，改前端/脚本时特别注意：
  * `tests/test_frontend_components.py` —— **模板里用到的组件必须 import**
    （Vue 对未解析标签是**静默**跳过：页面空白 + `ref` 拿到 DOM 元素，调方法直接 TypeError）；
  * `tests/test_frontend_menu_actions.py` —— 模板里传的动作名必须在处理函数里有对应分支、`catch` 不许空吞；
  * `tests/test_undefined_names.py` —— 整包禁 `undefined name`（pyflakes）；
  * `tests/test_memory_log.py` / `test_single_instance.py` / `test_injection_switches.py`。

### 2. 版本号（只跟「最新 Release」比）

* 规则：**本地 = 最新 Release + 1**；**只推了源码、没发 Release 时，版本号不用改**（这是软约束，可豁免但要说明）。
* 改了 `endfieldmodcontroller/version.py` 就**必须同时改这两处的"当前版本"**：
  * `README.md`（hero 区那行）
  * `docs/README.detailed.md`（开头）
  * `scripts/build_release.py` 第 0 步会**卡住**不一致的提交（直接 exit 1），别绕。
* 可以先跑 `python scripts/release_version.py` 看当前该怎么定号。

### 3. 结构树（normify）—— 改了源码就要刷新

结构数据的**源目录**在 dsh 的 profile 下（不进 git）：
`~/.dsh/profiles/desktop/normify-modecontroller/`；仓库里的 `docs/structure/` 是它的**镜像**。

改了哪个模块，就刷新哪些模块（改 `description` / `source` / `apis`），然后四步收尾：

```
1) python scripts/normify_realign.py --apply     # 按 git diff 平移 source 行号（改完代码必跑）
2) normify_module_refresh(all=true, repoRoot=…)  # 重算 fingerprint / revision
3) normify_validate(repoRoot=…)                  # 必须 0 error
4) normify_build → normify_render                # 产出 tree.json / outline.md / normify.html
```

* ⚠️ `normify_realign` **不是幂等的**：每跑一次都会按"结构树 revision → 当前工作区"的完整 diff 再平移一遍。
  同一批改动**只跑一次**；如果中间又改了代码，先看 dry-run 报告再决定。
* 新增模块：先 `state=planned` + `fingerprint=pending` 建，落地后 `normify_module_refresh(ids=[…], activate=true)` 转 active。
* **镜像进仓库**：`python scripts/sync_structure.py`（会整份覆盖 `docs/structure/`）。
  **这一步 `push.py` 会自动做**，你本地不用手动跑。

### 4. 记忆日志

`docs/AI-记忆日志.md` 是从工作区记忆库（`.dsh-meow/memory.db`）导出的**可读开发日志**
（决策、踩过的坑、为什么这么改），随源码一起给读者看。

```bash
python scripts/memory_log.py     # 重新导出（push.py 也会自动跑）
```

* 它是**自动生成**的，**不要手改**；要改内容 → 改记忆库，再重新导出。
* 本机主目录路径会自动脱敏成 `C:\Users\<user>`；**记忆库本身（`memory.db`）不上传**。

### 5. Release notes 与手测清单（改动面向用户时）

* 用户能感知的改动 → 写进 `RELEASE_NOTES.md`（**"与上一版的变动"只写这里，README 不写**）；
  修了 issue 就在**开头一行**写明编号 + 链接（例：`本版修复的反馈：#12 · mod无法解压`）。
* 需要用户点一下验证的 → 在 `TESTING.md` **末尾追加**编号条目（**新编号一律接在末尾、老编号不动**，
  用户是按编号回话的）；每条给「操作」+「预期结果」，本次新改的用 ★ 标记。
* **公告只发"大事"**（`alerts.json` 给所有用户弹的那种）：版本更新、功能上新**默认不发**。

---

## 三、提交与发布流程（照抄即可）

```bash
# ① 改代码 + 回归测试
python -m pytest tests -q

# ② 自己 commit（⚠️ push.py / build_release.py 都**不会**替你 commit，
#    忘了就会看到 "Everything up-to-date" 白跑一趟）
git add -A && git commit -m "…"

# ③ 构建（会校验 version.py 与两份 README 一致；产出 dist/ + 同步 modtest）
python scripts/build_release.py

# ④ 备齐 Release 附件并打印上传指引
python scripts/prepare_release.py

# ⑤ 推送 main（**先做状态快照，快照失败就不推**；顺带刷新并提交记忆日志 + 结构树）
python scripts/push.py
```

发 Release（**必须由项目所有者明确授权**）：

```bash
gh release create v1.0.x --draft --title "…" --notes-file RELEASE_NOTES.md
python scripts/upload_release_assets.py --tag v1.0.x     # DoH 查真实 IP + curl 直连
gh release edit v1.0.x --draft=false --latest            # 转正
```

* ⚠️ `gh release create` 建出来的 release **不带附件**，附件靠中间那条命令补。
* **先建 draft、上传附件、最后再转正**（顺序别反）—— **draft 阶段按 tag 查 release 会 404**，
  所以核对附件要**按 release id**：`gh api repos/<owner>/<repo>/releases/<id>`。
* 附件只推**两个、且都不带版本号**：`EndfieldModController.exe` + `assets-bundle.zip`；
  带版本号的副本、伪旧版（`-0.1.9-from-<版本>.exe`）**只本地留档**。
* 发完核对附件 sha256 与 `prepare_release.py` 打印的值一致。
* 快照落在工作区**外**：`D:\zmdmod\_snapshot_<标签>-<时间戳>\`（不进 git）。
* **`push main` ≠ 发 Release**：只推源码不动下载页 / Latest。

### ⚠️ 发完必查：**别留下未发布的 draft**

```bash
gh api repos/jing-hy/EndfieldModController/releases --jq '[.[] | select(.draft==true)] | length'
# 必须是 0
```

**GitHub 会把 Draft 排在 Releases 列表的最前面**（草稿对访客不可见、对作者可见），
所以只要遗留一个旧草稿，项目所有者打开 Releases 页就会看到**旧版本顶在新版本上面** ——
看起来就像"旧版本号比新版本号还新"（2026-10-07 实际发生过：v1.0.25 的草稿压在 v1.1.0 之上，
而它的内容早就在 v1.0.26 正式发过了，白占 262 MB 附件）。

**注意**：这只影响 GitHub 页面显示 ——
`/releases/latest`、网页 302、以及程序里的 `version.parse_version` 比较**都是对的**
（`is_newer("1.0.25", "1.1.0")` 返回 `False`）。所以排查这类问题时，
**先分清"页面排序"与"更新检查逻辑"两件事**，别去改版本比较代码。

遗留 draft 的处理：确认其内容已由后续正式版发布过，再 `gh release delete <tag> --repo <repo> --yes`。

---

## 四、代码约定（都是踩出来的）

1. **开关要真的有用**：UI 上每个开关/滑块必须与后端真实动作一一对应，而且要实测验证
   —— 写了配置不等于生效，**"我提示你了"不等于"我处理了"**。
2. **能自动做掉的别用"提示"交付**：能安全自动处理的（备份 + 可还原 + 只动确定目标）就自动做，
   并在自检里记一条 `fixed=True`；只有"要用户决策"或"程序确实做不到"才提示，且提示要出现在
   **用户一定会看到的位置**。
3. **不许静默失败**：`except` 不要空吞 —— 至少写日志；面向用户的操作失败要给一句能看懂的原因。
   前端 `catch` 里要 `console.error` + 弹窗（"点了没反应"大半是空 catch 造成的）。
4. **别在启动流程里偷偷下载**：用户关掉「自动更新依赖」+ 本地已就位 ⇒ **一个网络请求都不发**；
   显式点击（依赖页的更新按钮）才走 `force=True` 真的下载。
5. **多个插件共用引导文件时要当成一个整体**：任何一方的"卸载 / 还原"都要先问"还有别人在用吗"，
   **"被停用"也算在用**（否则会把对方的底座拆掉）。
6. **归因先找对照**：没有对照证据不要下结论；不确定就直说"判据不够"，并列出还缺什么。
7. **子进程一律带 `CREATE_NO_WINDOW`**（全程不许出现 cmd 黑窗）；启动脚本走 pythonw / vbs。
8. **弹窗文案自解释**：不用"确定 / 取消"，写清动作本身；破坏性动作默认聚焦安全项。

---

## 五、模块职责

后端约 2.9 万行，都在 `endfieldmodcontroller\`。改代码前先在这里定位该动哪个文件。

| 模块 | 职责 |
| --- | --- |
| `config.py` | 配置读写（原子写 / 损坏隔离）、路径解析、内嵌组件探测（带缓存，分"深/浅"两档） |
| `core.py` | Mod 库扫描、角色识别、ini 解析与热键改写（`patch_mod_hotkeys` **默认不启用**）、控制器产物生成、`d3dx_user.ini` 读写 |
| `activation.py` | 选择解析（同角色互斥 / 依赖按需）、staging 生成与清理（**库保护护栏在这里**） |
| `launcher.py` | 一键启动、注入库维护、注入器配置读写、ReShade 运行时准备、进程收尾 |
| `api.py` | 暴露给前端的接口层（pywebview `js_api`）；**构造必须保持"快"**，重活丢后台预热线程 |
| `initialize.py` | 初始化自检（重建配置时**必须保留所有段**、shader / preset / 运动矢量、游戏目录运行库、Mod 冲突检测） |
| `runtime_assets.py` | 随包资产的展开与基线（**DLSS 运行库按显卡架构选变体的唯一落点在 `ensure_dlssnr()`**） |
| `runtime_deps.py` / `dependencies.py` | 内置组件清单与安装（XXMI / Libraries / EFMI / Poser / 物理效果）、下载与解压（逐文件原子替换） |
| `dlss5_fetcher.py` / `reshade_integration.py` | DLSS5 组件、ReShade 集成与游戏目录注入审计 |
| `secondary_motion.py` / `sbm_data_sync.py` | 物理效果：状态、注入、模板实例化；角色参数后台拉取（**只补本地缺失的角色**，绝不碰 `presets\User.json`） |
| `poser.py` | 摆姿 / MMD：状态、安装包下载、调**它自己的**安装向导、开关（重命名 dll）、只读读它的摆姿页 |
| `game_clean.py` | 游戏目录净化 / 还原（备份式、内容级判定、越界拒绝） |
| `fastnet.py` / `github.py` / `fsutil.py` | 下载（并发 / 镜像 / 校验）、GitHub 查询与缓存、哈希与原子写等公共件 |
| `diagnostics.py` / `crashwatch.py` | 日志、诊断包采集、崩溃监视与归因 |
| `deviceinfo.py` | 设备与显卡（只读注册表 + ctypes，**不起子进程**）：写进诊断包，用来判断"是不是显卡不支持" |
| `filewatch.py` | 文件守护：**曾经在 + 连续两次启动都缺 + 同组还有别的文件** ⇒ 提示加杀软白名单 |
| `hot_reload.py` | 热重载：找游戏窗口并发按键 |
| `version.py` | **全项目唯一版本口径**（别再各处自己写正则抠数字） |
| `frontend\src\` | 前端源码（Vue 3 + Vite）；产物 `web\dist\index.html` 随 exe 打包，**改了必须先 build** |

---

## 六、自动生成的产物（**不要手改**）

| 路径 | 由谁生成 | 说明 |
| --- | --- | --- |
| `docs/structure/` | `scripts/sync_structure.py`（`push.py` 自动调用） | normify 结构树整份镜像（`modules/` 是**源**，`tree.json` / `normify.html` 是产物） |
| `docs/AI-记忆日志.md` | `scripts/memory_log.py`（`push.py` 自动调用） | 记忆库导出的开发日志 |
| `web/dist/index.html` | `frontend/` 里 `npm run build` | 前端单文件产物；**必须构建后再打包 exe**，否则改动不会进 exe |
| `dist/*.exe`、`assets-bundle.zip` | `scripts/build_release.py` / `prepare_release.py` | 发布产物，不进 git |

> 改了 `frontend/` 下的任何东西之后：`cd frontend && npm run build`，再 `python scripts/build_exe.py`
> （或直接 `build_release.py`），否则 exe 里还是旧界面。
