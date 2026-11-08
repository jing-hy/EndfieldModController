<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
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
import { ref, computed, nextTick, watch, onMounted, onUnmounted } from "vue";import { call } from "../lib/bridge.js";
import { store } from "../store.js";
import { showAlert, showToast } from "../lib/dialog.js";
import Card from "../components/ui/Card.vue";
import Btn from "../components/ui/Btn.vue";
import Badge from "../components/ui/Badge.vue";
import TextField from "../components/ui/TextField.vue";
// 统计行的图标（照 JASM 的卡片：底部一行"图标 + 数字"）
import { Heart, Eye } from "lucide-vue-next";

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
// 分类/角色的条目数 —— **从列表用的那份本地索引里数出来**（跟着 `mod_store_list` 一起来）。
// 2026-11-07 用户实测：「mod商城分类显示的数字和右上角不符」「前一小时还在的 mod 现在消失了」。
// 根因是数字取站点分类接口（分类树缓存 7 天）、列表取本地索引（缓存 1 天、刷新失败还会更旧、
// 残缺时还会少一批）—— 两个来源各说各话。现在**标签上的数 == 点进去看到的条数**。
const counts = ref(null);       // {total, roots:{名字:条数}, characters:{名字:条数}}
const indexMeta = ref(null);    // {items,total,complete,age,...}
const queued = ref({});

const detail = ref(null);
const detailLoading = ref(false);
const lightbox = ref("");          // 要放大的那张（可能是要现下的"大图"）
const lightboxFallback = ref("");  // 已在本地的缩略图：大图没到之前先用它顶着
const lightboxSlow = ref(false);   // 超过 12 秒还没到位 ⇒ 换一句实话，别一直"加载中"

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

async function prepareImages(urls) {
  // ⚠️ **一张图只请求一次**（2026-10-07 对照 JASM 后改）：原先做了"先 100 档秒出、再换 220 档"
  // 两波，在慢网下等于**请求数翻倍**、总耗时也翻倍 —— 而 JASM 的列表缩略图同样用 220 档，
  // 全程只请求一次，观感反而更快。慢网下"少请求"比"早出糊图"更值。
  await prepareBatch(urls);
}

// ── 后台下图的**轮询**：让图片"下好一张显一张" ─────────────────────────────────
// 用户 2026-10-07：「拉到下面也慢」—— 根因是同步等**整批**下完才一起返回。现在后端只返回
// 已经在本地的那几张、其余丢后台，这里就按 600ms 问一次"还没到位的那几张"。
// 上限 60 轮（约 36 秒）—— 该域的图有时会彻底不通，不能让轮询一直转下去。
const pendingImages2 = new Set();   // 注意：与上面的 pendingImages（攒批用）不是一回事
let pendingTimer = null;

function watchPending(urls) {
  for (const url of urls) if (url) pendingImages2.add(url);
  if (pendingTimer || !pendingImages2.size) return;
  let rounds = 0;
  pendingTimer = setInterval(async () => {
    rounds += 1;
    const still = [...pendingImages2].filter((url) => !thumbFiles.value[url]);
    for (const url of [...pendingImages2]) {
      if (thumbFiles.value[url]) pendingImages2.delete(url);   // 到位了就摘掉
    }
    if (!still.length || rounds > 60) {
      clearInterval(pendingTimer);
      pendingTimer = null;
      pendingImages2.clear();
      return;
    }
    await prepareBatch(still);
  }, 600);
}

