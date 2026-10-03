from pathlib import Path

s = Path("frontend/src/pages/ModLibraryPage.vue").read_text(encoding="utf-8")
i = s.find('"prepare"')
print("prepare 出现位置:", i)
print(repr(s[max(0, i - 120):i + 160]))
