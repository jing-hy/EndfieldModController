<script setup>
import { ref, computed, onMounted } from "vue";
import {
  Library, Wrench, PackageCheck, Rocket, Settings, Info, Palette,
} from "lucide-vue-next";
import { store, refreshState, applyTheme, currentTheme, THEMES } from "./store.js";
import { waitForBridge, reportFrontendError } from "./lib/bridge.js";
import { loadSettings } from "./lib/settings.js";
import { dragHasFiles, importDroppedFile } from "./lib/importMod.js";
import { normalizeAnnouncements } from "./lib/announce.js";
import { showModalDialog, showToast } from "./lib/dialog.js";
import { call } from "./lib/bridge.js";
import DialogHost from "./components/DialogHost.vue";
import ToastHost from "./components/ToastHost.vue";
import AboutPage from "./pages/AboutPage.vue";
import SettingsPage from "./pages/SettingsPage.vue";
import AssistPage from "./pages/AssistPage.vue";
import DepsPage from "./pages/DepsPage.vue";
import LaunchPage from "./pages/LaunchPage.vue";
import ModLibraryPage from "./pages/ModLibraryPage.vue";

const pages = {
  library: ModLibraryPage, assist: AssistPage, dependencies: DepsPage, launch: LaunchPage, settings: SettingsPage,
  about: AboutPage,
};
const tabs = [
  { id: "library", name: "Mod 库", icon: Library },
  { id: "assist", name: "辅助 Mod", icon: Wrench },
  { id: "dependencies", name: "依赖", icon: PackageCheck },
  { id: "launch", name: "启动", icon: Rocket },
  { id: "settings", name: "设置", icon: Settings },
  { id: "about", name: "说明", icon: Info },
];
const theme = ref(currentTheme());
// 拖放导入：提示层**松开鼠标就消失**（用户要求「应该是释放就消失」），拖拽计数避免子元素抖动
const dragging = ref(false);
// 公告条（用户每次启动都会看到；点关闭就告诉后端"已读"）
const notices = ref([]);
let firstRunChecked = false;
let dragDepth = 0;
async function dismissNotices() {
  notices.value = [];
  try { await call("announcements_seen"); } catch (e) { /* 忽略 */ }
}

async function onDrop(event) {
  event.preventDefault();
  dragDepth = 0;
  dragging.value = false;
  const files = Array.from((event.dataTransfer && event.dataTransfer.files) || []);
  for (const file of files) {
    await importDroppedFile(file, {
      onDone: async () => { await refreshState(); loadSettings(); },
    });
  }
}
const themeOpen = ref(false);
const currentPage = computed(() => pages[store.tab]);
const currentName = computed(() => tabs.find((t) => t.id === store.tab)?.name || "");

function pickTheme(name) {
  theme.value = name;
  applyTheme(name);
  themeOpen.value = false;
}

onMounted(async () => {
  // 拖放导入（全局：任何页都能拖）
  window.addEventListener("dragenter", (e) => {
    if (!dragHasFiles(e)) return;
    e.preventDefault();
    dragDepth += 1;
    dragging.value = true;
  });
  window.addEventListener("dragover", (e) => {
    if (!dragHasFiles(e)) return;
    e.preventDefault();                       // 不 preventDefault 就不会派发 drop
    if (e.dataTransfer) e.dataTransfer.dropEffect = "copy";
  });
  window.addEventListener("dragleave", () => {
    dragDepth = Math.max(0, dragDepth - 1);
    if (dragDepth === 0) dragging.value = false;
  });
  window.addEventListener("drop", onDrop);
  window.addEventListener("error", (e) => reportFrontendError("window.error", e.message || ""));
  window.addEventListener("unhandledrejection", (e) =>
    reportFrontendError("unhandledrejection", String((e.reason && e.reason.message) || e.reason)));
  // 桥没就绪时等一会儿（旧版有 pywebviewready + DOMContentLoaded 两道兜底，这里等价处理）
  if (await waitForBridge()) {
    try {
      await refreshState();
      // ⚠️ 必须把 config 灌进 settings —— 否则所有设置项/开关都显示成空（2026-10-02 实测：
      // 注入开关全显示"关"，因为 settings 从没被填充过）。
      loadSettings();
      // 旧版会记住上次停留的页签（config.last_tab）；带 hash 深链时以 hash 为准
      if (!location.hash && store.state.config && store.state.config.last_tab) {
        store.tab = store.state.config.last_tab;
      }
      notices.value = normalizeAnnouncements(store.state.announcements);
      // 首次启动：**只提示一次**（判据用后端持久化的 onboarding_done，而不是"当前还没就绪"
      // 这类会一直为真的状态 —— 否则会连环弹）。
      const fr = store.state.first_run || {};
      if (!firstRunChecked && fr.first_run && !fr.onboarding_done) {
        firstRunChecked = true;
        const missing = (fr.missing_components || []).join("、");
        const go = await showModalDialog({
          title: "第一次使用：还没完成初始化",
          message: [
            missing ? `当前缺少：${missing}。` : "当前还没生成控制器。",
            "",
            "接下来可以做两件事（约 1 分钟）：",
            "· 在「依赖」页点「自动安装/更新」把组件装齐；",
            "· 在「Mod 库」页把 .zip / .7z / .rar 拖进来导入 Mod。",
            "",
            "⚠️ 第一次点「一键启动」如果终末地没起来，再点一次通常就好。",
          ].join("\n"),
          okText: "去依赖页", cancelText: "跳过",
        });
        if (go) store.tab = "dependencies";
        try { await call("save_config", { onboarding_done: true }); } catch (e) { /* 记不上也不影响本次 */ }
      }
    } catch (e) { /* call() 已经弹过窗 */ }
  }
});
</script>

