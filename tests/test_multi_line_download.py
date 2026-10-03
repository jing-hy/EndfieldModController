"""多线路**动态抢块**（2026-10-04 落地）。

**为什么做**（用户要求「测一下混合动态并发」→ 实测后落地）：`scripts/speedtest_mixed.py` 在本机
用真实 Release 资产测出三种模式：

| 模式 | 速度 |
| --- | --- |
| ① 单线路 12 连接 | 0.664 MB/s |
| ② 多线路**静态等分**（每条线路各下自己那段） | 0.508 ← **负优化**（慢线路成木桶短板） |
| ③ 多线路**动态抢块**（共享块队列 + 停滞淘汰） | **0.975（+47%）** |

实现上**没另起一套下载器**：`_download_parallel` 的 `todo` 队列本来就是"共享队列 + 谁空谁领"
⇒ 动态分配天然成立；只补了两件事 —— 每次块重试**换一条线路**、**连挂两次的线路本次淘汰**。
本文件钉住这两条的判据（选线路是纯函数，测起来便宜）。
"""
from __future__ import annotations

from endfieldmodcontroller import fastnet


def test_first_attempt_uses_the_main_line() -> None:
    urls = ["https://main/", "https://alt1/", "https://alt2/"]
    assert fastnet._pick_line_url(urls, set(), 0) == "https://main/"


def test_retry_rotates_to_another_line() -> None:
    urls = ["https://main/", "https://alt1/", "https://alt2/"]
    assert fastnet._pick_line_url(urls, set(), 1) == "https://alt1/"
    assert fastnet._pick_line_url(urls, set(), 2) == "https://alt2/"
    # 轮完一圈回到主线路（重试上限是 4 次）
    assert fastnet._pick_line_url(urls, set(), 3) == "https://main/"


def test_dead_lines_are_skipped() -> None:
    urls = ["https://main/", "https://alt1/", "https://alt2/"]
    dead = {"https://alt1/"}
    assert fastnet._pick_line_url(urls, dead, 0) == "https://main/"
    assert fastnet._pick_line_url(urls, dead, 1) == "https://alt2/", "被淘汰的线路不该再被选中"


def test_all_dead_falls_back_to_everything() -> None:
    """★ 全被淘汰时**必须退回全部** —— 否则淘汰逻辑本身会把下载卡死。"""
    urls = ["https://main/", "https://alt1/"]
    dead = {"https://main/", "https://alt1/"}
    assert fastnet._pick_line_url(urls, dead, 0) in urls


def test_empty_urls_is_safe() -> None:
    assert fastnet._pick_line_url([], set(), 0) == ""


def test_download_parallel_accepts_alt_urls() -> None:
    """接口回归：`alt_urls` 是可选参数，不传时行为与以前完全一致（向后兼容）。"""
    import inspect

    sig = inspect.signature(fastnet._download_parallel)
    assert "alt_urls" in sig.parameters
    assert sig.parameters["alt_urls"].default is None
    # `_attempt_line` 也要能收到并转下去
    assert "alt_urls" in inspect.signature(fastnet._attempt_line).parameters


def test_download_enables_multi_only_for_the_first_line() -> None:
    """只有**第一条**线路的尝试带多线路候选；后面几条是兜底，走原逻辑。"""
    import inspect
    import re

    src = inspect.getsource(fastnet.download)
    assert re.search(r"alt_urls=multi_alt if index == 0", src), \
        "多线路候选只该给第一条线路的尝试"
    assert "multi_alt = [line.apply(url) for line in lines[1:]" in src, \
        "候选 = 其它线路的 URL"


def test_raw_github_urls_are_mirrorable() -> None:
    """★ 2026-10-04 补：**raw 也要能换线路**。

    原先 `_mirrorable` 只认 `github.com` ⇒ 角色表 / 乳摇参数 / 公告（都走 raw）**永远不换线**，
    直连一断就整块失败；而镜像实测支持 raw（`ghproxy.net/https://raw.githubusercontent.com/…` → 200）。
    """
    assert fastnet._mirrorable("https://raw.githubusercontent.com/o/r/main/a.json") is True
    assert fastnet._mirrorable("https://codeload.github.com/o/r/tar.gz/refs/heads/main") is True
    assert fastnet._mirrorable("https://objects.githubusercontent.com/x/y") is True
    assert fastnet._mirrorable("https://github.com/o/r/releases/download/v1/f.zip") is True
    # 非 GitHub 的源不该被套镜像（套了也取不到）
    assert fastnet._mirrorable("https://reshade.me/downloads/ReShade_Setup.exe") is False
    assert fastnet._mirrorable("http://127.0.0.1:18923/api/status") is False


def test_resolve_lines_offers_mirrors_for_raw() -> None:
    """raw 请求在 mirror 模式下也要给出镜像候选（以前只会返回直连）。"""
    lines = fastnet.resolve_lines("https://raw.githubusercontent.com/o/r/main/a.json", "mirror")
    names = [line.name for line in lines]
    assert names, "至少要有一条候选"
    assert any(name != "直连" for name in names), f"raw 也该有镜像候选，实际：{names}"
