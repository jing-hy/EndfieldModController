---
name: emc-publish-alert
description: 在 EndfieldModController 的 alerts.json 里新增一条公告/异常预警，或判定某条既有条目现在还会不会弹——按 level 语义填 id/title/body/until/版本区间，用本地 python 真跑 overview 证明会弹，只提交该文件并 push，再用 fetch_document 复核线上已生效。仅在处理 D:\zmdmod\modecontroller 这个项目、用户说「加一条公告」「发个预警」「上次那个紧急状态失效了没有」「公告推上去了吗」时使用。
whenToUse: 用户要发布重大信息（封禁风波、版本缺陷、风险提示）、要改/删 alerts.json 里的条目、或问某条 warning/critical 现在还会不会弹；也包括「正文怎么写才不像乱码」「为什么本地测出来不弹」这类问题。
---

# EndfieldModController 公告 / 预警（alerts.json）

对象：`D:\zmdmod\modecontroller`。公告与预警是**数据**，不是代码：`alerts.json` 文件头自己写着「唯一发布入口：改这个文件 push 即生效，不用发版」。所以**不要为发一条公告去改 .py，也不要 bump 版本号、不要发 Release**。

## 先定档：level 决定待遇

| level | 叫什么 | 行为 |
| --- | --- | --- |
| `info` / `warning` | 公告 | 管理器首屏弹一次，看过记已读（`_state/alerts_seen.json`），下次不再弹；**不锁启动** |
| `critical` | 异常状态预警 | **每次点「一键启动」都弹**（不记已读、无开关），强制停留 `hold_seconds` 秒（默认 10，上限 120），必须三选一：还原配置 / 保持配置但不启动 / 仍然启动 |

字段（`endfieldmodcontroller/alerts.py` 的 `normalize` 是准绳）：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `id` | 是 | 唯一，且**它就是已读键**；缺 id 的条目会被整条丢掉 |
| `level` | 否 | 默认 `info`；写了不认识的词（如 `warn`）会**退化成 info** |
| `title` | 否 | 空则显示「公告」 |
| `title_en` / `body_en` | 否 | **可选英文版**：界面语言为 English 时优先展示；留空回落中文（老公告无此字段照样显示） |
| `body` | 否 | 正文，用 `\n` 换行，**纯文本**（见 Pitfalls 第 1 条） |
| `url` | 否 | 详情链接 |
| `hold_seconds` | 否 | 覆盖文档级 `default_hold_seconds`，clamp 到 0..120 |
| `until` | 否 | `YYYY-MM-DD`（当天结束前有效，次日 0 点过期）或 ISO 时间；空 = 永不过期 |
| `min_version` / `max_version` | 否 | 版本区间，见下表 |
| `edition` | 否 | 适用形态：`both`（默认，两版都发）/ `full`（只发完整版）/ `lite`（只发轻量版）；见下段 |

适用形态（2026-11-28 用户：「公告也要区分两个版本，可以都发，也可以只发一个版本」；`edition_applies` 是准绳）：

| 写法 | 谁能收到 |
| --- | --- |
| 留空 / `both` | 完整版 + 轻量版（**默认**，绝大多数公告用这条） |
| `full` | 只发完整版（ReShade / DLSS5 / 第一人称这类 Lite 没有的功能） |
| `lite` | 只发轻量版 |

版本区间（比对的是本地 `endfieldmodcontroller/version.py` 的 `__version__`，beta 语义走全项目同一套 `version.parse_version`）：

| 写法 | 谁能收到 |
| --- | --- |
| 两个都留空 | 所有版本（重大信息 / 安全预警走这条） |
| 两个填同一个版本号 | 只有装了那个版本的人（「这个版本发的公告」最常用） |
| 只填 `min_version` | 从那一版起（含） |
| 只填 `max_version` | 到那一版为止（含） |

## Steps

1. **先读文件和实现**，别凭记忆写字段：
   ```
   read alerts.json
   read endfieldmodcontroller/alerts.py          # 至少看 normalize / is_expired / version_applies / overview
   ```
   `schema`、`default_hold_seconds`、`_readme` 是文档级字段，**改写时一个都不能丢**。

