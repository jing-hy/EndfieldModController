<script setup>
// Mod 商城（2026-10-07 新增）。
//
// 用户原话：「我希望加入 mod 商城功能，**可以看看 jasm 是怎么做的**，然后**匹配现在 emc 的 ui**
// 和接入下载功能」＋「mod 批量扫描、一键更新」＋「看商城不用下一个就跳转一次，**但是要有动态**」。
//
// 2026-10-07 第二轮（用户看过界面的原话）：
//   「mod商城**预览比例不对**，**图片清晰度太低**，最上面**搜索框太大**，**下拉框可以一排放三个**，
//    **r18 应该是显示、模糊、隐藏三档**，服装mod、辅助mod下面的**mod下载卡片挪到下载页**，
//    **预览图要更多**等等，可以更多参考 jasm，**显示详情可以不要用弹窗，直接在页面显示**，
//    **详情内容也参考 jasm**，搜索输入框太长」
//   随后澄清：「我的意思是**多参考 jasm 的组件排布**，只要**组件样式**和其他 ui 保持一致就行」
//   ⇒ 排布照 JASM（**左侧分类栏 + 右侧网格**、**页内详情**），样式一律用 EMC 自己的
//     `Card / Btn / Badge / TextField` + `tokens.css` 变量，不自造观感。
//
// 2026-10-07 第三轮：「**缩略图还是模糊而且速度太慢**」
//   ⇒ 根因不是参数，是通道：WebView2 读不到 `file://`，原先每张图都得 base64 成 data URI
//     经 pywebview 的桥**一张张**传（一页 24 张 ≈ 3 MB 字符串注入 + 24 次跨语言往返），
//     为压体积还只能缩图 ⇒ 又慢又糊。现在改成 `mod_store_prepare_images` 一次性准备好，
//     图片由 WebView2 **直接向本地只读服务取**（并发 / 磁盘缓存 / 解码都归浏览器），
//     而且用的就是站点原图（530 档），不重编码。
import { ref, computed, nextTick, onMounted, onUnmounted } from "vue";
import { call } from "../lib/bridge.js";
import { store } from "../store.js";
import { showAlert, showToast } from "../lib/dialog.js";
import Card from "../components/ui/Card.vue";
import Btn from "../components/ui/Btn.vue";
import Badge from "../components/ui/Badge.vue";
import TextField from "../components/ui/TextField.vue";

const PER_PAGE = 24;
const IMG_LIST = 360;      // 仅降级（data URI）路径用
const IMG_DETAIL = 800;

const items = ref([]);
const page = ref(1);
const hasMore = ref(false);
const loading = ref(false);
const loadingMore = ref(false);
const total = ref(0);
const errorText = ref("");
const indexed = ref(false);

const query = ref("");
const category = ref(0);
const character = ref("");
const sort = ref("updated");
// R18 三档（照 JASM 的策略 Show / Blur / Hide，默认模糊）
const NSFW_MODES = [
  { key: "show", label: "显示" },
  { key: "blur", label: "模糊" },
  { key: "hide", label: "隐藏" },
];
const nsfwMode = ref(localStorage.getItem("mc-store-nsfw") || "blur");

const categories = ref({ roots: [], characters: [] });
const queued = ref({});

const detail = ref(null);
const detailLoading = ref(false);
const lightbox = ref("");

const scan = ref({ running: false, message: "", result: {}, saved: {} });

const SORTS = [
  { key: "updated", label: "最近更新" },
  { key: "added", label: "最新发布" },
  { key: "likes", label: "最多点赞" },
  { key: "views", label: "最多浏览" },
];

// ── 图片：本地只读服务直出（正常路径）+ data URI 降级 ─────────────────────────
// 后端 `mod_store_prepare_images` 一次把这一页要用的图都备好，返回
// `{base: "http://127.0.0.1:端口", files: {源URL: 文件名}}` —— 之后 `<img>` 直接指向它，
// WebView2 自己并发取、自己缓存（后端也给了 Cache-Control）。
// 本地服务起不来时（base 为空）才回退到 `mod_store_thumbnail` 的 data URI。
const thumbBase = ref("");
const thumbFiles = ref({});
const fallback = ref({});        // 源 URL → data URI（仅在无本地服务时使用）
let preparing = null;

