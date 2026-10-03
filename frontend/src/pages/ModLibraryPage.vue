<script setup>
// Mod 库页（旧 #tab-library）：三个分区卡片 —— 皮肤 Mod / 下载 Mod / Mod 列表。
// 分组与过滤规则照抄旧 renderMods：按 conflict_group||group 分组，
// 跳过 _deps 分组与 kind=dependency/tool/assist（那些由依赖页 / 辅助页管）。
import { ref, computed, onMounted, onUnmounted, watch } from "vue";
import { call } from "../lib/bridge.js";
import { store, refreshState } from "../store.js";
import { loadSettings } from "../lib/settings.js";
import { settings, saveSetting } from "../lib/settings.js";
import { humanSize } from "../lib/util.js";
import Card from "../components/ui/Card.vue";
import { Library } from "lucide-vue-next";
import Btn from "../components/ui/Btn.vue";
import Switch from "../components/ui/Switch.vue";
import ConflictDialog from "../components/ConflictDialog.vue";
import { Check, ImageOff } from "lucide-vue-next";
import { showAlert, showModalDialog, showToast } from "../lib/dialog.js";
import { setStatus } from "../lib/status.js";

const urls = ref("");
const dl = ref({ items: [], counts: {}, done: true, total_bytes: 0, done_bytes: 0, speed_bps: 0 });
const dlStatus = ref("");
const covers = ref({});
const busy = ref(false);
// 「⋯ 更多」：就地弹出的小菜单（用户准则：⋯ 要就地弹小菜单，不要弹窗）
const menu = ref(null);          // { id, name, x, y }
const chars = ref([]);           // 已知角色（用于"更换归属"）
const keyword = ref("");          // 搜索（评审：Mod 一多，没搜索只能靠翻）
// 冲突处理：生成控制器之后检查一次，有冲突就弹「每组一个下拉框」的窗
const conflicts = ref(null);
let timer = null, dlTimer = null;

