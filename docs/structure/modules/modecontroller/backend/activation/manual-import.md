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
      
revision: 4c6f9c516371a0e037c4a033a394270fa154178d
updated_at: "2026-10-07T05:13:35.505Z"
fingerprint: 1c66d0a8893ddf5663010da5c68274f9657a68639d706dc41c8a61917df95902
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
