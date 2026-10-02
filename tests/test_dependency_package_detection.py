"""含依赖名的**皮肤包**不能被当成依赖包藏起来（2026-10-02 外部反馈定案）。

**现象**：反馈者导入

    laevatain_as_2b_nier_-_by_primostudios_-_premium_nsfw_version_-_rabbitfx_da62a.zip

（莱万汀 as 2B Nier 皮肤）**连导三次**，日志每次都写
`导入: 完成 …（识别=莱万汀，置信度=high，需确认=否）`，
但他的 Mod 列表里**永远看不到它** ⇒ 反馈"这个模型无法导入"。

**根因**：导入后的目录名 = zip 名（`api.py::_import_archive_file`），里面带 `rabbitfx`
⇒ `core.infer_kind_and_group()` 判成 `kind="dependency"` ⇒
① 前端 `web/app.js::renderMods()` 对依赖项整条 `continue`（**卡片根本不渲染**）；
② `activation.resolve_active_set()` 的候选也排除 `is_dependency`（**永远进不了 staging**）。

**判据修正**：**名字像依赖 且 自己不带换装资源** 才是依赖包 ——
真正的依赖包只有 .ini/.txt（实测 `（重要前置）RabbitFX v24_3d366` 如此），皮肤包一定有
Meshes/Textures 之类的换装资源。

要守住的性质：
* 名字里带依赖名的**皮肤包** → `character`（进列表、能勾选、能进 staging）；
* 名字里带依赖名的**真依赖包** → 仍是 `dependency`（不进 Mod 列表，由依赖链路按需激活）；
* **`_deps\\` 布局不受影响**；
* **"已知有害依赖自动不加载"照旧**（这次改动不能把它放进来）。
"""
from __future__ import annotations

from pathlib import Path

from endfieldmodcontroller import activation, core, crashwatch

SKIN_INI = """
namespace = Lae2B
[TextureOverride_Component0]
hash = 6ec0fbe0
[Resource_TextureDiffuse]
filename = Textures/Diffuse.dds
[CommandList_Draw_Component0]
; 真实包就是靠 RabbitFX 设置纹理的（见 231-235 行），这里如实保留
Resource\\RabbitFX\\Diffuse = ref Resource_TextureDiffuse
run = CommandList\\RabbitFX\\SetTextures
"""
DEP_INI = """
[ShaderRegex_1]
shader_model = vs_5_0
[Constants]
global $rabbitfx_active = 0
"""

SKIN_DIRNAME = "laevatain_as_2b_nier_-_by_primostudios_-_premium_nsfw_version_-_rabbitfx_da62a"


def _skin_pack(root: Path, *parts: str) -> Path:
    """一个有换装资源的皮肤包（Meshes + Textures + ini）。"""
    target = root.joinpath(*parts)
    target.mkdir(parents=True, exist_ok=True)
    (target / "0.ini").write_text(SKIN_INI, encoding="utf-8")
    (target / "Meshes").mkdir(exist_ok=True)
    (target / "Meshes" / "Component0_VB0.buf").write_bytes(b"\x00" * 32)
    (target / "Textures").mkdir(exist_ok=True)
    (target / "Textures" / "Diffuse.dds").write_bytes(b"DDS " + b"\x00" * 32)
    return target


def _dependency_pack(root: Path, *parts: str) -> Path:
    """一个真依赖包（只有 ini/txt，没有任何换装资源）。"""
    target = root.joinpath(*parts)
    target.mkdir(parents=True, exist_ok=True)
    (target / "RabbitFX.ini").write_text(DEP_INI, encoding="utf-8")
    (target / "README.txt").write_text("RabbitFX", encoding="utf-8")
    return target


def _hidden_in_mod_list(mod) -> bool:
    """前端 `renderMods()` 的可见性判据（照抄，防止两边判据漂移）。"""
    group_name = str(mod.conflict_group or mod.group or "")
    return group_name == "_deps" or mod.kind == "dependency"


