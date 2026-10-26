---
uid: b1d1000b
id: modecontroller.backend.game.jiggle-efmi
parent: modecontroller.backend.game
tags: [jiggle, efmi, mod]
name: {zh: "EndfieldJiggle 触摸形变", en: "EndfieldJiggle Touch Deformation"}
description:
  zh: >
      EndfieldJiggle（触摸形变 Mod）：已改成 Mod 库里的普通辅助 Mod —— 自动装进库并默认勾选，一键启动按普通 Mod 流程 stage 进 EFMI\Mods；另含内容级完整性校验（逐文件 sha256 + zip CRC + 上游 SHA256SUMS）与本地原始包自愈。
      
  en: >
      EndfieldJiggle (touch-deformation mod) is now a plain assist mod in the library: auto-installed and pre-selected, staged into EFMI\Mods by the normal launch flow. Also carries content-level integrity checks and local re-pack repair.
      
revision: 4c20d3f6f853c184a5b5f45604e8a406d2d05d30
updated_at: "2026-10-26T13:41:19.205Z"
fingerprint: a30289a9ac4fc2db27756173a3374a597c6e66d447cb9e6d0f35f8c67ba1701a
source:
  - path: "endfieldmodcontroller/efmi_jiggle.py"
    line: 1123
    end_line: 2871
apis:
  - protocol: rpc
    path: "efmi_jiggle.status"
    description:
      zh: >
          状态：是否在 Mod 库、版本、EFMI 版本门槛，以及内容级校验结果（损坏/缺失文件清单）。
          
      en: >
          Status: presence in the mod library, version, EFMI gate, and content-level verification result.
          
  - protocol: rpc
    path: "efmi_jiggle.install_to_library"
    description:
      zh: >
          把上游纯 Mod 包装进 Mod 库（幂等；本地载荷优先，零网络；写 sidecar 并默认勾选）。
          
      en: >
          Install the plain upstream Mod package into the library (idempotent, local payload first).
          
  - protocol: rpc
    path: "efmi_jiggle.ensure_in_library"
    description:
      zh: >
          一键启动/生成控制器/自检共用：保证它在库里（没有就装、旧 Mods 目录收进库、失败节流，不拦启动）。
          
      en: >
          Ensure the mod lives in the library before staging; adopts the legacy Mods dir, throttles failures.
          
  - protocol: rpc
    path: "efmi_jiggle.verify"
    description:
      zh: >
          按安装时记下的逐文件 sha256 比对，查出「文件在、内容不对」。
          
      en: >
          Compare against the per-file sha256 baseline to catch files that exist but are corrupt.
          
  - protocol: rpc
    path: "efmi_jiggle.repack_from_local"
    description:
      zh: >
          用留在 _pack 里的原始安装包重解载荷（不联网的自愈路径）。
          
      en: >
          Re-extract the payload from the original archive kept in _pack (offline self-repair).
          
deps:
  - kind: call
    to: modecontroller.backend.activation.stage
    label: {zh: "往 EFMI\\Mods（staging）铺目录 / 移出", en: "Deploy/remove in Mods"}
  - kind: call
    to: modecontroller.backend.upkeep.component-updates
    label: {zh: "版本检查与更新入口", en: "Version check and update"}
---

EndfieldJiggle-EFMI（上游 woakato/EndfieldJiggle-EFMI，GPL-3.0-only）是《明日方舟：终末地》的"鼠标拖动角色表面、松手回弹"形变 Mod。

**2026-10-19 起它不再是"自带组件"**（用户要求：「触摸 mod 移出自带，加入自动识别进辅助 mod」）：它是 **Mod 库里的一个普通辅助 Mod**，走和其它 Mod 完全相同的开关（辅助 Mod 页的勾选），由 `stage_and_prepare` 铺进 `EFMI\Mods\MC_其它辅助_EndfieldJiggleEFMI`。起因是反馈"触摸一键启动不行、需要手动移动进 Mods" —— 旧实现只在初始化自检那条路部署它，而 `launcher.launch` 根本不跑 initialize。

关键约束：

- **自动装进库**：`ensure_in_library` 接入一键启动（stage 之前）、生成控制器与自检；库里已有就零动作，旧版直接铺在 `Mods` 顶层的目录会被收进库（先复制成功再移除来源）。
- **用户意愿优先**：装进来时默认勾选；之后用户取消勾选就保持关着；用户主动移出/彻底删除它 ⇒ 记 `optout`，不再自动装回。
- **识别**：`core.is_touch_mod`（目录名含 jiggle/触摸，或存在 `EndfieldJiggle.ini`）⇒ `kind=assist` + 「其它辅助」；并且 `looks_like_ui_mod` 直接认它为真 ⇒ **不锁它的键、也不把它的 Key* 塞进 ReShade 面板**（它自己处理输入）。
- **不随包分发**：上游声明源码许可不转授其中的游戏衍生兼容材料（`Passes.ini` 等），所以只从官方 Release 下纯 Mod 包。
- **诚实报状态**：能否生效由上游抓的游戏 shader 决定（`Passes.ini` 是 12 组 ShaderRegex），游戏更新可能失配，表现为游戏内 `EJ: NO COMPATIBLE NATIVE PROGRAM`；本模块不承诺"装了就一定有效果"。