async function prepareImages(urls, tinyUrls = []) {
  // **两波**：先小图（100 档 3.9 KB，约 1~2 秒到）把格子填上，再换 220 档。
  // 在这台机器 9 KB/s 的网速下，"先出糊的、再变清晰"比"白等十几秒后一次出现"好得多。
  if (tinyUrls && tinyUrls.length) await prepareBatch(tinyUrls);
  await prepareBatch(urls);
}

async function prepareBatch(urls) {
  const need = [];
  for (const url of urls || []) {
    const value = String(url || "").trim();
    if (!value) continue;
    if (thumbFiles.value[value] !== undefined) continue;
    if (need.includes(value)) continue;
    need.push(value);
  }
  if (!need.length) return;
  // 占位：标成"已排队"，避免同一批在两次渲染里被重复请求
  for (const url of need) thumbFiles.value = { ...thumbFiles.value, [url]: "" };
  try {
    const result = await call("mod_store_prepare_images", need);
    if (result && result.ok && result.base) {
      thumbBase.value = result.base;
      const merged = { ...thumbFiles.value, ...(result.files || {}) };
      for (const url of result.failed || []) delete merged[url];   // 失败的允许之后再试
      thumbFiles.value = merged;
      return;
    }
  } catch (e) { /* 落到下面的降级路径 */ }
  // 降级：一张张取 data URI（慢，但至少能看图）
  for (const url of need) {
    try {
      const result = await call("mod_store_thumbnail", url, IMG_LIST);
      if (result && result.ok && result.data_uri) {
        fallback.value = { ...fallback.value, [url]: result.data_uri };
      }
    } catch (e) { /* 单张失败不影响别的 */ }
  }
}

function imageSrc(url) {
  if (!url) return "";
  const name = thumbFiles.value[url];
  if (name && thumbBase.value) return `${thumbBase.value}/${name}`;
  return fallback.value[url] || "";
}

function listSrc(item) {
  // 220 档到位就用它；没到就先用 100 档顶着（别让格子空着）
  return imageSrc(item.thumb) || imageSrc(item.thumb_tiny);
}

// ── 懒加载：只准备**视口内**的图 ─────────────────────────────────────────────
// 为什么必须这样（2026-10-07 实测）：这台机器到 `images.gamebanana.com` 只有约 **9 KB/s**
// —— 530 档一张 56 KB 要 5.9 秒、800 档 10.4 秒，而一屏就有十几张。一次性全下 =
// 打开商城先白等一分多钟（实测 15 张全超时失败）。改成"滚动到哪下到哪"后，
// 首屏只需要几张 100 档小图（3.9 KB）。
let observer = null;

function ensureObserver() {
  if (observer) return observer;
  observer = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      const url = entry.target.getAttribute("data-thumb");
      const tiny = entry.target.getAttribute("data-thumb-tiny");
      prepareImages(url ? [url] : [], tiny ? [tiny] : []);
      observer.unobserve(entry.target);       // 每张只触发一次
    }
  }, { rootMargin: "240px 0px" });            // 提前约一屏开始下，滚动时不至于一片空白
  return observer;
}

async function observeThumbs() {
  await nextTick();
  const watcher = ensureObserver();
  document.querySelectorAll("[data-thumb]").forEach((node) => watcher.observe(node));
}

// ── 列表 ─────────────────────────────────────────────────────────────────────
function options(nextPage) {
  return {
    page: nextPage, per_page: PER_PAGE, category: Number(category.value) || 0,
    character: character.value || "", sort: sort.value,
    query: query.value.trim(), nsfw: nsfwMode.value,
  };
}

