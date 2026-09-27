from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from endfieldmodcontroller import core, dependencies


class DependencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="mc-dep-")
        self.root = Path(self.tmp.name)
        self.library = self.root / "library"
        self.library.mkdir(parents=True)
        self.manifest_path = self.root / "dependencies.json"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _make_zip(self, name: str = "MyDep.zip") -> Path:
        archive = self.root / name
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("MyDep/mod.ini", "[Constants]\nglobal persist $enabled = 1\n")
        return archive

    def test_update_from_url_zip(self) -> None:
        archive = self._make_zip()
        spec = dependencies.DependencySpec(
            key="MyDep",
            display="MyDep",
            source="url",
            install_dir="_deps/MyDep",
            url=archive.as_uri(),
        )
        result = dependencies.update_dependency(spec, self.library)
        self.assertEqual(result.status, "downloaded")
        self.assertTrue((self.library / "_deps" / "MyDep" / "mod.ini").is_file())
        # second run should see the marker and report up to date
        result2 = dependencies.update_dependency(spec, self.library)
        self.assertEqual(result2.status, "up_to_date")

    def test_update_all_progress_callback(self) -> None:
        archive = self._make_zip()
        spec = dependencies.DependencySpec(
            key="MyDep",
            display="MyDep",
            source="url",
            install_dir="_deps/MyDep",
            url=archive.as_uri(),
        )
        events = []
        results = dependencies.update_all(
            {"MyDep": spec},
            self.library,
            dry_run=False,
            progress=lambda current, total, key, status: events.append((current, total, key, status)),
        )
        self.assertEqual(len(results), 1)
        self.assertTrue(events)
        self.assertEqual(events[-1][0], events[-1][1])
        self.assertEqual(events[-1][2], "MyDep")

    def test_select_missing_dependencies(self) -> None:
        spec = dependencies.DependencySpec(
            key="MyDep",
            display="MyDep",
            source="url",
            install_dir="_deps/MyDep",
            url="file:///nonexistent.zip",
        )
        selected = dependencies.select_missing_dependencies({"MyDep": spec}, self.library, ["MyDep"])
        self.assertIn("MyDep", selected)
        (self.library / "_deps" / "MyDep").mkdir(parents=True)
        selected = dependencies.select_missing_dependencies({"MyDep": spec}, self.library, ["MyDep"])
        self.assertNotIn("MyDep", selected)

    def test_manifest_and_report(self) -> None:
        self.manifest_path.write_text(json.dumps({
            "MyDep": {
                "display": "MyDep",
                "source": "url",
                "url": "file:///nonexistent.zip",
                "install_dir": "_deps/MyDep",
            }
        }), encoding="utf-8")
        manifest = dependencies.load_manifest(self.manifest_path)
        self.assertIn("MyDep", manifest)
        mod = core.ModInfo(
            id="m1", name="夏日", path=self.library / "夏日", kind="character",
            conflict_group="陈", requires=["MyDep"],
        )
        report = dependencies.dependency_report(self.library, [mod], self.manifest_path)
        self.assertEqual(report["required"], ["MyDep"])
        self.assertFalse(report["manifest"]["MyDep"]["present"])


if __name__ == "__main__":
    unittest.main()
