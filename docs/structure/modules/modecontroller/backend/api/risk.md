---
uid: b1d0c006
id: modecontroller.backend.api.risk
parent: modecontroller.backend.api
tags: [api, risk]
name: {zh: "风险预警与崩溃", en: "Risk, Alerts & Crash"}
description:
  zh: >
      跑之前/之后必须让用户看到的屏障：启动前风险包、冲突分组与“一键处理冲突”、公告与异常预警（含还原配置与撤销）、崩溃包状态与崩溃监视器状态。
      
  en: >
      The guard rails the UI must show before or after a run: pre-launch risk payload, conflict groups and the resolve-conflicts action, announcements and threat alerts (including the safe-mode restore / undo), crash-bundle status and the crash watcher state.
      
revision: 20521577d9cf0d2206617a54825953f305763895
updated_at: "2026-10-07T14:32:31.331Z"
fingerprint: ccf7e6da62fbc5fd85c1836a1d4e69d7b5520a7f3320ac3dddf0ca06aae773bb
source:
  - path: "endfieldmodcontroller/api.py"
    line: 1159
    end_line: 2672
apis:
  - protocol: rpc
    path: "prelaunch_risks"
    description:
      zh: >
          启动前风险包：静态冲突结论 + 这套组合的崩溃记忆。
          
      en: >
          The pre-launch risk payload: static conflict verdict plus remembered crashes for this combination.
          
  - protocol: rpc
    path: "conflict_groups"
    description:
      zh: >
          结构化冲突组（给“选择保留哪个”的弹窗用）。
          
      en: >
          Structured conflict groups (for the “pick which to keep” dialog).
          
  - protocol: rpc
    path: "resolve_mod_conflicts"
    description:
      zh: >
          保留选中的、取消其余的、重新生成控制器 —— **全程不碰 Mod 库**。
          
      en: >
          Keep the chosen mods, untick the rest, and regenerate the controller — without ever touching the library.
          
  - protocol: rpc
    path: "prelaunch_alerts"
    description:
      zh: >
          必须阻断启动的异常预警（critical 条目，带强制停留秒数）。
          
      en: >
          Threat alerts that must gate a launch (critical entries, with hold seconds).
          
  - protocol: rpc
    path: "alert_action"
    description:
      zh: >
          对一条预警做出动作：还原配置 / 暂不启动 / 仍然启动。
          
      en: >
          Act on an alert: restore config / hold / proceed.
          
  - protocol: rpc
    path: "collect_crash_report"
    description:
      zh: >
          不等游戏退出，立刻收一次崩溃报告。
          
      en: >
          Collect a crash report now instead of waiting for the game to exit.
          
deps:
  - kind: call
    to: modecontroller.backend.observe
    label: {zh: "读崩溃记忆", en: "Reads crash memory"}
  - kind: call
    to: modecontroller.backend.upkeep
    label: {zh: "读公告文档", en: "Reads alerts doc"}
---
