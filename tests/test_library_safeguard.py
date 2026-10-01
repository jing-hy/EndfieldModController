"""「不要动用户的 Mod 库」护栏测试（2026-10-01 用户硬规则）。

用户原话：「**任何情况（除用户手动点击移出库外）都不要动用户的 mod 库（包括换位置）**」。
背景：一条外部反馈说「重装的时候还把我 mod 都删完了，还好我备份了」——
根因是清理 staging 是无条件 `rmtree`，而一旦 `library_dir` 与 `staging_mods_dir`
相同或互相嵌套（老教程让人把 Mod 放进 EFMI 的 Mods 目录，很容易配成这样），
清理 staging 就等于把库删光。

这些用例覆盖"危险配置下：拒绝执行 + 库内文件一个都不能少"。
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from endfieldmodcontroller import activation, fsutil
from endfieldmodcontroller.config import AppConfig

MOD_INI = """
namespace = TestMod
[Constants]
global persist $x = 0
[KeyX]
key = no_modifiers VK_9
type = cycle
$x = 0,1
"""


@pytest.fixture()
def env(tmp_path):
    library = tmp_path / "library"
    (library / "陈" / "夏日").mkdir(parents=True)
    (library / "陈" / "夏日" / "mod.ini").write_text(MOD_INI, encoding="utf-8")
    (library / "陈" / "夏日" / "texture.png").write_bytes(b"\x89PNG fake")
    return library


def _config(tmp: Path, library: Path, staging: Path) -> AppConfig:
    return AppConfig(
        library_dir=str(library),
        runtime_dir=str(tmp / "runtime"),
        staging_mods_dir=str(staging),
    )


# --------------------------------------------------------------- 判据本身
def test_library_conflict_detects_all_three_dangerous_shapes(tmp_path):
    lib = tmp_path / "library"
    assert fsutil.library_conflict(lib, lib) != ""                      # 目标就是库
    assert fsutil.library_conflict(lib, lib / "某个Mod") != ""           # 目标在库内
    assert fsutil.library_conflict(lib, tmp_path) != ""                  # 目标是库的上级
    assert fsutil.library_conflict(lib, tmp_path / "staging") == ""      # 无关 → 安全
    assert fsutil.library_conflict(None, lib) == ""                      # 没传库 → 不拦


# --------------------------------------------------------------- staging 拒绝
@pytest.mark.parametrize("shape", ["same", "library_inside_staging", "staging_inside_library"])
def test_stage_and_prepare_refuses_and_keeps_library_intact(env, tmp_path, shape):
    if shape == "same":
        staging = env
    elif shape == "library_inside_staging":
        staging = tmp_path                     # 库在 staging 里
    else:
        staging = env / "_staged"              # staging 在库里
    config = _config(tmp_path, env, staging)
    before = sorted(p.relative_to(env).as_posix() for p in env.rglob("*") if p.is_file())

    with pytest.raises(activation.LibraryGuardError) as excinfo:
        activation.stage_and_prepare(
            config.library_path, config.staging_mods_path, config.runtime_path,
            selected_ids=["whatever"],
        )
    assert "Mod 库" in str(excinfo.value)

    after = sorted(p.relative_to(env).as_posix() for p in env.rglob("*") if p.is_file())
    assert after == before, "护栏触发时库内文件必须一个不少"


def test_empty_selection_also_refuses(env, tmp_path):
    """空选择走 `_stage_empty`（它会清空 staging 下所有目录）—— 同样必须被拦。"""
    config = _config(tmp_path, env, env)          # staging = library（危险配置）
    with pytest.raises(activation.LibraryGuardError):
        activation.stage_and_prepare(
            config.library_path, config.staging_mods_path, config.runtime_path,
            selected_ids=[],
        )
    assert (env / "陈" / "夏日" / "mod.ini").is_file()


# --------------------------------------------------------------- 其它删除入口
def test_cleanup_staging_skips_library_paths(env, tmp_path):
    """清单里若指向库（历史配置变化留下的旧路径），清理必须跳过 —— 这是真正的护栏。"""
    import json

    staging = tmp_path / "staging"
    managed = staging / "EndfieldModControllerManaged"
    managed.mkdir(parents=True)
    insider = env / "陈" / "夏日"
    (managed / "active_targets.json").write_text(json.dumps([str(insider)]), encoding="utf-8")
    (staging / "MC_Controller").mkdir()

    removed = activation.cleanup_staging(staging, env)

    assert insider.is_dir() and (insider / "mod.ini").is_file(), "库里的目录绝不能被清单带走"
    assert not (staging / "MC_Controller").exists(), "staging 自己的产物照常清"
    assert all("library" not in item.lower() for item in removed)


def test_cleanup_staging_without_library_still_works(tmp_path):
    """不传 library_root 时保持原行为（向后兼容）。"""
    staging = tmp_path / "staging"
    (staging / "MC_Controller").mkdir(parents=True)
    removed = activation.cleanup_staging(staging)
    assert removed and not (staging / "MC_Controller").exists()


def test_import_manual_mods_never_deletes_library_mods(env, tmp_path):
    """staging 与库重叠时，收编流程**不许**把库里的目录当"手动目录"删掉。"""
    config = _config(tmp_path, env, env)          # staging = library（危险配置）
    result = activation.import_manual_mods(config)
    assert (env / "陈" / "夏日" / "mod.ini").is_file(), "库里的 Mod 必须还在"
    # 库里那个目录不该被当作"手动 Mod"搬走/删掉
    assert not any("夏日" in str(item) for item in (result.get("imported") or []))


# --------------------------------------------------------------- 配置校验
def test_config_validate_reports_overlap(env, tmp_path):
    config = _config(tmp_path, env, env)
    problems = config.validate()
    assert any("Staging Mods 目录与 Mod 库重叠" in p for p in problems)

    ok_config = _config(tmp_path, env, tmp_path / "staging")
    assert not any("重叠" in p for p in ok_config.validate())


def test_dependency_install_dir_must_stay_in_deps(env):
    """依赖安装目录只允许落在 `_deps\\` 之内。

    下游紧接着就是 `shutil.rmtree(install_dir)` —— 若清单里写一个**普通 Mod 目录名**，
    就会把用户放进库里的 Mod 删掉（用户 2026-10-01 硬规则）。
    """
    from endfieldmodcontroller import dependencies

    lib = env
    assert dependencies._safe_install_dir(lib, "_deps/RabbitFX") == (lib / "_deps" / "RabbitFX").resolve()
    for bad in ("", "陈/夏日", "陈", ".", "..", "_deps/../陈/夏日", "C:/Windows"):
        with pytest.raises(ValueError):
            dependencies._safe_install_dir(lib, bad)
    assert (lib / "陈" / "夏日" / "mod.ini").is_file()


def test_safe_layout_still_stages_normally(env, tmp_path):
    """正常配置（staging 在库外）下，功能不受影响。"""
    from endfieldmodcontroller import core

    staging = tmp_path / "staging"
    config = _config(tmp_path, env, staging)
    mods = core.scan_library(config.library_path, staging)
    result = activation.stage_and_prepare(
        config.library_path, config.staging_mods_path, config.runtime_path,
        selected_ids=[m.id for m in mods],
    )
    assert result["patch_count"] == 0            # 默认不接管热键
    assert (env / "陈" / "夏日" / "mod.ini").is_file()
    assert list(staging.glob("MC_*")), "正常配置下该 stage 出产物"