2. **写条目**用 python 读改写（先整份读进变量，再写；不要边写边读）：
   ```python
   import json
   from pathlib import Path
   p = Path(r"D:\zmdmod\modecontroller\alerts.json")
   doc = json.loads(p.read_text(encoding="utf-8"))
   items = doc.setdefault("alerts", [])
   new = {
       "id": "2026-10-26-ban-wave-over-reshade-risk",   # 唯一；先 grep 现有 id 与 _state/alerts_seen.json，别复用
       "level": "warning",
       "title": "封禁风波已过；但 ReShade 仍是风险最大的一项，非必要别开",
       "until": "2026-12-31",
       "body": "先说结论：……\n\n第二段……",
   }
   items.append(new)
   with open(p, "w", encoding="utf-8", newline="\n") as fh:   # 显式 LF，别让 Windows 换成 CRLF
       fh.write(json.dumps(doc, ensure_ascii=False, indent=2) + "\n")
   print("已写入，条目数:", len(items))
   ```
   正文里**不要写 `**加粗**`、不要写表格**：弹窗正文按纯文本渲染。想强调就用「先说结论：」这类自然语言的领句。

3. **本地真跑，证明它真的会弹**。把脚本落盘再跑（别用一行 `python -c` 传中文，Windows 控制台是 GBK）：
   ```python
   import json, sys, tempfile
   from pathlib import Path
   sys.stdout.reconfigure(encoding="utf-8", errors="replace")
   sys.path.insert(0, r"D:\zmdmod\modecontroller")
   from endfieldmodcontroller import alerts, version

   doc = json.loads(Path(r"D:\zmdmod\modecontroller\alerts.json").read_text(encoding="utf-8"))
   print("本地版本:", version.__version__, "| 条目数:", len(doc.get("alerts") or []))
   for it in alerts.normalize(doc):
       print("  [%s] %-45s until=%s 过期=%s 适用本版=%s" % (
           it["level"], it["id"], it["until"] or "(无)",
           alerts.is_expired(it["until"]), alerts.version_applies(it)))

   class _Cfg:                     # 只给 runtime_path：已读记录从空开始，不碰真实的 _state/alerts_seen.json
       runtime_path = Path(tempfile.mkdtemp(prefix="emc-seen-"))
   ov = alerts.overview(_Cfg(), document=doc)
   print("overview.ok:", ov["ok"], "| 会弹公告:", [a["id"] for a in ov["announcements"]],
         "| 会拦启动的 critical:", [c["id"] for c in ov["critical"]])
   ```
   判据：新 id 必须出现在 `announcements`（info/warning）或 `critical` 里，同时那一行打印出 `过期=False`、`适用本版=True`。用临时 `runtime_path` 是为了模拟「没读过的新用户」；直接 `AppConfig()` 会读到本机已读记录，announcements 可能空。

4. **只提交这一个文件**：
   ```
   git status --short                    # 报告里写清：本次改动 = alerts.json；其它本地改动没动
   git add alerts.json
   git commit -m "公告：<一句话主题>" -m "<发布原因 / 有效期 / 给用户的一句话>"
   git diff --stat HEAD~1                # 必须是 1 file changed，行数是 +N（不是整份文件重写）
   ```

5. **推送**（只推 main，不发 Release）：
   ```
   python scripts/push.py                # 项目约定的推送出口：先 snapshot.py，失败就不推，然后推 main
   ```
   也可以 `git push` 直推——但那样**不会**刷新 `docs/AI-记忆日志.md`（那是 `push.py` 干的活）。反过来注意：`push.py` 只替你提交「记忆日志」和 `docs/structure`，**不提交你的 `alerts.json`**，第 4 步没 commit 就等于白推。

6. **线上复核**（不是看本地文件，是拉真的线上文档）：
   ```python
   import sys, tempfile
   from pathlib import Path
   sys.stdout.reconfigure(encoding="utf-8", errors="replace")
   sys.path.insert(0, r"D:\zmdmod\modecontroller")
   from endfieldmodcontroller import alerts
   NEW_ID = "2026-10-26-ban-wave-over-reshade-risk"
   doc = alerts.fetch_document(timeout=25)          # 不吃缓存：API 路线 + raw 网页路线
   ids = [a.get("id") for a in (doc.get("alerts") or [])]
   print("线上条目数:", len(ids), "| 含新 id:", NEW_ID in ids)
   class _Cfg:
       runtime_path = Path(tempfile.mkdtemp(prefix="emc-seen-"))
   ov = alerts.overview(_Cfg(), document=doc)
   print("线上会弹:", [a["id"] for a in ov["announcements"]], "| critical:", [c["id"] for c in ov["critical"]])
   ```

7. **汇报**：commit hash + 「只改了 alerts.json（1 file changed）」+ 本地那张逐条表 + 线上复核输出。别用计划冒充实测。

## 判定「既有条目还生效吗」

