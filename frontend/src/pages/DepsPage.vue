<script setup>
// 依赖页（旧 #tab-dependencies）：组件状态 + 下载进度 + 日志 + 已装清单。
// ⚠️ 日志框是**纯黑**的（.log-box 在 tokens.css 里，且 user-select: text 保证可复制）。
import { ref, computed, onMounted, onUnmounted } from "vue";
import { call } from "../lib/bridge.js";
import { store, refreshState } from "../store.js";
import Card from "../components/ui/Card.vue";
import Btn from "../components/ui/Btn.vue";
import Badge from "../components/ui/Badge.vue";

const items = ref([]);
const logLines = ref(["等待开始…（这里会显示下载线路尝试、断点续传、组件安装等详细过程）"]);
const status = ref("");
const percent = ref(0);
const progressText = ref("0/0");
let timer = null;

const deps = computed(() => store.state.dependencies || []);
const results = computed(() => store.state.dep_results || []);

function tone(state) {
  return state === "ok" ? "success" : state === "missing" ? "danger" : "muted";
}

async function refresh() {
  try {
    const data = await call("dependency_status");
    if (!data) return;
    items.value = data.items || data.components || [];
    if (data.log && data.log.length) logLines.value = data.log;
    if (data.message) status.value = data.message;
  } catch (e) { /* call 已弹窗 */ }
}

async function pollProgress() {
  try {
    const p = await call("get_dependency_progress");
    if (!p) return;
    if (typeof p.percent === "number") percent.value = p.percent;
    if (Array.isArray(p.log) && p.log.length) logLines.value = p.log;
    progressText.value = p.total ? `${p.current}/${p.total}` : (p.message || "");
  } catch (e) { /* 忽略轮询错误 */ }
}

async function start() {
  try { await call("start_full_update"); } catch (e) { return; }
  status.value = "已开始自动安装/更新…";
  await refresh();
}

onMounted(() => { refresh(); timer = setInterval(pollProgress, 1200); });
onUnmounted(() => { if (timer) clearInterval(timer); });
</script>

<template>
  <div class="space-y-4">
    <div class="flex flex-wrap gap-2">
      <Btn @click="refresh">刷新依赖状态</Btn>
      <Btn @click="call('ensure_initialized')">检查状态</Btn>
      <Btn variant="primary" @click="start">自动安装/更新</Btn>
    </div>

    <div v-if="status" class="text-xs" style="color: var(--text-muted)">{{ status }}</div>

    <div>
      <div class="h-1.5 rounded-full overflow-hidden" style="background: var(--surface-2); border: 1px solid var(--border)">
        <div class="h-full transition-all" :style="{ width: percent + '%', background: 'var(--accent)' }"></div>
      </div>
      <div class="text-xs mt-1.5" style="color: var(--text-muted)">{{ progressText }}</div>
    </div>

    <div class="log-box h-48">{{ logLines.join("\n") }}</div>

    <Card v-if="deps.length" title="组件状态">
      <div class="divide-y" style="border-color: var(--border)">
        <div v-for="d in deps" :key="d.key || d.name" class="py-2.5 flex items-center justify-between gap-4">
          <div class="min-w-0">
            <div class="font-medium truncate">{{ d.name }}</div>
            <div class="text-xs mt-0.5" style="color: var(--text-muted)">{{ d.version || "" }} {{ d.install_dir || "" }}</div>
          </div>
          <Badge :tone="tone(d.status)">{{ d.status || "未知" }}</Badge>
        </div>
      </div>
    </Card>

    <Card v-if="results.length" title="上次结果">
      <div v-for="(r, i) in results" :key="i" class="text-sm py-1">{{ r }}</div>
    </Card>
  </div>
</template>
