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
      
revision: 83a004bf635eab9ddbc7e3aa0e1545b11a005bff
updated_at: "2026-10-18T14:16:51.061Z"
fingerprint: 09f5e157c76c13bca84f645084de4c284fad4d0bc6f33fc352a257f9e49930dc
source:
  - path: "endfieldmodcontroller/game_clean.py"
    line: 102
    end_line: 280
  - path: "endfieldmodcontroller/game_clean.py"
    line: 205
    end_line: 860
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
