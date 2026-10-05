---
uid: b1d1ab02
id: modecontroller.tests.single-instance
parent: modecontroller.tests
tags: [tests]
name: {zh: "单实例锁测试", en: "Single Instance Tests"}
description:
  zh: >
      防多开的单实例锁回归（反馈：「关掉管理器，显示要管理员权限，然后就没反应」）：PID 被系统复用 / 陈旧锁 / 坏内容都必须**接管**而不是静默退出；真的还有实例（指纹对得上或屏幕上有窗口）仍然拒绝；释放时只删自己的锁。
      
  en: >
      Regression for the single-instance lock: a recycled PID (or a stale lock, or a broken lock file) must be taken over instead of causing a silent exit; a genuinely live instance (fingerprint match, or a window on screen) must still be refused; releasing only removes our own lock.
      
revision: 45e4d6d07cf81770c867c10f0f053a5efbf5e978
updated_at: "2026-10-03T15:48:42.330Z"
fingerprint: 6d7af66102dee5cb6f6370ce37de24dbe18ae8eebea0328e42e5e8d8819c9578
source:
  - path: "tests/test_single_instance.py"
    line: 229
    end_line: 592
apis: []
---
