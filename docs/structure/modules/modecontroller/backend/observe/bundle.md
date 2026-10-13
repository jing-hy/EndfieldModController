---
uid: b1d0f004
id: modecontroller.backend.observe.bundle
parent: modecontroller.backend.observe
tags: [bundle]
name: {zh: "崩溃包", en: "Crash Bundle"}
description:
  zh: >
      把现场打包给人类 / issue：把控制器日志、游戏日志、崩溃转储、事件日志片段、配置摘录与 Mods 目录树收进一个 zip，并附一份渲染好的报告 —— 因为用户只有一次反馈机会。
      
  en: >
      Package the scene for a human or an issue: copy controller logs, game logs, crash dumps, event-log slice, config excerpts and the mods tree into one zip plus a rendered report — because the user gets one shot at reporting.
      
revision: d6153bf31b870c1ccd2e00dac49af51793b5267a
updated_at: "2026-10-13T16:02:57.655Z"
fingerprint: d6da2d78e8e74533cf62f56410aedd8e735f25e10844e43bb7b754edef6088a8
source:
  - path: "endfieldmodcontroller/crashwatch.py"
    line: 2663
    end_line: 5331
  - path: "endfieldmodcontroller/crashwatch.py"
    line: 3214
    end_line: 5576
apis:
  - protocol: rpc
    path: "make_bundle"
    description:
      zh: >
          打崩溃包：报告、游戏日志、转储、事件日志片段、配置摘录、Mods 目录树与运行时件清单。
          
      en: >
          Build the crash zip: report, game logs, dumps, event-log slice, config excerpts, the mods tree and a runtime inventory.
          
  - protocol: rpc
    path: "take_bundle"
    description:
      zh: >
          把最新的崩溃包交给界面，且**只提示一次**。
          
      en: >
          Hand the newest bundle to the UI exactly once.
          
  - protocol: rpc
    path: "latest_bundle"
    description:
      zh: >
          最近一个崩溃包的路径（给状态查询用）。
          
      en: >
          Path of the most recent bundle (for the status call).
          
deps:
  - kind: call
    to: modecontroller.backend.observe.report
    label: {zh: "写报告正文", en: "Writes the report"}
---
