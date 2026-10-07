<script setup>
// 辅助 Mod 页（旧 #tab-assist）：只列辅助/工具类 Mod，不参与换装。
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { call } from "../lib/bridge.js";
import { store, refreshState } from "../store.js";
import { settings, loadSettings } from "../lib/settings.js";
import Card from "../components/ui/Card.vue";
import Switch from "../components/ui/Switch.vue";
import CharacterAssignDialog from "../components/CharacterAssignDialog.vue";
import { showToast, showAlert, showModalDialog } from "../lib/dialog.js";
import { placeMenu } from "../lib/floatingMenu.js";
import { ImageOff } from "lucide-vue-next";
import { Wrench } from "lucide-vue-next";
import Btn from "../components/ui/Btn.vue";

// state 里没有独立的 assist 列表：辅助 Mod 就是 mods 里 kind === "assist" 的那些
const list = computed(() => (store.state.mods || []).filter((m) => m.kind === "assist"));
const status = "把 .zip / .7z / .rar 拖到页面任意处即可导入。";

// ⚠️ 选中状态的真源是 **`config.selected_mods`**（`get_state()` 顶层没有 `selected`），
// 与「服装 Mod」页同一个来源。用户 2026-10-03 反馈「辅助 mod 还是没开关」——
// 辅助 Mod（公共前置资源）同样需要能启用/停用，之前这里只有一行名字。
const selected = computed(
  () => new Set((((store.state.config || {}).selected_mods) || []).map(String)),
);

async function toggleMod(mod) {
  const ids = new Set(selected.value);
  const id = String(mod.id);
  const turningOn = !ids.has(id);
  // ⚠️⚠️ **壁纸类互斥要在界面上当场生效**（2026-10-03 用户报「你壁纸互斥还是没做」）。
  //
  // 背景：我上一轮只改了后端 `activation.resolve_active_set`（staging 时只留一个），
  // 而**界面的开关直接读写 `selected_mods`** ⇒ 两个壁纸的开关都亮着，
  // 用户完全看不出互斥 —— 他要的是"**打开一个，另一个自动关掉**"。
  // 这里在做同一条规则：开启壁纸时**先把同组其它壁纸全部关掉**。
  const isWallpaper = String(mod.group || "") === WRAPPER_GROUP;
  const autoOff = [];
  if (turningOn && isWallpaper) {
    for (const other of wallpapers.value) {
      if (String(other.id) !== id && ids.has(String(other.id))) {
        ids.delete(String(other.id));
        autoOff.push(other.name || String(other.id));
      }
    }
  }
  if (turningOn) ids.add(id);
  else ids.delete(id);
  try {
    // 同「服装 Mod」页：**不调 refreshState()**（全量重拉 get_state 会重新扫描整个库，
    // 点一下要等很久）；直接写回派生来源，界面立刻响应。
    const result = await call("save_config", { selected_mods: Array.from(ids) });
    const applied = (result && result.config && result.config.selected_mods) || Array.from(ids);
    if (store.state) {
      if (!store.state.config || typeof store.state.config !== "object") store.state.config = {};
      store.state.config.selected_mods = applied;
    }
    // 自动关掉的要说一声，否则用户以为是"点一下把别的也弄没了"
    if (autoOff.length) {
      showToast(`壁纸是互斥的，已自动关掉：${autoOff.join("、")}`, "warn");
    }
  } catch (e) { /* call 已弹窗 */ }
}

// ⚠️ **常量必须在使用它的代码之前**（原来它定义在第 70 行，而上面的 toggleMod 里已经用了）
const WRAPPER_GROUP = "加载页与壁纸";   // 与后端 core.WALLPAPER_GROUP 对齐

// 本页所有**壁纸类** Mod —— 互斥规则要用（用户 2026-10-03：「你壁纸互斥还是没做」）
const wallpapers = computed(() => list.value.filter((m) => String(m.group || "") === WRAPPER_GROUP));

const covers = computed(() => store.covers);

