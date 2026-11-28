---
uid: b1d14006
id: modecontroller.scripts.build-release
parent: modecontroller.scripts
tags: [release]
name: {zh: "发布构建", en: "Release Build"}
description:
  zh: >
      一条命令走完发布构建：按「最新 Release + 1」核对版本号、发版闸核对**随包组件版本表与离线依赖包（deps-bundle.zip）**（对不上就中止并给出修复命令）、重建 exe、再构一个伪旧版用于测更新、把产物归置进 _old、并同步测试目录。
      
  en: >
      The one-command release build: verify the version rule against the latest Release, gate on the bundled component-version table **and the offline deps bundle** (an outdated bundle aborts the build with the fix command), rebuild the exe, build a fake-old-version copy for update testing, tidy artefacts into _old, and sync the test directory.
      
revision: 7d3751c3a9deb8ef56ad274079af27fe51475597
updated_at: "2026-11-28T06:33:44.900Z"
fingerprint: 7259fbb84c256adfd6200e4dd93c02ea912b8ff784fb455d0ff5cf4b65bab1f5
source:
  - path: "scripts/build_release.py"
    line: 2
apis:
  - protocol: rpc
    path: "scripts.build_release"
    description:
      zh: >
          一条命令走完发布构建：版本号规则 → 静态检查 → 组件版本表/离线包闸 → 测试 → exe → 伪旧版 → 归置 `_old` → 同步测试目录。
          
      en: >
          One-command release build: version rule → static checks → component-table/offline-bundle gate → tests → exe → fake-old copy → tidy _old → sync the test directory.
          
deps:
  - kind: call
    to: modecontroller.scripts.release-version
    label: {zh: "核对版本规则", en: "Checks version rule"}
---
