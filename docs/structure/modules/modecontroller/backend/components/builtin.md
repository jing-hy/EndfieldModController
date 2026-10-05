---
uid: b1d11004
id: modecontroller.backend.components.builtin
parent: modecontroller.backend.components
tags: [builtin]
name: {zh: "内置组件", en: "Built-in Components"}
description:
  zh: >
      内置组件（XXMI / XXMI-Libs / EFMI / Endfield Poser）：报告、补齐、更新。 ⚠️ 2026-10-03：「自动更新依赖」**关着**且本地已就位 ⇒ **一个网络请求都不发**（日志写「跳过联网检查」）。之前只有 XXMI 尊重那个开关，另外三个在启动流程里**静默下载**（实测 Poser 一步 54 秒，整个启动 62 秒）。显式点「一键更新全部组件」走 `force=True`，照旧真的下载。
      
  en: >
      Built-in components (XXMI / XXMI-Libs / EFMI / Endfield Poser): report, ensure, update. ⚠️ When “auto-update dependencies” is off and a local copy exists, **no network request is made at all** — before, only XXMI honoured that switch and the other three silently downloaded tens of MB during startup (measured: 54 s on Poser alone).
      
revision: 45e4d6d07cf81770c867c10f0f053a5efbf5e978
updated_at: "2026-10-03T15:48:42.299Z"
fingerprint: ec63e2d31a3dd8e7aa78cb23404530c6f1decb907a9a05343451912d318f205c
source:
  - path: "endfieldmodcontroller/runtime_deps.py"
    line: 36
    end_line: 104
  - path: "endfieldmodcontroller/runtime_deps.py"
    line: 104
    end_line: 409
  - path: "endfieldmodcontroller/runtime_deps.py"
    line: 188
    end_line: 776
apis:
  - protocol: rpc
    path: "runtime_deps.ensure_all"
    description:
      zh: >
          维护 XXMI / 库集 / EFMI / Poser 的唯一枢纽 —— 往这里加一项就同时进入全部四条链路。
          
      en: >
          The single hub that keeps XXMI / libs / EFMI / Poser in place — adding a component here wires it into all four routes at once.
          
  - protocol: rpc
    path: "runtime_deps.builtin_report"
    description:
      zh: >
          逐组件的内置报告，合并进依赖页显示。
          
      en: >
          Per-component built-in report merged into the dependency page.
          
---
