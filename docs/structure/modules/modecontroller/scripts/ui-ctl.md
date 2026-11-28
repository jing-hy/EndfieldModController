---
uid: b1d0e503
id: modecontroller.scripts.ui-ctl
parent: modecontroller.scripts
tags: [scripts, automation]
name: {zh: "界面操作命令行", en: "UI Control CLI"}
description:
  zh: >
      读 runtime/_state/ui_api.json 里的端口与 token，用命令行操作界面：看快照、按文字找元素、切页、点开关、赋值、滚动。
      
  en: >
      Reads port and token from runtime/_state/ui_api.json and drives the UI from the shell: snapshot, find by label, switch tabs, toggle switches, set values, scroll.
      
revision: 5b034875dd0ea08fcd1a78982c72969af5d72139
updated_at: "2026-11-28T15:58:50.129Z"
fingerprint: e3143135416810e9866c9566d1c4538ded16fe3a920ca2eea9c814fb4bec4a10
source:
  - path: "scripts/ui_ctl.py"
    line: 185
    end_line: 542
apis:
  - protocol: rpc
    path: "ui_ctl.py"
    description:
      zh: >
          命令行入口：state / find / tab / click / set / value / scroll / scroll-by。
          
      en: >
          CLI entry: state / find / tab / click / set / value / scroll / scroll-by.
          
deps:
  - kind: call
    to: modecontroller.backend.shell.ui-automation
    label: {zh: "调本地 HTTP 接口", en: "Call the local HTTP API"}
---
