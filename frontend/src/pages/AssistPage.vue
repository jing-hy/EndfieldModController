<script setup>
// 辅助 Mod 页（旧 #tab-assist）：只列辅助/工具类 Mod，不参与换装。
import { computed, onMounted, ref, watch } from "vue";
import { call } from "../lib/bridge.js";
import { store, refreshState } from "../store.js";
import { settings, loadSettings } from "../lib/settings.js";
import Card from "../components/ui/Card.vue";
import Switch from "../components/ui/Switch.vue";
import ModDownloadCard from "../components/ModDownloadCard.vue";
import CharacterAssignDialog from "../components/CharacterAssignDialog.vue";
import { showToast, showAlert, showModalDialog } from "../lib/dialog.js";
import { ImageOff } from "lucide-vue-next";
import { Wrench } from "lucide-vue-next";
import Btn from "../components/ui/Btn.vue";

// state 里没有独立的 assist 列表：辅助 Mod 就是 mods 里 kind === "assist" 的那些
const list = computed(() => (store.state.mods || []).filter((m) => m.kind === "assist"));
const status = "把 .zip / .7z / .rar 拖到页面任意处即可导入。";

// ⚠️ 选中状态的真源是 **`config.selected_mods`**（`get_state()` 顶层没有 `selected`），
// 与「服装 Mod」页同一个来源。用户 2026-10-03 反馈「辅助 mod 还是没开关」——
// 辅助 Mod（公共前置资源）同样需要能启用/停用，之前这里只有一行名字。
const selected = computed(
  () => new Set((((store.state.config || {}).selected_mods) || []).map(String)),
);

async function toggleMod(mod) {
  const ids = new Set(selected.value);
  const id = String(mod.id);
  if (ids.has(id)) ids.delete(id);
  else ids.add(id);
  // 辅助 Mod 不绑角色，所以**不做同角色互斥**（那是角色 Mod 的规则）
  try {
    // 同「服装 Mod」页：**不调 refreshState()**（全量重拉 get_state 会重新扫描整个库，
    // 点一下要等很久）；直接写回派生来源，界面立刻响应。
    const result = await call("save_config", { selected_mods: Array.from(ids) });
    const applied = (result && result.config && result.config.selected_mods) || Array.from(ids);
    if (store.state) {
      if (!store.state.config || typeof store.state.config !== "object") store.state.config = {};
      store.state.config.selected_mods = applied;
    }
  } catch (e) { /* call 已弹窗 */ }
}

const covers = computed(() => store.covers);

// 页内按**子类**分组（用户 2026-10-03：「辅助 Mod 是标签，实际页面卡片中需要在卡片细分
// 加载页和功能类之类的」）—— 「辅助 Mod」只是标签页，同一页里还要按子类分开列，
// 否则壁纸包和"隐藏 UI"混在一起看不出区别。顺序固定：加载页/壁纸 → 界面功能 → 工具 → 其它。
const WRAPPER_GROUP = "加载页与壁纸";   // 与后端 core.WALLPAPER_GROUP 对齐
const GROUP_ORDER = ["加载页与壁纸", "界面功能类", "工具画质类", "其它辅助"];
function groupsOf(list) {
  const picked = Array.isArray(list) ? list : [];
  const buckets = new Map();
  for (const m of picked) {
    const key = String(m.group || "其它辅助");
    if (!buckets.has(key)) buckets.set(key, []);
    buckets.get(key).push(m);
  }
  const known = GROUP_ORDER.filter((g) => buckets.has(g));
  const rest = [...buckets.keys()].filter((g) => !GROUP_ORDER.includes(g)).sort();
  return [...known, ...rest].map((name) => ({ name, mods: buckets.get(name) }));
}
const assistGroups = computed(() => groupsOf(list.value));

// 辅助 Mod 也要有预览图（用户 2026-10-03：「辅助性mod也要留预览」）——
// 与「服装 Mod」页共用 store.covers 缓存，同一次会话只取一次。
async function loadCover(id) {
  if (!id || covers.value[id]) return;
  const preset = (store.demoCovers || {})[id];
  if (preset) { store.covers[id] = preset; return; }
  try {
    const r = await call("get_mod_cover", id);
    const uri = r && (r.data_uri || r.data || r.uri || r.image || r.base64);
    if (r && r.ok && uri) store.covers[id] = uri;
  } catch (e) { /* 没有封面很正常 */ }
}
function queueCovers(list) {
  (list || []).forEach((m) => loadCover(m.id));
}
onMounted(() => { queueCovers(list.value); });
watch(() => [list.value.length, store.demoCovers], () => { queueCovers(list.value); });

// 「⋯ 更多」：就地弹出的小菜单（用户准则：⋯ 要就地弹小菜单，不要弹窗）
// ⚠️ 用户 2026-10-03：「还有辅助类 mod 没有更多按钮」—— 服装页早就有，辅助页一直没做，
// 于是"更改归属 / 移到皮肤 / 修复 / 回滚 / 移出库"这些在辅助页全都够不着。
const menu = ref(null);          // { id, name, x, y }
const assignRef = ref(null);     // 归属下拉（复用服装页那个两下拉的组件）

