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
      
revision: 0120311d3899178b1012f04bba614b1cec30e883
updated_at: "2026-10-26T14:34:24.396Z"
fingerprint: 494f5a6fe73f7e214b3ac18d664c8c3baf244894df82fa44c3809b74db7dac7e
source:
  - path: "endfieldmodcontroller/initialize.py"
    line: 458
    end_line: 1891
  - path: "endfieldmodcontroller/initialize.py"
    line: 4145
    end_line: 7998
  - path: "endfieldmodcontroller/initialize.py"
    line: 4742
    end_line: 8092
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
