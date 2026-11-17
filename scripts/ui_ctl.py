# SPDX-License-Identifier: GPL-3.0-or-later
"""用命令行操作 EndfieldModController 的界面（无障碍 / 自动化通道客户端）。

用户需求（2026-11-17）：「需要一个无障碍功能，能有个 api 或者命令行，允许 ai 操作 ui，
比如切换页面，点击开关，滑动这种」。

程序启动后在 `<数据根>/runtime/_state/ui_api.json` 里写下 `{url, port, token}`，
本脚本读它、带上 token 调本地 HTTP 接口。用户/AI 不需要关心 token。

用法：

    python scripts/ui_ctl.py state                  # 当前页面 + 所有可点元素
    python scripts/ui_ctl.py find 服装              # 按文字找元素（拿到 id）
    python scripts/ui_ctl.py tab library            # 切换页面
    python scripts/ui_ctl.py click '[data-mc-id="tab:settings"]'
    python scripts/ui_ctl.py set '...' on           # 开关类元素置开/关
    python scripts/ui_ctl.py value '...' "某个值"    # 输入框/滑块赋值
    python scripts/ui_ctl.py scroll '...'           # 滚到某个元素
    python scripts/ui_ctl.py scroll-by 400          # 页面向下滚 400px

所有命令都接受 `--json`（打印原始 JSON，方便程序/AI 解析）与 `--state-file <路径>`。
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STATE = ROOT / "runtime" / "_state" / "ui_api.json"


def _load_endpoint(state_file: Path) -> tuple[str, str]:
    if not state_file.is_file():
        raise SystemExit(
            f"找不到 {state_file} —— 管理器是不是没在运行？\n"
            "（这个文件是程序启动时写的，里面是本地端口与 token）"
        )
    try:
        data = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit(f"读不了 {state_file}: {exc}") from exc
    url = str(data.get("url") or "").rstrip("/")
    token = str(data.get("token") or "")
    if not url or not token:
        raise SystemExit(f"{state_file} 内容不完整（缺 url 或 token）")
    return url, token


def _request(url: str, token: str, method: str, body: dict | None = None) -> dict:
    payload = None
    headers = {"X-MC-Token": token}
    if body is not None:
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    req = urllib.request.Request(url, data=payload, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            return json.loads(raw)
        except ValueError:
            return {"ok": False, "message": f"HTTP {exc.code}: {raw[:400]}"}
    except urllib.error.URLError as exc:
        raise SystemExit(f"连不上本地接口（程序关了？）: {exc}") from exc
    try:
        return json.loads(raw)
    except ValueError:
        return {"ok": False, "message": f"返回的不是 JSON: {raw[:400]}"}


def _print_elements(snapshot: dict, keyword: str = "", as_json: bool = False) -> None:
    if as_json:
        print(json.dumps(snapshot, ensure_ascii=False, indent=2))
        return
    tab = snapshot.get("tab") or "?"
    print(f"当前页面: {tab}    元素数: {snapshot.get('count') or 0}")
    for item in snapshot.get("elements") or []:
        label = item.get("label") or ""
        if keyword and keyword not in label and keyword not in str(item.get("id")):
            continue
        flags = []
        if item.get("checked") is not None:
            flags.append("开" if item["checked"] else "关")
        if item.get("disabled"):
            flags.append("已禁用")
        if item.get("value"):
            flags.append(f"值={item['value']}")
        extra = ("  [" + " ".join(flags) + "]") if flags else ""
        print(f"  {item.get('role'):<10} {label[:60]:<60}{extra}")
        print(f"      id: {item.get('id')}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="操作 EndfieldModController 的界面")
    parser.add_argument("--state-file", default=str(DEFAULT_STATE))
    parser.add_argument("--json", action="store_true", help="打印原始 JSON")
    sub = parser.add_subparsers(dest="command")

    p_state = sub.add_parser("state", help="界面快照")
    p_state.add_argument("keyword", nargs="?", default="")

    p_find = sub.add_parser("find", help="按文字找元素")
    p_find.add_argument("keyword")

    p_tab = sub.add_parser("tab", help="切换页面（library/assist/store/downloads/dependencies/launch/settings/about）")
    p_tab.add_argument("name")

    p_click = sub.add_parser("click", help="点一个元素")
    p_click.add_argument("id")

    p_set = sub.add_parser("set", help="把开关类元素置开/关")
    p_set.add_argument("id")
    p_set.add_argument("state", choices=["on", "off", "true", "false", "1", "0"])

    p_value = sub.add_parser("value", help="给输入框/滑块赋值")
    p_value.add_argument("id")
    p_value.add_argument("text")

    p_scroll = sub.add_parser("scroll", help="滚动到某个元素")
    p_scroll.add_argument("id")

    p_scroll_by = sub.add_parser("scroll-by", help="页面滚动一段距离（正数向下）")
    p_scroll_by.add_argument("dy", type=int)

    sub.add_parser("help", help="打印用法")

    args = parser.parse_args(argv)
    if not args.command or args.command == "help":
        parser.print_help()
        return 0

    url, token = _load_endpoint(Path(args.state_file))

    if args.command in ("state", "find"):
        snap = _request(url + "/state", token, "GET")
        if snap.get("ok") is False:
            print(json.dumps(snap, ensure_ascii=False))
            return 2
        keyword = getattr(args, "keyword", "") or ""
        _print_elements(snap, keyword, as_json=args.json)
        return 0

    if args.command == "tab":
        body = {"id": "tab:" + str(args.name), "action": "click"}
    elif args.command == "click":
        body = {"id": args.id, "action": "click"}
    elif args.command == "set":
        want = str(args.state).lower() in ("on", "true", "1")
        body = {"id": args.id, "action": "set", "value": want}
    elif args.command == "value":
        body = {"id": args.id, "action": "value", "value": args.text}
    elif args.command == "scroll":
        body = {"id": args.id, "action": "scroll"}
    elif args.command == "scroll-by":
        body = {"id": "", "action": "scroll-by", "value": args.dy}
    else:
        parser.print_help()
        return 2

    result = _request(url + "/act", token, "POST", body)
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json
          else ("OK  " + str(result.get("message") or result.get("action") or "已执行"))
          if result.get("ok") else ("失败: " + str(result.get("message"))))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
