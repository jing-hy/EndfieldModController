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
      
revision: 4c6f9c516371a0e037c4a033a394270fa154178d
updated_at: "2026-10-07T05:13:35.511Z"
fingerprint: 3fa052e819c484c3d70643f885c7ec32db8ee15a5b2f36533e8aadcdcc8aa591
source:
  - path: "endfieldmodcontroller/runtime_assets.py"
    line: 85
    end_line: 274
  - path: "endfieldmodcontroller/runtime_assets.py"
    line: 194
    end_line: 1820
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
