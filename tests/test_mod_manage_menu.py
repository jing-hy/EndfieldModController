"""「⋯ 更多」里的三件：彻底删除 / 重命名 / 换预览图（2026-10-05 用户要求）。

用户原话：「**mod 的更多菜单中需要加入彻底删除（红字，需要用户输入 ok 二次确认）、
重命名和更换预览图（弹个选择文件的窗口）**」。

要守住的性质（都属于"错了就丢数据"那类）：

* **彻底删除**是**真删**（不进回收站）⇒ 护栏必须挡得住：没输 ok、库根、`_deps`
  依赖目录、库外面的路径；被挡住时**库里必须原封不动**；
* **重命名**不能把"已勾选"弄丢 ⇒ sidecar 里要**钉住 id**（id 由「路径 + 名字」算出，
  改名就会变，而勾选存的是 id）；改名失败要**把 sidecar 还原**；
* **换预览图**换完必须立刻生效 ⇒ `cover.<ext>` + sidecar 的 `cover`，并清掉旧的
  `cover.*`（免得越换越多、`find_cover` 挑到旧的那张）；
* 三个动作**失败一律不动用户的库**，并如实报错（不许失败还报成功）。

全部离线：`_mods()` 直接喂假数据（不受扫描规则变化影响），库落在 tmp 目录。
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from endfieldmodcontroller.api import EndfieldModControllerApi
from endfieldmodcontroller.config import AppConfig


@pytest.fixture()
def env(tmp_path):
    root = tmp_path / "root"
    library = root / "library"
    library.mkdir(parents=True)
    runtime = root / "runtime"
    (runtime / "_state").mkdir(parents=True)
    game = tmp_path / "game"
    game.mkdir()
    (game / "Endfield.exe").write_bytes(b"MZ")
    config = AppConfig(
        library_dir=str(library),
        runtime_dir=str(runtime),
        game_exe=str(game / "Endfield.exe"),
        dlss5_dir=str(runtime / "dlss5"),
        builtin_runtime_dir=str(runtime / "builtin"),
        staging_mods_dir=str(runtime / "EFMI" / "Mods"),
        dependency_manifest=str(root / "dependencies.json"),
    )
    config.save(root / "config.json")
    return SimpleNamespace(root=root, library=library, runtime=runtime,
                           config=config, config_path=root / "config.json")


def _make_mod(library: Path, name: str = "测试皮肤", mod_id: str = "m1") -> SimpleNamespace:
    """造一个"包套一层"的 Mod：`path` 指向**子目录**（真实库里的常见形状）。"""
    top = library / name
    inner = top / "sub"
    inner.mkdir(parents=True, exist_ok=True)
    (inner / "mod.ini").write_text("[TextureOverrideTest]\nhash = deadbeef\n", encoding="utf-8")
    return SimpleNamespace(id=mod_id, name=name, path=inner)


def _api(env, mods) -> EndfieldModControllerApi:
    api = EndfieldModControllerApi(env.config_path)
    api._mods = lambda: list(mods)        # 直接给扫描结果，测的是这三个动作本身
    return api


# ------------------------------------------------------------------ 彻底删除
def test_purge_requires_ok(env):
    """没输 ok（或输错）一律拒绝，而且**库里一点都不能动**。"""
    mod = _make_mod(env.library)
    api = _api(env, [mod])

    for bad in ("", "   ", "yes", "o", "okok", "确定"):
        r = api.purge_mod("m1", bad)
        assert r["ok"] is False, f"{bad!r} 不该被放行"
        assert (env.library / "测试皮肤").is_dir(), "没确认就把库删了"


def test_purge_accepts_ok_case_insensitive(env):
    """输 ok 才删（大小写与首尾空格宽容 —— 这道闸是防手滑，不是考拼写）。"""
    mod = _make_mod(env.library)
    api = _api(env, [mod])

    r = api.purge_mod("m1", " OK ")

    assert r["ok"] is True
    assert not (env.library / "测试皮肤").exists()


def test_purge_deletes_top_dir_not_inner_only(env):
    """删的是**库的顶层目录**，不是 `mod.path` 那个子目录（否则会把 Mod 包拆散）。"""
    mod = _make_mod(env.library)
    api = _api(env, [mod])

    api.purge_mod("m1", "ok")

    assert not (env.library / "测试皮肤").exists()
    assert list(env.library.iterdir()) == []


def test_purge_unselects(env):
    """删掉的 Mod 如果还在勾选里，必须同时去掉（否则下次启动找一个不存在的 Mod）。"""
    mod = _make_mod(env.library)
    env.config.selected_mods = ["m1", "other"]
    env.config.save(env.config_path)
    api = _api(env, [mod])

    r = api.purge_mod("m1", "ok")

    assert r["ok"] is True and r["unselected"] is True
    assert "m1" not in api.config.selected_mods
    assert "other" in api.config.selected_mods


def test_purge_refuses_dependency_dir(env):
    """`_deps`（重要前置）不是普通 Mod，拒绝删。"""
    deps = env.library / "_deps" / "RabbitFX"
    deps.mkdir(parents=True)
    api = _api(env, [SimpleNamespace(id="d1", name="_deps", path=deps)])

    r = api.purge_mod("d1", "ok")

    assert r["ok"] is False
    assert deps.is_dir()


def test_purge_refuses_library_root(env):
    """目标是库根本身 ⇒ 拒绝（这条最致命：删下去整个库都没了）。"""
    api = _api(env, [SimpleNamespace(id="root", name="library", path=env.library)])

    r = api.purge_mod("root", "ok")

    assert r["ok"] is False
    assert env.library.is_dir()


def test_purge_refuses_outside_library(env, tmp_path):
    """不在库里的路径（符号链接 / 配置指错）一律拒绝。"""
    outside = tmp_path / "别的地方"
    outside.mkdir()
    api = _api(env, [SimpleNamespace(id="x", name="别的地方", path=outside)])

    r = api.purge_mod("x", "ok")

    assert r["ok"] is False
    assert outside.is_dir()


def test_purge_unknown_mod(env):
    api = _api(env, [])
    assert api.purge_mod("nope", "ok")["ok"] is False


# ------------------------------------------------------------------ 重命名
def test_rename_moves_top_dir_and_keeps_id(env):
    """改名 = 库里的文件夹 + sidecar 的 name；**id 必须钉住**（勾选存的是 id）。"""
    mod = _make_mod(env.library)
    (mod.path / "mod.meta.json").write_text(
        json.dumps({"name": "测试皮肤", "id": "m1"}, ensure_ascii=False), encoding="utf-8")
    api = _api(env, [mod])

    r = api.rename_mod("m1", "我的新皮肤")

    assert r["ok"] is True
    assert not (env.library / "测试皮肤").exists()
    assert (env.library / "我的新皮肤" / "sub" / "mod.ini").is_file()
    payload = json.loads((env.library / "我的新皮肤" / "sub" / "mod.meta.json").read_text(encoding="utf-8"))
    assert payload["name"] == "我的新皮肤"
    assert payload["id"] == "m1", "id 变了就等于把用户已经选好的 Mod 丢了"


def test_rename_pins_id_when_sidecar_had_none(env):
    """sidecar 里原本没有 id 时，要在这次补上（否则新名字算出新 id）。"""
    mod = _make_mod(env.library)
    api = _api(env, [mod])

    api.rename_mod("m1", "有 id 了")

    payload = json.loads((env.library / "有 id 了" / "sub" / "mod.meta.json").read_text(encoding="utf-8"))
    assert payload["id"] == "m1"


def test_rename_rejects_bad_names(env):
    """空名 / 非法字符一律拒绝，库里原样不动。"""
    mod = _make_mod(env.library)
    api = _api(env, [mod])

    for bad in ("", "   ", "a/b", "a\\b", "a:b", "a?b", "a*b", "a<b", "a|b", "换\n行"):
        r = api.rename_mod("m1", bad)
        assert r["ok"] is False, f"{bad!r} 应该被拒"
    assert (env.library / "测试皮肤").is_dir()


def test_rename_rejects_existing_name(env):
    """库里已经有同名目录 ⇒ 拒绝（不许覆盖别人的 Mod）。"""
    _make_mod(env.library)
    (env.library / "另一个").mkdir()
    api = _api(env, [_make_mod(env.library)])

    r = api.rename_mod("m1", "另一个")

    assert r["ok"] is False
    assert (env.library / "另一个").is_dir() and (env.library / "测试皮肤").is_dir()


def test_rename_rolls_back_meta_when_move_fails(env, monkeypatch):
    """文件夹没改成，sidecar 必须还原 —— 别留下"名字和文件夹对不上"的现场。"""
    mod = _make_mod(env.library)
    meta = mod.path / "mod.meta.json"
    meta.write_text(json.dumps({"name": "测试皮肤"}, ensure_ascii=False), encoding="utf-8")
    api = _api(env, [mod])

    def boom(self, target):                      # noqa: ANN001
        raise OSError("被占用")

    monkeypatch.setattr(Path, "rename", boom)

    r = api.rename_mod("m1", "新名字")

    assert r["ok"] is False
    payload = json.loads(meta.read_text(encoding="utf-8"))
    assert payload.get("name") == "测试皮肤"
    assert (env.library / "测试皮肤").is_dir()


def test_rename_same_name_is_noop(env):
    mod = _make_mod(env.library)
    api = _api(env, [mod])

    r = api.rename_mod("m1", "测试皮肤")

    assert r["ok"] is True and r.get("unchanged") is True
    assert (env.library / "测试皮肤").is_dir()


# ------------------------------------------------------------------ 换预览图
def test_set_cover_copies_and_records(env, tmp_path):
    """把选的图存成 `cover.<ext>` + sidecar 写 `cover`，并清掉旧的那张。"""
    mod = _make_mod(env.library)
    (mod.path / "cover.jpg").write_bytes(b"old-cover")
    src = tmp_path / "新图.png"
    src.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    api = _api(env, [mod])
    api._native_file_dialog = lambda *a, **k: {"ok": True, "path": str(src)}   # noqa: ARG005

    r = api.set_mod_cover("m1")

    assert r["ok"] is True and r["cover"] == "cover.png"
    assert (mod.path / "cover.png").is_file()
    assert not (mod.path / "cover.jpg").exists(), "旧的 cover.* 要清掉，别越换越多"
    payload = json.loads((mod.path / "mod.meta.json").read_text(encoding="utf-8"))
    assert payload["cover"] == "cover.png"
    assert payload["id"] == "m1"


def test_set_cover_cancel_does_nothing(env):
    """用户关掉选图框 ⇒ 什么都不改，而且如实回 cancelled（前端不当失败弹窗）。"""
    mod = _make_mod(env.library)
    api = _api(env, [mod])
    api._native_file_dialog = lambda *a, **k: {"ok": False, "cancelled": True}   # noqa: ARG005

    r = api.set_mod_cover("m1")

    assert r["ok"] is False and r.get("cancelled") is True
    assert not list(mod.path.glob("cover.*"))


def test_set_cover_rejects_non_image(env, tmp_path):
    """选了非图片 ⇒ 拒绝，一个文件都不落。"""
    mod = _make_mod(env.library)
    src = tmp_path / "说明.txt"
    src.write_text("hello", encoding="utf-8")
    api = _api(env, [mod])
    api._native_file_dialog = lambda *a, **k: {"ok": True, "path": str(src)}   # noqa: ARG005

    r = api.set_mod_cover("m1")

    assert r["ok"] is False
    assert not list(mod.path.glob("cover.*"))


def test_set_cover_passes_file_type_filter(env, tmp_path):
    """选图框要**只列图片**（不然用户得在一堆 dll 里翻）—— 断言过滤条件真传下去了。"""
    mod = _make_mod(env.library)
    seen: dict = {}

    def fake_dialog(directory, title="", file_types=()):     # noqa: ANN001, ARG001
        seen["directory"] = directory
        seen["file_types"] = file_types
        return {"ok": False, "cancelled": True}

    api = _api(env, [mod])
    api._native_file_dialog = fake_dialog

    api.set_mod_cover("m1")

    assert seen["directory"] is False, "选的是文件不是目录"
    assert seen["file_types"], "没把图片过滤条件传下去"
    assert "png" in " ".join(seen["file_types"])
