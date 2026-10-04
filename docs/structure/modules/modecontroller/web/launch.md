---
uid: b1d13009
id: modecontroller.web.launch
parent: modecontroller.web
tags: [launch]
name: {zh: "启动页", en: "Launch Page"}
description:
  zh: >
      启动页（Vue）：一键启动大按钮 + 六个注入开关（与设置页共享同一份 settings 状态）+ 控制台日志框。 乳摇 / Poser 这两个是「拨动即装卸」：后端把动作结果**写回配置**并回传 `{config:{键:值}}`，前端据此回显并同步进 store —— 否则 `refreshState()` 会拿旧配置把开关弹回去（2026-10-03 用户实测「这两个按钮关不掉」）；处理期间还会忽略重复点击（装卸要动游戏目录文件）。
      
  en: >
      Launch page (Vue): one-click start button, six injection toggles sharing settings with the settings page, console log box. The jiggle-physics / Poser toggles apply-and-persist: the backend writes the result back into the config and returns it, so the switch cannot be bounced back by the old value.
      
revision: 45e4d6d07cf81770c867c10f0f053a5efbf5e978
updated_at: "2026-10-03T15:48:42.333Z"
fingerprint: 924d56ae67430c7d9e2425051dc85cb49b96d170a15ffa68a1b54fedd2b9bd13
source:
  - path: "frontend/src/pages/LaunchPage.vue"
    line: 1
    end_line: 778
apis:
  - protocol: rpc
    path: "web.runOneClickLaunch"
    description:
      zh: >
          一键启动序列：预警安全门 → 文件守护 → 风险确认 → 中转准备 → 拉起 → 开崩溃轮询。
          
      en: >
          The one-click sequence: alerts gate → watchdog → risk confirmation → prepare → launch → start crash polling.
          
  - protocol: rpc
    path: "web.previewLaunch"
    description:
      zh: >
          只中转不启动，并显示会加载什么。
          
      en: >
          Stage without launching, showing what would load.
          
  - protocol: rpc
    path: "web.enableSafeMode"
    description:
      zh: >
          进出反作弊安全模式与 d3d12 代理模式。
          
      en: >
          Enter / leave the anti-cheat safe mode and the d3d12 proxy mode.
          
  - protocol: rpc
    path: "web.auditGameInjections"
    description:
      zh: >
          展示注入审计（带分类）与一键清理/还原。
          
      en: >
          Show the injection audit with its classes and one-click clean / restore.
          
  - protocol: rpc
    path: "web.checkAndRepairIntegrity"
    description:
      zh: >
          跑自检、必要时跑修复链 —— 逐项结果写进日志窗。
          
      en: >
          Run the self-check and, if needed, the repair chain — with the per-item results written into the log window.
          
deps:
  - kind: call
    to: modecontroller.backend.api.launch
    label: {zh: "跑启动流程", en: "Runs launch flow"}
  - kind: call
    to: modecontroller.backend.api.inject-guard
    label: {zh: "跑安全动作", en: "Runs safety actions"}
---
