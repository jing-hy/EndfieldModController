<script setup>
// 服装 Mod页（旧 #tab-library）：三个分区卡片 —— 皮肤 Mod / 下载 Mod / Mod 列表。
// 分组与过滤规则照抄旧 renderMods：按 conflict_group||group 分组，
// 跳过 _deps 分组与 kind=dependency/tool/assist（那些由依赖页 / 辅助页管）。
import { ref, computed, onMounted, onUnmounted, watch } from "vue";
import { call } from "../lib/bridge.js";
import { store, refreshState } from "../store.js";
import { loadSettings } from "../lib/settings.js";
import { settings, saveSetting } from "../lib/settings.js";
import { humanSize } from "../lib/util.js";
import Card from "../components/ui/Card.vue";
import ModDownloadCard from "../components/ModDownloadCard.vue";
import { Library } from "lucide-vue-next";
import Btn from "../components/ui/Btn.vue";
import Switch from "../components/ui/Switch.vue";
import ConflictDialog from "../components/ConflictDialog.vue";
import { Check, ImageOff } from "lucide-vue-next";
import { showAlert, showModalDialog, showToast } from "../lib/dialog.js";
import { setStatus } from "../lib/status.js";

const urls = ref("");
// 封面缓存在 store 里（跨页面存活）—— 见 store.js 的注释
const covers = computed(() => store.covers);
const busy = ref(false);
// 「⋯ 更多」：就地弹出的小菜单（用户准则：⋯ 要就地弹小菜单，不要弹窗）
const menu = ref(null);          // { id, name, x, y }
const chars = ref([]);
const assignRef = ref(null);   // 「更换归属」弹窗（带下拉，见 CharacterAssignDialog）           // 已知角色（用于"更换归属"）
const keyword = ref("");          // 搜索（评审：Mod 一多，没搜索只能靠翻）
// 冲突处理：生成控制器之后检查一次，有冲突就弹「每组一个下拉框」的窗
const conflicts = ref(null);
let timer = null, dlTimer = null;

// ⚠️ 选中状态的真源是 **`config.selected_mods`**（后端 `get_state()` 顶层**没有**
// `selected` 这个键）。这里原来读的是 `store.state.selected` ⇒ 永远是空集合，
// 于是"点开关保存成功、界面却纹丝不动"（用户 2026-10-03 反馈「mod 的开关按了没反应」）。
const selected = computed(
  () => new Set((((store.state.config || {}).selected_mods) || []).map(String)),
);
const groups = computed(() => {
  const g = {};
  const kw = keyword.value.trim().toLowerCase();
  for (const mod of store.state.mods || []) {
    if (kw && !String(mod.name || "").toLowerCase().includes(kw)
        && !String(mod.conflict_group || mod.group || "").toLowerCase().includes(kw)) continue;
    const key = String(mod.conflict_group || mod.group || "");
    if (key === "_deps" || mod.kind === "dependency" || mod.kind === "tool") continue;
    if (mod.kind === "assist") continue;
    const name = mod.conflict_group || mod.group || "未分类";
    (g[name] ||= []).push(mod);
  }
  return Object.keys(g).sort((a, b) => String(a).localeCompare(String(b), "zh-Hans-CN"))
    .map((name) => ({
      name,
      mods: g[name],
      enabled: g[name].filter((m) => selected.value.has(String(m.id))).length,
    }));
});

async function loadCover(id) {
  if (covers.value[id]) return;
  // demo 模式：封面来自快照（file:// 下前端读不到本地图片，快照里已内联成 data URI）
  const preset = (store.demoCovers || {})[id];
  if (preset) { store.covers[id] = preset; return; }
  try {
    const r = await call("get_mod_cover", id);
    // ⚠️ 后端的字段名是 **data_uri**（其余几个是历史写法，留着兜底）——
    // 迁移时我写成了 `r.data`，导致封面一直取不到、列表里全是"无封面"占位。
    const uri = r && (r.data_uri || r.data || r.uri || r.image || r.base64);
    if (r && r.ok && uri) store.covers[id] = uri;
  } catch (e) { /* 没有封面很正常 */ }
}

