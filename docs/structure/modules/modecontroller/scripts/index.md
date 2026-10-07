---
uid: b1c0a003
id: modecontroller.scripts
parent: modecontroller
tags: [tooling, release]
name: {zh: "开发与发布脚本", en: "Dev & Release Scripts"}
description:
  zh: >
      scripts/ 下的工程脚本：构建单文件 exe 与 ReShade 面板、打包随包资产、状态快照、推送 GitHub、准备与上传 Release 附件、版本号规则核对、拉取官网角色表、生成拼音别名与热键词表、ini 体检等。只在开发机使用，不进 exe。
      
  en: >
      Engineering scripts under scripts/: build the single-file exe and the ReShade addon, pack bundled assets, take state snapshots, push to GitHub, prepare and upload release assets, check the version-number rule, fetch official character tables, generate pinyin aliases and hotkey hints, lint inis. Dev-machine only; not shipped in the exe.
      
revision: 4c6f9c516371a0e037c4a033a394270fa154178d
updated_at: "2026-10-07T05:13:35.538Z"
fingerprint: 43a12e7aa686e98abb14622a9405a602e9269e091244ae2ef1e423821f15bf89
source:
  - path: "scripts/build_release.py"
  - path: "scripts/push.py"
  - path: "scripts/release_version.py"
---
