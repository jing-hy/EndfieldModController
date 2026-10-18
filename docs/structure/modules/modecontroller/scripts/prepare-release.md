---
uid: b1d14008
id: modecontroller.scripts.prepare-release
parent: modecontroller.scripts
tags: [release]
name: {zh: "准备 Release", en: "Prepare Release"}
description:
  zh: >
      把一次 Release 需要的东西备齐：校验构建产物、重新生成资产包、列清“只上传哪两个文件”并打印 gh 命令 —— 故意到此为止，不替你上传。
      
  en: >
      Assemble what a Release needs: verify the built artefacts, regenerate the assets bundle, list exactly which two files to upload and print the gh command — deliberately stopping short of uploading.
      
revision: 8665ab0f899233347bb25a1f29f1a8e010befe64
updated_at: "2026-10-18T12:50:41.436Z"
fingerprint: cfe4f61e3c9780467a038d28da0d63f1f8b01a99756baa69bbf36c4cb5dd812e
source:
  - path: "scripts/prepare_release.py"
    line: 2
    end_line: 214
apis:
  - protocol: rpc
    path: "scripts.prepare_release"
    description:
      zh: >
          校验产物、重打资产包、列清“只传哪两个文件”并打印命令 —— **故意到此为止，不替你上传**。
          
      en: >
          Verify artefacts, regenerate the assets bundle, and print exactly which two files to upload — deliberately stopping short of uploading.
          
deps:
  - kind: call
    to: modecontroller.scripts.assets-bundle
    label: {zh: "打资产包", en: "Builds assets"}
---
