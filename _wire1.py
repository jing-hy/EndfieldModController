"""把「长路径」对策接进 `api._import_archive_file()`。

**issue #12 实测**：那条路径 264 字符 > Windows 上限 259 ⇒
`[Errno 2] No such file or directory`（父目录建得出、文件写不进）。

接入两块：
① **解压前预检**：扫一遍包内条目，预判会超长的**当场拦住**并给可照做的指引
   （而不是解到一半抛英文 errno）；
② **zip 能用长路径就用**：给目标目录加 `\\\\?\\` 前缀再解 ——
   Python 的 `open()` 认这个前缀，很多包其实能直接解开（预检只是兜底）。
   7z/rar 走外部 bsdtar，未必认这个前缀 ⇒ 那两种只做预检。
"""
from pathlib import Path

p = Path("endfieldmodcontroller/api.py")
s = p.read_text(encoding="utf-8")

# 在真正解压之前插入预检
old = '''        try:
            dest.mkdir(parents=True, exist_ok=True)
            if suffix == ".zip":
                self._extract_zip_into(archive_path, dest)
            else:'''
new = '''        # ⚠️⚠️ **解压前预判"长路径"**（issue #12：「mod无法解压」，实测 264 字符 > Windows 上限 259）。
        # 不做这一步的话，解到一半才会抛 `[Errno 2] No such file or directory`，
        # 用户完全不知道为什么、也不知道怎么办。这里**开场就说清**。
        try:
            from . import longpath as _longpath

            if suffix == ".zip":
                import zipfile as _zf

                with _zf.ZipFile(archive_path) as _arc:
                    _members = _arc.namelist()
            else:
                _members = _names_from_archive(archive_path)
            _verdict = _longpath.check_lengths(dest, _members)
            if _verdict.get("too_long"):
                launcher._append_log(
                    self.config,
                    f"导入: {name} 有 {len(_verdict['too_long'])} 个条目路径过长"
                    f"（最长 {_verdict['worst']} 字符，上限 {_verdict['limit']}）")
                # zip 先试试用扩展长度前缀解（Python 的 open() 认 `\\\\?\\`）；
                # 成功就继续，失败再如实报错。
                if suffix != ".zip" or not self._extract_zip_into_long(archive_path, dest):
                    return {"ok": False, "long_path": True,
                            "source_path": str(_longpath_keep(self.config, archive_path, name)),
                            "target_dir": str(self.config.library_path),
                            "message": _longpath.explain(dest, _verdict)}
        except Exception as exc:  # noqa: BLE001 —— 预判本身出错不该挡住导入
            launcher._append_log(self.config, f"导入: 长路径预判出错（忽略继续）：{exc}")

        try:
            dest.mkdir(parents=True, exist_ok=True)
            if suffix == ".zip":
                if _longpath_ok(dest):
                    pass          # 上面已经用扩展前缀解过了
                else:
                    self._extract_zip_into(archive_path, dest)
            else:'''
assert old in s, "解压前锚点未命中"
s = s.replace(old, new, 1)
print("  ① 已插入解压前预检")
p.write_text(s, encoding="utf-8")
