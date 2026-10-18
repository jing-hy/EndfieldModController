---
uid: b1d11005
id: modecontroller.backend.components.assets-baseline
parent: modecontroller.backend.components
tags: [baseline]
name: {zh: "资产基线", en: "Asset Baseline"}
description:
  zh: >
      “必须一字不差”的那批文件的基线：资产清单、基线差异检测（哪些已部署文件偏离了随包版本）、摘要、修复动作，以及带哈希的运行时件清单（供诊断包用）。
      
  en: >
      The baseline of files that must be exactly right: the asset manifest, a baseline mismatch detector (which deployed files drifted from the shipped copy), a summary, a repair action, and a runtime inventory with hashes for diagnostic bundles.
      
revision: 67a073215c2dce317e8190d381e16868baade880
updated_at: "2026-10-18T09:12:03.872Z"
fingerprint: 571093f5dd765a9c43ebca8256cc4413b66b99b2ad64b613c995869b8254deb3
source:
  - path: "endfieldmodcontroller/runtime_assets.py"
    line: 86
    end_line: 312
  - path: "endfieldmodcontroller/runtime_assets.py"
    line: 213
    end_line: 1932
apis:
  - protocol: rpc
    path: "baseline_mismatches"
    description:
      zh: >
          哪些已部署文件偏离了随包基线。
          
      en: >
          Which deployed files drifted from the shipped baseline.
          
  - protocol: rpc
    path: "repair_mismatched"
    description:
      zh: >
          把偏离基线的随包组件重新展开（**先把用户那份备份**）。
          
      en: >
          Re-unpack the mismatched bundled components from the baseline, backing the user's copy up first.
          
  - protocol: rpc
    path: "runtime_inventory"
    description:
      zh: >
          运行时件的字节与 sha256 清单，供诊断包用。
          
      en: >
          Byte + sha256 inventory of the runtime, for diagnostic bundles.
          
---