// 页内按**子类**分组（用户 2026-10-03：「辅助 Mod 是标签，实际页面卡片中需要在卡片细分
// 加载页和功能类之类的」）—— 「辅助 Mod」只是标签页，同一页里还要按子类分开列，
// 否则壁纸包和"隐藏 UI"混在一起看不出区别。顺序固定：加载页/壁纸 → 界面功能 → 工具 → 其它。
// ⚠️ 顺序 = 页内展示顺序。**「贴图替换类」与壁纸并列**（2026-10-03 用户要求：
//    「那个能不能和皮肤 mod 做区分，算辅助 mod，然后给个其他 group（其他和壁纸那些并列）」）——
//    它放的是"只替换贴图、不换模型"的 Mod，例如把饮料罐贴图换成真实品牌的那种。
const GROUP_ORDER = ["加载页与壁纸", "贴图替换类", "界面功能类", "工具画质类", "其它辅助"];
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
// 与「服装 Mod」页共用 store.covers 缓存，同一次会话只取一次。
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

// 「⋯ 更多」：就地弹出的小菜单（用户准则：⋯ 要就地弹小菜单，不要弹窗）
// ⚠️ 用户 2026-10-03：「还有辅助类 mod 没有更多按钮」—— 服装页早就有，辅助页一直没做，
// 于是"更改归属 / 移到皮肤 / 修复 / 回滚 / 移出库"这些在辅助页全都够不着。
const menu = ref(null);          // { id, name, x, y }
const menuEl = ref(null);        // 菜单根节点：用来**实测**尺寸（不再靠估计高度）
const assignRef = ref(null);     // 归属下拉（复用服装页那个两下拉的组件）

async function openMenu(mod, event) {
  event.stopPropagation();
  const box = event.currentTarget.getBoundingClientRect();
  // 与服装页共用 `lib/floatingMenu.js`：先摆一次，再按**实测高度**修正（同一帧内完成）
  const viewport = { width: window.innerWidth || 1200, height: window.innerHeight || 800 };
  const first = placeMenu(box, { width: 176, height: 0 }, viewport);
  menu.value = { id: String(mod.id), name: mod.name, x: first.x, y: first.y };
  await nextTick();
  const el = menuEl.value;
  if (!el || !menu.value || menu.value.id !== String(mod.id)) return;
  const pos = placeMenu(box, { width: el.offsetWidth || 176, height: el.offsetHeight || 0 }, viewport);
  menu.value = { ...menu.value, x: pos.x, y: pos.y };
}
// 鼠标悬停打开 / 离开收起（2026-10-05 用户要求：「只要鼠标放到更多按钮上就弹出菜单，
// 然后鼠标不在更多按钮或菜单上就收起」）。
// 关键在于**延迟关闭**：菜单与按钮之间有 4px 间隙，鼠标横穿时必然有一瞬间两边都不在，
// 立即关掉会让人根本点不到菜单。给 180ms 宽限，这期间进入按钮或菜单就取消。
let menuCloseTimer = null;
function cancelMenuClose() {
  if (menuCloseTimer) { clearTimeout(menuCloseTimer); menuCloseTimer = null; }
}
function scheduleMenuClose() {
  cancelMenuClose();
  menuCloseTimer = setTimeout(() => { menuCloseTimer = null; closeMenu(); }, 180);
}
function closeMenu() { cancelMenuClose(); menu.value = null; }