async function loadMore() {
  if (loading.value || loadingMore.value) return;
  const nextPage = items.value.length ? page.value + 1 : 1;
  if (nextPage === 1) loading.value = true; else loadingMore.value = true;
  try {
    const result = await call("mod_store_list", options(nextPage));
    if (!result || result.ok === false) {
      errorText.value = (result && result.message) || "商城数据没取到";
      if (nextPage === 1) items.value = [];
      return;
    }
    errorText.value = "";
    const rows = result.items || [];
    items.value = nextPage === 1 ? rows : items.value.concat(rows);
    page.value = nextPage;
    total.value = Number(result.total || 0);
    hasMore.value = !!result.has_more;
    indexed.value = !!result.indexed;
    observeThumbs();               // 只把这一页里**进入视口**的图排进下载
  } catch (e) {
    errorText.value = String((e && e.message) || "商城数据没取到");
  } finally {
    loading.value = false;
    loadingMore.value = false;
  }
}

function reload() {
  items.value = [];
  page.value = 1;
  hasMore.value = false;
  loadMore();
}

async function loadCategories() {
  try {
    const result = await call("mod_store_categories");
    if (result && result.ok) {
      categories.value = { roots: result.roots || [], characters: result.characters || [] };
    }
  } catch (e) { /* 分类拉不到不影响浏览 */ }
}

async function prefetch() {
  try { await call("mod_store_prefetch"); } catch (e) { /* 后台任务 */ }
}

function pickCategory(id) {
  category.value = category.value === id ? 0 : id;
  character.value = "";
  reload();
}

function pickCharacter(name) {
  character.value = character.value === name ? "" : name;
  category.value = 0;
  reload();
}

function setNsfw(mode) {
  if (!NSFW_MODES.some((m) => m.key === mode)) return;
  nsfwMode.value = mode;
  try { localStorage.setItem("mc-store-nsfw", mode); } catch (e) { /* 隐私模式 */ }
  reload();
}

function isBlurred(item) {
  return !!(item && item.nsfw) && nsfwMode.value === "blur";
}

// ── 详情（页内视图，非弹窗）─────────────────────────────────────────────────
const detailImages = computed(() => {
  const item = detail.value || {};
  const images = (item.images || []).filter((img) => img && img.thumb);
  if (images.length) return images;
  return item.thumb ? [{ thumb: item.thumb, big: item.thumb, full: item.thumb }] : [];
});

async function openDetail(item) {
  detail.value = { ...item, loading: true };
  detailLoading.value = true;
  // 先用列表已有的小图顶着，大图另外拉（详情要清晰，值得多等）
  prepareImages([item.thumb_big || item.thumb].filter(Boolean), [item.thumb_tiny].filter(Boolean));
  try {
    const result = await call("mod_store_detail", item.id);
    if (result && result.ok) {
      detail.value = { ...item, ...result.item, loading: false };
      // 详情换**大档**（列表用的是 220 小档）—— 用户已经点进来了，值得多等一会儿换清晰
      prepareImages((result.item.images || []).map((img) => img.thumb_big || img.thumb));
    } else {
      detail.value = { ...item, loading: false, error: (result && result.message) || "详情没取到" };
    }
  } catch (e) {
    detail.value = { ...item, loading: false, error: String((e && e.message) || "详情没取到") };
  } finally {
    detailLoading.value = false;
  }
}

function closeDetail() {
  detail.value = null;
  lightbox.value = "";
}

function openLightbox(url) {
  if (!url) return;
  lightbox.value = url;
  prepareImages([url]);
}

function closeLightbox() {
  lightbox.value = "";
}

// ── 下载（不跳转）───────────────────────────────────────────────────────────
async function download(item) {
  const url = item.url || `https://gamebanana.com/mods/${item.id}`;
  try {
    const result = await call("start_mod_download", url);
    if (!result || result.ok === false) {
      showToast(String((result && result.message) || "没能加入下载队列"), "danger");
      return;
    }
    queued.value = { ...queued.value, [item.id]: true };
    store.activeDownloads = Math.max(store.activeDownloads, 1);
    if (result.added) {
      showToast(`已加入下载队列（共 ${result.queued} 个）—— 进度看「下载」页`, "success");
    } else {
      showToast("这个已经在下载队列里了", "info");
    }
  } catch (e) { /* call 已经弹过错误窗 */ }
}

async function openPage(url) {
  if (!url) return;
  try { await call("open_external", url); } catch (e) { /* 已经弹过 */ }
}

