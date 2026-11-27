---
uid: b1d14006
id: modecontroller.scripts.build-release
parent: modecontroller.scripts
tags: [release]
name: {zh: "发布构建", en: "Release Build"}
description:
  zh: >
      一条命令走完发布构建：按“最新 Release + 1”核对版本号、跑全量测试、重建 exe、再构一个伪旧版用于测更新、把产物归置进 _old、并同步测试目录。
      
  en: >
      The one-command release build: verify the version rule against the latest Release, run the full test suite, rebuild the exe, build a fake-old-version copy for update testing, tidy artefacts into _old, and sync the test directory.
      
revision: 4467eb0705c4b5e7557d2c9d18f21d53778bd2de
updated_at: "2026-11-27T14:08:48.104Z"
fingerprint: a0038329a2a3d967664a90276edfbca3c38e45a3b3cf3a9adf8c7ad3a399f38b
source:
  - path: "scripts/build_release.py"
    line: 2
apis:
  - protocol: rpc
    path: "scripts.build_release"
    description:
      zh: >
          一条命令走完发布构建：版本号规则 → 静态检查 → 测试 → exe → 伪旧版 → 归置 `_old` → 同步测试目录。
          
      en: >
          One-command release build: version rule → static checks → tests → exe → fake-old copy → tidy _old → sync the test directory.
          
deps:
  - kind: call
    to: modecontroller.scripts.release-version
    label: {zh: "核对版本规则", en: "Checks version rule"}
---