<template>
  <div class="flex h-full">
    <aside class="w-52 shrink-0 flex flex-col border-r" style="background: var(--surface); border-color: var(--border)">
      <div class="h-12 px-4 flex items-center text-sm font-semibold border-b" style="border-color: var(--border)">
        终末地 Mod 管理器
      </div>
      <nav class="flex-1 p-2 space-y-0.5">
        <button v-for="t in tabs" :key="t.id" @click="store.tab = t.id"
          class="w-full flex items-center gap-2.5 px-3 py-2 rounded text-left transition-colors"
          :style="store.tab === t.id
            ? { background: 'var(--accent-soft)', color: 'var(--accent)', fontWeight: 500 }
            : { color: 'var(--text-muted)' }">
          <component :is="t.icon" :size="16" />
          <span class="text-sm">{{ t.name }}</span>
        </button>
      </nav>
      <div class="p-2 border-t relative" style="border-color: var(--border)">
        <button @click="themeOpen = !themeOpen"
          class="w-full flex items-center gap-2.5 px-3 py-2 rounded text-sm"
          style="color: var(--text-muted)">
          <Palette :size="16" />
          <span>主题：{{ theme }}</span>
        </button>
        <div v-if="themeOpen" class="absolute bottom-12 left-2 right-2 card p-1.5 shadow-lg z-20">
          <button v-for="t in THEMES" :key="t" @click="pickTheme(t)"
            class="w-full text-left px-2.5 py-1.5 rounded text-sm"
            :style="t === theme ? { background: 'var(--accent-soft)', color: 'var(--accent)' } : {}">
            {{ t }}
          </button>
        </div>
      </div>
    </aside>

    <main class="flex-1 min-w-0 overflow-auto">
      <!-- 公告条 -->
      <div v-if="notices.length" class="px-6 pt-4">
        <div class="card p-3" style="border-color: var(--accent)">
          <div class="flex items-start justify-between gap-3">
            <div class="min-w-0 space-y-1">
              <div v-for="n in notices" :key="n.key" class="text-sm">
                <b v-if="n.title">{{ n.title }}</b>
                <span v-if="n.body" class="ml-1">{{ n.body }}</span>
                <a v-if="n.link" class="text-accent ml-1" :href="n.link" target="_blank" rel="noopener">{{ n.link }}</a>
              </div>
            </div>
            <button class="btn btn-mini shrink-0" @click="dismissNotices">知道了</button>
          </div>
        </div>
      </div>
      <header class="h-12 px-6 flex items-center justify-between border-b sticky top-0 z-10"
              style="background: var(--surface); border-color: var(--border)">
        <h1 class="text-base font-semibold">{{ currentName }}</h1>
        <span class="text-xs" style="color: var(--text-muted)">v{{ store.state.version || "…" }}</span>
      </header>
      <div class="p-6 max-w-4xl">
        <component :is="currentPage" v-if="currentPage" />
        <div v-else class="card p-6 text-sm" style="color: var(--text-muted)">
          「{{ currentName }}」还在迁移中（新前端逐页搬，这一页暂时用旧界面）。
        </div>
      </div>
    </main>

    <!-- 拖放提示层：松手即消失，职责只是"告诉你松手就能导入" -->
    <div v-if="dragging" class="fixed inset-0 z-[70] flex items-center justify-center"
         style="background: rgba(0,0,0,.35)">
      <div class="card px-6 py-4 text-center shadow-lg">
        <div class="font-medium">松手即可导入 Mod</div>
        <div class="text-xs mt-1" style="color: var(--text-muted)">支持 .zip / .7z / .rar（进度显示在顶部提示条）</div>
      </div>
    </div>

    <DialogHost />
    <ToastHost />
  </div>
</template>




