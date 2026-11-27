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
      
revision: 4467eb0705c4b5e7557d2c9d18f21d53778bd2de
updated_at: "2026-11-27T14:08:48.111Z"
fingerprint: 1228365e25a64a1b070eed63b44333fd83e1816cf582cb950741e5e6cdb30c24
source:
  - path: "tests/test_download_mirror.py"
    line: 130
    end_line: 387
apis: []
---
