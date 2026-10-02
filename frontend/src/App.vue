<script setup>
import { ref, computed, onMounted } from "vue";
import {
  Library, Wrench, PackageCheck, Rocket, Settings, Info, Palette,
} from "lucide-vue-next";
import { store, refreshState, applyTheme, currentTheme, THEMES } from "./store.js";
import { waitForBridge, reportFrontendError } from "./lib/bridge.js";
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
const themeOpen = ref(false);
const currentPage = computed(() => pages[store.tab]);
const currentName = computed(() => tabs.find((t) => t.id === store.tab)?.name || "");

function pickTheme(name) {
  theme.value = name;
  applyTheme(name);
  themeOpen.value = false;
}

onMounted(async () => {
  window.addEventListener("error", (e) => reportFrontendError("window.error", e.message || ""));
  window.addEventListener("unhandledrejection", (e) =>
    reportFrontendError("unhandledrejection", String((e.reason && e.reason.message) || e.reason)));
  // 桥没就绪时等一会儿（旧版有 pywebviewready + DOMContentLoaded 两道兜底，这里等价处理）
  if (await waitForBridge()) {
    try {
      await refreshState();
      // 旧版会记住上次停留的页签（config.last_tab）；带 hash 深链时以 hash 为准
      if (!location.hash && store.state.config && store.state.config.last_tab) {
        store.tab = store.state.config.last_tab;
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

    <DialogHost />
    <ToastHost />
  </div>
</template>




