# SPDX-License-Identifier: GPL-3.0-or-later
"""GitHub 镜像表 / 手选镜像源（2026-11-18 用户要求）。

用户原话：「另外要加一下 github 镜像表」+ 一张界面上「选择源」单选列表的截图
（每项名字 + 地址、选中的打勾、旁边有连通性测试）。

这里钉住的判据：
* `""` = 自动；`"direct"` = 仅直连；某个域名 = **优先用它**，其余线路仍作兜底；
* 不认识的域名**回落成自动**（脏配置不能把下载搞停）；
* 界面拿到的表顺序固定：自动 / 仅直连 / 各镜像，且 `selected` 只有一个为 True；
* `set_download_mirror("")` **必须能切回自动**（空串是有效值，不能被"空就跳过"吃掉）。
"""
from __future__ import annotations

import pytest

from endfieldmodcontroller import api as A, fastnet
from endfieldmodcontroller.config import AppConfig

RELEASE_URL = "https://github.com/jing-hy/EndfieldModController/releases/download/v1.0.0/x.zip"


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    """每条用例都从"自动、没测速记录、没有死域名"开始。"""
    monkeypatch.setattr(fastnet, "_load_lines_cache", lambda: {})
    monkeypatch.setattr(fastnet, "_DNS_DEAD", {})
    fastnet.set_mirror("")
    yield
    fastnet.set_mirror("")


def _names(lines) -> list[str]:
    return [line.name for line in lines]


def test_default_is_auto():
    assert fastnet.get_mirror() == ""
    names = _names(fastnet.resolve_lines(RELEASE_URL, "auto"))
    assert names[0] == fastnet.DIRECT.name
    assert "gh.monlor.com" in names


def test_unknown_name_falls_back_to_auto():
    fastnet.set_mirror("no-such-mirror.example")
    assert fastnet.get_mirror() == ""


def test_direct_mode_lists_only_direct():
    fastnet.set_mirror("direct")
    assert _names(fastnet.resolve_lines(RELEASE_URL, "auto")) == [fastnet.DIRECT.name]


def test_picked_mirror_goes_first_but_keeps_fallbacks():
    fastnet.set_mirror("gh.nxnow.top")
    names = _names(fastnet.resolve_lines(RELEASE_URL, "auto"))
    assert names[0] == "gh.nxnow.top", names
    assert fastnet.DIRECT.name in names, "其余线路要留作兜底"
    assert "gh.monlor.com" in names


def test_picked_mirror_also_works_in_mirror_mode():
    fastnet.set_mirror("gh-proxy.com")
    names = _names(fastnet.resolve_lines(RELEASE_URL, "mirror"))
    assert names[0] == "gh-proxy.com"


def test_dead_domain_does_not_block_the_choice():
    """选中的镜像域名解析不了 ⇒ 不硬塞到第一位（但也不崩）。"""
    fastnet.set_mirror("gh-proxy.com")
    fastnet._DNS_DEAD["gh-proxy.com"] = fastnet.time.time() + 600
    names = _names(fastnet.resolve_lines(RELEASE_URL, "auto"))
    assert names[0] != "gh-proxy.com"
    assert "gh-proxy.com" not in names


def test_mirror_table_shape():
    rows = fastnet.mirror_table()
    assert [r["name"] for r in rows[:2]] == ["", "direct"]
    assert sum(1 for r in rows if r["selected"]) == 1
    assert rows[0]["selected"] is True                 # 默认自动
    assert {r["name"] for r in rows[2:]} == set(fastnet._known_mirror_names())
    for row in rows[2:]:
        assert row["url"].startswith("https://")
        assert row["hint"]


def _api(tmp_path) -> A.EndfieldModControllerApi:
    (tmp_path / "runtime").mkdir(parents=True, exist_ok=True)
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text("{}", encoding="utf-8")
    cfg = AppConfig.load(cfg_path)
    cfg.data_root = str(tmp_path)
    cfg.save()
    return A.EndfieldModControllerApi(str(cfg_path))


def test_api_set_mirror_persists_and_takes_effect(tmp_path):
    api = _api(tmp_path)
    result = api.set_download_mirror("gh.monlor.com")
    assert result["mirror"] == "gh.monlor.com"
    assert api.config.download_mirror == "gh.monlor.com"
    assert app_config_reload(api) == "gh.monlor.com"
    assert {r["name"] for r in result["mirrors"] if r["selected"]} == {"gh.monlor.com"}


def test_api_can_switch_back_to_auto(tmp_path):
    """★ 空串是有效值：选了镜像之后必须能切回「自动」。"""
    api = _api(tmp_path)
    api.set_download_mirror("gh.nxnow.top")
    back = api.set_download_mirror("")
    assert back["mirror"] == ""
    assert api.config.download_mirror == ""
    assert {r["name"] for r in back["mirrors"] if r["selected"]} == {""}


def test_api_rejects_unknown_mirror(tmp_path):
    api = _api(tmp_path)
    api.set_download_mirror("gh.nxnow.top")
    result = api.set_download_mirror("bogus.example")
    assert result["mirror"] == ""


def app_config_reload(api) -> str:
    path = getattr(api, "_config_path", None)
    if path is None:
        return ""
    return AppConfig.load(path).download_mirror

