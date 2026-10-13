---
name: emc-new-managed-component
description: 把第三方组件（Mod / 插件 / 工具）接成 EndfieldModController 的"受管组件"（依赖页条目 + 启动页开关 + 启动自检 + 版本检查与更新）时使用。仅在处理 D:\zmdmod\modecontroller 这个项目时使用；规定了必须同步的十来处落点、三条硬约束，以及 staging 三份平行白名单。
---

# 给 EndfieldModController 新增一个受管组件

项目：`D:\zmdmod\modecontroller`（Python + pywebview 单文件 exe，包目录 `endfieldmodcontroller\`，扁平结构——没有 `game\`、`api\` 子包）。
先读项目自己的 [AGENTS.md](../../../../../zmdmod/modecontroller/AGENTS.md) 与 `CONTRIBUTING.md`（本 skill 只补"新增组件"这条线）。

## 一、先判形态：它属于哪一类？

| 形态 | 参照物 | "装载"是什么 | 开关怎么实现 |
| --- | --- | --- | --- |
| **游戏目录 proxy 注入型** | 乳摇 `secondary_motion.py` | 替换游戏目录 `d3dcompiler_47.dll` / `vulkan-1.dll` + `plugin\*.dll` | 真装卸（还原 `.bak`）+ 认"别的插件还在用" |
| **包装上游向导型** | Poser `poser.py` | 下安装包 → 调上游自己的 `deploy.ps1` | 重命名 `plugin\poser.dll`（可逆、不动 proxy） |
| **EFMI Mod 包型** | EndfieldJiggle `efmi_jiggle.py` | 往 `EFMI\Mods` 铺一个目录 | **把目录移出 Mods**（见下方红线） |

## 二、必须同步的落点（漏一处就半成品）

**组件实现**
- 新建 `endfieldmodcontroller/<name>.py`：`status()` / `install()`（本地就位则零网络）/ `set_enabled()` / `import_pack()` / `verify()` / `repack_from_local()`。仿 `poser.py`（结构最干净）。

**配置**
- `config.py`：字段（`xxx_dir`、`xxx_injection`）+ 属性（`xxx_path`）+ 把 `xxx_dir` 加进 `_DATA_ROOT_RELATIVE_FIELDS`。
- 默认值：**跟产品语义走**，别顺手抄参照物（用户 2026-10-13 定过一版："防护开、ReShade 管的关、其他都开"）。

**staging 三份平行白名单**（⚠️ 只有"往 `EFMI\Mods` 铺目录"的组件才需要；各写一份，必须同步）
- `activation.CONTROLLER_OWNED_NAMES`
- `initialize.MOD_CONFLICT_IGNORE_NAMES`
- `crashwatch._CONTROLLER_DIRS`
> 少任何一处：`find_manual_mods` 会把它当"用户手工放的 Mod"→ `import_manual_mods` **copytree 进库、勾选、再从 staging 移走**。触发点是 `api.prepare_launch`（点一次「生成控制器」），**不受** `auto_adopt_manual_mods` 开关保护。

**自检 / 接口 / 更新链**
- `initialize.py`：`_check_<name>()` + 在 `ensure_all()` 里调用（"铺目录"类动作必须排在 `_check_staging` / `_check_controller` **之后**，它们会重建 Mods）。
- `api.py`：`xxx_status` / `xxx_install` / `xxx_uninstall`（后两个必须走 `_persist_injection_switch`，否则界面会被旧值弹回）；`_dependency_report()` 加 `report["manifest"]["xxx"]`（依赖页是泛型渲染，加这一条就够了，**前端零改动**）；`start_full_update()` 加一段 + **同步 `_estimate_update_total()` 分母**；`pending_component_updates()` 的外部键列表；`update_component()` 分支。
- `updates.py`：`component_versions()` 条目 + `check_updates()` 一节 + `update_<name>()`（**文件名要保留资产原名**，版本号是从文件名解析的）。
- `component_versions.json` 的 `external` 段（发版闸 `scripts/check_component_versions.py --strict` 读它）。
- `alerts.py` 的 `INJECTION_FIELDS`（安全模式「还原配置」靠它关开关）。

**前端**
- `frontend/src/pages/LaunchPage.vue` 的 `SWITCHES` 加一条（有真实动作的走 `apply`）；受总闸管的还要加 `locked`/`lockReason` 并进 `RESHADE_DEPENDENT`。
- `frontend/src/pages/SettingsPage.vue`：状态查询进 `PROBES`，打开上游/日志这类入口放这里（**项目铁律：启动页只放开关**）。

**收尾**
- 测试（新增 + 同步被改动语义影响的旧断言）、结构树（见 skill `emc-structure-closeout`）、`TESTING.md` 末尾追加编号条目给用户点验。

## 三、三条硬约束（越线就是白干）

1. **`library/` 只读**——不删、不移、不改名。组件自己的东西一律放 `<数据根>\runtime\<组件>`。
2. **不动第三方依赖本体**（XXMI / EFMI / ReShade / 乳摇 / Poser）——改了会被上游更新覆盖、静默失效。
3. **别在启动流程里偷偷下载**——本地已就位就零网络请求；显式入口（依赖页）才 `force=True`。

## 四、"关"要真的关掉

- EFMI 的 `d3dx.ini` 是 `include_recursive = Mods`——**改名、挪进子目录都挡不住加载**，必须把目录**移出** Mods。
- 有 loader 共享的组件（乳摇 / Poser）卸载前先问"还有别人在用吗"，**"被停用"也算在用**。

## 五、诚实报状态

- 别只判"文件在不在"：**存在 ≠ 正确**。该按 sha256 / 必需文件清单 / 大小校验的就校验（本项目返工最多的一类 bug）。
- 组件的"能不能生效"若取决于外部（如按游戏 shader 抓的兼容材料），要在文案里说清，不要承诺"装了就一定有效果"。