用户问「上次那个紧急状态失效没有」，要回答的是**三选一**，不是一句「应该不弹了」：

1. 逐条跑 `alerts.normalize(线上 doc)`，对每条打印 `until`、`is_expired(until)`、`version_applies(item)`（脚本同 Step 3，只把 `doc` 换成 `alerts.fetch_document()` 的结果）。
2. 结论落到具体一环：**已过期**（`until=YYYY-MM-DD` 的次日 0 点起）/ **版本区间不适用**（给别的版本发的）/ **命中已读**（`_state/alerts_seen.json` 里已有这个 id，只影响 info/warning）。说不清是哪一环就不算判据。
3. **critical 没有旁路**：`overview()` 里 critical 和普通公告走同一个循环、同一道 `is_expired` + `version_applies` 过滤；后端只有两处调 `alerts.overview(...)`（`api.py` 启动首屏一次、`prelaunch_alerts` 每次点「一键启动」一次），两处都过这道闸。别以为「critical 会绕过 until」。
4. 过期的条目**可以留着**，到期自然不弹，还留着历史；用户明确要清理时再删条目（删了不影响其它条目）。

## Pitfalls

1. **别照抄现有条目的 `**`**。弹窗正文用 `textContent` 渲染、**不解析 markdown**（`frontend/src/components/DialogHost.vue` 顶部注释、`frontend/src/lib/dialog.js`、`frontend/src/pages/SettingsPage.vue` 都写着同一句）；现有条目里的 `**` 是残留问题，复制它只会在弹窗里显示成星号。
2. **overview 返回空 ≠ 条目失效**。announcements 被 `_state/alerts_seen.json` 的 `ids` 过滤（`mark_seen` 只保留最近 200 个）。要判失效就逐条打印 `is_expired` / `version_applies`，或者用临时 `runtime_path` 换个「新用户视角」。
3. **`until` 写错格式 = 永不过期**。`is_expired` 解析不了时返回 `False`（宁可多提示也不漏预警）—— 写 `2026/12/31` 或 `12-31` 的 critical 会**每次点启动都弹**，而且没人会想到是格式问题。
4. **id 是已读键**：复用旧 id 的 warning 会被当已读直接不弹；critical 虽然不看已读，但弹窗与已读记录都按 id 认条目，同样一条一个唯一 id，别复用。
5. **level 拼错会静默降级**：`warn` / `urgent` 之类会被 `normalize` 改成 `info`，于是一条本该强制确认的预警变成「不锁启动的普通公告」——而且没有任何报错。
6. **缺 `id` 的条目被整条丢掉**，文件里看着有、线上永远不弹。
7. **别在启动流程里为发布做改动**：公告是数据文件，改 `.py` 要走测试、重建产物、结构树四步收尾，那是另一条流程（`emc-structure-closeout`）；发公告不需要这些。
8. **提交只带 `alerts.json`**：`git add` 写明确路径，别 `git add -A` 把别的本地改动带进去；也别顺手动 `version.py`（推 main ≠ 发 Release，`push.py` 自己会打印这句）。
9. **`git diff --stat` 显示整份文件重写** ⇒ 换行符被换成了 CRLF（`open(..., newline="\n")` 没写）。回滚重写一次，别带着这个 diff 提交。
10. **本地测 `overview()` 要用 `document=` 或临时 runtime**：不传 document 会走 `load_document`（拉线上、写 `_state/alerts_cache.json`）；用 `AppConfig()` 会读本机已读记录。两条都会让「会不会弹」这个结论失真。
11. **Windows 控制台编码**：脚本落盘成 `.py` 再跑，并在开头 `sys.stdout.reconfigure(encoding="utf-8", errors="replace")`；一行 `python -c` 里的中文在 GBK 控制台会乱码甚至抛 `UnicodeEncodeError`。

## Verification

- JSON 合法、`alerts` 条目数 +1、新 id 不重复：Step 3 的脚本打印 `条目数` 与全表即证明。
- 本地 `overview` 里新 id 出现在 `announcements`（或 `critical`），且该行是 `过期=False 适用本版=True`。
- `git diff --stat HEAD~1` = `1 file changed`，行数是增量（不是整份重写）。
- 推送后 `alerts.fetch_document(timeout=25)`：线上条目数 +1、`含新 id: True`，再对该线上文档跑一次 `overview` 仍会弹。
- 汇报里同时给出：commit hash、改动文件清单（只 1 个）、本地逐条表、线上复核输出。四样缺一就是没做完。
