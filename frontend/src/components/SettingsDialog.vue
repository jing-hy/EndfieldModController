<!-- SPDX-License-Identifier: AGPL-3.0-only -->
<script setup>
// 设置浮窗（2026-11-28 用户要求）：
//   * 侧栏不再有「设置」「说明」两个页面；点底部齿轮在窗口中央浮出一个小窗，背景虚化；
//   * 小窗内左侧是设置导航（8 类），但右侧是**一整页可连续滚动**的内容 ——
//     点左栏只是滚到对应分组，不再"切标签"（用户明确：要能直接滑到底）；
//   * 「说明」放在小窗底部，点开在同一小窗内切换内容（左上角可返回）。
//
// ⚠️ 层级必须是 z-40：设置里的「还原游戏本体」等操作会弹 DialogHost（z-50），
//    浮层高了就把确认框盖住了（用户会以为按钮没反应）。
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import {
  Settings2, Palette, FolderOpen, Download, Globe, Wrench, Bug, Info, X, ArrowLeft,
} from "lucide-vue-next";
import {
  store, closeSettings, openSettings, showAbout, backToSettings, refreshState,
} from "../store.js";
import { loadSettings } from "../lib/settings.js";
import { call } from "../lib/bridge.js";
import { t } from "../lib/i18n.js";
import SettingsPage from "../pages/SettingsPage.vue";
import AboutPage from "../pages/AboutPage.vue";

// 左栏顺序 = 右栏分组顺序（SettingsPage 里用同一个 id 生成锚点）。
const SECTIONS = [
  { id: "general", name: "通用", icon: Settings2 },
  { id: "appearance", name: "外观", icon: Palette },
  { id: "paths", name: "路径", icon: FolderOpen },
  { id: "downloads", name: "下载", icon: Download },
  { id: "webserver", name: "Web 服务", icon: Globe },
  { id: "maintenance", name: "维护", icon: Wrench },
  { id: "debug", name: "调试", icon: Bug },
  { id: "about", name: "关于", icon: Info },
];

const activeSection = ref(store.settingsSection || "general");
const bodyRef = ref(null);
let scrollRaf = 0;
let lastFocus = null;
const closeBtn = ref(null);

function sectionEl(id) {
  return document.getElementById("settings-section-" + id);
}

function sectionTop(el) {
  const body = bodyRef.value;
  if (!body) return 0;
  return el.getBoundingClientRect().top - body.getBoundingClientRect().top + body.scrollTop;
}

function scrollToSection(id, smooth = true) {
  const el = sectionEl(id);
  const body = bodyRef.value;
  if (!el || !body) return;
  body.scrollTo({ top: Math.max(0, sectionTop(el) - 8), behavior: smooth ? "smooth" : "auto" });
}

function pickSection(id) {
  if (store.settingsMode === "about") backToSettings();
  store.settingsSection = id;
  activeSection.value = id;
  nextTick(() => scrollToSection(id));
}

// 滚动时高亮左栏（只改本地 activeSection，不回写 store —— 免得和"打开到某分类"互相打架）
function onBodyScroll() {
  if (scrollRaf) return;
  scrollRaf = requestAnimationFrame(() => {
    scrollRaf = 0;
    if (!bodyRef.value || store.settingsMode !== "settings") return;
    const marker = bodyRef.value.scrollTop + 24;
    let current = SECTIONS[0].id;
    for (const s of SECTIONS) {
      const el = sectionEl(s.id);
      if (el && sectionTop(el) <= marker) current = s.id;
    }
    activeSection.value = current;
  });
}

// 底部版本号（轻量版额外标出来）。版本号与 UpdateBadge 同源：get_app_info。
const version = ref("");
const versionText = computed(() => {
  const parts = [];
  if (version.value) parts.push("v" + version.value);
  if ((store.state && store.state.edition) === "lite") parts.push(t("轻量版"));
  return parts.join(" · ");
});

watch(() => store.settingsOpen, async (open) => {
  if (open) {
    lastFocus = document.activeElement;
    loadSettings();
    // 设置里的路径/状态卡依赖 store.state；刷新放后台，别卡住开窗。
    refreshState().then(() => loadSettings()).catch(() => {});
    const wanted = SECTIONS.some((s) => s.id === store.settingsSection)
      ? store.settingsSection : "general";
    activeSection.value = wanted;
    await nextTick();
    await nextTick();
    scrollToSection(wanted, false);
    if (closeBtn.value && closeBtn.value.focus) closeBtn.value.focus();
  } else if (lastFocus && lastFocus.focus) {
    try { lastFocus.focus(); } catch (e) { /* 焦点还回去失败无所谓 */ }
    lastFocus = null;
  }
}, { immediate: true });

// 外部（新手引导第 4 步 / #settings 深链）指定了分类 ⇒ 滚过去
watch(() => store.settingsSection, (id) => {
  if (!store.settingsOpen || store.settingsMode !== "settings") return;
  if (!SECTIONS.some((s) => s.id === id)) return;
  activeSection.value = id;
  nextTick(() => scrollToSection(id));
});

// 版本号：桥就绪后再问（与 UpdateBadge 同一个坑：子组件 onMounted 早于桥就绪）
watch(() => store.ready, async (ready) => {
  if (!ready || version.value) return;
  try {
    const info = await call("get_app_info");
    if (info && info.version) version.value = String(info.version);
  } catch (e) { /* 拿不到就不显示版本 */ }
}, { immediate: true });

