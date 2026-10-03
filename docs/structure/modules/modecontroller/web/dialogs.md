---
uid: b1d1300a
id: modecontroller.web.dialogs
parent: modecontroller.web
tags: [dialogs]
name: {zh: "弹窗与安全门", en: "Dialogs & Gates"}
description:
  zh: >
      命令式弹窗与 Toast（Vue）：保留旧 API（showAlert / showConfirm / showModalDialog，Promise 版）以便业务代码零改动地搬过来。
      
  en: >
      Imperative dialogs and toasts (Vue) keeping the legacy API so business code could move over unchanged.
      
revision: 45e4d6d07cf81770c867c10f0f053a5efbf5e978
updated_at: "2026-10-03T15:48:42.332Z"
fingerprint: 073bf9a8ce955a68277da76bc5fc54ced82364a8ba592c2e33917e1efdfbdc3d
source:
  - path: "frontend/src/lib/dialog.js"
    line: 1
    end_line: 166
apis:
  - protocol: rpc
    path: "web.showModalDialog"
    description:
      zh: >
          公用的弹窗：主选在右、按钮文字自解释、默认聚焦安全项。
          
      en: >
          The shared dialog: primary action on the right, self-explaining button text, default focus on the safe choice.
          
  - protocol: rpc
    path: "web.showConflictResolveModal"
    description:
      zh: >
          每组冲突一个下拉框，选保留哪个。
          
      en: >
          Pick which mod to keep for each conflict group (one dropdown per group).
          
  - protocol: rpc
    path: "web.showAlertGate"
    description:
      zh: >
          不可跳过的 critical 预警安全门：倒计时、三选一、默认聚焦“还原配置”。
          
      en: >
          The unskippable critical-alert gate: countdown, three choices, restore-config focused by default.
          
  - protocol: rpc
    path: "web.maybeShowAnnouncements"
    description:
      zh: >
          公告按 id 只弹一次（幂等，每次刷新状态后都可以放心调）。
          
      en: >
          Show announcements once per id (idempotent, safe to call after every state refresh).
          
  - protocol: rpc
    path: "web.showCrashModal"
    description:
      zh: >
          崩溃弹窗 —— 归因判定为 Mod 资源冲突时它长得不一样。
          
      en: >
          The crash modal, which differs when the verdict says "mod resource conflict".
          
deps:
  - kind: call
    to: modecontroller.backend.api.risk
    label: {zh: "读风险数据", en: "Reads risk payload"}
---
