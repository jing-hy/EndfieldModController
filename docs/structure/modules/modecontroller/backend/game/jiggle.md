---
uid: b1d10004
id: modecontroller.backend.game.jiggle
parent: modecontroller.backend.game
tags: [jiggle]
name: {zh: "乳摇物理插件", en: "Jiggle Physics Plugin"}
description:
  zh: >
      乳摇物理插件：报告已装版本与代理归属、决定用哪份上游构建、注入或移除它的 dll、同步它的管理器设置，并从控制器里启动它的管理器界面。
      
  en: >
      The jiggle-physics plugin: report installed version and proxy ownership, resolve which upstream build to use, inject or remove its dll, keep its manager settings in sync, and launch its manager UI from the controller.
      
revision: 45e4d6d07cf81770c867c10f0f053a5efbf5e978
updated_at: "2026-10-03T15:48:42.304Z"
fingerprint: d56c291f41c0573cd191dcb7dabeb3ad7d89d44864c8eef399ce963d4c4cc2cd
source:
  - path: "endfieldmodcontroller/secondary_motion.py"
    line: 50
    end_line: 395
  - path: "endfieldmodcontroller/secondary_motion.py"
    line: 298
    end_line: 527
  - path: "endfieldmodcontroller/secondary_motion.py"
    line: 368
    end_line: 928
apis:
  - protocol: rpc
    path: "secondary_motion.status"
    description:
      zh: >
          已装版本、代理归属，以及数据文件是否就绪。
          
      en: >
          Installed version, proxy ownership and whether the data files are ready.
          
  - protocol: rpc
    path: "secondary_motion.ensure_injection"
    description:
      zh: >
          铺两个 loader 代理 + `plugin/sbm.dll` 与最小数据集（185 KB，随包带）。
          
      en: >
          Deploy the two loader proxies plus plugin/sbm.dll and the minimum data set (185 KB, shipped).
          
  - protocol: rpc
    path: "secondary_motion.remove_injection"
    description:
      zh: >
          卸掉注入：**先还原 .bak 代理、再删**，两步独立、互不连坐。
          
      en: >
          Remove the injection, restoring the .bak proxies first and only then deleting — two independent steps.
          
  - protocol: rpc
    path: "secondary_motion.launch_manager"
    description:
      zh: >
          启动它自己的管理器界面。
          
      en: >
          Launch the plugin's own manager UI.
          
deps:
  - kind: call
    to: modecontroller.backend.game.reshade-deploy
    label: {zh: "靠部署类型", en: "Uses deploy kind"}
---