# ------------------------------------------------- ① 名字里带依赖名的皮肤包
def test_skin_pack_with_dependency_name_is_character(tmp_path):
    """本包的实际形态：目录名带 rabbitfx，但它是莱万汀的皮肤。"""
    library = tmp_path / "library"
    staging = tmp_path / "Mods"
    _skin_pack(library, SKIN_DIRNAME)

    mods = core.scan_library(library, staging)

    assert len(mods) == 1
    assert mods[0].kind == "character", mods[0].kind
    assert mods[0].is_dependency is False
    # 识别照旧（不是靠降级成依赖来"解决"）
    assert mods[0].group == "莱万汀", mods[0].group
    # 关键：**界面上必须看得见**
    assert _hidden_in_mod_list(mods[0]) is False


def test_skin_pack_with_dependency_name_reaches_staging(tmp_path):
    """光是"看得见"不够 —— 它还得能作为候选进 staging。"""
    library = tmp_path / "library"
    staging = tmp_path / "Mods"
    _skin_pack(library, SKIN_DIRNAME)

    mods = core.scan_library(library, staging)
    # 它**确实**引用了 RabbitFX —— 这个事实不能被"改判据"弄丢（真依赖包照旧会命中）
    assert core.collect_required_dependency_names(mods) == ["RabbitFX"]

    active, report = activation.resolve_active_set(mods, {mods[0].id})

    assert mods[0].id in report.selected
    assert [m.id for m in active] == [mods[0].id]


# ------------------------------------------------- ② 真依赖包仍是依赖
def test_real_dependency_package_is_still_dependency(tmp_path):
    library = tmp_path / "library"
    staging = tmp_path / "Mods"
    _dependency_pack(library, "RabbitFX -ENDMI-")

    mods = core.scan_library(library, staging)

    assert len(mods) == 1
    assert mods[0].kind == "dependency", mods[0].kind
    assert _hidden_in_mod_list(mods[0]) is True


def test_prefixed_dependency_package_is_still_dependency(tmp_path):
    """用户手放的"重要前置"包（带包裹层 + 前缀）同样不能变成皮肤卡。"""
    library = tmp_path / "library"
    staging = tmp_path / "Mods"
    _dependency_pack(library, "（重要前置）RabbitFX v24_3d366", "RabbitFX -ENDMI-")

    mods = core.scan_library(library, staging)

    assert len(mods) == 1
    assert mods[0].kind == "dependency", (mods[0].name, mods[0].kind)


def test_deps_dir_layout_unaffected(tmp_path):
    """`_deps\\<依赖>` 布局照旧（它是内部依赖，与名字判据无关）。"""
    library = tmp_path / "library"
    staging = tmp_path / "Mods"
    _dependency_pack(library, "_deps", "RabbitFX")
    _skin_pack(library, "陈千语-夏日")

    mods = {m.name: m for m in core.scan_library(library, staging)}

    assert mods["RabbitFX"].kind == "dependency"
    assert mods["RabbitFX"].is_dependency is True
    assert mods["陈千语-夏日"].kind == "character"


# ------------------------------------------------- ③ 判据本身
def test_is_dependency_package_name_only_fallback():
    """拿不到路径时退化成"只看名字"（保持老行为）。"""
    assert core.is_dependency_package("RabbitFX -ENDMI-") is True
    assert core.is_dependency_package("陈千语-夏日") is False
    assert core.is_dependency_package(SKIN_DIRNAME) is True       # 只看名字：像依赖


def test_is_dependency_package_with_path_splits_by_resources(tmp_path):
    skin = _skin_pack(tmp_path / "lib", SKIN_DIRNAME)
    dep = _dependency_pack(tmp_path / "lib", "RabbitFX -ENDMI-")

    assert core.is_dependency_package(skin.name, skin) is False
    assert core.is_dependency_package(dep.name, dep) is True


def test_dependency_key_of_unchanged():
    """`dependency_key_of`（按名字包含找依赖）语义不变 —— 依赖按需激活还靠它。"""
    assert core.dependency_key_of("（重要前置）RabbitFX v24_3d366") == "rabbitfx"
    assert core.dependency_key_of("Orfix") == "orfix"
    assert core.dependency_key_of(SKIN_DIRNAME) == "rabbitfx"


