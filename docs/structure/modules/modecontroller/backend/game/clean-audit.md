---
uid: b1d10001
id: modecontroller.backend.game.clean-audit
parent: modecontroller.backend.game
tags: [audit]
name: {zh: "游戏目录审计", en: "Game Folder Audit"}
description:
  zh: >
      读游戏目录并指出哪些东西不属于它：按内容认出 ReShade 载荷与第三方代理、给每条发现算哈希，并报告“会移走什么、移到哪” —— 清理流程里只读的那一半。
      
  en: >
      Read the game folder and say what does not belong there: recognise ReShade payloads and third-party proxies by content, hash each finding, and report what would be moved where — the read-only half of the cleaning flow.
      
revision: ec6d352f646115c51b7b413c56b5095ba5e52eeb
updated_at: "2026-10-06T05:52:00.964Z"
fingerprint: f5028d650b3eea84783d0aac28bd4537dd3c82208e4cc4b7d48a7c0547969586
source:
  - path: "endfieldmodcontroller/game_clean.py"
    line: 87
    end_line: 210
  - path: "endfieldmodcontroller/game_clean.py"
    line: 177
    end_line: 635
apis:
  - protocol: rpc
    path: "game_clean.audit"
    description:
      zh: >
          读游戏目录，列清哪些东西不属于它（已分类、已算哈希）—— 只读的那一半。
          
      en: >
          Read the game folder and list what does not belong there, classified and hashed — the read-only half.
          
  - protocol: rpc
    path: "game_clean.Finding"
    description:
      zh: >
          一条发现：分类、路径、大小、sha256，以及它是不是被认成 ReShade 载荷。
          
      en: >
          One finding: category, path, size, sha256 and whether it is recognised as a ReShade payload.
          
---
