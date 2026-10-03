<script setup>
import { ref, computed, onMounted } from "vue";
import {
  Library, Wrench, PackageCheck, Rocket, Settings, Info, Palette,
} from "lucide-vue-next";
import { store, refreshState, applyTheme, currentTheme, THEMES, PAGE_IDS } from "./store.js";
import { waitForBridge, reportFrontendError } from "./lib/bridge.js";
import { loadSettings } from "./lib/settings.js";
import { dragHasFiles, importDroppedFile } from "./lib/importMod.js";
import { normalizeAnnouncements } from "./lib/announce.js";
import UpdateBadge from "./components/UpdateBadge.vue";
import { showModalDialog, showToast } from "./lib/dialog.js";
import { call } from "./lib/bridge.js";
import DialogHost from "./components/DialogHost.vue";
import OnboardingTour from "./components/OnboardingTour.vue";
import ToastHost from "./components/ToastHost.vue";
import AboutPage from "./pages/AboutPage.vue";
import SettingsPage from "./pages/SettingsPage.vue";
import AssistPage from "./pages/AssistPage.vue";
import DepsPage from "./pages/DepsPage.vue";
import LaunchPage from "./pages/LaunchPage.vue";
import ModLibraryPage from "./pages/ModLibraryPage.vue";
import UiPreviewPage from "./pages/UiPreviewPage.vue";

const pages = {
  preview: UiPreviewPage,
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
const THEME_LABELS = { light: "浅色", dark: "深色", amber: "琥珀", cyan: "青蓝", violet: "紫罗兰", emerald: "翡翠" };
const theme = ref(currentTheme());
const themeLabel = computed(() => THEME_LABELS[theme.value] || theme.value);
// 版本号与更新入口统一在左侧栏的 UpdateBadge 里（顶栏不再显示，这里也就没有 versionText 了）
// 拖放导入：提示层**松开鼠标就消失**（用户要求「应该是释放就消失」），拖拽计数避免子元素抖动
const dragging = ref(false);
// 公告条（用户每次启动都会看到；点关闭就告诉后端"已读"）
const notices = ref([]);
let firstRunChecked = false;
const tourVisible = ref(false);   // 新手引导浮层（挖孔高亮 + 箭头指向目标）
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

// 切页签要**写回** config.last_tab —— 之前只有启动时读、从不保存，"记住上次页签"实际不成立。
async function goTab(id) {
  store.tab = id;
  try { await call("save_config", { last_tab: id }); } catch (e) { /* 记不上不影响使用 */ }
}

function pickTheme(name) {
  theme.value = name;
  applyTheme(name);
  themeOpen.value = false;
}

onMounted(async () => {
  // UI 预览页（#preview?d=xxx）：只截图/回归用，不碰后端
  if (String(location.hash || "").startsWith("#preview")) {
    store.tab = "preview";
    return;
  }
  // `?demo=1`：用真实库快照渲染 —— **只在 `VITE_UI_DEMO=1 npm run build` 的构建里存在**。
  // 正式构建会被下面这行 `import.meta.env.VITE_UI_DEMO` 判断整段摇掉（rollup 常量折叠），
  // 所以正式包既没有这段逻辑、也不会去读任何本地文件（用户准则：正式版不含测试通道）。
  if (import.meta.env.VITE_UI_DEMO === "1"
      && new URLSearchParams(location.search).get("demo") === "1") {
    await new Promise((resolve) => {
      const el = document.createElement("script");
      el.src = "./demo-state.js";
      el.onload = resolve;
      el.onerror = resolve;
      document.head.appendChild(el);
    });
    if (window.__DEMO_STATE__) {
      store.state = window.__DEMO_STATE__;
      store.mods = store.state.mods || [];
      // 快照里预置的封面（data URI）——file:// 下前端拿不到本地图片，只能内联
      store.demoCovers = window.__DEMO_STATE__.demo_covers || {};
      store.config = store.state.config || {};
      store.ready = true;
      loadSettings();
      // demo 模式也要能看引导：快照里把 first_run.onboarding_done 置 false 即可复现首启
      const demoFr = store.state.first_run || {};
      if (demoFr.first_run && !demoFr.onboarding_done) tourVisible.value = true;
      return;
    }
  }
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
      // 校验后再用：配置里残留的旧页签名会让 currentPage 变成 undefined、页面一片空白
      const lastTab = store.state.config && store.state.config.last_tab;
      if (!location.hash && PAGE_IDS.includes(lastTab)) store.tab = lastTab;
      notices.value = normalizeAnnouncements(store.state.announcements);
      // 首次启动：**只提示一次**（判据用后端持久化的 onboarding_done，而不是"当前还没就绪"
      // 这类会一直为真的状态 —— 否则会连环弹）。
      const fr = store.state.first_run || {};
      if (!firstRunChecked && fr.first_run && !fr.onboarding_done) {
        firstRunChecked = true;
        // 用户 2026-10-03：「现在首次使用引导变成只有文字的了，我需要那种一个箭头指向按钮的
        // 那种」—— 原来那个纯文字弹窗是评审建议下改的，但他要的是**高亮 + 箭头指向**的
        // 分步引导（0.4.0 那版就是分步 tour，本次移植回来并补上箭头）。
        tourVisible.value = true;
      }
    } catch (e) { /* call() 已经弹过窗 */ }
  }
});

