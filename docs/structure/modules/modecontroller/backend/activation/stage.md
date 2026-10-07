---
uid: b1d0b005
id: modecontroller.backend.activation.stage
parent: modecontroller.backend.activation
tags: [staging]
name: {zh: "staging 生成", en: "Staging Generation"}
description:
  zh: >
      生成游戏要读的中转树：安全清空中转区、把每个选中的 Mod 以 MC_ 前缀拷过去、清理其 ini、可选接管热键、把默认选项状态带过去、写控制器 Mod，并留下一份可机器读的已中转清单。
      
  en: >
      Produce the staged tree the game reads: clear the staging area safely, copy each selected mod under a MC_ prefix, sanitise its inis, optionally take over hotkeys, carry over default option states, write the controller mod, and leave a machine-readable list of what was staged.
      
revision: 4c6f9c516371a0e037c4a033a394270fa154178d
updated_at: "2026-10-07T05:13:35.506Z"
fingerprint: 1c66d0a8893ddf5663010da5c68274f9657a68639d706dc41c8a61917df95902
source:
  - path: "endfieldmodcontroller/activation.py"
    line: 539
    end_line: 908
  - path: "endfieldmodcontroller/activation.py"
    line: 757
    end_line: 1315
apis:
  - protocol: rpc
    path: "stage_and_prepare"
    description:
      zh: >
          生成游戏要读的中转树：只清我们自己的 `MC_` 产物、逐个拷贝选中的 Mod、清理 ini、可选接管热键、写控制器 Mod。
          
      en: >
          Produce the staged tree the game reads: clean only our own MC_ artefacts, copy each selected mod, sanitise, optionally take over hotkeys, write the controller mod.
          
  - protocol: rpc
    path: "cleanup_staging"
    description:
      zh: >
          清掉我们自己的中转产物，同时**绝不动**用户手动放在那里的东西。
          
      en: >
          Remove our own staging artefacts while refusing to touch anything the user placed there.
          
  - protocol: rpc
    path: "apply_default_action_states"
    description:
      zh: >
          把当前开着的那几档选项状态带进新生成的中转副本。
          
      en: >
          Carry the currently-on option states over into the freshly staged copy.
          
deps:
  - kind: call
    to: modecontroller.backend.activation.resolve
    label: {zh: "用解好的激活集", en: "Uses the resolved set"}
  - kind: call
    to: modecontroller.backend.library.controller
    label: {zh: "写控制器 Mod", en: "Writes controller mod"}
---