async function toggleMod(mod) {
  const ids = new Set(selected.value);
  const id = String(mod.id);
  if (ids.has(id)) ids.delete(id);
  else {
    ids.add(id);
    // 同角色互斥：除非用户在设置里明确关掉了互斥
    if (!settings.allow_same_character_mods) {
      for (const other of store.state.mods || []) {
        if (String(other.id) !== id && (other.conflict_group || other.group) &&
            (other.conflict_group || other.group) === (mod.conflict_group || mod.group)) {
          ids.delete(String(other.id));
        }
      }
    }
  }
  try {
    // ⚠️ 这里**不要**调 `refreshState()`：那会全量重拉 `get_state()`（重新扫描整个 服装 Mod），
    //    每次点开关都要等它跑完 —— 用户 2026-10-03 反馈「mod 的按钮反应怎么这么慢，
    //    其他开关都没这个问题」（设置页/启动页的开关只发一个键，所以快）。
    //    `selected` 是从 `store.state.config.selected_mods` 派生的，把新值写回去界面就立刻响应。
    const result = await call("save_config", { selected_mods: Array.from(ids) });
    const applied = (result && result.config && result.config.selected_mods) || Array.from(ids);
    if (store.state) {
      if (!store.state.config || typeof store.state.config !== "object") store.state.config = {};
      store.state.config.selected_mods = applied;
    }
  } catch (e) { /* call 已弹窗 */ }
}

function openMenu(mod, event) {
  event.stopPropagation();
  const box = event.currentTarget.getBoundingClientRect();
  // ⚠️ 坐标必须在**脚本**里算好：Vue 模板作用域拿不到 window（写了会直接报错）。
  const width = 172;
  const x = Math.max(8, Math.min(box.right - width, (window.innerWidth || 1200) - width - 8));
  // 上下都要兜底：窗口很矮时 `innerHeight - 190` 会是负数，菜单就跑到窗口上方看不见了
  const y = Math.max(8, Math.min(box.bottom + 4, (window.innerHeight || 800) - 190));
  // ⚠️ 把 `kind` 一起存下来 —— 模板里判断「移到辅助/服装」要用它（模板作用域拿不到 mod）
  menu.value = {
    id: String(mod.id), name: mod.name, kind: String(mod.kind || ""), x, y,
    // ⚠️ C4：回滚是否可用（后端按"有没有修复备份"算）
    can_rollback: mod.can_rollback !== false,
  };
}
function closeMenu() { menu.value = null; }