const selected = computed(() => new Set((store.state.selected || []).map(String)));
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
  if (preset) { covers.value[id] = preset; return; }
  try {
    const r = await call("get_mod_cover", id);
    // ⚠️ 后端的字段名是 **data_uri**（其余几个是历史写法，留着兜底）——
    // 迁移时我写成了 `r.data`，导致封面一直取不到、列表里全是"无封面"占位。
    const uri = r && (r.data_uri || r.data || r.uri || r.image || r.base64);
    if (r && r.ok && uri) covers.value[id] = uri;
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
    await call("save_config", { selected_mods: Array.from(ids) });
    await refreshState();
    loadSettings();
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
  menu.value = { id: String(mod.id), name: mod.name, x, y };
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
        title: "移出 Mod 库？",
        message: `${m.name}\n\n它会从 Mod 库列表里移出并留一份备份，之后不再加载。`
          + `\n不会删除你的其它 Mod，也不会动游戏本体。`,
        okText: "移出并备份", cancelText: "保留在库",
      });
      if (!ok) return;
      const r = await call("delete_mod", m.id);
      if (r && r.ok === false) await showAlert("移出失败", r.message || "未知原因");
      else showToast(r && r.moved_to ? `已移出库：${r.moved_to}` : "已移出 Mod 库", "success");
    } else if (act === "character") {
      if (!chars.value.length) {
        const r = await call("known_characters");
        chars.value = (r && (r.characters || r.items)) || [];
      }
      const pick = await showModalDialog({
        title: `「${m.name}」归到哪个角色？`,
        message: "输入角色名（留空 = 保持未分类）。已知角色：" + chars.value.slice(0, 40).join("、"),
        okText: "设定归属", cancelText: "取消",
      });
      if (pick === false) return;
      const r = await call("set_mod_character", m.id, pick === true ? "" : String(pick));
      if (r && r.ok === false) await showAlert("设定失败", r.message || "未知原因");
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
    await call("prepare");
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
async function fixAll() { try { await call("fix_all_mods"); } catch (e) {} }

async function startDownload() {
  const text = urls.value.trim();
  if (!text) { await showAlert("没有网址", "先粘贴至少一个 http(s) 网址。"); return; }
  try {
    const r = await call("start_mod_download", text);
    if (!r || r.ok === false) { await showAlert("没能开始下载", (r && r.message) || "未知原因"); return; }
    dlStatus.value = `已开始 ${r.total} 个下载任务（并行）`;
    pollDownload();
  } catch (e) { /* call 已弹窗 */ }
}

async function pollDownload() {
  try {
    const s = await call("mod_download_progress");
    if (!s) return;
    dl.value = s;
    if (!s.done && !dlTimer) dlTimer = setInterval(pollDownload, 1000);
    if (s.done && dlTimer) { clearInterval(dlTimer); dlTimer = null; await refreshState();
    loadSettings(); }
  } catch (e) { /* 忽略 */ }
}

function speedText() {
  const bps = dl.value.speed_bps || 0;
  if (!dl.value.total_bytes) return dl.value.done_bytes ? `已下 ${humanSize(dl.value.done_bytes)}` : "等待服务器响应…";
  return `${humanSize(dl.value.done_bytes)} / ${humanSize(dl.value.total_bytes)} · `
    + `${Math.round((dl.value.done_bytes / dl.value.total_bytes) * 100)}% · ${humanSize(bps)}/s`;
}

onMounted(async () => {
  await refreshState().catch(() => {});
  (store.state.mods || []).forEach((m) => loadCover(m.id));
});
onUnmounted(() => { if (timer) clearInterval(timer); if (dlTimer) clearInterval(dlTimer); });

// ⚠️ Vue 里**子组件的 onMounted 先于父组件执行**，而 demo 模式的封面是父组件（App.vue）
// 在自己的 onMounted 里才灌进 store 的 —— 那时封面还没到，一开始全是占位图。
// 这里监听它，数据到位后把封面补齐。
watch(() => store.demoCovers, (val) => {
  if (!val) return;
  (store.state.mods || []).forEach((m) => loadCover(m.id));
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
        <Btn variant="ghost" @click="fixAll">一键修复所有 Mod</Btn>
        <Badge tone="warn">实验性</Badge>
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
          <div>如果你已经把 Mod 放进 Mod 库目录了，点「重新扫描」。</div>
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
                <span class="mt-1.5 flex items-center gap-1.5 text-xs"
                      :style="{ color: selected.has(String(m.id)) ? 'var(--accent)' : 'var(--text-muted)' }">
                  <Check v-if="selected.has(String(m.id))" :size="12" :stroke-width="3" />
                  {{ selected.has(String(m.id)) ? "已启用" : "未启用" }}{{ m.kind === "unknown" ? " · 类型待确认" : "" }}
                </span>
                <span class="mt-auto flex items-center justify-end">
                  <button class="btn btn-mini shrink-0" title="更多：更改所属角色 / 修复 / 回滚 / 移出库"
                          @click="openMenu(m, $event)">⋯</button>
                </span>
              </span>
            </div>
          </div>
        </div>
      </div>
    </Card>

    <Card title="下载 Mod">
      <div class="flex items-start justify-between gap-4">
        <div class="text-xs" style="color: var(--text-muted)"
             title="粘贴网址一行一个 → 并行下载；zip / 7z / rar 会自动解压进 Mod 库并识别角色。直接支持香蕉网（GameBanana）页面地址：会自动换成真实文件直链，并带出封面、作者与版本；打不开时请检查 VPN。">
          粘贴网址，<b>一行一个</b>。支持香蕉网页面地址（自动取真实直链与封面）。
        </div>
        <Btn variant="primary" @click="startDownload">开始下载</Btn>
      </div>
      <textarea class="field mt-3" rows="2" v-model="urls"
                placeholder="https://gamebanana.com/mods/721442&#10;https://example.com/another-mod.7z"></textarea>
      <div class="flex items-center gap-2 mt-2">
        <Btn size="sm" @click="call('open_download_dir')">打开下载目录</Btn>
        <span class="text-xs" style="color: var(--text-muted)">{{ dlStatus }}</span>
      </div>
      <div v-if="dl.items && dl.items.length" class="mt-3 space-y-2">
        <div class="flex items-center justify-between text-xs">
          <span style="color: var(--text-muted)">
            共 {{ dl.counts.total || dl.items.length }} 个 · 已入库 {{ dl.counts.imported || 0 }}
            · 需手动解压 {{ dl.counts.manual || 0 }} · 失败 {{ dl.counts.failed || 0 }}
          </span>
          <span class="flex gap-2">
            <Btn size="mini" v-if="!dl.done" @click="call('pause_mod_downloads')">暂停</Btn>
            <Btn size="mini" v-if="!dl.done" @click="call('cancel_mod_downloads')">终止</Btn>
            <Btn size="mini" @click="call('clear_mod_downloads')">清除记录</Btn>
          </span>
        </div>
        <div class="text-xs" style="color: var(--text-muted)">{{ speedText() }}</div>
        <div class="h-1.5 rounded-full overflow-hidden" style="background: var(--surface-2); border: 1px solid var(--border)">
          <div class="h-full transition-all"
               :style="{ width: (dl.total_bytes ? (dl.done_bytes / dl.total_bytes) * 100 : 0) + '%', background: 'var(--accent)' }"></div>
        </div>
        <div v-for="(it, i) in dl.items" :key="i" class="rounded border p-2.5 text-sm" style="border-color: var(--border)">
          <div class="flex items-center justify-between gap-3">
            <b class="truncate">{{ it.title || it.name || it.url }}</b>
            <span class="text-xs shrink-0" style="color: var(--text-muted)">{{ it.status }} {{ it.percent || 0 }}%</span>
          </div>
          <div v-if="it.message" class="text-xs mt-1" style="color: var(--text-muted)">{{ it.message }}</div>
        </div>
      </div>
    </Card>

    <ConflictDialog v-if="conflicts" :groups="conflicts"
                    @resolve="resolveConflicts" @cancel="conflicts = null" />

    <!-- ⋯ 就地小菜单（浮层，点空白处关闭） -->
    <div v-if="menu" class="fixed inset-0 z-40" @click="closeMenu"></div>
    <div v-if="menu" class="fixed z-50 card py-1 shadow-lg" style="min-width: 168px"
         :style="{ left: menu.x + 'px', top: menu.y + 'px' }">
      <button class="w-full text-left px-3 py-1.5 text-sm" @click="menuAct('character')">更改所属角色…</button>
      <button class="w-full text-left px-3 py-1.5 text-sm" @click="menuAct('fix')">修复 Mod 文件（实验性）</button>
      <button class="w-full text-left px-3 py-1.5 text-sm" @click="menuAct('rollback')">回滚</button>
      <button class="w-full text-left px-3 py-1.5 text-sm" @click="menuAct('open')">打开所在目录</button>
      <div style="height:1px;background:var(--border)" class="my-1"></div>
      <button class="w-full text-left px-3 py-1.5 text-sm" style="color: var(--danger)"
              @click="menuAct('delete')">移出 Mod 库</button>
    </div>
  </div>
</template>
