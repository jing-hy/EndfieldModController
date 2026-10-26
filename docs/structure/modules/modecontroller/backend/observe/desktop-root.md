---
uid: b1d0f012
id: modecontroller.backend.observe.desktop-root
parent: modecontroller.backend.observe
tags: [desktop, startup]
name: {zh: "桌面运行提醒", en: "Desktop-root notice"}
description:
  zh: >
      发现程序的数据根就是桌面时，在启动最早期把它搬到 D 盘（没有 D 盘则回退 C 盘）：建目录、复制 exe、桌面建快捷方式、在新位置重启，原实例退出 —— 桌面不会再被 config.json / runtime / assets 铺满。搬不动时如实报告原因，并允许手动把程序挪到磁盘根目录；library（用户的 Mod 库）任何情况下都不删。
      
  en: >
      When the data root is the Desktop folder, relocate the executable at the earliest point of startup: create D:\EndfieldModController (falling back to C:), copy the exe, create a desktop shortcut, restart from the new location and exit the old instance — so config.json / runtime / assets never pile up on the desktop. If the move fails it reports why; library (the user's mod store) is never deleted.
      
revision: 0120311d3899178b1012f04bba614b1cec30e883
updated_at: "2026-10-26T14:34:24.390Z"
fingerprint: 95e43acf97f7d27808eb576b0567b775cf256895928fcadc0ef97e01756f90ec
source:
  - path: "endfieldmodcontroller/desktop_root.py"
apis:
  - protocol: rpc
    path: "desktop_root.report"
    description:
      zh: >
          数据根是否就是桌面、桌面上会生成哪些项、本次搬家成功与否及原因。
          
      en: >
          Whether the data root is the desktop, which entries get generated there, and whether this run's relocation succeeded (and why not).
          
  - protocol: rpc
    path: "desktop_root.relocate_if_needed"
    description:
      zh: >
          启动第一件事：在桌面运行就搬到 D 盘（回退 C 盘）、建快捷方式、启动新实例。
          
      en: >
          First thing at startup: if running from the desktop, move to D: (fallback C:), create a shortcut and launch the new instance.
          
  - protocol: rpc
    path: "desktop_root.target_dir"
    description:
      zh: >
          选目标目录：逐个盘做写入探针，第一个写进去的生效；都不行返回空。
          
      en: >
          Pick the target folder: probe each drive for writability, first one wins; empty when none is writable.
          
  - protocol: rpc
    path: "desktop_root.create_shortcut"
    description:
      zh: >
          用 WScript.Shell 在桌面建一个指向新 exe 的快捷方式（不弹黑窗）。
          
      en: >
          Create a desktop shortcut to the new exe via WScript.Shell (no console window).
          
  - protocol: rpc
    path: "desktop_root.wipe_generated"
    description:
      zh: >
          删掉程序自己生成的 config.json / runtime / assets（手动处置用）；library 永不删。
          
      en: >
          Delete the program's own config.json / runtime / assets (manual cleanup); library is never touched.
          
---