async function menuAct(act) {
  const m = menu.value;
  if (!m) return;
  closeMenu();
  try {
    if (act === "fix") {
      const r = await call("fix_mod", m.id);
      if (r && r.ok === false) await showAlert("修复失败", r.message || "未知原因");
      else showToast(`已修复 ${m.name}`, "success");
    } else if (act === "rollback") {
      const r = await call("rollback_mod", m.id);
      if (r && r.ok === false) await showAlert("回滚失败", r.message || "未知原因");
      else showToast(`已回滚 ${m.name}`, "success");
    } else if (act === "delete") {
      // 破坏性动作：默认聚焦安全项、按钮文字自解释（用户准则）
      const ok = await showModalDialog({
        // 标题直接说动作（评审：原标题"确认"、以及把 runtime\backups\mod-trash 这种内部路径
        // 摆给用户，都会让人以为要删到系统目录里去）
        title: "移出 服装 Mod？",
        message: `${m.name}\n\n它会从 服装 Mod列表里移出并留一份备份，之后不再加载。`
          + `\n不会删除你的其它 Mod，也不会动游戏本体。`,
        okText: "移出并备份", cancelText: "保留在库",
      });
      if (!ok) return;
      const r = await call("delete_mod", m.id);
      if (r && r.ok === false) await showAlert("移出失败", r.message || "未知原因");
      else showToast(r && r.moved_to ? `已移出库：${r.moved_to}` : "已移出 服装 Mod", "success");
    } else if (act === "character") {
      if (!chars.value.length) {
        const r = await call("known_characters");
        // ⚠️ 后端 `known_characters()` 返回的是**纯数组 list[str]**（不是 {characters:[...]}），
        // 原先按对象读 ⇒ 永远拿到空数组 ⇒「更改所属角色」的下拉里一个角色都没有（2026-10-03 修）。
        chars.value = Array.isArray(r) ? r : ((r && (r.characters || r.items)) || []);
      }
      // ⚠️ 以前这里用 showModalDialog —— 它**只返回 true/false、没有输入控件**，
      // 于是文案写着"输入角色名（留空 = 保持未分类）"却没法输入，
      // `pick === true ? "" : String(pick)` **永远把归属设成空**。
      // 改成真正的下拉选择器（CharacterAssignDialog）。
      assignRef.value.openFor(m);
      return;
    } else if (act === "toAssist" || act === "toSkin") {
      // 判据从 `menu.kind` 来（模板只传 act）
      // 用户 2026-10-03：「一些被误识别的 mod 可以在辅助和皮肤之间移动」——
      // 自动判据只能猜，猜错了要让用户一句话改过来（写进该 Mod 的 mod.meta.json）。
      const want = act === "toAssist" ? "assist" : "character";
      const r = await call("set_mod_kind", m.id, want);
      if (r && r.ok === false) await showAlert("移动失败", r.message || "未知原因");
      else showToast(want === "assist" ? `「${m.name}」已移到辅助 Mod` : `「${m.name}」已移到皮肤 Mod`, "success");
    } else if (act === "open") {
      const mod = (store.state.mods || []).find((x) => String(x.id) === m.id);
      if (mod && mod.path) await call("open_path_in_explorer", mod.path);
    }
    await refreshState();
    loadSettings();
  } catch (e) { /* call() 已经弹过窗 */ }
}

async function scan() { busy.value = true; try { await call("scan"); await refreshState();
    loadSettings(); } catch (e) {} finally { busy.value = false; } }
async function prepare() {
  busy.value = true;
  try {
    // ⚠️⚠️ **B11：被后端拒绝时不能静默**（2026-10-03 补回归）。
    // staging 与 Mod 库重叠时后端**拒绝执行**并返回
    // `{ok: false, blocked: "library_overlap", message: ...}`（保护用户的 Mod 库 ——
    // 用户 2026-10-01 定下的硬规则）。0.9.5 拿到这个结构会弹「保护 Mod 库」说明框；
    // 换代后这里**忽略返回值**、只在没冲突时给 toast ⇒ 点了没反应也不知道为什么。
    const prep = await call("prepare");
    if (prep && prep.ok === false) {
      if (prep.blocked === "library_overlap") {
        await showModalDialog({
          title: "为了保护你的 Mod 库，已停止生成",
          message: [
            prep.message || "暂存目录和 Mod 库重叠了。",
            "",
            "这个检查是故意的：暂存目录若落在 Mod 库里面，每次生成控制器都会清空暂存目录，"
              + "等于把你库里的 Mod 删掉。",
            "",
            "去「设置 → 工作区与 Mod 库」看一眼这两个路径，把它们分开就好。",
          ].join("\n"),
          okText: "知道了", showCancel: false,
        });
      } else {
        await showAlert("生成控制器失败", prep.message || "未知原因");
      }
      return;
    }
    // prepare 会刷新 runtime\_state\mod_conflicts.json，紧接着读一次结论
    const info = await call("conflict_groups");
    const groups = (info && info.groups) || [];
    if (groups.length) conflicts.value = groups;
    else showToast("生成完毕，没有发现资源冲突。", "success");
  } catch (e) { /* call 已弹窗 */ } finally { busy.value = false; }
}

