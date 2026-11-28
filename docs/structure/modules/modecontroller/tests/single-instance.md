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
      
revision: acc360d0a14c16ea7116b9922b7383553e40a3a3
updated_at: "2026-11-28T16:11:18.936Z"
fingerprint: 5bc1804876b0c020416c380154032766eb9cf80ac45ef5f9abd6de97fe2ed6e8
source:
  - path: "tests/test_single_instance.py"
    line: 344
    end_line: 822
apis: []
---
