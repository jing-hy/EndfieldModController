---
uid: b1d1100e
id: modecontroller.backend.upkeep.alerts
parent: modecontroller.backend.upkeep
tags: [alerts]
name: {zh: "公告与异常预警", en: "Announcements & Alerts"}
description:
  zh: >
      远端公告通道：解码 contents 响应、规范化条目、丢弃过期的、按**本地版本号**过滤每一条（于是“只给某个版本发的公告”不再打扰其他人），并执行 critical 预警要求的“还原配置”动作。
      
  en: >
      The remote announcement channel: decode the contents response, normalise entries, drop expired ones, gate each entry by the local version (so an announcement for one version stops bothering everyone else), and run the safe-mode action a critical alert can demand.
      
revision: 20521577d9cf0d2206617a54825953f305763895
updated_at: "2026-10-07T14:32:31.353Z"
fingerprint: a34e3bb120681a4d0aaf7eb1e1908c50a0efccfe3489b0957a79b06d4ef1694a
source:
  - path: "endfieldmodcontroller/alerts.py"
    line: 102
    end_line: 226
  - path: "endfieldmodcontroller/alerts.py"
    line: 222
    end_line: 324
  - path: "endfieldmodcontroller/alerts.py"
    line: 318
    end_line: 412
apis:
  - protocol: rpc
    path: "alerts.overview"
    description:
      zh: >
          界面看的视图：未读公告（info/warning）+ 所有适用的 critical 预警，**按本地版本过滤**。
          
      en: >
          The UI's view: unread announcements (info/warning) plus every applicable critical alert, filtered by local version.
          
  - protocol: rpc
    path: "alerts.mark_seen"
    description:
      zh: >
          把公告标为已读（critical 预警**从不**标已读 —— 它必须每次都拦一下）。
          
      en: >
          Mark announcements as read (critical alerts are never marked — they must gate every launch).
          
  - protocol: rpc
    path: "alerts.safe_mode"
    description:
      zh: >
          最强的保护动作：先快照开关，再关注入 + 清理游戏目录。
          
      en: >
          The strongest protective action: turn every injection off and clean the game folder, after snapshotting the switches.
          
  - protocol: rpc
    path: "alerts.undo_safe_mode"
    description:
      zh: >
          把那次快照里的开关改回去。
          
      en: >
          Undo that snapshot's switch changes.
          
  - protocol: rpc
    path: "alerts.version_applies"
    description:
      zh: >
          这条公告适不适用于本地这个版本（区间留空 = 所有版本都收）。
          
      en: >
          Does this entry apply to the given local version (empty range = every version).
          
---
