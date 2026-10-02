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
import { showAlert, showConfirm, showModalDialog, showToast } from "../lib/dialog.js";

const urls = ref("");
const dl = ref({ items: [], counts: {}, done: true, total_bytes: 0, done_bytes: 0, speed_bps: 0 });
const dlStatus = ref("");
const covers = ref({});
const busy = ref(false);
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

async function scan() { busy.value = true; try { await call("scan"); await refreshState();
    loadSettings(); } catch (e) {} finally { busy.value = false; } }
async function prepare() { busy.value = true; try { await call("prepare"); } catch (e) {} finally { busy.value = false; } }
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
      <div class="divide-y" style="border-color: var(--border)">
        <div class="py-3 flex items-center justify-between gap-4">
          <div class="min-w-0">
            <div class="font-medium">开启皮肤 Mod</div>
            <div class="text-xs mt-0.5" style="color: var(--text-muted)">
              总开关：关闭后一个皮肤都不加载（Mods 目录会被清空，随时可开回来）。⚠️ 注意这不是停掉 EFMI 注入 —— 实测那样终末地会直接拉不起来。
            </div>
          </div>
          <Switch :model-value="!!settings.efmi_injection" @update:model-value="(v) => saveSetting('efmi_injection', v)" />
        </div>
        <div class="py-3 flex items-center justify-between gap-4">
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
        <div class="text-xs" style="color: var(--text-muted)">
          粘贴网址，<b>一行一个</b> → <b>并行下载</b>；能解压的（zip / 7z / rar）自动解压进 Mod 库并识别角色。
          直接支持<b>香蕉网（GameBanana）页面地址</b>：会自动换成真实文件直链，并带出封面、作者与版本。
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
        <Btn @click="scan" :disabled="busy">重新扫描</Btn>
        <Btn variant="primary" @click="prepare" :disabled="busy">生成控制器</Btn>
        <Btn @click="fixAll">一键修复所有 Mod（实验性）</Btn>
        <span class="text-xs" style="color: var(--text-muted)">同角色自动互斥，选择自动保存。把 .zip / .7z / .rar 拖到页面任意处即可导入。</span>
      </div>
      <div class="mt-3 space-y-4">
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
              <div class="font-medium truncate text-sm">{{ m.name }}</div>
              <div class="text-xs mt-0.5" style="color: var(--text-muted)">
                {{ selected.has(String(m.id)) ? "已勾选" : "未勾选" }}
              </div>
            </div>
          </div>
        </div>
      </div>
    </Card>
  </div>
</template>
