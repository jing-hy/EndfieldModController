"""宽松 JSON 解析（`fsutil.loads_tolerant`）的回归测试（2026-10-06）。

现场：香蕉网 `https://gamebanana.com/apiv11/Mod/<id>/ProfilePage` 会在 JSON **前面**
打一条 PHP Warning（服务端自己的 bug）——

    Warning: Undefined array key "oneclick_support" in .../TableRowCacher.php on line 87
    { "_idRow": 690864, … }

直接 `json.loads(整段)` 抛 `Expecting value: line 2 column 1 (char 1)`，界面显示的是
「Mod 下载失败：返回的不是有效数据」—— 而它**与网络 / 代理 / VPN 无关**
（本机实测：带不带代理、带不带浏览器 UA，服务端返回逐字节一样）。

要守住的性质：
* 真实那条（带 Warning 前缀）必须能解析出来；
* 正常 JSON、带 BOM 的 JSON 照常；
* 纯粹不是 JSON 的响应仍然要**报错**（不能把"坏数据"当成"解析成功、内容为空"）；
* **所有解析网络响应的地方都走它** —— 只修被撞到的那一处，下次换个接口还会栽
  （教训：做"统一走某通道"的改造必须系统排查所有旁路）。
"""
from __future__ import annotations

import inspect
import json

import pytest

from endfieldmodcontroller import alerts, fsutil, github, moddl, poser, sbm_data_sync

# 真实报文开头（本机 curl 抓的原文，只截了前几行）
REAL_BODY = (
    "\n"
    'Warning: Undefined array key "oneclick_support" in '
    "/home/publisher/live/gamebanana/classes/Library/Cache/TableRowCacher.php on line 87\n"
    "{\n"
    '    "_idRow": 690864,\n'
    '    "_sName": "AI generated)Background Image Alteration",\n'
    '    "_aFiles": []\n'
    "}\n"
)


def test_real_gamebanana_body_with_php_warning():
    with pytest.raises(json.JSONDecodeError):
        json.loads(REAL_BODY)                      # 旧的严格解析必然失败（复现现场）
    data = fsutil.loads_tolerant(REAL_BODY)
    assert data["_idRow"] == 690864
    assert "Background Image Alteration" in data["_sName"]


def test_plain_and_bom_json_still_work():
    assert fsutil.loads_tolerant('{"a": 1}') == {"a": 1}
    assert fsutil.loads_tolerant('\ufeff{"b": 2}') == {"b": 2}
    assert fsutil.loads_tolerant("  [1, 2, 3]  ") == [1, 2, 3]


def test_html_before_json_is_tolerated():
    """被网关/防护页夹了 HTML 头也一样（找得到 JSON 就认）。"""
    body = "<html><body>Access denied</body></html>\n{\"ok\": true}"
    assert fsutil.loads_tolerant(body) == {"ok": True}


def test_garbage_still_raises():
    """不是 JSON 就必须报错 —— 不许把坏响应当成"成功但空"。"""
    for bad in ("完全不是 JSON", "<html>only html</html>", ""):
        with pytest.raises(ValueError):
            fsutil.loads_tolerant(bad)


@pytest.mark.parametrize("module", [github, moddl, alerts, sbm_data_sync, poser])
def test_network_response_parsing_goes_through_the_tolerant_loader(module):
    """每个解析网络响应的模块都必须用 `fsutil.loads_tolerant`（不许再留裸 `json.loads`）。"""
    source = inspect.getsource(module)
    assert "loads_tolerant" in source, f"{module.__name__} 没有用宽松解析"
    for bad in ('json.loads(response.read()', 'json.loads(body.decode(',
                'json.loads(raw.decode(', 'json.loads(text)'):
        assert bad not in source, f"{module.__name__} 里还留着裸解析：{bad}"
