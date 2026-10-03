import re
from pathlib import Path

p = Path("src/App.vue"); s = p.read_text(encoding="utf-8")
script = s.split("</script>")[0]

# 收集 import 进来的名字（含解构与默认）
imported = set()
for m in re.finditer(r'import\s+(?:(\w+)\s*,?\s*)?(?:\{([^}]*)\})?\s*from', script):
    if m.group(1):
        imported.add(m.group(1).strip())
    if m.group(2):
        for part in m.group(2).split(","):
            name = part.strip().split(" as ")[-1].strip()
            if name:
                imported.add(name)

# 本文件内定义的名字（const/let/function/class）
defined = set(re.findall(r'\b(?:const|let|var|function|class)\s+([A-Za-z_$][\w$]*)', script))
# 解构声明 const { a, b } = ...
for m in re.finditer(r'\b(?:const|let|var)\s*\{([^}]*)\}', script):
    for part in m.group(1).split(","):
        name = part.strip().split(":")[-1].split("=")[0].strip()
        if name:
            defined.add(name)

# 模板 + script 里被调用的那些"看起来是本项目的"标识符
used = set(re.findall(r'\b([a-z][A-Za-z0-9_$]*)\s*\(', script + s.split("</script>")[-1]))
# 排除 JS 内置与常见全局
builtin = {
    "if","for","while","switch","catch","return","typeof","function","new","await","do",
    "parseInt","parseFloat","String","Number","Boolean","Array","Object","JSON","Math","Date",
    "Set","Map","Promise","setTimeout","setInterval","clearTimeout","clearInterval",
    "requestAnimationFrame","console","alert","confirm","prompt","require","fetch",
    "decodeURIComponent","encodeURIComponent","isNaN","RegExp","Error","Symbol",
}
missing = sorted(n for n in used - imported - defined - builtin)
print("  App.vue 里可能未定义就被调用的名字：")
for n in missing:
    # 只报告真正可疑的（排除模板里本地方法之外的零散）
    print("    ", n)
print("\n  合计:", len(missing))
