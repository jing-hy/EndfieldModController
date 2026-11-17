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
      
revision: 8bc32703d96b038ba06f91f7f4a5a9a7076791ac
updated_at: "2026-11-17T16:18:39.121Z"
fingerprint: 764433a7a1b948267d1c4af68c89d0c7b799517c2ed6b118b29aa5b8bcd7b48a
source:
  - path: "scripts/ui_ctl.py"
    line: 1
    end_line: 174
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
