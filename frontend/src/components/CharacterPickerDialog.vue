<script setup>
// 「角色归属待确认」弹窗 —— 预识别失败/不确定时让用户选（用户 2026-10-03：
// 「自动预识别和识别mod对应人物都被吞了，另外预识别和无法识别不是应该有个按钮可以选择
//  任务的吗，那个也没了」）。
//
// 移植自 0.4.0 的 `showCharacterModal`（web/app.js）：列出每条待确认的 Mod、
// **说明为什么认不出**（名字里没有角色名 / 出现多个角色名分不清主体）、
// 下拉选角色（默认预选"最可能的"那个），可跳过。
//
// 为什么必须做：识别错会让「同角色互斥」失效 —— 两个同角色 Mod 同时生效会导致游戏崩溃。
import { ref, computed, watch } from "vue";
import { call } from "../lib/bridge.js";
import { store } from "../store.js";
import { showToast } from "../lib/dialog.js";
import Btn from "./ui/Btn.vue";

const pending = ref([]);
const known = ref([]);
const picked = ref({});     // { modId: 角色名 }
const busy = ref(false);

const open = computed(() => pending.value.length > 0);

function why(item) {
  if (item.confidence === "none") return "名字里没找到任何角色名";
  return "出现了多个角色名，分不清哪个才是主体";
}

// 候选 = 它自己猜出来的 + 已知角色表（去重）
function optionsFor(item) {
  const all = [...new Set([...(item.candidates || []), ...(known.value || [])])].filter(Boolean);
  return all;
}

function selectedFor(item) {
  if (picked.value[item.id] !== undefined) return picked.value[item.id];
  return (item.candidates || [])[0] || "";
}

async function load() {
  // demo 模式（只在 VITE_UI_DEMO=1 的构建里存在）：用快照里的假数据渲染，
  // 这样这条链路能在本地截图验证，不必每次都让用户实机试。
  if (import.meta.env.VITE_UI_DEMO === "1" && store.demoPending) {
    pending.value = store.demoPending.pending || [];
    known.value = store.demoPending.known || [];
    const init = {};
    for (const item of pending.value) init[item.id] = (item.candidates || [])[0] || "";
    picked.value = init;
    return;
  }
  try {
    const data = await call("pending_characters");
    const list = (data && data.pending) || [];
    known.value = (data && data.known) || [];
    if (list.length) {
      pending.value = list;
      // 每条默认预选"最可能的"
      const init = {};
      for (const item of list) init[item.id] = (item.candidates || [])[0] || "";
      picked.value = init;
    }
  } catch (e) { /* 没有待确认的很正常 */ }
}

async function save() {
  busy.value = true;
  let saved = 0;
  try {
    for (const item of pending.value) {
      const name = selectedFor(item);
      if (!name) continue;
      const r = await call("set_mod_character", String(item.id), name);
      if (r && r.ok !== false) saved += 1;
    }
  } catch (e) { /* call 已弹窗 */ }
  busy.value = false;
  pending.value = [];
  if (saved) showToast(`已确认 ${saved} 个 Mod 的角色归属`, "success");
  try { await call("scan"); } catch (e) { /* 忽略 */ }
}

function skip() { pending.value = []; }

// ⚠️ **不能直接在 setup 顶层 load()**：Vue 里子组件的 setup 早于父组件（App.vue）的
// `boot()`，那时前后端桥还没就绪、`store.demoPending` 也还没灌进来 —— 拿不到任何东西。
// 这是本窗口第三次踩同一个坑（前两次：UpdateBadge 的版本号、demo 快照注入），
// 统一改成等 `store.ready`。（`onMounted` 也一样不安全，它同样早于父组件。）
watch(() => store.ready, (ready) => { if (ready && !open.value) load(); }, { immediate: true });

// ⚠️ **B12：导入 Mod 之后要能立刻刷新这张表**（2026-10-03 补回归）。
// 这个弹窗原本**只在 `store.ready` 变化时加载一次** —— 而 `ready` 启动后就不再变，
// 所以用户拖进一个"认不出角色"的包之后，选择窗**不会自己出现**（0.9.5 会当场推给用户）。
// `App.vue` 在导入完成后调这里暴露的 `reload()` 补上这一步。
defineExpose({ reload: load });
// 用户回到窗口时再顺手看一眼（导入完 Mod 切回来就会检查）
window.addEventListener("focus", () => { if (!open.value) load(); });
</script>

<template>
  <div v-if="open" class="fixed inset-0 z-50 flex items-center justify-center" style="background: rgba(0,0,0,.45)">
    <div class="card w-[min(620px,94vw)] shadow-lg" style="background: var(--surface)">
      <div class="card-head">有 {{ pending.length }} 个 Mod 需要你确认角色</div>
      <div class="card-body" style="max-height: 60vh; overflow: auto">
        <p class="text-xs mb-3" style="color: var(--text-muted)">
          认不出角色不影响使用，但<b>同角色互斥</b>要靠它 —— 归属没填对时，同一个角色的两个 Mod
          可能一起生效，那样游戏容易崩。选不准就先跳过。
        </p>
        <div v-for="item in pending" :key="item.id" class="mb-3 p-2.5 rounded"
             style="background: var(--surface-2)">
          <div class="text-sm font-medium truncate">{{ item.name }}</div>
          <div class="text-xs mt-0.5 mb-1.5" style="color: var(--text-muted)">{{ why(item) }}</div>
          <select class="field" style="min-width: 240px"
                  :value="selectedFor(item)"
                  @change="(e) => (picked[item.id] = e.target.value)">
            <option value="">（请选择角色）</option>
            <option v-for="name in optionsFor(item)" :key="name" :value="name">{{ name }}</option>
          </select>
        </div>
      </div>
      <div class="px-4 py-3 flex justify-end gap-2 border-t" style="border-color: var(--border)">
        <Btn @click="skip">稍后再说</Btn>
        <Btn variant="primary" :disabled="busy" @click="save">保存选择</Btn>
      </div>
    </div>
  </div>
</template>