function openMenu(mod, event) {
  event.stopPropagation();
  const box = event.currentTarget.getBoundingClientRect();
  const width = 176;
  const x = Math.max(8, Math.min(box.right - width, (window.innerWidth || 1200) - width - 8));
  const y = Math.max(8, Math.min(box.bottom + 4, (window.innerHeight || 800) - 200));
  menu.value = { id: String(mod.id), name: mod.name, x, y };
}
function closeMenu() { menu.value = null; }

async function menuAct(act) {
  const m = menu.value;
  if (!m) return;
  closeMenu();
  try {
    if (act === "character") {
      const mod = (store.state.mods || []).find((x) => String(x.id) === m.id);
      if (mod && assignRef.value) { assignRef.value.openFor(mod); return; }
    } else if (act === "toSkin") {
      const r = await call("set_mod_kind", m.id, "character");
      if (r && r.ok === false) await showAlert("移动失败", r.message || "未知原因");
      else showToast(`「${m.name}」已移到服装 Mod`, "success");
    } else if (act === "fix") {
      const r = await call("fix_mod", m.id);
      if (r && r.ok === false) await showAlert("修复失败", r.message || "未知原因");
      else showToast(`已修复 ${m.name}`, "success");
    } else if (act === "rollback") {
      const r = await call("rollback_mod", m.id);
      if (r && r.ok === false) await showAlert("回滚失败", r.message || "未知原因");
      else showToast(`已回滚 ${m.name}`, "success");
    } else if (act === "open") {
      const mod = (store.state.mods || []).find((x) => String(x.id) === m.id);
      if (mod && mod.path) await call("open_path_in_explorer", mod.path);
    } else if (act === "delete") {
      const ok = await showModalDialog({
        title: "移出 辅助 Mod？",
        message: `${m.name}\n\n它会从辅助 Mod 列表里移出并留一份备份，之后不再加载。`
          + `\n不会删除你的其它 Mod，也不会动游戏本体。`,
        okText: "移出并备份", cancelText: "保留在库",
      });
      if (!ok) return;
      const r = await call("delete_mod", m.id);
      if (r && r.ok === false) await showAlert("移出失败", r.message || "未知原因");
      else showToast(r && r.moved_to ? `已移出库：${r.moved_to}` : "已移出 辅助 Mod", "success");
    }
    await call("scan");
    await refreshState();
  } catch (e) { /* call 已弹窗 */ }
}

async function rescan() { try { await call("scan"); } catch (e) { /* call 已弹窗 */ } }
async function openLib() { try { await call("open_path_in_explorer", "library"); } catch (e) {} }
</script>

