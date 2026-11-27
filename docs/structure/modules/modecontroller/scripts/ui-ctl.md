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
      
revision: 4467eb0705c4b5e7557d2c9d18f21d53778bd2de
updated_at: "2026-11-27T14:08:48.108Z"
fingerprint: 6d5e2928b5c14120daecc59341cc970232976793c39799ba4b17e2f99c094879
source:
  - path: "scripts/ui_ctl.py"
    line: 175
    end_line: 522
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