# ------------------------------------------------- ④ 皮肤包不能当依赖候选
def test_skin_pack_is_not_a_dependency_candidate(tmp_path):
    """名字带 rabbitfx 的皮肤包不能被当成"那份 RabbitFX"（否则会被整包塞进 staging）。"""
    library = tmp_path / "library"
    staging = tmp_path / "Mods"
    _skin_pack(library, SKIN_DIRNAME)

    mods = core.scan_library(library, staging)
    picked, blocked = activation.plan_dependencies(mods, {"rabbitfx"}, skip_known_bad=False)

    assert picked == {}, picked
    assert blocked == [], blocked


def test_real_dependency_is_picked_when_not_known_bad(tmp_path):
    """对照组：真依赖包照旧能被按需激活（关掉"已知有害"闸门时）。"""
    library = tmp_path / "library"
    staging = tmp_path / "Mods"
    _dependency_pack(library, "_deps", "RabbitFX")

    mods = core.scan_library(library, staging)
    picked, _ = activation.plan_dependencies(mods, {"rabbitfx"}, skip_known_bad=False)

    assert "rabbitfx" in picked, picked


# ------------------------------------------------- ⑤ 已知有害仍照旧生效
def test_known_bad_dependency_still_skipped_when_gate_on(tmp_path, monkeypatch):
    """闸门**显式打开**时，"自动不加载"照旧生效 —— 机制没被弄坏。

    ⚠️ `core.KNOWN_BAD_DEPENDENCIES` 现在**是空的**（RabbitFX 已于 2026-10-02 由用户实测洗清、
    条目被移除 —— 原话「**是带着 RabbitFX 的，进去渲染啥的都没啥问题**」），闸门默认也已是关的；
    所以这里**自己塞一条**进去，测的是"闸门机制本身还活着"，而不是"RabbitFX 还被禁着"。
    """
    monkeypatch.setitem(core.KNOWN_BAD_DEPENDENCIES, "rabbitfx", "测试用（演示闸门仍可用）")
    library = tmp_path / "library"
    staging = tmp_path / "Mods"
    _dependency_pack(library, "_deps", "RabbitFX")
    _skin_pack(library, SKIN_DIRNAME)

    mods = core.scan_library(library, staging)
    skin_mod = next(m for m in mods if m.kind == "character")
    active, report = activation.resolve_active_set(
        mods, {skin_mod.id}, skip_known_bad_dependencies=True
    )

    # 皮肤包照旧生效
    assert [m.id for m in active] == [skin_mod.id]
    # 真 RabbitFX 被那道闸拦下，且**不算"依赖缺失"**（2026-10-02 的语义）
    assert any(item.get("skipped") == "known_bad" for item in report.blocked_dependencies), \
        report.blocked_dependencies
    assert "RabbitFX" not in [m.name for m in active]
    assert report.missing_dependencies == []


def test_known_bad_dependency_goes_to_staging_by_default(tmp_path):
    """**默认**（闸门关着）RabbitFX 会被按需激活进 staging —— 这正是用户要实测的那条。"""
    library = tmp_path / "library"
    staging = tmp_path / "Mods"
    _dependency_pack(library, "_deps", "RabbitFX")
    _skin_pack(library, SKIN_DIRNAME)

    mods = core.scan_library(library, staging)
    skin_mod = next(m for m in mods if m.kind == "character")
    active, report = activation.resolve_active_set(mods, {skin_mod.id})

    assert sorted(m.name for m in active) == sorted([skin_mod.name, "RabbitFX"]), \
        [m.name for m in active]
    assert report.missing_dependencies == []


# ------------------------------------------------- ⑥ staging 清单（崩溃归因）
def test_staging_dir_of_skin_pack_is_not_dependency(tmp_path):
    """staging 里这个皮肤包不能被当成依赖排除 —— 否则崩溃归因会漏掉真正的 Mod。"""
    staging = tmp_path / "EFMI" / "Mods"
    skin = _skin_pack(staging, f"MC_莱万汀_{SKIN_DIRNAME}")
    dep = _dependency_pack(staging, "MC_RabbitFX -ENDMI-_RabbitFX -ENDMI-")
    _skin_pack(staging, "MC_陈千语_夏日")

    assert crashwatch._is_dependency_dir(skin) is False
    assert crashwatch._is_dependency_dir(dep) is True