<template>
  <div class="space-y-4">
    <div class="flex flex-wrap items-center gap-2">
      <Btn variant="primary" @click="rescan">重新扫描</Btn>
      <Btn @click="openLib">打开 Mod 文件夹</Btn>
      <span class="text-xs" style="color: var(--text-muted)">{{ status }}</span>
    </div>
    <Card v-if="!list.length" title="辅助 Mod">
      <div class="empty-state">
        <component :is="Wrench" :size="30" class="empty-icon" />
        <div class="empty-title">这里还没有辅助 Mod</div>
        <div>辅助 Mod 是"不绑角色"的工具类 Mod（例如公共前置资源）。</div>
        <div>把 .zip / .7z / .rar 拖到窗口任意处即可导入，导入后会自动归类到这里。</div>
      </div>
    </Card>
    <!-- 标题不再写成「辅助 Mod（1）」—— 括号里那个数字没人知道是什么。
         数量挪到标题右侧的副标题位，并在卡片里说清"辅助 Mod"到底指什么。 -->
    <Card v-else title="辅助 Mod" :sub="`${list.length} 个`">
      <p class="text-xs mb-2" style="color: var(--text-muted)">
        这里放的是<b>不绑角色</b>的 Mod —— 加载页/壁纸、隐藏 UI、去水印、公共前置资源
        （例如湿润效果修复、RabbitFX 这类别人依赖的东西）。它们不参与换装，所以不占「服装 Mod」里的角色分组。
      </p>
      <!-- 按**子类**分组列出（用户 2026-10-03：「辅助 Mod 是标签，实际页面卡片中需要在卡片细分
           加载页和功能类之类的」）。
           **两类用两套卡片形态**（用户明确要求）：壁纸类看着像"一件作品"，用**服装 Mod 那种大封面
           卡片**（120×140，能看出是哪张图）；功能性 Mod（隐藏 UI、去水印这类）没有观赏性，
           保持**紧凑列表行**更好扫。 -->
      <div v-for="grp in assistGroups" :key="grp.name"
           class="rounded-lg border p-3 mb-3 last:mb-0" style="border-color: var(--border)">
        <div class="flex items-center justify-between mb-3">
          <h3 class="font-semibold">{{ grp.name }}</h3>
          <span class="text-xs" style="color: var(--text-muted)">
            {{ grp.mods.length }} 个 Mod · 已启用 {{ grp.mods.filter((m) => selected.has(String(m.id))).length }}
          </span>
        </div>

        <!-- ① 壁纸类：大封面卡片（对齐服装 Mod 的卡片） -->
        <div v-if="grp.name === WRAPPER_GROUP"
             class="grid gap-3" style="grid-template-columns: repeat(auto-fill, minmax(320px, 1fr))">
          <div v-for="m in grp.mods" :key="m.id"
               class="relative flex gap-3 rounded-lg border p-2.5 cursor-pointer transition-colors"
               :style="{ borderColor: selected.has(String(m.id)) ? 'var(--accent)' : 'var(--border)',
                         background: selected.has(String(m.id)) ? 'var(--accent-soft)' : 'var(--surface)' }"
               @click="toggleMod(m)">
            <span class="shrink-0 rounded-md overflow-hidden flex items-center justify-center"
                  style="width: 120px; height: 140px; background: var(--surface-2)">
              <img v-if="covers[m.id]" :src="covers[m.id]" class="w-full h-full object-cover" alt="" />
              <span v-else class="flex flex-col items-center gap-1 empty-icon">
                <ImageOff :size="18" />
              </span>
            </span>
            <span class="min-w-0 flex-1 flex flex-col">
              <span class="text-sm leading-5" style="display: -webkit-box; -webkit-line-clamp: 2;
                    -webkit-box-orient: vertical; overflow: hidden" :title="m.name">{{ m.name }}</span>
              <span class="mt-1.5 text-xs"
                    :style="{ color: selected.has(String(m.id)) ? 'var(--accent)' : 'var(--text-muted)' }">
                {{ selected.has(String(m.id)) ? "已启用" : "未启用" }}
              </span>
              <span class="mt-auto flex items-center justify-between gap-2">
                <Switch :model-value="selected.has(String(m.id))"
                        @update:model-value="() => toggleMod(m)" />
                <button class="btn btn-mini shrink-0" title="更多：分类 / 移到服装 Mod / 修复 / 回滚 / 移出库"
                        @click="openMenu(m, $event)">⋯</button>
              </span>
            </span>
          </div>
        </div>

        <!-- ② 功能性 / 其它：保持紧凑列表行 -->
        <div v-else class="divide-y" style="border-color: var(--border)">
          <div v-for="m in grp.mods" :key="m.id"
               class="py-2.5 flex items-center justify-between gap-4 cursor-pointer"
               @click="toggleMod(m)">
            <span class="shrink-0 rounded overflow-hidden flex items-center justify-center"
                  style="width: 44px; height: 44px; background: var(--surface-2)">
              <img v-if="covers[m.id]" :src="covers[m.id]" class="w-full h-full object-cover" alt="" />
              <ImageOff v-else :size="16" class="empty-icon" />
            </span>
            <div class="min-w-0 flex-1">
              <div class="font-medium truncate">{{ m.name }}</div>
            </div>
            <span class="flex items-center gap-2 shrink-0">
              <span class="switch-state">{{ selected.has(String(m.id)) ? "已启用" : "未启用" }}</span>
              <Switch :model-value="selected.has(String(m.id))"
                      @update:model-value="() => toggleMod(m)" />
              <button class="btn btn-mini shrink-0" title="更多：分类 / 移到服装 Mod / 修复 / 回滚 / 移出库"
                      @click="openMenu(m, $event)">⋯</button>
            </span>
          </div>
        </div>
      </div>
    </Card>
    <ModDownloadCard />

    <!-- ⋯ 就地小菜单（浮层，点空白处关闭） -->
    <div v-if="menu" class="fixed inset-0 z-40" @click="closeMenu"></div>
    <div v-if="menu" class="fixed z-50 card py-1 shadow-lg" style="min-width: 172px"
         :style="{ left: menu.x + 'px', top: menu.y + 'px' }">
      <button class="w-full text-left px-3 py-1.5 text-sm" @click="menuAct('character')">更改分类…</button>
      <button class="w-full text-left px-3 py-1.5 text-sm" @click="menuAct('toSkin')">移到「服装 Mod」</button>
      <button class="w-full text-left px-3 py-1.5 text-sm" @click="menuAct('fix')">修复 Mod 文件</button>
      <button class="w-full text-left px-3 py-1.5 text-sm" @click="menuAct('rollback')">回滚</button>
      <button class="w-full text-left px-3 py-1.5 text-sm" @click="menuAct('open')">打开所在目录</button>
      <div style="height:1px;background:var(--border)" class="my-1"></div>
      <button class="w-full text-left px-3 py-1.5 text-sm" style="color: var(--danger)"
              @click="menuAct('delete')">移出 辅助 Mod</button>
    </div>

    <CharacterAssignDialog ref="assignRef" />
  </div>
</template>