// ── 批量扫描 / 一键更新 ─────────────────────────────────────────────────────
async function scanUpdates() {
  try {
    const result = await call("mod_store_check_updates");
    if (!result || result.ok === false) {
      showAlert("扫描没能开始", (result && result.message) || "未知原因");
      return;
    }
    scan.value = { ...scan.value, running: true, message: "正在扫描…" };
  } catch (e) { /* 已经弹过 */ }
}

async function updateAll() {
  try {
    const result = await call("mod_store_update_all", []);
    if (!result || result.ok === false) {
      showAlert("一键更新没能开始", (result && result.message) || "未知原因");
      return;
    }
    showToast(`已把 ${result.added || 0} 个更新排进下载队列 —— 进度看「下载」页`, "success");
  } catch (e) { /* 已经弹过 */ }
}

async function pollScan() {
  try {
    const result = await call("mod_store_task_status");
    if (!result || result.ok === false) return;
    scan.value = {
      running: !!result.running, message: result.message || "",
      result: result.result || {}, saved: result.scan || {},
    };
  } catch (e) { /* 轮询失败忽略 */ }
}

const updateRows = computed(() => (scan.value.saved && scan.value.saved.updates) || []);
const updateCount = computed(() => updateRows.value.length);
const missingCount = computed(() => ((scan.value.saved && scan.value.saved.missing) || []).length);

