---
uid: b1d0d004
id: modecontroller.backend.launch.dlss5-targets
parent: modecontroller.backend.launch
tags: [dlss5]
name: {zh: "XXMI 注入库", en: "XXMI Injection Library"}
description:
  zh: >
      注入库（extra_libraries）里到底写什么、以及它必须和谁一致：ReShade 底座 d3d12.dll + EFMI 的 d3d11.dll（顺序不能反）。列的那份 loader 必须与 XXMI 自己会注入的那份是同一个文件（同路径它才会去重）—— importer_folder 被指到别处（实测是 Mod 库）时 XXMI 会去注入另一份同名 loader，此时不再叠加第二条，并把那个配置字段自动改回这个 XXMI 自己的目录（原值备份、可回滚）。
      
  en: >
      What goes into the injection library (extra_libraries) and who it must agree with: the ReShade base d3d12.dll plus EFMI's d3d11.dll, in that order. The loader listed must be the same file XXMI itself injects (same path, so it dedupes); when importer_folder points elsewhere XXMI injects a second same-named loader, so no second entry is added and that setting is repaired back to this installation's own directory.
      
revision: 7c36babb44091a5965ab7f0da97455ec81ad7f61
updated_at: "2026-10-07T07:30:40.237Z"
fingerprint: e6caf67402aa640892ab0f595aed44045002c053eb58f71cc2467be001d1956a
source:
  - path: "endfieldmodcontroller/launcher.py"
    line: 249
    end_line: 400
  - path: "endfieldmodcontroller/launcher.py"
    line: 1092
    end_line: 4082
  - path: "endfieldmodcontroller/launcher.py"
    line: 2404
    end_line: 4970
apis:
  - protocol: rpc
    path: "dlss5_injection_targets"
    description:
      zh: >
          这次部署里注入库该列哪些 dll：ReShade 底座 + EFMI loader（后者与 XXMI 自己那份同路径时才列）。
          
      en: >
          Which DLLs the injection library should list: the ReShade base plus the EFMI loader (listed only when it is the same file XXMI itself injects).
          
  - protocol: rpc
    path: "configure_dlss5_injection"
    description:
      zh: >
          一步配好注入库及其签名（先纠正 XXMI 的 EFMI 运行目录、再重新读配置写入）。
          
      en: >
          Configure the injection library and its signing in one step (repair XXMI's EFMI folder first, then re-read the config before writing).
          
  - protocol: rpc
    path: "ensure_efmi_importer_folder"
    description:
      zh: >
          把 XXMI 的 EFMI 运行目录改回这个 XXMI 自己的那份（原值备份、可回滚）—— 避免它去注入另一个目录里的同名 loader。
          
      en: >
          Repair XXMI's EFMI importer folder back to this installation's own directory (backed up, reversible) so it stops injecting a same-named loader from elsewhere.
          
  - protocol: rpc
    path: "xxmi_importer_folder"
    description:
      zh: >
          读出 XXMI 的 importer_folder 现状：原值、解析路径、是否在这个 XXMI 树内、里面有没有 d3d11.dll / d3dx.ini。
          
      en: >
          Read the current importer_folder: raw value, resolved path, whether it is inside this XXMI, and whether d3d11.dll / d3dx.ini live there.
          
  - protocol: rpc
    path: "xxmi_foreign_loader"
    description:
      zh: >
          判断 XXMI 自己会不会去注入一份落在这个 XXMI 之外的 loader。
          
      en: >
          Detect whether XXMI would inject a loader living outside this installation.
          
  - protocol: rpc
    path: "prepare_reshade_runtime"
    description:
      zh: >
          把 ReShade 运行时、环境变量与 shader 搜索路径摆好。
          
      en: >
          Stage the ReShade runtime with the right environment and effect search paths.
          
---
