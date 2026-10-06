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
      
revision: ec6d352f646115c51b7b413c56b5095ba5e52eeb
updated_at: "2026-10-06T05:52:00.989Z"
fingerprint: 2c34458ec1ad939f91f90a651d97b33485273c7c5c41dc54890b6f4b4a9c8b59
source:
  - path: "scripts/prepare_release.py"
    line: 1
    end_line: 212
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
