---
uid: b1d0e003
id: modecontroller.backend.selfcheck.runtime
parent: modecontroller.backend.selfcheck
tags: [runtime]
name: {zh: "运行时文件检查", en: "Runtime File Checks"}
description:
  zh: >
      验运行时自己的文件：展开随包资产、把偏离基线的随包组件按基线重展、确认游戏目录里有启动链需要的 dll，并让 ReShade.ini 与程序的前提一致。
      
  en: >
      Verify the runtime's own files: unpack bundled assets, restore bundled components that drifted from the baseline, make sure the game folder has the dlls the launch chain expects, and keep ReShade.ini coherent with what the program assumes.
      
revision: 83a004bf635eab9ddbc7e3aa0e1545b11a005bff
updated_at: "2026-10-18T14:16:51.081Z"
fingerprint: 334016859c4b0b377474eb3c4dfa8e8207cba1c9329986788d8f207687218859
source:
  - path: "endfieldmodcontroller/initialize.py"
    line: 458
    end_line: 1891
  - path: "endfieldmodcontroller/initialize.py"
    line: 4237
    end_line: 8182
  - path: "endfieldmodcontroller/initialize.py"
    line: 4834
    end_line: 8276
apis:
  - protocol: rpc
    path: "bundled_assets"
    description:
      zh: >
          自检项 key：随包资产是否已展开到预期位置。
          
      en: >
          Self-check key: bundled assets are unpacked where expected.
          
  - protocol: rpc
    path: "bundled_versions"
    description:
      zh: >
          自检项 key：已部署的随包组件是否仍符合基线（偏离就**自动按基线重展开**）。
          
      en: >
          Self-check key: deployed bundled components still match the baseline (auto re-unpacks when they drifted).
          
  - protocol: rpc
    path: "game_libs"
    description:
      zh: >
          自检项 key：游戏目录里有没有启动链需要的 dll。
          
      en: >
          Self-check key: the game folder has the dlls the launch chain expects.
          
  - protocol: rpc
    path: "reshade_ini"
    description:
      zh: >
          自检项 key：ReShade.ini 与程序的前提是否一致。
          
      en: >
          Self-check key: ReShade.ini is coherent with what the program assumes.
          
---
