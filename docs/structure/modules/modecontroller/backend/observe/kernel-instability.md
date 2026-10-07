---
uid: 46ddaca9
id: modecontroller.backend.observe.kernel-instability
parent: modecontroller.backend.observe
tags: [crash, diagnostics, system-log, hardware]
name: {zh: "机器侧稳定性", en: "Machine-side Stability"}
description:
  zh: >
      从 System 日志读这台机器自己的内核级事件：蓝屏（BugCheck 1001）、非正常关机（Kernel-Power 41 / EventLog 6008）、硬件错误（WHEA-Logger）与谁发起的关机（User32 1074），渲染成诊断报告里的一段与时间轴。此前只采 Application 日志，System 侧一条都拿不到。
      
  en: >
      Read the machine's own kernel-level events from the System log — bugchecks (1001), unexpected shutdowns (Kernel-Power 41 / EventLog 6008), WHEA hardware errors and who initiated a shutdown (User32 1074) — rendered as a diagnostic-report section with a timeline. Previously only the Application log was read, so nothing from the System side was ever captured.
      
revision: 20521577d9cf0d2206617a54825953f305763895
updated_at: "2026-10-07T14:33:00.728Z"
fingerprint: 12d919810c46ff200a7cdaabe69117e74ffbba3b9dfbb7ff2e072cd038d44945
source:
  - path: "endfieldmodcontroller/kernel_instability.py"
    line: 1
    end_line: 390
apis:
  - protocol: rpc
    path: "collect_kernel_events"
    description:
      zh: >
          采一次机器侧稳定性（System 日志，默认 30 天窗口）。采集失败时 ok=False 并如实给出原因 —— 绝不能被当成「机器是稳的」。
      en: >
          Collect machine-side stability once (System log, 30-day window by default). On failure ok=False with an honest reason — never to be read as "the machine is fine".
  - protocol: rpc
    path: "render_kernel_section"
    description:
      zh: >
          把结果渲染成诊断报告里的一段（自带标题）与时间轴；调用方给了本次启动时刻时，额外汇总「距本次启动最近的一条」供对照。
      en: >
          Render the result as a diagnostic-report section (heading included) with a timeline; when the caller passes the launch time, also report the nearest preceding event for reference.
---

## 为什么需要它

本程序查「是不是外部把游戏干掉了」一直只看 **Application** 日志。而「这台机器自己稳不稳」—— 内核蓝屏（`BugCheck`）、非正常关机（`Kernel-Power 41` / `EventLog 6008`）、硬件错误（`WHEA-Logger`）、谁发起的关机（`User32 1074`）—— **一条都采不到**。

实测证据（2026-10-07）：一份 283 项的诊断包里，`windows-events-*.log` 的 Provider 只有 `Windows Error Reporting` 与 `RestartManager` 两类，**System 侧 0 条** —— 现有窗口只有「崩溃前 5 分钟」，30 天的回溯窗口根本不存在。缺了它，「游戏随机起不来」就永远没有机器侧对照，排查只能在 Mod 侧反复打转。

## 它是「背景判据」，不是结论

三条纪律，缺一条就不要这段数据：

1. **不下结论** —— 只如实陈述「窗口内有过哪些内核级事件 + 时间轴」，**不参与** `observe.classify` 的任何归因优先级。蓝屏是**整机**事件：它既不能证明、也不能否定本次故障由 Mod 侧引起。文本里必须写明「相关不等于因果」。
2. **拿不到 ≠ 稳** —— 采集失败一律如实写「没查到」并给出原因，**绝不**渲染成「这台机器没有问题」；把「采不到」当成一条错误的正面判据，比没有这条判据更糟。
3. **要能对照** —— 时间轴带绝对时间；调用方给了「本次启动时刻」时，额外汇总「距本次启动最近的一条」，让人自己看时间关系，而不是替他下判断。

## 落点

`diagnostics.collect_environment_report()` 里在「设备与显卡」段之后追加一段，崩溃包与手动诊断包**共用**这条入口。

## 实测

* 本机采集 0.39 秒 / 67 条事件；端到端 `collect_environment_report()` 4.6 秒，报告里已带上该段。
* `pytest tests -q -n 4` → 1274 passed。
* 两处实测踩过的坑已写进代码注释并被单测钉住：时间必须走 `[DateTimeOffset]`（用 `DateTime` 相减会整整错一个时区），输出必须 `Out-String -Width 4096`（否则 `Format-List` 会把 `Message` 里的 exe 路径折成两半）。
