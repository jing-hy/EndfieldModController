<script setup>
// 辅助 Mod 页（旧 #tab-assist）：只列辅助/工具类 Mod，不参与换装。
import { computed, onMounted, watch } from "vue";
import { call } from "../lib/bridge.js";
import { store, refreshState } from "../store.js";
import { settings, loadSettings } from "../lib/settings.js";
import Card from "../components/ui/Card.vue";
import Switch from "../components/ui/Switch.vue";
import ModDownloadCard from "../components/ModDownloadCard.vue";
import { ImageOff } from "lucide-vue-next";
import { Wrench } from "lucide-vue-next";
import Btn from "../components/ui/Btn.vue";

// state 里没有独立的 assist 列表：辅助 Mod 就是 mods 里 kind === "assist" 的那些
const list = computed(() => (store.state.mods || []).filter((m) => m.kind === "assist"));
const status = "把 .zip / .7z / .rar 拖到页面任意处即可导入。";

// ⚠️ 选中状态的真源是 **`config.selected_mods`**（`get_state()` 顶层没有 `selected`），
// 与「Mod 库」页同一个来源。用户 2026-10-03 反馈「辅助 mod 还是没开关」——
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
    // 同「Mod 库」页：**不调 refreshState()**（全量重拉 get_state 会重新扫描整个库，
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
const GROUP_ORDER = ["加载页 / 壁纸", "界面 / 功能类", "工具 / 画质类", "其它辅助"];
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
// 与「Mod 库」页共用 store.covers 缓存，同一次会话只取一次。
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

async function rescan() { try { await call("scan"); } catch (e) { /* call 已弹窗 */ } }
async function openLib() { try { await call("open_path_in_explorer", "library"); } catch (e) {} }
</script>

<template>
  <div class="space-y-4">
    <div class="flex flex-wrap items-center gap-2">
      <Btn variant="primary" @click="rescan">重新扫描</Btn>
      <Btn @click="openLib">打开 Mod 库文件夹</Btn>
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
        （例如湿润效果修复、RabbitFX 这类别人依赖的东西）。它们不参与换装，所以不占「Mod 库」里的角色分组。
      </p>
      <!-- 按**子类**分组列出（用户 2026-10-03：「辅助 Mod 是标签，实际页面卡片中需要在卡片细分
           加载页和功能类之类的」）—— 壁纸包和"隐藏 UI"混在一起看不出区别。
           同一子类共用 group ⇒ 「同角色互斥」把「加载页 / 壁纸」变成"同时只能开一个"。 -->
      <div v-for="grp in assistGroups" :key="grp.name" class="mb-3 last:mb-0">
        <div class="flex items-center justify-between mb-1">
          <h4 class="text-xs font-semibold" style="color: var(--text-muted)">{{ grp.name }}</h4>
          <span class="text-xs" style="color: var(--text-muted)">{{ grp.mods.length }} 个</span>
        </div>
        <div class="divide-y" style="border-color: var(--border)">
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
            <!-- 组名常常就是它自己的名字（公共前置资源没有角色归属），一样就不要重复显示；
                 现在分组标题已经写了子类，明细行里就不再重复 -->
          </div>
          <span class="flex items-center gap-2 shrink-0">
            <span class="switch-state">{{ selected.has(String(m.id)) ? "已启用" : "未启用" }}</span>
            <Switch :model-value="selected.has(String(m.id))"
                    @update:model-value="() => toggleMod(m)" />
          </span>
        </div>
        </div>
      </div>
    </Card>
    <ModDownloadCard />
  </div>
</template>
