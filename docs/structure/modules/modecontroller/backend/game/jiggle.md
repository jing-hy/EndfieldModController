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
      
revision: 83a004bf635eab9ddbc7e3aa0e1545b11a005bff
updated_at: "2026-10-18T14:16:51.063Z"
fingerprint: 9042f01e6897c0fdee7576e7c5b68400802e765cb903d03564e05ed5f16ae4fb
source:
  - path: "endfieldmodcontroller/secondary_motion.py"
    line: 53
    end_line: 680
  - path: "endfieldmodcontroller/secondary_motion.py"
    line: 434
    end_line: 851
  - path: "endfieldmodcontroller/secondary_motion.py"
    line: 504
    end_line: 1278
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