async function menuAct(act) {
  const m = menu.value;
  if (!m) return;
  closeMenu();
  try {
    if (act === "character" || act === "assign") {
      // 从菜单里调时 `menu` 只存了 id/name，**必须**拿回完整的 mod（它带 `kind: "assist"`），
      // 否则弹窗会按"服装"打开、辅助的分组下拉根本不出现（2026-10-03 核对）。
      const full = (store.state.mods || []).find((x) => String(x.id) === m.id);
      if (!assignRef.value) {
        await showAlert("选分类的窗口没准备好",
          "界面刚重载过、弹窗还没挂上。稍等一下再点一次就好（这次没有改动任何东西）。");
        return;
      }
      assignRef.value.openFor(full || m);
      return;
    } else if (act === "toSkin") {
      const r = await call("set_mod_kind", m.id, "character");
      if (r && r.ok === false) await showAlert("移动失败", r.message || "未知原因");
      else showToast(`「${m.name}」已移到服装 Mod`, "success");
    } else if (act === "fix") {
      const r = await call("fix_mod", m.id);
      if (r && r.ok === false) await showAlert("修复失败", r.message || "未知原因");
      else showToast(`已修复 ${m.name}`, "success");
    } else if (act === "rollback") {
      const r = await call("rollback_mod", m.id);
      if (r && r.ok === false) await showAlert("回滚失败", r.message || "未知原因");
      else showToast(`已回滚 ${m.name}`, "success");
    } else if (act === "open") {
      const mod = (store.state.mods || []).find((x) => String(x.id) === m.id);
      if (mod && mod.path) await call("open_path_in_explorer", mod.path);
    } else if (act === "delete") {
      const ok = await showModalDialog({
        title: "移出 辅助 Mod？",
        message: `${m.name}\n\n它会从辅助 Mod 列表里移出并留一份备份，之后不再加载。`
          + `\n不会删除你的其它 Mod，也不会动游戏本体。`,
        okText: "移出并备份", cancelText: "保留在库", focusCancel: true,
      });
      if (!ok) return;
      const r = await call("delete_mod", m.id);
      if (r && r.ok === false) await showAlert("移出失败", r.message || "未知原因");
      else showToast(r && r.moved_to ? `已移出库：${r.moved_to}` : "已移出 辅助 Mod", "success");
    } else if (act === "rename") {
      // 输入型弹窗：确认时 resolve 的是**用户输入的那串文本**（不是 true）
      const name = await showModalDialog({
        title: `重命名「${m.name}」`,
        message: `新名字会同时改到库里那个文件夹上（你在资源管理器里看到的也是它）。`
          + `\n已经启用/勾选的状态、预览图和 Mod 内容都不受影响。`,
        okText: "改名", cancelText: "不改了",
        input: { label: "新名字", value: m.name, maxlength: 80 },
      });
      if (!name) return;
      const r = await call("rename_mod", m.id, name);
      if (r && r.ok === false) await showAlert("改名失败", r.message || "未知原因");
      else if (r && r.unchanged) showToast("名字没变", "info");
      else showToast(`已改名为「${(r && r.name) || name}」`, "success");
    } else if (act === "cover") {
      const r = await call("set_mod_cover", m.id);
      if (r && r.ok === false && r.cancelled) return;      // 用户自己关掉了选图框，不算失败
      if (r && r.ok === false) await showAlert("换预览图失败", r.message || "未知原因");
      else {
        // 封面有缓存（`store.covers`，与服装页共用）—— 不清掉的话界面上还是旧图
        if (store.covers) delete store.covers[m.id];
        await loadCover(m.id);
        showToast(`「${m.name}」的预览图已更新`, "success");
      }
    } else if (act === "purge") {
      // 真删、恢复不了 —— 破坏性最强的一档：红字入口 + **手输 ok** 才放行。
      // 后端也会再判一次 `confirm`（界面只是第一道闸，绕不过去第二道）。
      const typed = await showModalDialog({
        title: `彻底删除「${m.name}」？`,
        message: `${m.name}\n\n这会把这个 Mod 的文件夹从库里**直接删掉**：不进回收站、`
          + `**删了就找不回来**。\n已经启用/勾选的话会同时从勾选里去掉；游戏本体和别的 Mod 不受影响。`
          + `\n\n确定要删，请在下面输入 ok。`,
        okText: "彻底删除", cancelText: "不删了", focusCancel: true,
        requireText: "ok",
        input: { label: "输入 ok 确认", placeholder: "ok", maxlength: 8 },
      });
      if (!typed) return;
      const r = await call("purge_mod", m.id, String(typed));
      if (r && r.ok === false) await showAlert("删除失败", r.message || "未知原因");
      else showToast(`已彻底删除「${m.name}」`, "success");
    }
    await call("scan");
    await refreshState();
  } catch (e) {
    // 与服装页同一处理（2026-10-03）：本地异常不许被空 catch 吞掉，否则就是"点了没反应"。
    console.error("[Assist] menuAct 失败", act, e);
    await showAlert("这个操作没能完成", (e && e.message) ? String(e.message) : String(e));
  }
}