// 引导步骤（沿用 0.4.0 的四步，内容按现在的界面更新；
// 第二步按用户要求补上"也可以直接下载"这条路）。
const TOUR_STEPS = [
  {
    tab: "dependencies", target: "dep-update-all-btn",
    title: "第一步：先把组件装齐",
    body: "这里是「依赖」页。点这个「安装缺失依赖」按钮，程序会自动下载并安装\n"
      + "XXMI Launcher、XXMI 库、EFMI、DLSS5 组件等全部依赖（需要联网）。\n\n"
      + "建议先点它，等装完再去启动。右边那个黑框会显示下载线路与进度。",
  },
  {
    tab: "library", target: "mod-download-box",
    title: "第二步：把 Mod 弄进来",
    body: "有两种方式：\n"
      + "① 把 Mod 的 .zip / .7z / .rar 拖到窗口任意位置 —— 松手后自动解压进库并识别角色；\n"
      + "② 直接下载：在「下载 Mod」里粘贴网址（一行一个），也支持香蕉网页面地址，\n"
      + "   会自动取真实文件直链、并带出封面。\n\n"
      + "同一个角色默认只保留一个 Mod（自动互斥），避免游戏崩。",
  },
  {
    tab: "launch", target: "oneclick-launch-btn",
    title: "第三步：一键启动",
    body: "点这个「一键启动」：程序会补齐缺失组件、同步注入库、跑一遍初始化自检，\n"
      + "然后拉起 XXMI Launcher（不会自动进游戏，进游戏在 XXMI 里点 Start）。\n\n"
      + "第一次可能会提示「请再点一次一键启动」，看到后再点一次即可。",
  },
  {
    tab: "settings", target: "game-restore-btn",
    title: "第四步：随时可以还原",
    body: "「设置」页有「还原游戏本体」：\n"
      + "本程序对游戏目录做的任何改动都可回滚（净化前会完整备份、只移动不删除）。\n\n"
      + "同一页还有「依赖清空并重新下载」——组件装坏了、缺文件时可以一键清空重来。",
  },
];

async function finishTour() {
  tourVisible.value = false;
  try { await call("save_config", { onboarding_done: true }); } catch (e) { /* 记不上也不影响本次 */ }
}
</script>

<template>
  <div class="flex h-full">
    <aside class="w-52 shrink-0 flex flex-col border-r" style="background: var(--surface); border-color: var(--border)">
      <div class="h-12 px-4 flex items-center text-sm font-semibold border-b" style="border-color: var(--border)">
        终末地 Mod 管理器
      </div>
      <nav class="flex-1 p-2 space-y-0.5">
        <button v-for="t in tabs" :key="t.id" @click="goTab(t.id)"
          class="w-full flex items-center gap-2.5 px-3 py-2 rounded text-left transition-colors"
          :style="store.tab === t.id
            ? { background: 'var(--accent-soft)', color: 'var(--accent)', fontWeight: 500 }
            : { color: 'var(--text-muted)' }">
          <component :is="t.icon" :size="16" />
          <span class="text-sm">{{ t.name }}</span>
        </button>
      </nav>
      <!-- 自更新入口（用户要求：左侧导航下面、主题色上面） -->
      <div class="p-1.5 border-t" style="border-color: var(--border)">
        <UpdateBadge />
      </div>
      <div class="p-2 border-t relative" style="border-color: var(--border)">
        <button @click="themeOpen = !themeOpen"
          class="w-full flex items-center gap-2.5 px-3 py-2 rounded text-sm"
          style="color: var(--text-muted)">
          <Palette :size="16" />
          <span>主题：{{ themeLabel }}</span>
        </button>
        <div v-if="themeOpen" class="absolute bottom-12 left-2 right-2 card p-1.5 shadow-lg z-20">
          <button v-for="t in THEMES" :key="t" @click="pickTheme(t)"
            class="w-full text-left px-2.5 py-1.5 rounded text-sm"
            :style="t === theme ? { background: 'var(--accent-soft)', color: 'var(--accent)' } : {}">
            {{ THEME_LABELS[t] }}
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
      <header class="h-14 px-6 flex items-center justify-between border-b sticky top-0 z-10"
              style="background: var(--surface); border-color: var(--border)">
        <div>
          <h1 class="page-title">{{ currentName }}</h1>
        </div>
        <!-- 版本号与更新入口统一放在左侧栏底部（顶栏不再重复显示） -->
      </header>
      <div class="px-6 py-5">
        <div class="page-inner">
          <component :is="currentPage" v-if="currentPage" />
          <div v-else class="card p-6 text-sm" style="color: var(--text-muted)">
            「{{ currentName }}」还在迁移中（新前端逐页搬，这一页暂时用旧界面）。
          </div>
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

    <!-- 新手引导：挖孔高亮 + 箭头指向目标控件（用户要的"一个箭头指向按钮"） -->
    <OnboardingTour v-model="tourVisible" :steps="TOUR_STEPS" @finish="finishTour" />

    <DialogHost />
    <ToastHost />
  </div>
</template>