async function resolveConflicts(keep) {
  conflicts.value = null;
  try {
    const r = await call("resolve_mod_conflicts", keep);
    if (r && r.ok === false) await showAlert("处理失败", r.message || "未知原因");
    else showToast((r && r.message) || "已处理冲突", "success");
    await refreshState();
    loadSettings();
  } catch (e) { /* call 已弹窗 */ }
}
// ⚠️ **「一键修复所有 Mod」补齐确认 / 进度 / 结果**（2026-10-03 修回归）。
// 0.9.5 是：确认框（讲清会备份、可回滚、跳过已修的）→ `fix_all_mods(true)`
// → `setInterval` 轮询 `fix_all_progress`，把「修复中 3/29：名字」写进状态行
// → 完成后列出失败项。
// 换代到 Vue 之后只剩一句 `await call("fix_all_mods")`：**没有确认、没有进度、没有结果**
//（后端 `fix_all_progress` 前端零调用）—— 这是个要跑 29 个 Mod 的后台长任务，
// 全程零反馈会让人以为卡死了。这里按 0.9.5 的语义补回来，展示沿用现有 Btn/Card/Toast。
const fixRunning = ref(false);
const fixText = ref("");
let fixTimer = null;

function stopFixPoll() {
  if (fixTimer) { clearInterval(fixTimer); fixTimer = null; }
}

async function fixAll() {
  const ok = await showModalDialog({
    title: "一键修复所有 Mod",
    message: [
      "会逐个修复「服装 Mod」里还没修过的那些。",
      "",
      "• 每个 Mod 修复前都会**备份**，可随时用 ⋯→「回滚」还原",
      "• 已经修过的会跳过",
      "• 过程中界面不会卡（后台跑，这里显示进度）",
    ].join("\n"),
    okText: "开始修复", cancelText: "取消",
  });
  if (!ok) return;

  const started = await call("fix_all_mods", true);
  if (started && started.ok === false) {
    showToast(String(started.message || "启动修复失败"), "danger");
    return;
  }
  if (started && started.already) {
    showToast("已经有一轮修复在进行中", "info");
  } else {
    showToast(`已开始修复${started && started.count ? ` ${started.count} 个` : ""} Mod…`, "success");
  }

  fixRunning.value = true;
  fixText.value = "修复中…";
  stopFixPoll();
  fixTimer = setInterval(async () => {
    let p = null;
    try { p = await call("fix_all_progress"); } catch (e) { /* 忽略单次失败 */ }
    if (!p) return;
    const cur = Number(p.current || 0);
    const total = Number(p.total || 0);
    if (p.running) {
      fixText.value = total
        ? `修复中 ${cur}/${total}：${p.name || ""}`
        : `修复中：${p.name || ""}`;
      return;
    }
    // 跑完了
    stopFixPoll();
    fixRunning.value = false;
    fixText.value = "";
    const results = Array.isArray(p.results) ? p.results : [];
    const failed = results.filter((r) => r && r.ok === false);
    await scan();
    await refreshState();
    if (failed.length) {
      await showModalDialog({
        title: `修复完成（${results.length - failed.length} 成功 / ${failed.length} 失败）`,
        message: "这几项没修好：\n\n" +
          failed.slice(0, 12).map((r) => `• ${r.name || r.id || "?"}：${r.message || "未知原因"}`).join("\n") +
          (failed.length > 12 ? `\n…另有 ${failed.length - 12} 项` : ""),
        okText: "知道了",
      });
    } else {
      showToast(`修复完成，共 ${results.length} 个 Mod`, "success");
    }
  }, 800);
}



function speedText() {
  const bps = dl.value.speed_bps || 0;
  if (!dl.value.total_bytes) return dl.value.done_bytes ? `已下 ${humanSize(dl.value.done_bytes)}` : "等待服务器响应…";
  return `${humanSize(dl.value.done_bytes)} / ${humanSize(dl.value.total_bytes)} · `
    + `${Math.round((dl.value.done_bytes / dl.value.total_bytes) * 100)}% · ${humanSize(bps)}/s`;
}

// 封面**串行**加载：后端每张都要 PIL 打开+缩放+JPEG 编码（CPU 密集），
// 一次性并发十几张会把界面拖卡、用户感觉"图片加载很慢"（2026-10-03 反馈）。
// 这里一张一张来，并且让出一帧，界面先出来、封面随后补上。
let coverQueue = [];
let coverRunning = false;