async function rescan() { try { await call("scan"); } catch (e) { /* call 已弹窗 */ } }
// ⚠️ 同 SettingsPage：`open_path_in_explorer` 要**真实路径**，不是 "library" 这个标签
//（2026-10-03 修：原先传标签 ⇒ 后台报"路径不存在"、界面什么都不发生）。
async function openLib() {
  try {
    const dirs = await call("log");
    const path = String((dirs && dirs.library) || "");
    if (!path) { showToast("拿不到 Mod 库路径", "danger"); return; }
    const r = await call("open_path_in_explorer", path);
    if (r && r.ok === false) showToast(String(r.message || "打不开 Mod 库"), "danger");
  } catch (e) { /* call 已提示 */ }
}
</script>

<template>
  <div class="space-y-4">
    <div class="flex flex-wrap items-center gap-2">
      <Btn variant="primary" @click="rescan">重新扫描</Btn>
      <Btn @click="openLib">打开 Mod 文件夹</Btn>
      <span class="text-xs" style="color: var(--text-muted)">{{ status }}</span>
    </div>
    <!-- ★ 同「服装 Mod」页：**"还没读到" ≠ "没有"** —— 首屏状态未到之前给加载态，
         别让它显示成"这里还没有辅助 Mod"（用户 2026-10-07 要求：要等就显示加载页面）。 -->
    <Card v-if="!store.ready" title="辅助 Mod">
      <div class="empty-state">
        <component :is="Wrench" :size="30" class="empty-icon" />
        <div class="empty-title">正在读取 Mod 库…</div>
        <div>状态读完后列表会自动出现（首次启动要扫一遍库）。</div>
      </div>
    </Card>
    <Card v-else-if="!list.length" title="辅助 Mod">
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
        （例如湿润效果修复、RabbitFX 这类别人依赖的东西）。它们不参与换装，所以不占「服装 Mod」里的角色分组。
      </p>
      <!-- 按**子类**分组列出（用户 2026-10-03：「辅助 Mod 是标签，实际页面卡片中需要在卡片细分
           加载页和功能类之类的」）。
           **两类用两套卡片形态**（用户明确要求）：壁纸类看着像"一件作品"，用**服装 Mod 那种大封面
           卡片**（120×140，能看出是哪张图）；功能性 Mod（隐藏 UI、去水印这类）没有观赏性，
           保持**紧凑列表行**更好扫。 -->
      <div v-for="grp in assistGroups" :key="grp.name"
           class="rounded-lg border p-3 mb-3 last:mb-0" style="border-color: var(--border)">
        <div class="flex items-center justify-between mb-3">
          <h3 class="font-semibold">{{ grp.name }}</h3>
          <span class="text-xs" style="color: var(--text-muted)">
            {{ grp.mods.length }} 个 Mod · 已启用 {{ grp.mods.filter((m) => selected.has(String(m.id))).length }}
          </span>
        </div>

        <!-- ① 壁纸类：大封面卡片（对齐服装 Mod 的卡片） -->
        <div v-if="grp.name === WRAPPER_GROUP"
             class="grid gap-3" style="grid-template-columns: repeat(auto-fill, minmax(320px, 1fr))">
          <div v-for="m in grp.mods" :key="m.id"
               class="relative flex gap-3 rounded-lg border p-2.5 cursor-pointer transition-colors"
               :style="{ borderColor: selected.has(String(m.id)) ? 'var(--accent)' : 'var(--border)',
                         background: selected.has(String(m.id)) ? 'var(--accent-soft)' : 'var(--surface)' }"
               @click="toggleMod(m)">
            <span class="shrink-0 rounded-md overflow-hidden flex items-center justify-center"
                  style="width: 120px; height: 140px; background: var(--surface-2)">
              <img v-if="covers[m.id]" :src="covers[m.id]" class="w-full h-full object-cover" alt="" />
              <span v-else class="flex flex-col items-center gap-1 empty-icon">
                <ImageOff :size="18" />
              </span>
            </span>
            <span class="min-w-0 flex-1 flex flex-col">
              <span class="text-sm leading-5" style="display: -webkit-box; -webkit-line-clamp: 2;
                    -webkit-box-orient: vertical; overflow: hidden" :title="m.name">{{ m.name }}</span>
              <span class="mt-1.5 text-xs"
                    :style="{ color: selected.has(String(m.id)) ? 'var(--accent)' : 'var(--text-muted)' }">
                {{ selected.has(String(m.id)) ? "已启用" : "未启用" }}
              </span>
              <span class="mt-auto flex items-center justify-between gap-2">
                <Switch :model-value="selected.has(String(m.id))"
                        @update:model-value="() => toggleMod(m)" />
                <button class="btn btn-mini shrink-0" title="更多：分类 / 移到服装 Mod / 修复 / 回滚 / 重命名 / 换预览图 / 移出库 / 彻底删除"
                        @mouseenter="openMenu(m, $event)" @click="openMenu(m, $event)" @mouseleave="scheduleMenuClose()">⋯</button>
              </span>
            </span>
          </div>
        </div>

        <!-- ② 功能性 / 其它：保持紧凑列表行 -->
        <div v-else class="divide-y" style="border-color: var(--border)">
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
            </div>
            <span class="flex items-center gap-2 shrink-0">
              <span class="switch-state">{{ selected.has(String(m.id)) ? "已启用" : "未启用" }}</span>
              <Switch :model-value="selected.has(String(m.id))"
                      @update:model-value="() => toggleMod(m)" />
              <button class="btn btn-mini shrink-0" title="更多：分类 / 移到服装 Mod / 修复 / 回滚 / 重命名 / 换预览图 / 移出库 / 彻底删除"
                      @mouseenter="openMenu(m, $event)" @click="openMenu(m, $event)" @mouseleave="scheduleMenuClose()">⋯</button>
            </span>
          </div>
        </div>
      </div>
    </Card>
    <!-- 2026-10-07：「mod 下载」卡片搬到「下载」页了（用户要求"服装mod、辅助mod 下面的
         mod 下载卡片挪到下载页"）—— 与「服装 Mod」页一致。 -->

    <!-- ⋯ 就地小菜单（浮层，点空白处关闭） -->
    <div v-if="menu" class="fixed inset-0 z-40" @click="closeMenu" @mouseenter="scheduleMenuClose()"></div>
    <div v-if="menu" ref="menuEl" class="fixed z-50 card py-1 shadow-lg"
         style="min-width: 176px; max-height: calc(100vh - 16px); overflow-y: auto"
         :style="{ left: menu.x + 'px', top: menu.y + 'px' }" @mouseenter="cancelMenuClose()" @mouseleave="scheduleMenuClose()">
      <button class="w-full text-left px-3 py-1.5 text-sm" @click="menuAct('character')">更改分类…</button>
      <button class="w-full text-left px-3 py-1.5 text-sm" @click="menuAct('toSkin')">移到「服装 Mod」</button>
      <button class="w-full text-left px-3 py-1.5 text-sm" @click="menuAct('fix')">修复 Mod 文件</button>
      <button class="w-full text-left px-3 py-1.5 text-sm" @click="menuAct('rollback')">回滚</button>
      <button class="w-full text-left px-3 py-1.5 text-sm" @click="menuAct('open')">打开所在目录</button>
      <div style="height:1px;background:var(--border)" class="my-1"></div>
      <button class="w-full text-left px-3 py-1.5 text-sm" @click="menuAct('rename')">重命名…</button>
      <button class="w-full text-left px-3 py-1.5 text-sm" @click="menuAct('cover')">更换预览图…</button>
      <div style="height:1px;background:var(--border)" class="my-1"></div>
      <button class="w-full text-left px-3 py-1.5 text-sm" style="color: var(--danger)"
              @click="menuAct('delete')">移出 辅助 Mod</button>
      <!-- ⚠️ 彻底删除（真删、恢复不了）：红字 + 更重一点的字体，排在最后一个 -->
      <button class="w-full text-left px-3 py-1.5 text-sm"
              style="color: var(--danger); font-weight: 600"
              @click="menuAct('purge')">彻底删除…</button>
    </div>

    <CharacterAssignDialog ref="assignRef" />
  </div>
</template>