async function prepareBatch(urls) {
  const need = [];
  for (const url of urls || []) {
    const value = String(url || "").trim();
    if (!value) continue;
    // 只有**真的拿到文件名**才算"有了"（后端走的是后台下载，没到位的要能重复来问）
    if (thumbFiles.value[value]) continue;
    if (need.includes(value)) continue;
    need.push(value);
  }
  if (!need.length) return;
  try {
    const result = await call("mod_store_prepare_images", need);
    if (result && result.ok && result.base) {
      thumbBase.value = result.base;
      const merged = { ...thumbFiles.value, ...(result.files || {}) };
      for (const url of result.failed || []) delete merged[url];   // 失败的允许之后再试
      thumbFiles.value = merged;
      // 后端在**后台**下这批图（它只返回"已经在本地"的那些）⇒ 没到位的过一会儿再问一次，
      // 于是图片是**下好一张显一张**，而不是等整批下完才一起出现。
      watchPending(result.pending || []);
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

// ── 让一屏图片**同时并发取**（用户 2026-10-07：「jasm 一下就全出」）──────────────
// 懒加载是**一条一条**触发回调的。若每条都单独发一次请求，后端就只能一张一张排队下载 ——
// 总耗时差不多，但观感是"一张一张往外蹦"，而 JASM 是全部一起请求、一起到。
// 做法：把 **50ms 内**触发的请求攒成一批再发 ⇒ 一屏图片同时起飞。
const pendingImages = new Set();
let flushTimer = null;

function queueImage(url) {
  const key = String(url || "").trim();
  if (!key) return;
  if (thumbFiles.value[key] !== undefined || pendingImages.has(key)) return;
  pendingImages.add(key);
  if (flushTimer) return;
  flushTimer = setTimeout(() => {
    flushTimer = null;
    const batch = Array.from(pendingImages);
    pendingImages.clear();
    prepareImages(batch);
  }, 50);
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
      if (url) queueImage(url);      // 攒批后再发 ⇒ 一屏同时并发
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

// ── 无限滚动：滚到底部自动加载下一页 ─────────────────────────────────────────
// 用户 2026-10-07：「在线商城应该划到最下面**自动往下加载**，而不是靠我手点」。
// **两条腿走路**，缺一条都会卡住：
//   ① `IntersectionObserver` 负责"用户滚到哨兵附近"；
//   ② 每次列表变长后再**主动量一次**哨兵位置 —— 列表短或屏幕大时，哨兵会一直待在视口里，
//      而 observer 只在"进出视口"时回调 ⇒ 只看它会停在第二页不动（纯 observer 写法的经典坑）。
const sentinel = ref(null);
let sentinelObserver = null;

async function fillIfNeeded() {
  if (detail.value || !hasMore.value || loading.value || loadingMore.value) return;
  await nextTick();
  const node = sentinel.value;
  if (!node) return;
  if (node.getBoundingClientRect().top <= window.innerHeight + 400) {
    await loadMore();
    await fillIfNeeded();     // 一页填不满屏幕就继续填（items 变多后自然停下）
  }
}

function watchSentinel() {
  if (!sentinelObserver) {
    sentinelObserver = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) fillIfNeeded();
    }, { rootMargin: "400px 0px" });
  }
  sentinelObserver.disconnect();
  if (sentinel.value) sentinelObserver.observe(sentinel.value);
}

// 列表一变长就重新盯住哨兵（详情页切回来时哨兵是新渲染出来的，也得重新盯）+ 主动补填
// ⚠️⚠️ **必须 post-flush + 等一次 nextTick**（2026-11-07 用户报「滑到最底显示『往下滑自动加载』
// 然后就划不动了」）：默认 flush='pre'，回调在 DOM 更新**之前**跑 —— 首屏第一页渲染出来那一刻
// 哨兵节点还不存在（模板是 `v-if="items.length"`），于是 `watchSentinel()` 拿到 null、
// 只执行了 disconnect()，**observer 从此没盯上任何节点**；如果首屏一页就铺满了视口
// （`fillIfNeeded` 不需要补第二页），就再没有任何地方去 observe 它 ——
// 用户滚到底部时 IntersectionObserver 一次都不会回调，列表也就不再往下加载。
watch(() => items.value.length, async () => {
  await nextTick();
  watchSentinel();
  fillIfNeeded();
}, { flush: "post" });

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
    // 分类数字跟着列表走（同源）；没有就置空，避免拿上一次的旧数字硬套
    counts.value = result.counts || null;
    indexMeta.value = result.index || null;
    observeThumbs();               // 只把这一页里**进入视口**的图排进下载
  } catch (e) {
    errorText.value = String((e && e.message) || "商城数据没取到");
  } finally {
    loading.value = false;
    loadingMore.value = false;
    // 兜底重新盯哨兵：只靠上面的 watcher 会漏（首屏哨兵尚未渲染、或 reload 后节点被替换）
    nextTick(() => { watchSentinel(); });
    if (headReloadPending) {
      headReloadPending = false;
      // 顶部刷新拿到了新条目，而这次列表是从旧索引读出来的 ⇒ 等它落地后重载一次
      loadCategories();
      reload();
    }
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
  prepareImages([item.thumb_big || item.thumb].filter(Boolean));
  try {
    const result = await call("mod_store_detail", item.id);
    if (result && result.ok) {
      detail.value = { ...item, ...result.item, loading: false };
      // 详情换**大档**（列表用的是 220 小档）—— 用户已经点进来了，值得多等一会儿换清晰
      // ⚠️ 2026-11-07：detail 的 images 只有 full/big/thumb 三档，**没有 thumb_big**
      // （列表卡片才有）。原来这里取 img.thumb_big || img.thumb ⇒ 预取的永远是缩略图，
      // 点开"大图"每次都要现下 —— 用户看到的就是"大图加载中"（第一张常常已经缓存所以能开）。
      // 2026-11-08：优先预取 `preview`（530 档）—— 详情那一排就是用它，点开前也已经缓存。
      prepareImages((result.item.images || []).map((img) => img.preview || img.big || img.full || img.thumb));
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
  closeLightbox();
  // 列表重新渲染出来 ⇒ 哨兵是新的 DOM，得重新盯上（否则从详情返回后就不再自动加载）
  nextTick(() => { watchSentinel(); fillIfNeeded(); });
}

function openLightbox(url, small = "") {
  const big = String(url || small || "");
  if (!big) return;
  lightbox.value = big;
  lightboxFallback.value = String(small || "");
  lightboxSlow.value = false;
  // 先把已经在本地的那张备好（点开立刻有画面），再去要真正的大图
  prepareImages([big, lightboxFallback.value].filter(Boolean));
  // 12 秒还拿不到 ⇒ 明确说"取不回来"，而不是永远转"加载中"
  //（GameBanana 有些截图根本没有大档，也有整个域名抽风的时候）
  setTimeout(() => {
    if (lightbox.value === big && !imageSrc(big) && !imageSrc(lightboxFallback.value)) {
      lightboxSlow.value = true;
    }
  }, 12000);
}

function closeLightbox() {
  lightbox.value = "";
  lightboxFallback.value = "";
  lightboxSlow.value = false;
}

// 灯箱里到底画哪张：大图到位就画大图，否则先用缩略图顶着
const lightboxSrc = computed(() =>
  imageSrc(lightbox.value) || imageSrc(lightboxFallback.value) || "");

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

// 上一轮轮询时"索引任务"是否在跑 —— 用来捕捉"刚跑完"这个时刻
let indexTaskRunning = false;

async function pollScan() {
  try {
    const result = await call("mod_store_task_status");
    if (!result || result.ok === false) return;
    const wasIndexRunning = indexTaskRunning;
    indexTaskRunning = !!result.running && String(result.kind || "") === "index";
    scan.value = {
      running: !!result.running, kind: String(result.kind || ""), message: result.message || "",
      result: result.result || {}, saved: result.scan || {},
    };
    // 索引刚建完 ⇒ **立刻重载列表与分类**。否则后台补好的新索引要等用户手动切一次分类才生效，
    // 观感就是"刚补到的 Mod 还是不出现"（2026-11-07 用户实测）。
    if (wasIndexRunning && !indexTaskRunning && !detail.value) {
      await loadCategories();
      reload();
    }
  } catch (e) { /* 轮询失败忽略 */ }
}

// ── 顶部增量刷新（2026-11-07 用户要求）────────────────────────────────────────
// 「刷新应该增量刷新，改成点开 mod 商城页就刷新最上面，停留 mod 商城页就继续刷新」。
// 只拉第 1~2 页（100 条，约 1 秒）并进索引 —— 新 Mod 立刻出现，老条目一条不动；
// 全量重建仍在程序启动时由 `mod_store_prefetch` 按 TTL 在后台做。
const HEAD_REFRESH_MS = 60 * 1000;
let headTimer = null;
let headReloadPending = false;
const headNote = ref("");          // "顶部新增 N 个 Mod"

let headRetryTimer = null;
let headRetries = 0;            // busy 时的重试次数（全量索引十几秒，最多等 ~30 秒）
async function refreshHead(retried = false) {
  try {
    const result = await call("mod_store_head_refresh", nsfwMode.value);
    if (!result) return;
    if (result.ok === false) {
      // 全量索引正在建（busy）：6 秒后再来一次，而不是干等 60 秒的定时器
      if (result.busy) {
        headRetries += 1;
        if (headRetries <= 5) {
          if (headRetryTimer) clearTimeout(headRetryTimer);
          headRetryTimer = setTimeout(() => refreshHead(true), 6000);
          headNote.value = `索引正在全量刷新，好后自动继续（第 ${headRetries} 次等待）`;
          return;
        }
        headNote.value = "索引正在全量刷新，本次先不做顶部检查（稍后会自动再试）";
        return;
      }
      headRetries = 0;
      // ⚠️ 失败**必须让用户看到**（2026-11-07 用户反馈"根本不会自动刷新"时，
      //   前端把失败全吞了，界面上没有任何痕迹）。
      headNote.value = result.unreachable
        ? "顶部刷新失败：连不上香蕉网（开加速器后可点「刷新索引」重试）"
        : (result.message || "顶部刷新失败，下次自动再试");
      return;
    }
    headRetries = 0;
    if (result.counts) counts.value = result.counts;
    if (result.index) indexMeta.value = result.index;
    if (result.added > 0) {
      headNote.value = `顶部新增 ${result.added} 个 Mod`;
      // 用户就在顶部 ⇒ 顺手重载，新 Mod 直接出现在列表里；滚到很下面时不打断他
      if (window.scrollY < 800 && !detail.value) {
        if (loading.value || loadingMore.value) headReloadPending = true;
        else { await loadCategories(); reload(); }
      }
    } else {
      headNote.value = "";
    }
  } catch (e) { /* 顶部刷新失败不打扰：网络抖一下很常见 */ }
}

// 强制重建索引（自动刷新有 TTL，用户"那个 Mod 不见了"是当场的事，不能等一天）
async function refreshIndex() {
  try {
    const result = await call("mod_store_refresh_index");
    if (!result || result.ok === false) {
      showAlert("索引刷新没能开始", (result && result.message) || "未知原因");
      return;
    }
    // 与后端 `_store_start_task` 的开场白保持一致（自动刷新走同一条状态行）
    scan.value = { ...scan.value, running: true, kind: "index", message: "正在刷新索引…" };
  } catch (e) { /* call 已经弹过错误窗 */ }
}

// ── 左侧分类/角色的数字：优先用索引数出来的（与列表同源），没有才用站点自报的 ──────────
function lowerCounts(source) {
  const out = {};
  for (const [name, value] of Object.entries(source || {})) {
    out[String(name || "").trim().toLowerCase()] = Number(value) || 0;
  }
  return out;
}
const countLookup = computed(() => (counts.value
  ? { roots: lowerCounts(counts.value.roots), characters: lowerCounts(counts.value.characters) }
  : null));
function rowCount(row, kind) {
  const key = String((row && row.name) || "").trim().toLowerCase();
  if (!countLookup.value) return (row && row.count) || 0;
  return countLookup.value[kind][key] || 0;
}
const rootRows = computed(() => (categories.value.roots || []).map((row) => ({ ...row, count: rowCount(row, "roots") })));
const characterRows = computed(() => (categories.value.characters || []).map((row) => ({ ...row, count: rowCount(row, "characters") })));
const catalogTotal = computed(() => (counts.value ? Number(counts.value.total || 0) : 0));
const headAgeText = computed(() => {
  const meta = indexMeta.value || {};
  if (!meta.head_at) return "";
  const seconds = Number(meta.head_age || 0);
  if (seconds < 90) return "顶部已检查（刚刚）";
  if (seconds < 3600) return `顶部已检查（${Math.floor(seconds / 60)} 分钟前）`;
  return `顶部已检查（${Math.floor(seconds / 3600)} 小时前）`;
});

const indexAgeText = computed(() => {
  const seconds = Number((indexMeta.value && indexMeta.value.age) || 0);
  if (!seconds) return "";
  if (seconds < 120) return "刚刚更新";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟前更新`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} 小时前更新`;
  return `${Math.floor(seconds / 86400)} 天前更新`;
});

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
  prefetch();                       // 索引过期/残缺 ⇒ 后台全量重建（启动时已发起，这里只兜底）
  loadCategories();
  // 列表先用本地索引出（毫秒级）；**顶部增量刷新并行起**（2026-11-07 用户：进商城仍不会自动刷新）
  // —— 以前是 `loadMore().finally(refreshHead)`：第一页读完才开始拉最新 100 条，慢，而且
  //    界面上完全看不出"到底刷过没有"（状态行显示的是全量索引的 fetched_at）。
  loadMore();
  refreshHead();
  pollScan();
  timer = setInterval(pollScan, 2000);
  // 停留在商城页：每 60 秒继续增量刷新顶部（切走/在详情页时不做）
  headTimer = setInterval(() => {
    if (!document.hidden && !detail.value) refreshHead();
  }, HEAD_REFRESH_MS);
});
onUnmounted(() => {
  if (timer) clearInterval(timer);
  if (headTimer) { clearInterval(headTimer); headTimer = null; }
  if (observer) { observer.disconnect(); observer = null; }
  if (sentinelObserver) { sentinelObserver.disconnect(); sentinelObserver = null; }
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
               @click="openLightbox(img.full || img.big || img.preview, img.preview || img.thumb)">
            <img v-if="imageSrc(img.preview || img.thumb)" :src="imageSrc(img.preview || img.thumb)"
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
      <Card title="Mod 商城" id="store-browse-box">
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
            {{ scan.running ? (scan.kind === "index" ? "刷新中…" : "扫描中…") : "扫描更新" }}
          </Btn>
          <Btn size="sm" variant="primary" :disabled="!updateCount" @click="updateAll">
            一键更新{{ updateCount ? `（${updateCount}）` : "" }}
          </Btn>
        </div>
        <div v-if="scan.running || scan.message || indexMeta" class="text-xs mt-2"
             style="color: var(--text-muted)">
          {{ scan.message }}
          <span v-if="updateCount">· 有 {{ updateCount }} 个可更新</span>
          <span v-if="missingCount">· {{ missingCount }} 个远端已找不到</span>
          <span v-if="indexed">· 已用本地索引</span>
          <span v-if="headNote" style="color: var(--accent)">· {{ headNote }}</span>
          <!-- 索引状态要说清楚：条数 / 多久以前 / 完整不完整 ——
               「数字对不上」「Mod 消失了」时，用户看这一行就能判断是不是索引的问题 -->
          <template v-if="indexMeta && indexMeta.items">
            <span>· 索引 {{ indexMeta.items }} 个</span>
            <span v-if="!indexMeta.complete" style="color: var(--danger)">
              （不完整 {{ indexMeta.items }}/{{ indexMeta.total }}）
            </span>
            <span v-else-if="indexAgeText">（{{ indexAgeText }}）</span>
            <span v-if="headAgeText" style="color: var(--accent)">· {{ headAgeText }}</span>
          </template>
          <a class="ml-2 cursor-pointer" style="color: var(--accent)"
             :style="scan.running ? 'opacity:.4; pointer-events:none' : ''"
             @click="refreshIndex">刷新索引</a>
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
            <button class="w-full text-left px-2 py-1 rounded flex items-center gap-1"
                    :style="!category && !character
                      ? { background: 'var(--accent-soft)', color: 'var(--accent)' }
                      : { color: 'var(--text-muted)' }"
                    @click="category = 0; character = ''; reload()">
              <span class="truncate flex-1">全部</span>
              <span v-if="catalogTotal" class="text-xs">{{ catalogTotal }}</span>
            </button>
            <button v-for="root in rootRows" :key="root.id"
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
              <button v-for="row in characterRows" :key="row.id"
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
                <!-- 标题限 **2 行**（照 JASM 的 "Title max 2 lines"）：用 -webkit-line-clamp 真截断，
                     而不是只留出两行的高度（那样长标题会溢出到下面的行上） -->
                <div class="text-sm font-medium cursor-pointer" :title="item.name"
                     style="line-height: 1.35; height: 2.7em; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden"
                     @click="openDetail(item)">
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
                </div>
                <!-- 统计行：图标 + 数字（列表接口里没有下载量，只有点赞与浏览，所以不编一个出来） -->
                <div class="flex items-center gap-3 text-xs" style="color: var(--text-muted)">
                  <span class="flex items-center gap-1" :title="`点赞 ${item.likes}`"><Heart :size="12" />{{ item.likes }}</span>
                  <span class="flex items-center gap-1" :title="`浏览 ${item.views}`"><Eye :size="12" />{{ item.views }}</span>
                </div>
                <!-- 卡片上只留「下载」+「详情」（照 JASM：点卡片就是进详情）；
                     **网页链接挪到详情页** —— 那才是决定"要不要去站点看看"的地方，卡片上摆着只会挤 -->
                <div class="flex items-center gap-2 mt-auto">
                  <Btn size="sm" :variant="queued[item.id] ? 'secondary' : 'primary'"
                       :disabled="!!queued[item.id] || !item.has_files" @click="download(item)">
                    {{ queued[item.id] ? "已加入下载" : "下载" }}
                  </Btn>
                  <a class="text-xs cursor-pointer" style="color: var(--accent)" @click="openDetail(item)">详情</a>
                </div>
              </div>
            </div>
          </div>

          <Card v-else-if="!loading">
            <p class="text-sm" style="color: var(--text-muted)">
              没有匹配的 Mod。换个关键词、或者把左边的分类/角色改回「全部」再看看。
            </p>
          </Card>

          <!-- 哨兵：滚到这儿自动加载下一页（用户 2026-10-07：「划到最下面自动往下加载，而不是靠我手点」） -->
          <div v-if="items.length" ref="sentinel"
               class="flex items-center justify-center gap-3" style="min-height: 44px">
            <span v-if="loadingMore" class="text-xs" style="color: var(--text-muted)">正在加载更多…</span>
            <span v-else-if="!hasMore" class="text-xs" style="color: var(--text-muted)">已经到底了（共 {{ items.length }} 个）</span>
            <span v-else class="text-xs" style="color: var(--text-muted)">往下滑自动加载</span>
          </div>
        </div>
      </div>
    </template>

    <!-- 灯箱：点预览图看大图 -->
    <div v-if="lightbox" class="fixed inset-0 z-50 flex items-center justify-center p-6"
         style="background: rgba(0,0,0,.8)" @click="closeLightbox">
      <img v-if="lightboxSrc" :src="lightboxSrc"
           style="max-width: 94vw; max-height: 88vh; object-fit: contain" alt="" />
      <div v-else class="text-sm" style="color: #fff">
        {{ lightboxSlow ? "这张大图取不回来（点任意处关闭）" : "大图加载中…（点任意处关闭）" }}
      </div>
    </div>
  </div>
</template>
