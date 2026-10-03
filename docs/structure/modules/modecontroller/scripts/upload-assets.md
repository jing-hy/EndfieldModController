---
uid: b1d14009
id: modecontroller.scripts.upload-assets
parent: modecontroller.scripts
tags: [release]
name: {zh: "上传 Release 附件", en: "Upload Release Assets"}
description:
  zh: >
      上传那两个 Release 附件，并绕开本机网络的坑：先用 DoH 拿到 GitHub 真实 IP，再用 curl --resolve 发送，避免上传死在 DNS 污染上；逐文件报 HTTP 状态与耗时。
      
  en: >
      Upload the two release assets, working around this network: resolve the real GitHub IP over DoH, then send with curl --resolve so the upload does not die on a hijacked DNS answer; reports per-file HTTP status and timing.
      
revision: 45e4d6d07cf81770c867c10f0f053a5efbf5e978
updated_at: "2026-10-03T15:48:42.324Z"
fingerprint: c55c7c15415e02e99dd31b1208f591f510f369f791e201d1b9a512cffa1e0d52
source:
  - path: "scripts/upload_release_assets.py"
    line: 1
    end_line: 180
apis:
  - protocol: rpc
    path: "scripts.upload_release_assets"
    description:
      zh: >
          上传那两个 Release 附件，并绕开本机网络：DoH 查真实 IP + `curl --resolve` 发送。
          
      en: >
          Upload the two release assets over this network by resolving GitHub's real IP via DoH and sending with curl --resolve.
          
deps:
  - kind: call
    to: modecontroller.scripts.push
    label: {zh: "用 GitHub API", en: "Uses GitHub API"}
  - kind: call
    to: modecontroller.scripts.prepare-release
    label: {zh: "用切好的附件", en: "Uses cut assets"}
---
