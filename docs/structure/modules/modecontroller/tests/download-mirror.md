---
uid: b1d0e505
id: modecontroller.tests.download-mirror
parent: modecontroller.tests
tags: [tests]
name: {zh: "镜像源测试", en: "Mirror Source Tests"}
description:
  zh: >
      钉住 GitHub 镜像表的判据：自动/仅直连/手选某条、脏域名回落自动、死域名不硬塞、选完能切回自动。
      
  en: >
      Pins the mirror table semantics: auto / direct-only / picked mirror, unknown names fall back to auto, dead domains are not forced first, and switching back to auto always works.
      
revision: 702c5e42321f8e9b483e17ba55f39b5eed1fc548
updated_at: "2026-11-28T16:50:57.019Z"
fingerprint: 1228365e25a64a1b070eed63b44333fd83e1816cf582cb950741e5e6cdb30c24
source:
  - path: "tests/test_download_mirror.py"
    line: 130
    end_line: 387
apis: []
---
