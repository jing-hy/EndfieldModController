<script setup>
// 依赖页（旧 #tab-dependencies）：组件状态 + 下载进度 + 日志 + 已装清单。
// ⚠️ 日志框是**纯黑**的（.log-box 在 tokens.css 里，且 user-select: text 保证可复制）。
import { ref, computed, onMounted, onUnmounted } from "vue";
import { call } from "../lib/bridge.js";
import { store, refreshState } from "../store.js";
import { loadSettings } from "../lib/settings.js";
import Card from "../components/ui/Card.vue";
import Btn from "../components/ui/Btn.vue";
import Badge from "../components/ui/Badge.vue";

const items = ref([]);
const running = ref(false);
const checked = ref(false);   // 是否至少查过一次（区分"未检查"和"已就绪"）
const logLines = ref(["等待开始…（这里会显示下载线路尝试、断点续传、组件安装等详细过程）"]);
const status = ref("");
const percent = ref(0);
const progressText = ref("");   // 空 = 尚未开始，由 {{ ... || "尚未开始" }} 兜底
let timer = null;

// 真实结构：get_state().dependency_report = { required:[], manifest:{key:{display,status,version,install_dir,present,needed}}, unknown:[] }
const deps = computed(() => {
  const m = (store.state.dependency_report || {}).manifest || {};
  return Object.entries(m).map(([key, v]) => ({ key, ...v }));
});
const required = computed(() => (store.state.dependency_report || {}).required || []);
const okCount = computed(() => deps.value.filter((d) => d.status === "已安装").length);
const missingCount = computed(() => deps.value.filter((d) => d.status === "缺失").length);
const progressLabel = computed(() => {
  // 评审指出：摘要写「已就绪」、进度写「尚未开始」，两个状态互相打架 ——
  // 这里统一成**一次流程**的状态，并且明确"还没检查过"这一档。
  if (running.value) return "进行中";
  if (!checked.value) return "未检查";
  if (missingCount.value) return "待补齐";
  return "全部就位";
});

function tone(state) {
  return state === "ok" ? "success" : state === "missing" ? "danger" : "muted";
}

async function refresh() {
  try {
    await refreshState();
    checked.value = true;
    loadSettings();
    const total = deps.value.length;
    const ok = deps.value.filter((d) => d.status === "已安装").length;
    status.value = total ? `${ok}/${total} 个组件已就位` : "";
  } catch (e) { /* call 已弹窗 */ }
}

async function pollProgress() {
  try {
    const p = await call("get_dependency_progress");
    if (!p) return;
    running.value = !!p.running;
    if (typeof p.percent === "number") percent.value = p.percent;
    if (Array.isArray(p.log) && p.log.length) logLines.value = p.log;
    progressText.value = p.total ? `${p.current}/${p.total}` : (p.message || "");
  } catch (e) { /* 忽略轮询错误 */ }
}

async function start() {
  running.value = true;
  try { await call("start_full_update"); } catch (e) { running.value = false; return; }
  status.value = "已开始自动安装/更新…";
  await refresh();
}

onMounted(() => { refresh(); timer = setInterval(pollProgress, 1200); });
onUnmounted(() => { if (timer) clearInterval(timer); });
</script>

<template>
  <div class="space-y-4">
    <div class="flex flex-wrap gap-2">
      <Btn @click="refresh">重新扫描</Btn>
      <Btn @click="call('ensure_initialized')">检查并补齐</Btn>
      <Btn variant="primary" @click="start">安装缺失依赖</Btn>
    </div>

    <!-- 两列（GPT-6 Astra 评审：摘要/进度/日志全占首屏，真正要看的组件列表起点太低）：
         左 = 摘要 + 进度 + 组件列表（要看的）；右 = 安装日志（要盯的，滚动时吸顶）。 -->
    <div class="two-col grid gap-4">
      <div class="space-y-4 min-w-0">

    <!-- 状态摘要：把"现在到底什么情况"用三个数字说清楚（评审：原来只有 0/0 和一行日志） -->
    <div class="grid gap-3" style="grid-template-columns: repeat(auto-fit, minmax(150px, 1fr))">
      <div class="card"><div class="card-body">
        <div class="text-xl font-semibold">{{ okCount }}</div>
        <div class="text-xs mt-0.5" style="color: var(--text-muted)">已就位组件</div>
      </div></div>
      <div class="card"><div class="card-body">
        <div class="text-xl font-semibold">{{ missingCount }}</div>
        <div class="text-xs mt-0.5" style="color: var(--text-muted)">缺失组件</div>
      </div></div>
      <div class="card"><div class="card-body">
        <div class="text-xl font-semibold">{{ progressLabel }}</div>
        <div class="text-xs mt-0.5" style="color: var(--text-muted)">当前状态</div>
      </div></div>
    </div>

    <div>
      <div class="h-1.5 rounded-full overflow-hidden" style="background: var(--surface-2); border: 1px solid var(--border)">
        <div class="h-full transition-all" :style="{ width: percent + '%', background: 'var(--accent)' }"></div>
      </div>
      <div class="text-xs mt-1.5" style="color: var(--text-muted)">{{ progressText || "尚未开始" }}</div>
    </div>

    <Card v-if="deps.length" title="组件状态">
      <div class="divide-y" style="border-color: var(--border)">
        <div v-for="d in deps" :key="d.key" class="py-2.5 flex items-center justify-between gap-4">
          <div class="min-w-0">
            <div class="font-medium truncate">{{ d.display || d.key }}</div>
            <div class="text-xs mt-0.5" style="color: var(--text-muted)">{{ d.version || "" }}</div>
          </div>
          <Badge :tone="tone(d.status)">{{ d.status || "未知" }}</Badge>
        </div>
      </div>
    </Card>

    <Card v-if="required.length" title="被引用的依赖名">
      <div class="flex flex-wrap gap-1.5">
        <Badge v-for="r in required" :key="r" tone="muted">{{ r }}</Badge>
      </div>
    </Card>
      </div>

      <!-- 右栏：安装日志（滚动时吸顶） -->
      <div class="min-w-0" style="align-self: start; position: sticky; top: 12px">
        <div class="log-card">
          <div class="log-card-head">
            <span>安装日志</span>
            <span class="text-xs" style="color: var(--text-muted); font-weight: 400">
              {{ logLines.length > 1 ? logLines.length + " 行" : "尚无日志" }}
            </span>
          </div>
          <div v-if="logLines.length" class="log-box" style="max-height: 420px; border-radius: 0">{{ logLines.join("\n") }}</div>
          <div v-else class="log-empty" style="min-height: 52px; text-align: center">
            尚未开始。点「安装缺失依赖」后，这里会显示下载线路与安装过程。
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