function onKeydown(event) {
  if (!store.settingsOpen) return;
  if (event.key === "Escape") {
    event.preventDefault();
    closeSettings();
  }
}
onMounted(() => window.addEventListener("keydown", onKeydown));
onUnmounted(() => window.removeEventListener("keydown", onKeydown));
</script>

<template>
  <div v-if="store.settingsOpen" class="settings-overlay" role="dialog" aria-modal="true"
       :aria-label="t('设置')">
    <!-- 背景虚化：点遮罩关闭 -->
    <div class="settings-backdrop" @click="closeSettings"></div>
    <section class="settings-card" @click.stop>
      <div class="settings-columns">
        <aside class="settings-nav" :aria-label="t('设置分类')">
          <div class="settings-brand">{{ t(store.settingsMode === "about" ? "说明" : "设置") }}</div>
          <button v-for="s in SECTIONS" :key="s.id"
                  :data-mc-id="'settings:section:' + s.id"
                  class="settings-nav-item"
                  :class="{ active: store.settingsMode === 'settings' && activeSection === s.id }"
                  :aria-current="store.settingsMode === 'settings' && activeSection === s.id ? 'true' : 'false'"
                  @click="pickSection(s.id)">
            <component :is="s.icon" :size="16" />
            <span>{{ t(s.name) }}</span>
          </button>
        </aside>
        <div class="settings-main">
          <header class="settings-head">
            <button v-if="store.settingsMode === 'about'" class="settings-back"
                    data-mc-id="settings:back" @click="backToSettings">
              <ArrowLeft :size="14" />
              <span>{{ t("返回设置") }}</span>
            </button>
            <span class="settings-title">{{ t(store.settingsMode === "about" ? "说明" : "设置") }}</span>
            <button ref="closeBtn" class="settings-close" data-mc-id="settings:close"
                    :aria-label="t('关闭设置')" :title="t('关闭（Esc）')" @click="closeSettings">
              <X :size="16" />
            </button>
          </header>
          <div ref="bodyRef" class="settings-body" @scroll="onBodyScroll">
            <AboutPage v-if="store.settingsMode === 'about'" />
            <SettingsPage v-else />
          </div>
        </div>
      </div>
      <footer class="settings-foot">
        <button class="settings-link" data-mc-id="settings:about" @click="showAbout">
          <Info :size="14" />
          <span>{{ t("说明") }}</span>
        </button>
        <span class="settings-version">{{ versionText }}</span>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.settings-overlay {
  position: fixed;
  inset: 0;
  z-index: 40;              /* 必须低于 DialogHost(50) / Toast(60) / 引导(800) */
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}
.settings-backdrop {
  position: absolute;
  inset: 0;
  background: rgba(0, 0, 0, .35);
  -webkit-backdrop-filter: blur(10px);
  backdrop-filter: blur(10px);
}
.settings-card {
  position: relative;
  display: flex;
  flex-direction: column;
  width: min(880px, 92vw);
  height: min(640px, 88vh);
  min-width: 0;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  box-shadow: var(--sh-lg);
  overflow: hidden;
  animation: settings-in .16s ease-out;
}
@keyframes settings-in {
  from { opacity: 0; transform: scale(.985) translateY(4px); }
  to { opacity: 1; transform: none; }
}
@media (prefers-reduced-motion: reduce) {
  .settings-card { animation: none; }
}
.settings-columns {
  display: flex;
  flex: 1;
  min-height: 0;
}
.settings-nav {
  width: 180px;
  flex: none;
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 10px 8px;
  overflow-y: auto;
  border-right: 1px solid var(--border);
  background: var(--surface-2);
}
.settings-brand {
  padding: 6px 10px 10px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
}
.settings-nav-item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 7px 10px;
  border-radius: 8px;
  font-size: 13px;
  text-align: left;
  color: var(--text-muted);
  transition: background .15s, color .15s;
}
.settings-nav-item:hover { background: var(--surface); color: var(--text); }
.settings-nav-item.active {
  background: var(--accent-soft);
  color: var(--accent);
  font-weight: 500;
}
.settings-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}
.settings-head {
  flex: none;
  height: 44px;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 12px 0 16px;
  border-bottom: 1px solid var(--border);
}
.settings-title { font-size: 14px; font-weight: 600; }
.settings-back {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
  border-radius: 6px;
  font-size: 12px;
  color: var(--text-muted);
}
.settings-back:hover { background: var(--surface-2); color: var(--text); }
.settings-close {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 6px;
  color: var(--text-muted);
}
.settings-close:hover { background: var(--surface-2); color: var(--text); }
.settings-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 16px 18px 24px;
  scroll-behavior: smooth;
}
.settings-foot {
  flex: none;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 14px;
  border-top: 1px solid var(--border);
  background: var(--surface-2);
}
.settings-link {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  border-radius: 6px;
  font-size: 12px;
  color: var(--text-muted);
}
.settings-link:hover { background: var(--surface); color: var(--text); }
.settings-version {
  margin-left: auto;
  font-size: 12px;
  color: var(--text-muted);
}
</style>