async function pumpCovers() {
  if (coverRunning) return;
  coverRunning = true;
  try {
    while (coverQueue.length) {
      const id = coverQueue.shift();
      if (!store.covers[id]) await loadCover(id);
      await new Promise((r) => setTimeout(r, 0));   // 让出主线程，界面不被卡住
    }
  } finally {
    coverRunning = false;
  }
}

function queueCovers(mods) {
  const ids = (mods || []).map((m) => m.id).filter((id) => id && !store.covers[id]);
  if (!ids.length) return;
  coverQueue = ids;
  pumpCovers();
}

onMounted(async () => {
  await refreshState().catch(() => {});
  queueCovers(store.state.mods);
});
onUnmounted(() => { if (timer) clearInterval(timer); stopFixPoll(); coverQueue = []; });

// ⚠️ Vue 里**子组件的 onMounted 先于父组件执行**，而 demo 模式的封面是父组件（App.vue）
// 在自己的 onMounted 里才灌进 store 的 —— 那时封面还没到，一开始全是占位图。
// 这里监听它，数据到位后把封面补齐。
watch(() => store.demoCovers, (val) => {
  if (!val) return;
  queueCovers(store.state.mods);
}, { immediate: true });
</script>

<template>
  <div class="space-y-4">
    <!-- 两个开关放这里（紧邻 Mod 列表之上）：
         上一版把它们挪到了页面最底部（理由是"设一次就不动"），结果用户找不到、
         以为开关没了 —— 可见"总开关"这类东西必须待在它管的那块内容旁边。 -->
    <Card title="皮肤 Mod">
      <template #badge><Badge tone="muted">总开关</Badge></template>
      <div class="space-y-0.5">
        <div class="switch-row" @click="saveSetting('efmi_injection', !settings.efmi_injection)">
          <span class="min-w-0">
            <span class="text-sm font-medium">开启皮肤 Mod</span>
            <span class="block text-xs mt-0.5" style="color: var(--text-muted)">
              关掉后一个皮肤都不加载（Mods 目录会被清空，随时可开回来）。
              ⚠️ 这不是停掉 EFMI 注入 —— 实测那样终末地会直接拉不起来。
            </span>
          </span>
          <span class="flex items-center gap-2 shrink-0">
            <span class="switch-state">{{ settings.efmi_injection ? "已开启" : "已关闭" }}</span>
            <Switch :model-value="!!settings.efmi_injection" @update:model-value="(v) => saveSetting('efmi_injection', v)" />
          </span>
        </div>
        <div class="switch-row" @click="saveSetting('allow_same_character_mods', !settings.allow_same_character_mods)">
          <span class="min-w-0">
            <span class="text-sm font-medium">强行关闭角色 Mod 互斥</span>
            <span class="block text-xs mt-0.5" style="color: var(--text-muted)">
              开启后勾选一个 Mod 不会再把同角色的其它 Mod 自动取消。<b>默认关闭</b> ——
              同角色两个 Mod 同时生效常常会让游戏崩，只在确认它们改的不是同一批资源时再打开。
            </span>
          </span>
          <span class="flex items-center gap-2 shrink-0">
            <span class="switch-state">{{ settings.allow_same_character_mods ? "已开启" : "已关闭" }}</span>
            <Switch :model-value="!!settings.allow_same_character_mods" @update:model-value="(v) => saveSetting('allow_same_character_mods', v)" />
          </span>
        </div>
      </div>
    </Card>

    <Card title="Mod 列表">
      <div class="flex flex-wrap items-center gap-2">
        <Btn variant="primary" @click="prepare" :disabled="busy">生成控制器</Btn>
        <Btn @click="scan" :disabled="busy">重新扫描</Btn>
        <Btn @click="fixAll">一键修复所有 Mod</Btn>
        <span class="ml-auto flex items-center gap-2">
          <input v-model="keyword" class="field" style="width: 200px" placeholder="搜索 Mod / 角色…" />
        </span>
      </div>
      <div v-if="!groups.length" class="empty-state">
        <Library :size="30" class="empty-icon" />
        <!-- 两种情况必须说清楚：库里真的没有 vs 搜索没匹配上（文案混用会让人以为 Mod 丢了） -->
        <div class="empty-title">{{ keyword ? "没有匹配的 Mod" : "还没有发现 Mod" }}</div>
        <template v-if="keyword">
          <div>当前搜索「{{ keyword }}」没有结果。换个关键字，或者清空搜索框看全部。</div>
        </template>
        <template v-else>
          <div>把 .zip / .7z / .rar 拖到窗口任意处即可导入；也可以在上面粘贴网址下载。</div>
          <div>如果你已经把 Mod 放进 服装 Mod目录了，点「重新扫描」。</div>
        </template>
      </div>
      <div v-else class="mt-3 space-y-4">
        <div v-for="g in groups" :key="g.name" class="rounded-lg border p-3" style="border-color: var(--border)">
          <div class="flex items-center justify-between mb-3">
            <h3 class="font-semibold">{{ g.name }}</h3>
            <span class="text-xs" style="color: var(--text-muted)">{{ g.mods.length }} 个 Mod · 已启用 {{ g.enabled }}</span>
          </div>
          <!-- 紧凑横向列表（用真实库数据验证后改的）：
               原来是「通栏组框 + 内部固定 168px 大卡片」—— 每个角色往往只有 1 个 Mod，
               于是右侧 4/5 全空、卡片还很高，一屏只看得下 4 个。
               改成一行一个 Mod：缩略图 + 名字 + 状态 + ⋯，一屏能看十几个。 -->
          <!-- 组内网格 + 横向卡片（GPT-6 Astra 方案）：
               原来是 40x40 的紧凑行 —— 只能看出"有个人"，看不出长裙/短裙、制服/礼服、
               有没有披风长靴，等于图片白放。现在封面 120x140（服装要竖看全身，不裁正方形），
               名字与状态放右侧；无封面也占同样尺寸，避免组内视觉节奏被破坏。 -->
          <div class="grid gap-3" style="grid-template-columns: repeat(auto-fill, minmax(320px, 1fr))">
            <div v-for="m in g.mods" :key="m.id"
                 class="relative flex gap-3 rounded-lg border p-2.5 cursor-pointer transition-colors"
                 :style="{ borderColor: selected.has(String(m.id)) ? 'var(--accent)' : 'var(--border)',
                           background: selected.has(String(m.id)) ? 'var(--accent-soft)' : 'var(--surface)' }"
                 @click="toggleMod(m)">
              <span class="shrink-0 rounded-md overflow-hidden flex items-center justify-center"
                    style="width: 120px; height: 140px; background: var(--surface-2)">
                <img v-if="covers[m.id]" :src="covers[m.id]" class="w-full h-full object-cover" alt="" />
                <span v-else class="flex flex-col items-center gap-1 empty-icon">
                  <ImageOff :size="20" />
                  <span class="text-xs">无封面</span>
                </span>
              </span>
              <span class="min-w-0 flex-1 flex flex-col">
                <span class="text-sm leading-5" style="display: -webkit-box; -webkit-line-clamp: 2;
                      -webkit-box-orient: vertical; overflow: hidden" :title="m.name">{{ m.name }}</span>
                <span class="mt-1.5 text-xs"
                      :style="{ color: selected.has(String(m.id)) ? 'var(--accent)' : 'var(--text-muted)' }">
                  {{ selected.has(String(m.id)) ? "已启用" : "未启用" }}
                </span>
                <!-- ⚠️ 用户 2026-10-03：「现在没有之前那种**黄色的未识别的标记，可以点一下就切换的**」
                     —— 旧版在角色识别不确定（low/none）时会在卡片上打一个黄色标记，点它直接进选角色。
                     点击要 .stop，否则会先触发整卡的启用/停用。 -->
                <span v-if="!m.group || m.confidence === 'none' || m.confidence === 'low'"
                      class="badge mt-1 cursor-pointer" style="background: #f0b429; color: #3a2a00"
                      title="角色归属没认出来 —— 点这里选一个（识别错了会让同角色互斥失效，容易崩）"
                      @click.stop="menuAct('assign', m)">未识别 · 点此选角色</span>
                <!-- 类型待确认（例如把壁纸/加载页包当成了角色皮肤）也放这里，点一下改归属 -->
                <span v-else-if="m.kind === 'unknown'"
                      class="badge mt-1 cursor-pointer" style="background: #f0b429; color: #3a2a00"
                      title="看不出这是哪一类 Mod，点此指定角色归属（或设为未分类）"
                      @click.stop="menuAct('assign', m)">类型待确认</span>
              <!-- ⚠️ **C1：重复副本标记**（2026-10-03 补回归）。0.9.5 有
                   `⚠ 与「X」内容相同（重复副本）`；后端 `mod.duplicate_of` 一直在算，
                   而前端 grep 该字段 **0 命中** ⇒ 用户看不出哪些是重复的。 -->
              <span v-if="m.duplicate_of" class="ml-1" style="color: var(--warn)"
                    :title="`与「${m.duplicate_of}」内容相同（重复副本），留着会占空间`">⚠ 重复</span>
                <!-- 显式的启用开关（用户 2026-10-03 三次反馈"mod 开关还是没有"——
                     之前只有一行状态文字 + 点整卡切换，看不出那是个开关）。 -->
                <span class="mt-auto flex items-center justify-between gap-2">
                  <Switch :model-value="selected.has(String(m.id))"
                          @update:model-value="() => toggleMod(m)" />
                  <button class="btn btn-mini shrink-0" title="更多：更改所属角色 / 修复 / 回滚 / 移出库"
                          @click="openMenu(m, $event)">⋯</button>
                </span>
              </span>
            </div>
          </div>
        </div>
      </div>
    </Card>

    <CharacterAssignDialog ref="assignRef" />
    <ModDownloadCard />

    <ConflictDialog v-if="conflicts" :groups="conflicts"
                    @resolve="resolveConflicts" @cancel="conflicts = null" />

    <!-- ⋯ 就地小菜单（浮层，点空白处关闭） -->
    <div v-if="menu" class="fixed inset-0 z-40" @click="closeMenu"></div>
    <div v-if="menu" class="fixed z-50 card py-1 shadow-lg" style="min-width: 168px"
         :style="{ left: menu.x + 'px', top: menu.y + 'px' }">
      <button class="w-full text-left px-3 py-1.5 text-sm" @click="menuAct('character')">更改所属角色…</button>
      <button class="w-full text-left px-3 py-1.5 text-sm" @click="menuAct('fix')">修复 Mod 文件</button>
      <!-- ⚠️ **不要再引用 `m`**（2026-10-03 修「点了更多页面就变纯白」）：
           `m` 只存在于 `menuAct()` 函数体内，**模板作用域里没有它** ——
           渲染这个浮层时会抛 `ReferenceError`，整页直接白掉。
           （服装页白、辅助页正常，因为辅助页是我照着新写的那份、没带这个错。）
           要用就用 `menu` —— 它带着 `id / name / kind`。 -->
      <button v-if="menu.kind !== 'assist'" class="w-full text-left px-3 py-1.5 text-sm"
              @click="menuAct('toAssist')">移到「辅助 Mod」</button>
      <button v-else class="w-full text-left px-3 py-1.5 text-sm"
              @click="menuAct('toSkin')">移到「服装 Mod」</button>
      <!-- ⚠️ **C4：回滚要按 `can_rollback` 置灰**（2026-10-03 补回归）：
             0.9.5 里没备份过就是灰的（点了也没用），现在无论有没有备份都可点。 -->
      <button class="w-full text-left px-3 py-1.5 text-sm" :disabled="!menu.can_rollback"
              :style="menu.can_rollback ? '' : 'opacity:.45;cursor:not-allowed'"
              :title="menu.can_rollback ? '' : '这个 Mod 还没有修复备份，没什么可回滚的'"
              @click="menuAct('rollback')">回滚</button>
      <button class="w-full text-left px-3 py-1.5 text-sm" @click="menuAct('open')">打开所在目录</button>
      <div style="height:1px;background:var(--border)" class="my-1"></div>
      <button class="w-full text-left px-3 py-1.5 text-sm" style="color: var(--danger)"
              @click="menuAct('delete')">移出 服装 Mod</button>
    </div>
  </div>
</template>
