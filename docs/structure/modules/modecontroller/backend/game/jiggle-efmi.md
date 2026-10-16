---
uid: b1d1000b
id: modecontroller.backend.game.jiggle-efmi
parent: modecontroller.backend.game
tags: [jiggle, efmi, mod]
name: {zh: "EndfieldJiggle 触摸形变", en: "EndfieldJiggle Touch Deformation"}
description:
  zh: >
      EndfieldJiggle（触摸形变 Mod）集成：它**不装游戏目录**，只是 EFMI 框架下的一个 Mod 目录 —— 铺进 / 移出 `EFMI\Mods` 就是它的开关；另含内容级完整性校验（逐文件 sha256 基线 + zip CRC + 上游 SHA256SUMS）与本地原始包自愈重铺。
      
  en: >
      EndfieldJiggle (touch-deformation mod) integration: it never touches the game folder — it is just a Mod directory under the EFMI framework, so toggling means deploying into or moving out of EFMI\Mods. Also carries content-level integrity checks (per-file sha256 baseline, zip CRC, upstream SHA256SUMS) and local re-pack repair.
      
revision: aa44cfc4d4acf8d739688300e2e94583b312f729
updated_at: "2026-10-16T14:01:30.033Z"
fingerprint: de6dbef501c53a6dc3d0d79d7e55a725cc0eee1a81b51b8067c40b8e3a1d1a0d
source:
  - path: "endfieldmodcontroller/efmi_jiggle.py"
    line: 649
    end_line: 1923
apis:
  - protocol: rpc
    path: "efmi_jiggle.status"
    description:
      zh: >
          状态：是否铺在 `EFMI\Mods`、本地载荷/停用副本、EFMI 版本门槛，以及**内容级校验结果**（损坏/缺失文件清单）。
          
      en: >
          Status: deployment in EFMI\Mods, local payload/parked copies, EFMI version gate, and the content-level verification result.
          
  - protocol: rpc
    path: "efmi_jiggle.install"
    description:
      zh: >
          本地载荷在位就一个字节都不下；否则从上游 Release 下**纯 Mod 包**（约 120 KB，排除 72 MB 拖放包与 149 MB 独立包）并用上游 sha256 校验。
          
      en: >
          Fetches only the plain Mod package (~120 KB) from upstream, verified against upstream sha256; nothing is downloaded when a local payload exists.
          
  - protocol: rpc
    path: "efmi_jiggle.set_enabled"
    description:
      zh: >
          开关：开 = 铺进 `EFMI\Mods`，关 = **真移出**（EFMI 是 `include_recursive = Mods`，改名挡不住加载）。
          
      en: >
          Toggle: on deploys into EFMI\Mods, off really moves it out (EFMI uses include_recursive = Mods).
          
  - protocol: rpc
    path: "efmi_jiggle.verify"
    description:
      zh: >
          按安装时记下的逐文件 sha256 比对，查出「文件在、内容不对」（半截下载 / 被破坏 / 复制中断）。
          
      en: >
          Compares against the per-file sha256 baseline recorded at install time to catch files that exist but are corrupt.
          
  - protocol: rpc
    path: "efmi_jiggle.repack_from_local"
    description:
      zh: >
          用留在 `_pack` 里的原始安装包重解载荷（不联网的自愈路径）。
          
      en: >
          Re-extracts the payload from the original archive kept in _pack — the offline repair path.
          
deps:
  - kind: call
    to: modecontroller.backend.activation.stage
    label: {zh: "往 EFMI\\Mods（staging）铺目录 / 移出", en: "Deploy/remove in Mods"}
  - kind: call
    to: modecontroller.backend.upkeep.component-updates
    label: {zh: "版本检查与更新入口", en: "Version check and update"}
---

EndfieldJiggle-EFMI（上游 woakato/EndfieldJiggle-EFMI，GPL-3.0-only）是《明日方舟：终末地》的"鼠标拖动角色表面、松手回弹"形变 Mod。

**与乳摇 / Poser 不是一类东西**：那两个是"游戏目录 proxy + `plugin\*.dll`"注入型插件，而它只是 **EFMI 框架下的一个 Mod 目录** —— 放进 `EFMI\Mods` 就会被 `include_recursive` 加载。所以本模块的"装卸"就是铺目录 / 移出目录，**不碰游戏目录、不需要 loader**。

关键约束：

- **「关」必须真的移出 `Mods`**：EFMI 的 `d3dx.ini` 是 `include_recursive = Mods`，改名或挪进子目录**都挡不住加载**。
- **三份 staging 白名单要同步**：`activation.CONTROLLER_OWNED_NAMES`、`initialize.MOD_CONFLICT_IGNORE_NAMES`、`crashwatch._CONTROLLER_DIRS` —— 少一处就会被 `import_manual_mods` 当"用户手工放的 Mod"收编进库再从 staging 搬走（点「生成控制器」即触发）。
- **不随包分发**：上游声明源码许可不转授其中的游戏衍生兼容材料（`Passes.ini` 等），所以只从官方 Release 下纯 Mod 包。
- **诚实报状态**：能否生效由上游抓的游戏 shader 决定（`Passes.ini` 是 12 组 ShaderRegex），游戏更新可能失配，表现为游戏内 `EJ: NO COMPATIBLE NATIVE PROGRAM`；本模块不承诺"装了就一定有效果"。
- **默认关闭**（`jiggle_efmi_injection = False`）：上游自述游戏内视觉、同进程热重载、全干员覆盖均未验证。
