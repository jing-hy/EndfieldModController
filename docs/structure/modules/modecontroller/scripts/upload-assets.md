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
      
revision: fc554f9d7ee000bfbf7fb07d55f223390dff7a4e
updated_at: "2026-11-28T14:59:05.771Z"
fingerprint: 638a42806b249cddc5b17b0de428d85f16d889cabdfe0e1cf96e56517f979db6
source:
  - path: "scripts/upload_release_assets.py"
    line: 2
    end_line: 298
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
