---
uid: b1d0b004
id: modecontroller.backend.activation.manual-import
parent: modecontroller.backend.activation
tags: [import]
name: {zh: "手动 Mod 收编", en: "Manual Mod Adoption"}
description:
  zh: >
      收编用户直接丢进游戏 Mods 目录的 Mod：找出不是控制器生成的目录，靠 namespace 特征识别（改名也认得），搬进库，并只在能证明安全时才删掉原目录。
      
  en: >
      Adopt mods the user dropped straight into the game's Mods folder: find directories the controller did not generate, recognise them by namespace signature even if renamed, move them into the library, and delete the original only when it is provably safe.
      
revision: ec6d352f646115c51b7b413c56b5095ba5e52eeb
updated_at: "2026-10-06T05:52:00.952Z"
fingerprint: c738191f4d1490b9970ba92e09859bbd2d55ee2657c9ce9e29ef3ba74891baca
source:
  - path: "endfieldmodcontroller/activation.py"
    line: 396
    end_line: 615
apis:
  - protocol: rpc
    path: "activation.find_manual_mods"
    description:
      zh: >
          找出用户直接丢进游戏 Mods 目录、而非控制器生成的 Mod 目录。
          
      en: >
          Find mod folders the user dropped straight into the game's Mods directory (not controller-generated).
          
  - protocol: rpc
    path: "activation.import_manual_mods"
    description:
      zh: >
          收编它们：靠 namespace 特征识别（改名也认得）、搬进库，只在能证明安全时才删原目录。
          
      en: >
          Adopt them: recognise by namespace signature even if renamed, move into the library, delete the original only when provably safe.
          
deps:
  - kind: call
    to: modecontroller.backend.activation.guard
    label: {zh: "先过安全护栏", en: "Uses the guard"}
---