function formatDay(seconds) {
  const value = Number(seconds || 0);
  if (!value) return "";
  const date = new Date(value * 1000);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

function formatSize(bytes) {
  const value = Number(bytes || 0);
  if (!value) return "";
  return value >= 1048576 ? `${(value / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(value / 1024))} KB`;
}

let timer = null;
onMounted(() => {
  prefetch();
  loadCategories();
  loadMore();
  pollScan();
  timer = setInterval(pollScan, 2000);
});
onUnmounted(() => {
  if (timer) clearInterval(timer);
  if (observer) { observer.disconnect(); observer = null; }
});
</script>

<template>
  <div class="space-y-4">
    <!-- ══════════ 详情（页内视图，不用弹窗）══════════ -->
    <template v-if="detail">
      <div class="flex items-center gap-2 flex-wrap">
        <Btn size="sm" @click="closeDetail">← 返回商城</Btn>
        <span class="text-base font-semibold truncate" style="max-width: 42vw">{{ detail.name || `#${detail.id}` }}</span>
        <span v-if="detail.nsfw" class="text-xs px-1.5 rounded"
              style="background: var(--danger); color: #fff; font-weight: 600; line-height: 18px">R18</span>
        <Badge v-if="detail.installed && detail.update_available" tone="warn">有更新</Badge>
        <Badge v-else-if="detail.installed" tone="success">已安装</Badge>
        <span class="flex-1"></span>
        <Btn size="sm" variant="primary" :disabled="!!queued[detail.id] || !detail.has_files" @click="download(detail)">
          {{ queued[detail.id] ? "已加入下载" : "下载" }}
        </Btn>
        <a class="text-xs cursor-pointer" style="color: var(--accent)" @click="openPage(detail.url)">网页</a>
      </div>

      <div v-if="detail.loading" class="text-sm" style="color: var(--text-muted)">正在读取详情…</div>
      <div v-else-if="detail.error" class="text-sm" style="color: var(--danger)">{{ detail.error }}</div>
      <template v-else>
        <!-- 预览图：「预览图要更多」—— 多张横滚，点开灯箱看大图 -->
        <div v-if="detailImages.length" class="flex gap-2 overflow-x-auto pb-1">
          <div v-for="(img, index) in detailImages" :key="index"
               class="shrink-0 rounded overflow-hidden cursor-pointer"
               style="width: 200px; aspect-ratio: 16 / 9; background: var(--surface-2); border: 1px solid var(--border)"
               @click="openLightbox(img.big || img.full || img.thumb)">
            <img v-if="imageSrc(img.thumb_big || img.thumb)" :src="imageSrc(img.thumb_big || img.thumb)"
                 class="w-full h-full object-cover" alt="" />
            <div v-else class="w-full h-full flex items-center justify-center text-xs" style="color: var(--text-muted)">…</div>
          </div>
        </div>

        <Card title="信息">
          <div class="grid gap-x-6 gap-y-1.5 text-xs" style="grid-template-columns: repeat(auto-fit, minmax(200px, 1fr))">
            <div><span style="color: var(--text-muted)">作者：</span>{{ detail.author || "—" }}</div>
            <div><span style="color: var(--text-muted)">角色：</span>{{ detail.character_zh || detail.character || "—" }}</div>
            <div><span style="color: var(--text-muted)">分类：</span>{{ detail.category_path_zh || detail.category_path || "—" }}</div>
            <div><span style="color: var(--text-muted)">版本：</span>{{ detail.version || "—" }}</div>
            <div><span style="color: var(--text-muted)">发布：</span>{{ formatDay(detail.added) || "—" }}</div>
            <div><span style="color: var(--text-muted)">最近更新：</span>{{ formatDay(detail.updated) || "—" }}</div>
            <div><span style="color: var(--text-muted)">点赞 / 浏览：</span>{{ detail.likes }} / {{ detail.views }}</div>
            <div><span style="color: var(--text-muted)">总下载：</span>{{ detail.downloads || "—" }}</div>
          </div>
          <div v-if="detail.license" class="text-xs mt-2" style="color: var(--text-muted)">许可：{{ detail.license }}</div>
        </Card>

        <Card v-if="detail.description || detail.summary" title="简介">
          <div v-if="detail.summary" class="text-sm mb-2">{{ detail.summary }}</div>
          <div v-if="detail.description" class="text-xs whitespace-pre-wrap"
               style="color: var(--text-muted); max-height: 260px; overflow: auto">{{ detail.description }}</div>
        </Card>

        <Card v-if="(detail.updates || []).length" title="更新记录">
          <div class="space-y-2">
            <div v-for="row in detail.updates" :key="row.id" class="text-xs">
              <div class="flex flex-wrap items-center gap-2">
                <Badge tone="muted">{{ row.version || "更新" }}</Badge>
                <span style="color: var(--text-muted)">{{ formatDay(row.added) }}</span>
              </div>
              <div v-if="row.text" class="mt-1 whitespace-pre-wrap" style="color: var(--text-muted)">{{ row.text }}</div>
            </div>
          </div>
        </Card>

        <Card v-if="(detail.files || []).length" title="文件">
          <div class="space-y-1">
            <div v-for="file in detail.files.slice(0, 8)" :key="file.id"
                 class="text-xs flex flex-wrap gap-x-3" style="color: var(--text-muted)">
              <span class="truncate" style="max-width: 44vw">{{ file.name }}</span>
              <span>{{ formatSize(file.size) }}</span>
              <span v-if="file.version">v{{ file.version }}</span>
              <span v-if="file.archived">已归档</span>
              <span v-if="file.av === 'clean'">✓ 已扫描</span>
            </div>
          </div>
          <div class="text-xs mt-2" style="color: var(--text-muted)">
            下载时会按作者最新的更新记录自动挑该下的那几个文件（主包 + 配套小文件）。
          </div>
        </Card>
      </template>
    </template>

    <!-- ══════════ 列表视图（左侧分类栏 + 右侧网格，照 JASM 的排布）══════════ -->
    <template v-else>
      <Card title="Mod 商城">
        <template #badge>
          <span class="text-xs" style="color: var(--text-muted)">
            香蕉网 · 终末地{{ total ? ` · ${total} 个` : "" }}
          </span>
        </template>
        <div class="flex flex-wrap items-center gap-2">
          <TextField v-model="query" placeholder="搜名字或作者" style="width: 190px; flex: none"
                     @keyup.enter="reload" />
          <Btn size="sm" @click="reload">搜索</Btn>
          <select v-model="sort" class="field text-xs" style="width: 118px; flex: none" @change="reload">
            <option v-for="option in SORTS" :key="option.key" :value="option.key">{{ option.label }}</option>
          </select>
          <span class="text-xs" style="color: var(--text-muted)">R18</span>
          <div class="flex gap-1">
            <Btn v-for="mode in NSFW_MODES" :key="mode.key" size="sm"
                 :variant="nsfwMode === mode.key ? 'primary' : 'secondary'"
                 @click="setNsfw(mode.key)">{{ mode.label }}</Btn>
          </div>
          <span class="flex-1"></span>
          <Btn size="sm" :disabled="scan.running" @click="scanUpdates">
            {{ scan.running ? "扫描中…" : "扫描更新" }}
          </Btn>
          <Btn size="sm" variant="primary" :disabled="!updateCount" @click="updateAll">
            一键更新{{ updateCount ? `（${updateCount}）` : "" }}
          </Btn>
        </div>
        <div v-if="scan.running || scan.message" class="text-xs mt-2" style="color: var(--text-muted)">
          {{ scan.message }}
          <span v-if="updateCount">· 有 {{ updateCount }} 个可更新</span>
          <span v-if="missingCount">· {{ missingCount }} 个远端已找不到</span>
          <span v-if="indexed">· 已用本地索引</span>
        </div>
      </Card>

      <Card v-if="errorText">
        <div class="text-sm" style="color: var(--danger)">{{ errorText }}</div>
        <div class="text-xs mt-2" style="color: var(--text-muted)">
          先用浏览器确认能不能打开 gamebanana.com；直连不通就开一下加速器/VPN 再点重试。
        </div>
        <div class="mt-3"><Btn variant="primary" @click="reload">重试</Btn></div>
      </Card>

      <div class="flex gap-4 items-start">
        <!-- 左：分类 + 角色（JASM 也是这个排布；EMC 里用现有 Card）。
             2026-10-07 用户：「角色分类那个卡片可以做长一点」⇒ 卡片更高、一次能看到更多角色，
             宽度也略放宽（中文角色名 + 数量在 178px 里容易被截断）。 -->
        <Card title="分类" class="shrink-0" style="width: 198px">
          <div class="space-y-0.5 text-sm">
            <button class="w-full text-left px-2 py-1 rounded"
                    :style="!category && !character
                      ? { background: 'var(--accent-soft)', color: 'var(--accent)' }
                      : { color: 'var(--text-muted)' }"
                    @click="category = 0; character = ''; reload()">全部</button>
            <button v-for="root in categories.roots" :key="root.id"
                    class="w-full text-left px-2 py-1 rounded flex items-center gap-1"
                    :style="category === root.id
                      ? { background: 'var(--accent-soft)', color: 'var(--accent)' }
                      : { color: 'var(--text-muted)' }"
                    @click="pickCategory(root.id)">
              <span class="truncate flex-1">{{ root.name_zh || root.name }}</span>
              <span class="text-xs">{{ root.count }}</span>
            </button>
          </div>
          <div v-if="categories.characters.length" class="mt-2 pt-2"
               style="border-top: 1px solid var(--border)">
            <div class="text-xs mb-1" style="color: var(--text-muted)">角色</div>
            <!-- 「做长一点」：原来只给 320px（一屏看得到十来个角色、其余要滚）⇒ 加高到 620px，
                 并与窗口高度联动（`calc(100vh - 320px)`），长列表尽量一屏看完。 -->
            <div class="space-y-0.5 overflow-auto" style="max-height: max(320px, calc(100vh - 340px)); min-height: 420px">
              <button v-for="row in categories.characters" :key="row.id"
                      class="w-full text-left px-2 py-1 rounded text-sm flex items-center gap-1"
                      :style="character === row.name
                        ? { background: 'var(--accent-soft)', color: 'var(--accent)' }
                        : { color: 'var(--text-muted)' }"
                      @click="pickCharacter(row.name)">
                <span class="truncate flex-1">{{ row.name_zh || row.name }}</span>
                <span class="text-xs">{{ row.count }}</span>
              </button>
            </div>
          </div>
        </Card>

        <!-- 右：网格 -->
        <div class="flex-1 min-w-0 space-y-3">
          <div v-if="items.length" class="grid gap-3"
               style="grid-template-columns: repeat(auto-fill, minmax(280px, 1fr))">
            <div v-for="item in items" :key="item.id" class="card overflow-hidden flex flex-col">
              <div class="relative cursor-pointer" :data-thumb="item.thumb" :data-thumb-tiny="item.thumb_tiny"
                   style="aspect-ratio: 16 / 9; background: var(--surface-2)"
                   @click="openDetail(item)">
                <img v-if="listSrc(item)" :src="listSrc(item)" class="w-full h-full object-cover" alt=""
                     :style="isBlurred(item) ? 'filter: blur(16px); transform: scale(1.08)' : ''" />
                <div v-else class="w-full h-full flex items-center justify-center text-xs" style="color: var(--text-muted)">
                  加载中…
                </div>
                <div v-if="isBlurred(item)"
                     class="absolute inset-0 flex items-center justify-center text-xs"
                     style="color: var(--text); background: rgba(0,0,0,.25)">R18 · 点开查看</div>
                <!-- R18 标签用**实心**红底白字（用户 2026-10-07：「r18 那个标签不要透明」）——
                     默认的 `.badge-danger` 是 14% 透明底 + 红字，压在封面上几乎看不清。 -->
                <span v-if="item.nsfw && nsfwMode === 'show'"
                      class="absolute top-1.5 right-1.5 text-xs px-1.5 rounded"
                      style="background: var(--danger); color: #fff; font-weight: 600; line-height: 18px">R18</span>
              </div>
              <div class="p-3 flex-1 flex flex-col gap-2">
                <div class="text-sm font-medium cursor-pointer" style="line-height: 1.35; min-height: 2.7em"
                     :title="item.name" @click="openDetail(item)">
                  {{ item.name || `#${item.id}` }}
                </div>
                <div class="flex flex-wrap items-center gap-1.5 text-xs" style="color: var(--text-muted)">
                  <span v-if="item.author">作者 {{ item.author }}</span>
                  <span v-if="item.character_zh || item.character">· {{ item.character_zh || item.character }}</span>
                  <span v-else-if="item.root_category">· {{ item.root_category_zh || item.root_category }}</span>
                </div>
                <div class="flex flex-wrap items-center gap-1.5">
                  <Badge v-if="item.installed && item.update_available" tone="warn">有更新</Badge>
                  <Badge v-else-if="item.installed" tone="success">已安装</Badge>
                  <Badge v-if="item.version" tone="muted">v{{ item.version }}</Badge>
                  <span class="text-xs" style="color: var(--text-muted)">♥ {{ item.likes }} · 浏览 {{ item.views }}</span>
                </div>
                <div class="flex items-center gap-2 mt-auto">
                  <Btn size="sm" :variant="queued[item.id] ? 'secondary' : 'primary'"
                       :disabled="!!queued[item.id] || !item.has_files" @click="download(item)">
                    {{ queued[item.id] ? "已加入下载" : "下载" }}
                  </Btn>
                  <a class="text-xs cursor-pointer" style="color: var(--accent)" @click="openDetail(item)">详情</a>
                  <a class="text-xs cursor-pointer" style="color: var(--accent)" @click="openPage(item.url)">网页</a>
                </div>
              </div>
            </div>
          </div>

          <Card v-else-if="!loading">
            <p class="text-sm" style="color: var(--text-muted)">
              没有匹配的 Mod。换个关键词、或者把左边的分类/角色改回「全部」再看看。
            </p>
          </Card>

          <div v-if="items.length" class="flex items-center justify-center gap-3">
            <Btn v-if="hasMore" size="sm" :disabled="loadingMore" @click="loadMore">
              {{ loadingMore ? "加载中…" : "加载更多" }}
            </Btn>
            <span v-else class="text-xs" style="color: var(--text-muted)">已经到底了（共 {{ items.length }} 个）</span>
          </div>
        </div>
      </div>
    </template>

    <!-- 灯箱：点预览图看大图 -->
    <div v-if="lightbox" class="fixed inset-0 z-50 flex items-center justify-center p-6"
         style="background: rgba(0,0,0,.8)" @click="closeLightbox">
      <img v-if="imageSrc(lightbox)" :src="imageSrc(lightbox)"
           style="max-width: 94vw; max-height: 88vh; object-fit: contain" alt="" />
      <div v-else class="text-sm" style="color: #fff">大图加载中…（点任意处关闭）</div>
    </div>
  </div>
</template>
