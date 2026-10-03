<script setup>
// Mod 库页（旧 #tab-library）：三个分区卡片 —— 皮肤 Mod / 下载 Mod / Mod 列表。
// 分组与过滤规则照抄旧 renderMods：按 conflict_group||group 分组，
// 跳过 _deps 分组与 kind=dependency/tool/assist（那些由依赖页 / 辅助页管）。
import { ref, computed, onMounted, onUnmounted } from "vue";
import { call } from "../lib/bridge.js";
import { store, refreshState } from "../store.js";
import { loadSettings } from "../lib/settings.js";
import { settings, saveSetting } from "../lib/settings.js";
import { humanSize } from "../lib/util.js";
import Card from "../components/ui/Card.vue";
import Btn from "../components/ui/Btn.vue";
import Switch from "../components/ui/Switch.vue";
import ConflictDialog from "../components/ConflictDialog.vue";
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
// 冲突处理：生成控制器之后检查一次，有冲突就弹「每组一个下拉框」的窗
const conflicts = ref(null);
let timer = null, dlTimer = null;

const selected = computed(() => new Set((store.state.selected || []).map(String)));
const groups = computed(() => {
  const g = {};
  for (const mod of store.state.mods || []) {
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
  try {
    const r = await call("get_mod_cover", id);
    const uri = r && (r.data || r.uri || r.image || r.base64);
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
  const y = Math.min(box.bottom + 4, (window.innerHeight || 800) - 190);
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
      else setStatus(`已修复 ${m.name}`);
    } else if (act === "rollback") {
      const r = await call("rollback_mod", m.id);
      if (r && r.ok === false) await showAlert("回滚失败", r.message || "未知原因");
      else setStatus(`已回滚 ${m.name}`);
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
      else setStatus(r && r.moved_to ? `已移出库：${r.moved_to}` : "已移出 Mod 库");
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
    else setStatus("生成完毕，没有发现资源冲突。");
  } catch (e) { /* call 已弹窗 */ } finally { busy.value = false; }
}

async function resolveConflicts(keep) {
  conflicts.value = null;
  try {
    const r = await call("resolve_mod_conflicts", keep);
    if (r && r.ok === false) await showAlert("处理失败", r.message || "未知原因");
    else setStatus((r && r.message) || "已处理冲突");
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

onMounted(async () => { await refreshState().catch(() => {}); (store.state.mods || []).forEach((m) => loadCover(m.id)); });
onUnmounted(() => { if (timer) clearInterval(timer); if (dlTimer) clearInterval(dlTimer); });
</script>

<template>
  <div class="space-y-4">
    <Card title="皮肤 Mod">
      <template #badge><Badge tone="muted">总开关</Badge></template>
      <div class="divide-y" style="border-color: var(--border)">
        <div class="switch-row" @click="saveSetting('efmi_injection', !settings.efmi_injection)">
          <div class="min-w-0">
            <div class="font-medium">开启皮肤 Mod</div>
            <div class="text-xs mt-0.5" style="color: var(--text-muted)">
              总开关：关闭后一个皮肤都不加载（Mods 目录会被清空，随时可开回来）。⚠️ 注意这不是停掉 EFMI 注入 —— 实测那样终末地会直接拉不起来。
            </div>
          </div>
          <Switch :model-value="!!settings.efmi_injection" @update:model-value="(v) => saveSetting('efmi_injection', v)" />
        </div>
        <div class="switch-row" @click="saveSetting('allow_same_character_mods', !settings.allow_same_character_mods)">
          <div class="min-w-0">
            <div class="font-medium">强行关闭角色 Mod 互斥</div>
            <div class="text-xs mt-0.5" style="color: var(--text-muted)">
              开启后勾选一个 Mod 不会再把同角色的其它 Mod 自动取消。<b>默认关闭</b> —— 同角色两个 Mod 同时生效常常会让游戏崩。
            </div>
          </div>
          <Switch :model-value="!!settings.allow_same_character_mods" @update:model-value="(v) => saveSetting('allow_same_character_mods', v)" />
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

    <Card title="Mod 列表">
      <div class="flex flex-wrap items-center gap-2">
        <Btn variant="primary" @click="prepare" :disabled="busy">生成控制器</Btn>
        <Btn @click="scan" :disabled="busy">重新扫描</Btn>
        <Btn variant="ghost" @click="fixAll">一键修复所有 Mod</Btn>
        <Badge tone="warn">实验性</Badge>
        <span class="text-xs" style="color: var(--text-muted)">同角色自动互斥，勾选自动保存。</span>
      </div>
      <div v-if="!groups.length" class="empty-state">
        <div class="empty-title">还没有发现 Mod</div>
        <div>把 .zip / .7z / .rar 拖到窗口任意处即可导入；也可以在上面粘贴网址下载。</div>
        <div>如果你已经把 Mod 放进 Mod 库目录了，点「重新扫描」。</div>
      </div>
      <div v-else class="mt-3 space-y-4">
        <div v-for="g in groups" :key="g.name" class="rounded-lg border p-3" style="border-color: var(--border)">
          <div class="flex items-center justify-between mb-3">
            <h3 class="font-semibold">{{ g.name }}</h3>
            <span class="text-xs" style="color: var(--text-muted)">{{ g.mods.length }} 个 Mod · 已启用 {{ g.enabled }}</span>
          </div>
          <div class="grid gap-3" style="grid-template-columns: repeat(auto-fill, minmax(200px, 1fr))">
            <div v-for="m in g.mods" :key="m.id"
                 class="rounded-lg border p-2.5 cursor-pointer transition-colors"
                 :style="{ borderColor: selected.has(String(m.id)) ? 'var(--accent)' : 'var(--border)',
                           background: selected.has(String(m.id)) ? 'var(--accent-soft)' : 'var(--surface)' }"
                 @click="toggleMod(m)">
              <div class="h-24 rounded mb-2 overflow-hidden flex items-center justify-center"
                   style="background: var(--surface-2)">
                <img v-if="covers[m.id]" :src="covers[m.id]" class="w-full h-full object-cover" alt="" />
                <span v-else class="text-xs" style="color: var(--text-muted)">无预览图</span>
              </div>
              <div class="flex items-start justify-between gap-2">
                <div class="min-w-0">
                  <div class="font-medium truncate text-sm">{{ m.name }}</div>
                  <div class="text-xs mt-0.5" style="color: var(--text-muted)">
                    {{ selected.has(String(m.id)) ? "已勾选" : "未勾选" }}
                  </div>
                </div>
                <button class="btn btn-mini shrink-0" title="更多：更换归属 / 修复 / 回滚 / 移出库"
                        @click="openMenu(m, $event)">⋯</button>
              </div>
            </div>
          </div>
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
