<script setup>
// 服装 Mod页（旧 #tab-library）：三个分区卡片 —— 皮肤 Mod / 下载 Mod / Mod 列表。
// 分组与过滤规则照抄旧 renderMods：按 conflict_group||group 分组，
// 跳过 _deps 分组与 kind=dependency/tool/assist（那些由依赖页 / 辅助页管）。
import { ref, computed, nextTick, onMounted, onUnmounted, watch } from "vue";
import { call } from "../lib/bridge.js";
import { store, refreshState } from "../store.js";
import { loadSettings } from "../lib/settings.js";
import { settings, saveSetting } from "../lib/settings.js";
import { humanSize } from "../lib/util.js";
import { placeMenu } from "../lib/floatingMenu.js";
import Card from "../components/ui/Card.vue";
// ⚠️ 与 CharacterAssignDialog 同一类漏网：模板 `<template #badge><Badge …>` 用到了它，
// 但这里从来没 import（依赖页 / 设置页都有）⇒ 「皮肤 Mod 总开关」那个角标一直渲染不出来。
import Badge from "../components/ui/Badge.vue";
import { Library } from "lucide-vue-next";
import Btn from "../components/ui/Btn.vue";
import Switch from "../components/ui/Switch.vue";
import ConflictDialog from "../components/ConflictDialog.vue";
// ⚠️⚠️ **2026-10-03 真因**：模板里一直写着 `<CharacterAssignDialog ref="assignRef" />`，
// 但这个组件**从来没被 import 过** —— 于是 Vue 把那个标签当成"未知自定义元素"，
// `assignRef.value` 拿到的是一个 **DOM 元素**（`<characterassigndialog>`）而不是组件实例，
// 调 `assignRef.value.openFor(...)` 直接抛
// `TypeError: l.value.openFor is not a function`，又被 menuAct 的空 catch 吞掉
// ⇒ 用户看到的就是「更改所属角色点了没反应、弹窗不出来」。
// 辅助页（AssistPage）第 10 行有 import，所以那边一直正常 —— 这就是"服装页不行、辅助页行"的原因。
import CharacterAssignDialog from "../components/CharacterAssignDialog.vue";
import { Check, ImageOff } from "lucide-vue-next";
import { showAlert, showModalDialog, showToast } from "../lib/dialog.js";
import { setStatus } from "../lib/status.js";

const urls = ref("");
// 封面缓存在 store 里（跨页面存活）—— 见 store.js 的注释
const covers = computed(() => store.covers);
const busy = ref(false);
// 「⋯ 更多」：就地弹出的小菜单（用户准则：⋯ 要就地弹小菜单，不要弹窗）
const menu = ref(null);          // { id, name, x, y }
const chars = ref([]);
const assignRef = ref(null);   // 「更换归属」弹窗（带下拉，见 CharacterAssignDialog）           // 已知角色（用于"更换归属"）
const keyword = ref("");          // 搜索（评审：Mod 一多，没搜索只能靠翻）
// 冲突处理：生成控制器之后检查一次，有冲突就弹「每组一个下拉框」的窗
const conflicts = ref(null);
let timer = null, dlTimer = null;

// ── 香蕉网**网站分类**（皮肤 / UI / 其它）────────────────────────────────────
// 2026-10-04 接入：值来自后端 `mod.site_category` / `mod.site_category_root` ——
// 下载香蕉网链接时解析 ProfilePage 的 `_aCategory` / `_aSuperCategory`（见
// `moddl.gamebanana_category`），写进这个 Mod 自己的 `mod.meta.json`，扫描时带出来。
// ⚠️ **只认实测到的三个根分类**（终末地全量 695 个 Mod 100% 都带分类，根只有这三个）；
// 别的分类 id 原样显示 —— 宁可不翻译，也不能猜错。
const SITE_ROOT_LABELS = { Skins: "皮肤", UI: "UI", "Other/Misc": "其它" };
function siteRootLabel(root) {
  return SITE_ROOT_LABELS[root] || String(root || "");
}

// ⚠️ 选中状态的真源是 **`config.selected_mods`**（后端 `get_state()` 顶层**没有**
// `selected` 这个键）。这里原来读的是 `store.state.selected` ⇒ 永远是空集合，
// 于是"点开关保存成功、界面却纹丝不动"（用户 2026-10-03 反馈「mod 的开关按了没反应」）。
const selected = computed(
  () => new Set((((store.state.config || {}).selected_mods) || []).map(String)),
);
// ── 角色视图（用户 2026-10-07：「第一页展示所有角色（包括头像，可以从官网拉），
//    然后点进去是他自己的 mod」）──────────────────────────────────────────────
// 是一个**开关**（`config.library_character_view`），默认关 = 现在这样。
// 数据来自后端 `character_gallery`：**全部角色**（含一个 Mod 都没有的），
// 头像由后端从官网抓、经本地只读服务直出。
const characterView = computed(() => !!((settings || {}).library_character_view));
const gallery = ref({ characters: [], base: "", other: { count: 0 } });
const character = ref("");        // 点进去的那个角色（空 = 还在角色墙那一层）
let avatarTimer = null;

async function loadGallery() {
  try {
    const result = await call("character_gallery");
    if (!result || result.ok === false) return;
    gallery.value = {
      characters: result.characters || [],
      base: result.base || "",
      other: result.other || { count: 0 },
    };
    pollAvatars(result.pending || []);
  } catch (e) { /* 拿不到就退化成占位块，不是错误 */ }
}

// 头像"后端后台抓 + 这里逐张问"（与商城图片同一套）：官网有快有慢，
// 等整批会让整页空白，所以按 800ms 轮询、最多 40 轮。
function pollAvatars(pending) {
  if (avatarTimer || !(pending || []).length) return;
  let rounds = 0;
  avatarTimer = setInterval(async () => {
    rounds += 1;
    try {
      const result = await call("character_gallery");
      if (result && result.ok !== false) {
        gallery.value = {
          characters: result.characters || [],
          base: result.base || "",
          other: result.other || { count: 0 },
        };
        if (!(result.pending || []).length || rounds > 40) {
          clearInterval(avatarTimer);
          avatarTimer = null;
        }
      }
    } catch (e) { /* 忽略这次，下一轮再来 */ }
  }, 800);
}

// ⚠️ 头像文件名在**每一行的 `c.avatar`** 上（后端直接给本地文件名），
//    不是 `result.files` 那个映射 —— 2026-10-07 我错读成后者，表现就是"角色墙一个头像都没有"。
function avatarSrc(item) {
  return item && item.avatar && gallery.value.base ? `${gallery.value.base}/${item.avatar}` : "";
}

function openCharacter(name) {
  character.value = name;
}

// 「其他」= 认不出角色归属的那些（用户 2026-10-07：「不是说单列一个其他角色吗」）。
// 它和其他角色**平级**地摆在角色墙里，点进去就能看到它们 —— 而不是只留一句说明文字。
const OTHER_NAME = "其他";
const otherIds = computed(
  () => new Set(((gallery.value.other || {}).mods || []).map((m) => String(m.id))),
);

// 统一卡片的标题与角标（用户 2026-10-07：「全部合成一个卡片」）——
// 三态共用一个 Card，标题跟着状态走，不再各开一张卡。
const listTitle = computed(() => {
  if (!characterView.value) return "Mod 列表";
  return character.value ? `${character.value} 的 Mod` : "角色";
});
const listBadge = computed(() => {
  if (!characterView.value) return "按角色分组显示";
  if (character.value === OTHER_NAME) {
    return `${((gallery.value.other || {}).count) || 0} 个`;
  }
  if (character.value) {
    const row = gallery.value.characters.find((c) => c.name === character.value) || {};
    return `${row.count || 0} 个`;
  }
  return `共 ${gallery.value.characters.length} 位 · 点进去看他的 Mod`;
});

function backToCharacters() {
  character.value = "";
  loadGallery();          // 回来时顺手再拉一次，把期间下好的头像补上
}

// ⚠️ **切换开关时必须自己去取数据**（2026-10-07 用户实测："刚进去都要正在读取角色表…"）：
//    原先把"加载"挂在旧的 toggleLayout 上，改用 saveSetting 直接写开关之后就没人调它了 ——
//    表现是开关打开了、角色表却一直不出现（那句"正在读取角色表…"是**卡住**，不是真在同步）。
async function setCharacterView(next) {
  await saveSetting("library_character_view", !!next);
  character.value = "";
  if (next) loadGallery();
}

// 兜底：无论是点开关、还是从别处改了配置（设置页/同步），只要它是开的就去取
watch(characterView, (on) => {
  if (on && !gallery.value.characters.length) loadGallery();
});

// 搜索是**全局**的（用户 2026-10-07：「搜索框搜索了自动切回 mod 列表」）：
// 一输入关键字就退出角色详情 —— 否则搜出来的东西会被"某个角色"的过滤条件吃掉，
// 表现得像"搜了没结果"。
watch(keyword, (text) => {
  if (String(text || "").trim()) character.value = "";
});

const groups = computed(() => {
  const g = {};
  const kw = keyword.value.trim().toLowerCase();
  for (const mod of store.state.mods || []) {
    if (kw && !String(mod.name || "").toLowerCase().includes(kw)
        && !String(mod.conflict_group || mod.group || "").toLowerCase().includes(kw)) continue;
    const key = String(mod.conflict_group || mod.group || "");
    if (key === "_deps" || mod.kind === "dependency" || mod.kind === "tool") continue;
    if (mod.kind === "assist") continue;
    // 角色墙选中的那个角色 ⇒ 这张列表只留他的（"点进去是他自己的 mod"）；
    // 选「其他」时按**后端给的 id 名单**匹配 —— 因为那些 Mod 的分组名五花八门，
    // 不能拿"其他"去比分组名。
    if (character.value === OTHER_NAME) {
      if (!otherIds.value.has(String(mod.id))) continue;
    } else if (character.value
               && String(mod.conflict_group || mod.group || "") !== character.value) {
      continue;
    }
    const name = mod.conflict_group || mod.group || "未分类";
    (g[name] ||= []).push(mod);
  }
  return Object.keys(g).sort((a, b) => String(a).localeCompare(String(b), "zh-Hans-CN"))
    .map((name) => ({
      name,
      mods: g[name],
      enabled: g[name].filter((m) => selected.value.has(String(m.id))).length,
    }));
});

async function loadCover(id) {
  if (covers.value[id]) return;
  // demo 模式：封面来自快照（file:// 下前端读不到本地图片，快照里已内联成 data URI）
  const preset = (store.demoCovers || {})[id];
  if (preset) { store.covers[id] = preset; return; }
  try {
    const r = await call("get_mod_cover", id);
    // ⚠️ 后端的字段名是 **data_uri**（其余几个是历史写法，留着兜底）——
    // 迁移时我写成了 `r.data`，导致封面一直取不到、列表里全是"无封面"占位。
    const uri = r && (r.data_uri || r.data || r.uri || r.image || r.base64);
    if (r && r.ok && uri) store.covers[id] = uri;
  } catch (e) { /* 没有封面很正常 */ }
}

async function toggleMod(mod) {
  const ids = new Set(selected.value);
  const id = String(mod.id);
  if (ids.has(id)) ids.delete(id);
  else {
    ids.add(id);
    // 同角色互斥：除非用户在设置里明确关掉了互斥
    if (!settings.allow_same_character_mods) {
      for (const other of store.state.mods || []) {
        if (String(other.id) !== id && (other.conflict_group || other.group) &&
            (other.conflict_group || other.group) === (mod.conflict_group || mod.group)) {
          ids.delete(String(other.id));
        }
      }
    }
  }
  try {
    // ⚠️ 这里**不要**调 `refreshState()`：那会全量重拉 `get_state()`（重新扫描整个 服装 Mod），
    //    每次点开关都要等它跑完 —— 用户 2026-10-03 反馈「mod 的按钮反应怎么这么慢，
    //    其他开关都没这个问题」（设置页/启动页的开关只发一个键，所以快）。
    //    `selected` 是从 `store.state.config.selected_mods` 派生的，把新值写回去界面就立刻响应。
    const result = await call("save_config", { selected_mods: Array.from(ids) });
    const applied = (result && result.config && result.config.selected_mods) || Array.from(ids);
    if (store.state) {
      if (!store.state.config || typeof store.state.config !== "object") store.state.config = {};
      store.state.config.selected_mods = applied;
    }
  } catch (e) { /* call 已弹窗 */ }
}

const menuEl = ref(null);        // 菜单根节点：用来**实测**尺寸（不再靠估计高度）

async function openMenu(mod, event) {
  event.stopPropagation();
  const box = event.currentTarget.getBoundingClientRect();
  // ⚠️ 坐标必须在**脚本**里算好：Vue 模板作用域拿不到 window（写了会直接报错）。
  const viewport = { width: window.innerWidth || 1200, height: window.innerHeight || 800 };
  // 第一遍还不知道菜单多高（传 0 = 只夹横向），`nextTick` 之后按**实测高度**再摆一次；
  // 两次都在同一帧内完成，用户看不到跳动。定位规则见 `lib/floatingMenu.js`。
  const first = placeMenu(box, { width: 176, height: 0 }, viewport);
  // ⚠️ 把 `kind` 一起存下来 —— 模板里判断「移到辅助/服装」要用它（模板作用域拿不到 mod）
  menu.value = {
    id: String(mod.id), name: mod.name, kind: String(mod.kind || ""), x: first.x, y: first.y,
    // ⚠️ C4：回滚是否可用（后端按"有没有修复备份"算）
    can_rollback: mod.can_rollback !== false,
  };
  await nextTick();
  const el = menuEl.value;
  if (!el || !menu.value || menu.value.id !== String(mod.id)) return;
  const pos = placeMenu(
    box,
    { width: el.offsetWidth || 176, height: el.offsetHeight || 0 },
    viewport,
  );
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

// ⚠️ 2026-10-03 三修（用户：「Mod 的更多中点击更改角色归属无反应」）—— 三个真 bug 叠在一起：
//   ① 卡片上那个黄色标签直接调 `menuAct('assign', mod)`，而函数**只看 `menu.value`**；
//      那时浮层根本没打开 ⇒ `if (!m) return` 当场返回 ⇒ 点了完全没反应。
//      现在第二个参数优先（从 ⋯ 菜单里调用仍然走 `menu.value`）。
//   ② `'assign'` 这个动作名**一个分支都没有**（下面只写了 `'character'`）⇒ 就算 m 拿得到，
//      也会掉到函数末尾什么都不做。现在两个名字走同一条路。
//   ③ 这里的 catch 原来是空的（注释说"call() 已经弹过窗"），但**本地异常**（典型：弹窗组件
//      的 ref 还没挂上时的 `TypeError`）会被静默吞掉 —— 用户看到的同样是"点了没反应"。
//      现在控制台留痕，并在界面上说一句。
async function menuAct(act, mod = null) {
  const m = mod || menu.value;
  if (!m) return;
  closeMenu();
  try {
    if (act === "fix") {
      // ⚠️ **C5：修之前先查工具在不在**（2026-10-03 补回归）。
      // 0.9.5（`app.js:808-817`）会先 `modfix_status`，工具缺失时讲清"放 assets\\modfix
      // 或 runtime\\modfix"；换代后 grep `modfix_status` **0 命中** ⇒ 用户点了"修复"，
      // 失败也只看到一句错误码，不知道该往哪放工具。
      // ⚠️ 按用户准则：**不能因为"当前没就位"就把按钮禁用**（工具随包、点下去会自动展开），
      // 所以只在**确实不可用**（`usable === false`：随包与 runtime 都没有）时才说明。
      // 注意后端返回的是 `{ tool: {...} }`。
      try {
        const st = await call("modfix_status");
        const tool = (st && st.tool) || {};
        if (tool.usable === false) {
          await showModalDialog({
            title: "修复工具不在",
            message: [
              "这个修复工具是随包分发的，但当前两份都没有：",
              "· assets\\modfix\\（随包那份）",
              "· runtime\\modfix\\（运行时那份）",
              "",
              "从 Release 下载的话，重新展开一次 assets-bundle.zip 即可。",
            ].join("\n"),
            okText: "知道了", showCancel: false,
          });
          return;
        }
      } catch (e) { /* 查不到就直接试，别因为检查本身挡住 */ }
      const r = await call("fix_mod", m.id);
      if (r && r.ok === false) await showAlert("修复失败", r.message || "未知原因");
      else showToast(`已修复 ${m.name}`, "success");
    } else if (act === "rollback") {
      const r = await call("rollback_mod", m.id);
      if (r && r.ok === false) await showAlert("回滚失败", r.message || "未知原因");
      else showToast(`已回滚 ${m.name}`, "success");
    } else if (act === "delete") {
      // 破坏性动作：默认聚焦安全项、按钮文字自解释（用户准则）
      const ok = await showModalDialog({
        // 标题直接说动作（评审：原标题"确认"、以及把 runtime\backups\mod-trash 这种内部路径
        // 摆给用户，都会让人以为要删到系统目录里去）
        title: "移出 服装 Mod？",
        message: `${m.name}\n\n它会从 服装 Mod列表里移出并留一份备份，之后不再加载。`
          + `\n不会删除你的其它 Mod，也不会动游戏本体。`,
        okText: "移出并备份", cancelText: "保留在库", focusCancel: true,
      });
      if (!ok) return;
      const r = await call("delete_mod", m.id);
      if (r && r.ok === false) await showAlert("移出失败", r.message || "未知原因");
      else showToast(r && r.moved_to ? `已移出库：${r.moved_to}` : "已移出 服装 Mod", "success");
    } else if (act === "rename") {
      // 输入型弹窗：确认时 resolve 的是**用户输入的那串文本**（不是 true）
      const name = await showModalDialog({
        title: `重命名「${m.name}」`,
        message: `新名字会同时改到库里那个文件夹上（你在资源管理器里看到的也是它）。`
          + `\n已经勾选的状态、预览图和 Mod 内容都不受影响。`,
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
        // 封面有缓存（`store.covers`）—— 不清掉的话界面上还是旧图，看着像"没换成功"
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
          + `**删了就找不回来**。\n已经勾选的话会同时从勾选里去掉；游戏本体和别的 Mod 不受影响。`
          + `\n\n确定要删，请在下面输入 ok。`,
        okText: "彻底删除", cancelText: "不删了", focusCancel: true,
        requireText: "ok",
        input: { label: "输入 ok 确认", placeholder: "ok", maxlength: 8 },
      });
      if (!typed) return;
      const r = await call("purge_mod", m.id, String(typed));
      if (r && r.ok === false) await showAlert("删除失败", r.message || "未知原因");
      else showToast(`已彻底删除「${m.name}」`, "success");
    } else if (act === "character" || act === "assign") {
      if (!chars.value.length) {
        const r = await call("known_characters");
        // ⚠️ 后端 `known_characters()` 返回的是**纯数组 list[str]**（不是 {characters:[...]}），
        // 原先按对象读 ⇒ 永远拿到空数组 ⇒「更改所属角色」的下拉里一个角色都没有（2026-10-03 修）。
        chars.value = Array.isArray(r) ? r : ((r && (r.characters || r.items)) || []);
      }
      // ⚠️ 以前这里用 showModalDialog —— 它**只返回 true/false、没有输入控件**，
      // 于是文案写着"输入角色名（留空 = 保持未分类）"却没法输入，
      // `pick === true ? "" : String(pick)` **永远把归属设成空**。
      // 改成真正的下拉选择器（CharacterAssignDialog）。
      if (!assignRef.value) {
        await showAlert("选角色的窗口没准备好",
          "界面刚重载过、弹窗还没挂上。稍等一下再点一次就好（这次没有改动任何东西）。");
        return;
      }
      assignRef.value.openFor(m);
      return;
    } else if (act === "toAssist" || act === "toSkin") {
      // 判据从 `menu.kind` 来（模板只传 act）
      // 用户 2026-10-03：「一些被误识别的 mod 可以在辅助和皮肤之间移动」——
      // 自动判据只能猜，猜错了要让用户一句话改过来（写进该 Mod 的 mod.meta.json）。
      const want = act === "toAssist" ? "assist" : "character";
      const r = await call("set_mod_kind", m.id, want);
      if (r && r.ok === false) await showAlert("移动失败", r.message || "未知原因");
      else showToast(want === "assist" ? `「${m.name}」已移到辅助 Mod` : `「${m.name}」已移到皮肤 Mod`, "success");
    } else if (act === "open") {
      const mod = (store.state.mods || []).find((x) => String(x.id) === m.id);
      if (mod && mod.path) await call("open_path_in_explorer", mod.path);
    }
    await refreshState();
    loadSettings();
  } catch (e) {
    // 不许静默吞（2026-10-03）：本地异常（TypeError 之类）不是 call() 弹的那种窗，
    // 空 catch 会让用户看到"点了没反应"、我们这边也查不到任何线索。
    console.error("[ModLibrary] menuAct 失败", act, e);
    await showAlert("这个操作没能完成", (e && e.message) ? String(e.message) : String(e));
  }
}

async function scan() { busy.value = true; try { await call("scan"); await refreshState();
    loadSettings(); } catch (e) {} finally { busy.value = false; } }
async function prepare() {
  busy.value = true;
  try {
    // ⚠️⚠️ **B11：被后端拒绝时不能静默**（2026-10-03 补回归）。
    // staging 与 Mod 库重叠时后端**拒绝执行**并返回
    // `{ok: false, blocked: "library_overlap", message: ...}`（保护用户的 Mod 库 ——
    // 用户 2026-10-01 定下的硬规则）。0.9.5 拿到这个结构会弹「保护 Mod 库」说明框；
    // 换代后这里**忽略返回值**、只在没冲突时给 toast ⇒ 点了没反应也不知道为什么。
    const prep = await call("prepare");
    if (prep && prep.ok === false) {
      if (prep.blocked === "library_overlap") {
        await showModalDialog({
          title: "为了保护你的 Mod 库，已停止生成",
          message: [
            prep.message || "暂存目录和 Mod 库重叠了。",
            "",
            "这个检查是故意的：暂存目录若落在 Mod 库里面，每次生成控制器都会清空暂存目录，"
              + "等于把你库里的 Mod 删掉。",
            "",
            "去「设置 → 工作区与 Mod 库」看一眼这两个路径，把它们分开就好。",
          ].join("\n"),
          okText: "知道了", showCancel: false,
        });
      } else {
        await showAlert("生成控制器失败", prep.message || "未知原因");
      }
      return;
    }
    // prepare 会刷新 runtime\_state\mod_conflicts.json，紧接着读一次结论
    const info = await call("conflict_groups");
    const groups = (info && info.groups) || [];
    if (groups.length) conflicts.value = groups;
    else showToast("生成完毕，没有发现资源冲突。", "success");
  } catch (e) { /* call 已弹窗 */ } finally { busy.value = false; }
}

async function resolveConflicts(keep) {
  conflicts.value = null;
  try {
    const r = await call("resolve_mod_conflicts", keep);
    if (r && r.ok === false) await showAlert("处理失败", r.message || "未知原因");
    else showToast((r && r.message) || "已处理冲突", "success");
    await refreshState();
    loadSettings();
  } catch (e) { /* call 已弹窗 */ }
}
// ⚠️ **「一键修复所有 Mod」补齐确认 / 进度 / 结果**（2026-10-03 修回归）。
// 0.9.5 是：确认框（讲清会备份、可回滚、跳过已修的）→ `fix_all_mods(true)`
// → `setInterval` 轮询 `fix_all_progress`，把「修复中 3/29：名字」写进状态行
// → 完成后列出失败项。
// 换代到 Vue 之后只剩一句 `await call("fix_all_mods")`：**没有确认、没有进度、没有结果**
//（后端 `fix_all_progress` 前端零调用）—— 这是个要跑 29 个 Mod 的后台长任务，
// 全程零反馈会让人以为卡死了。这里按 0.9.5 的语义补回来，展示沿用现有 Btn/Card/Toast。
const fixRunning = ref(false);
const fixText = ref("");
let fixTimer = null;

function stopFixPoll() {
  if (fixTimer) { clearInterval(fixTimer); fixTimer = null; }
}

async function fixAll() {
  const ok = await showModalDialog({
    title: "一键修复所有 Mod",
    message: [
      "会逐个修复「服装 Mod」里还没修过的那些。",
      "",
      "• 每个 Mod 修复前都会**备份**，可随时用 ⋯→「回滚」还原",
      "• 已经修过的会跳过",
      "• 过程中界面不会卡（后台跑，这里显示进度）",
    ].join("\n"),
    okText: "开始修复", cancelText: "先不修复",
  });
  if (!ok) return;

  const started = await call("fix_all_mods", true);
  if (started && started.ok === false) {
    showToast(String(started.message || "启动修复失败"), "danger");
    return;
  }
  if (started && started.already) {
    showToast("已经有一轮修复在进行中", "info");
  } else {
    // ⚠️ 后端 `fix_all_mods()` 返回的是 `{ok, started, total, message}`（2026-10-04 修）：
    // 原来读 `started.count` ⇒ 恒 undefined ⇒ 数量永远不显示，提示退化成"已开始修复 Mod…"。
    showToast(
      `已开始修复${started && started.total ? ` ${started.total} 个` : ""} Mod…`,
      "success",
    );
  }

  fixRunning.value = true;
  fixText.value = "修复中…";
  stopFixPoll();
  fixTimer = setInterval(async () => {
    let p = null;
    try { p = await call("fix_all_progress"); } catch (e) { /* 忽略单次失败 */ }
    if (!p) return;
    const cur = Number(p.current || 0);
    const total = Number(p.total || 0);
    if (p.running) {
      fixText.value = total
        ? `修复中 ${cur}/${total}：${p.name || ""}`
        : `修复中：${p.name || ""}`;
      return;
    }
    // 跑完了
    stopFixPoll();
    fixRunning.value = false;
    fixText.value = "";
    const results = Array.isArray(p.results) ? p.results : [];
    const failed = results.filter((r) => r && r.ok === false);
    await scan();
    await refreshState();
    if (failed.length) {
      await showModalDialog({
        title: `修复完成（${results.length - failed.length} 成功 / ${failed.length} 失败）`,
        message: "这几项没修好：\n\n" +
          failed.slice(0, 12).map((r) => `• ${r.name || r.id || "?"}：${r.message || "未知原因"}`).join("\n") +
          (failed.length > 12 ? `\n…另有 ${failed.length - 12} 项` : ""),
        okText: "知道了",
      });
    } else {
      showToast(`修复完成，共 ${results.length} 个 Mod`, "success");
    }
  }, 800);
}



// ⚠️ 2026-10-04 删掉 `speedText()`：它读的是一个**本文件从未定义**的 `dl.value`，
// 完全是历史上那次 `modDownloadFinished is not defined` 的同型残留 —— 现在模板没引用它
// 所以还没炸，但只要有人把它接回模板（Mod 下载速度显示本来就需要它），页面立刻 ReferenceError。
// 真要做下载速度显示，数据源应当是 `call("mod_download_progress")` 的返回值。

// 封面**串行**加载：后端每张都要 PIL 打开+缩放+JPEG 编码（CPU 密集），
// 一次性并发十几张会把界面拖卡、用户感觉"图片加载很慢"（2026-10-03 反馈）。
// 这里一张一张来，并且让出一帧，界面先出来、封面随后补上。
let coverQueue = [];
let coverRunning = false;

async function pumpCovers() {
  if (coverRunning) return;
  coverRunning = true;
  try {
    while (coverQueue.length) {
      const id = coverQueue.shift();
      if (!store.covers[id]) await loadCover(id);
      await new Promise((r) => setTimeout(r, 0));   // 让出主线程，界面不被卡住
    }
  } finally {
    coverRunning = false;
  }
}

function queueCovers(mods) {
  const ids = (mods || []).map((m) => m.id).filter((id) => id && !store.covers[id]);
  if (!ids.length) return;
  coverQueue = ids;
  pumpCovers();
}

// ⚠️ **C2：Esc 关闭 ⋯ 菜单**（0.9.5 的 `app.js:805` 有，换代时丢了）。
// ⚠️ 回调必须**具名**才能解绑（2026-10-04 修）：原来传的是匿名箭头函数，`onUnmounted`
// 里既没解绑、也没法解绑 ⇒ `<component :is>` 每次切页都会重建本组件，监听器一次次累积
// （闭包还一直持有已卸载组件的 `menu` ref），页签来回切 N 次就挂上 N 个 Esc 处理器。
function onEscapeKey(e) {
  if (e.key === "Escape" && menu.value) closeMenu();
}
onMounted(() => {
  window.addEventListener("keydown", onEscapeKey);
});

onMounted(async () => {
  await refreshState().catch(() => {});
  queueCovers(store.state.mods);
  // 上次退出时开着角色视图 ⇒ 进来就把角色墙数据拉上（头像随包，本地就有）
  if (characterView.value) loadGallery();
});
onUnmounted(() => {
  window.removeEventListener("keydown", onEscapeKey);
  if (timer) clearInterval(timer);
  if (avatarTimer) { clearInterval(avatarTimer); avatarTimer = null; }
  stopFixPoll();
  coverQueue = [];
});

// ⚠️ Vue 里**子组件的 onMounted 先于父组件执行**，而 demo 模式的封面是父组件（App.vue）
// 在自己的 onMounted 里才灌进 store 的 —— 那时封面还没到，一开始全是占位图。
// 这里监听它，数据到位后把封面补齐。
watch(() => store.demoCovers, (val) => {
  if (!val) return;
  queueCovers(store.state.mods);
}, { immediate: true });
</script>

<template>
  <div class="space-y-4">
    <!-- 两个开关放这里（紧邻 Mod 列表之上）：
         上一版把它们挪到了页面最底部（理由是"设一次就不动"），结果用户找不到、
         以为开关没了 —— 可见"总开关"这类东西必须待在它管的那块内容旁边。 -->
    <Card title="皮肤 Mod">
      <template #badge><Badge tone="muted">总开关</Badge></template>
      <div class="space-y-0.5">
        <div class="switch-row" @click="saveSetting('efmi_injection', !settings.efmi_injection)">
          <span class="min-w-0">
            <span class="text-sm font-medium">开启皮肤 Mod</span>
            <span class="block text-xs mt-0.5" style="color: var(--text-muted)">
              关掉后一个皮肤都不加载（Mods 目录会被清空，随时可开回来）。
              ⚠️ 这不是停掉 EFMI 注入 —— 实测那样终末地会直接拉不起来。
            </span>
          </span>
          <span class="flex items-center gap-2 shrink-0">
            <span class="switch-state">{{ settings.efmi_injection ? "已开启" : "已关闭" }}</span>
            <Switch :model-value="!!settings.efmi_injection" @update:model-value="(v) => saveSetting('efmi_injection', v)" />
          </span>
        </div>
        <div class="switch-row" @click="saveSetting('allow_same_character_mods', !settings.allow_same_character_mods)">
          <span class="min-w-0">
            <span class="text-sm font-medium">强行关闭角色 Mod 互斥</span>
            <span class="block text-xs mt-0.5" style="color: var(--text-muted)">
              开启后勾选一个 Mod 不会再把同角色的其它 Mod 自动取消。<b>默认关闭</b> ——
              同角色两个 Mod 同时生效常常会让游戏崩，只在确认它们改的不是同一批资源时再打开。
            </span>
          </span>
          <span class="flex items-center gap-2 shrink-0">
            <span class="switch-state">{{ settings.allow_same_character_mods ? "已开启" : "已关闭" }}</span>
            <Switch :model-value="!!settings.allow_same_character_mods" @update:model-value="(v) => saveSetting('allow_same_character_mods', v)" />
          </span>
        </div>
      </div>
    </Card>

    <!-- 「角色视图」开关**单独一张卡片**（用户 2026-10-07：「开关单独卡片，其他部分共用一张」）。
         刚才是塞在「皮肤 Mod」卡里的，而那张卡管的是 EFMI / 互斥那些注入开关，
         Mod 库的显示方式跟它们不是一回事，混在一起反而找不到。 -->
    <Card title="Mod 库视图">
      <div class="switch-row" @click="setCharacterView(!characterView)">
        <span class="min-w-0">
          <span class="text-sm font-medium">角色视图</span>
          <span class="block text-xs mt-0.5" style="color: var(--text-muted)">
            开启后：Mod 库先按<b>角色</b>排（头像 + 各自的 Mod 数），<b>点进去才是该角色的 Mod</b>。
            左边小图是列表的样子，右边是角色视图的样子。<b>默认关闭</b> —— 关着就是现在这样。
          </span>
        </span>
        <span class="flex items-center gap-2 shrink-0">
          <span class="switch-state">{{ characterView ? "已开启" : "已关闭" }}</span>
          <!-- 图示滑块（用户 2026-10-07：「做成滑块里是样式展示 —— 划到左边是一个框然后一个
               横杠，到右边是几个框」）：左=列表（一个框 + 一根横杠）、右=角色视图（四个小框），
               当前那侧用主题色高亮。 -->
          <span class="flex items-center gap-1.5 px-1.5 py-1 rounded-full"
                :style="{ background: 'var(--surface-2)', border: '1px solid var(--border)' }">
            <span class="flex items-center justify-center"
                  :style="{ width: '24px', height: '18px', gap: '2px', borderRadius: '4px',
                            border: characterView ? '1px solid var(--border)' : '1px solid var(--accent)',
                            background: characterView ? 'transparent' : 'var(--accent-soft)' }">
              <span :style="{ width: '9px', height: '8px', borderRadius: '2px',
                              background: characterView ? 'var(--text-muted)' : 'var(--accent)' }"></span>
              <span :style="{ width: '6px', height: '2px', borderRadius: '1px',
                              background: characterView ? 'var(--text-muted)' : 'var(--accent)' }"></span>
            </span>
            <span class="grid"
                  :style="{ gridTemplateColumns: 'repeat(2, 1fr)', gap: '2px',
                            width: '24px', height: '18px', padding: '2px', borderRadius: '4px',
                            border: characterView ? '1px solid var(--accent)' : '1px solid var(--border)',
                            background: characterView ? 'var(--accent-soft)' : 'transparent' }">
              <span v-for="n in 4" :key="n"
                    :style="{ borderRadius: '1px',
                              background: characterView ? 'var(--accent)' : 'var(--text-muted)' }"></span>
            </span>
          </span>
        </span>
      </div>
    </Card>

    <!-- ══════════ Mod 列表（**只有一个卡片**）══════════
         用户 2026-10-07：「你不要返回角色列表单开一个卡片，**全部合成一个卡片**，
         还有**生成控制器那些不要放在角色里面，放在角色列表那里**」——
         于是工具栏落在卡片顶部（属于整个 Mod 区域、不属于某个角色，两层都看得到），
         内容按"角色墙 / 某个角色的 Mod / 全量列表"三态切换，不再各占一张卡。 -->
    <Card :title="listTitle">
      <template #badge>
        <span class="text-xs" style="color: var(--text-muted)">{{ listBadge }}</span>
      </template>

      <!-- 工具栏：生成控制器那些放这儿（角色列表那一层） -->
      <div class="flex flex-wrap items-center gap-2">
        <Btn variant="primary" @click="prepare" :disabled="busy">生成控制器</Btn>
        <Btn @click="scan" :disabled="busy">重新扫描</Btn>
        <!-- ⚠️ **C3：库状态行**（2026-10-03 补回归）。0.9.5 有一行
             「已发现 N 个 Mod，按角色分组显示」（`app.js:643`），换代后丢了 ——
             用户不知道自己库里到底有多少个、也没法判断扫描有没有生效。 -->
        <span class="text-xs self-center" style="color: var(--text-muted)">
          <!-- 状态没到之前**不要**显示"已发现 0 个"——那会被读成"库是空的" -->
          <template v-if="store.ready">已发现 {{ store.state.mods ? store.state.mods.length : 0 }} 个 Mod，按角色分组显示</template>
          <template v-else>正在读取 Mod 库…</template>
        </span>
        <Btn @click="fixAll">一键修复所有 Mod</Btn>
        <span class="ml-auto flex items-center gap-2">
          <input v-model="keyword" class="field" style="width: 220px" placeholder="搜索 Mod / 角色…" />
        </span>
      </div>

      <!-- ① 角色墙（角色视图 + 还没点进去）-->
      <div v-if="characterView && !character" class="mt-3">
      <!-- 角色表和头像都**随包**（用户要求"直接随包"），所以这里正常是**一闪而过**。
           不再写"首次会从官网同步"——那会让人以为要联网等，而实际上本地就有。 -->
      <div v-if="!gallery.characters.length" class="text-sm" style="color: var(--text-muted)">
        正在读取角色表…
      </div>
      <div v-else class="grid gap-3"
           style="grid-template-columns: repeat(auto-fill, minmax(110px, 1fr))">
        <button v-for="c in gallery.characters" :key="c.name"
                class="rounded-lg border p-2 flex flex-col items-center gap-1.5"
                style="border-color: var(--border)"
                :title="`${c.name}${c.codename ? ' · ' + c.codename : ''} · ${c.count} 个 Mod`"
                @click="openCharacter(c.name)">
          <img v-if="avatarSrc(c)" :src="avatarSrc(c)"
               class="rounded-full object-cover" style="width: 56px; height: 56px" alt="" />
          <span v-else class="rounded-full flex items-center justify-center text-lg"
                style="width: 56px; height: 56px; background: var(--surface-2); color: var(--accent)">
            {{ (c.name || "?").slice(0, 1) }}
          </span>
          <span class="text-xs truncate w-full text-center">{{ c.name }}</span>
          <span class="text-xs" style="color: var(--text-muted)">{{ c.count }} 个</span>
        </button>
        <!-- 「其他」单列（用户 2026-10-07：「不是说单列一个其他角色吗」）：
             认不出角色归属的 Mod 全都挂这儿，点进去就是它们 —— **不硬塞给任何角色**
             （硬塞会让同角色互斥误判，也可能把别人的皮肤算到某个角色头上）。 -->
        <button v-if="gallery.other && gallery.other.count"
                class="rounded-lg border p-2 flex flex-col items-center gap-1.5"
                style="border-color: var(--border)"
                :title="`没认出角色归属的 ${gallery.other.count} 个 Mod —— 点进去看，之后可以逐个指定`"
                @click="openCharacter(OTHER_NAME)">
          <span class="rounded-full flex items-center justify-center text-xl"
                style="width: 56px; height: 56px; background: var(--surface-2); color: var(--text-muted)">?</span>
          <span class="text-xs truncate w-full text-center">其他</span>
          <span class="text-xs" style="color: var(--text-muted)">{{ gallery.other.count }} 个</span>
        </button>
      </div>
      </div>

      <!-- ② 点进去之后：一条明确的回头路 + 这个角色的 Mod（**都在同一个卡片里**）-->
      <div v-if="characterView && character" class="flex items-center gap-2 flex-wrap mt-3">
        <Btn @click="backToCharacters">← 返回角色列表</Btn>
        <span class="text-xs" style="color: var(--text-muted)">
          下面是 {{ character }} 的 Mod，操作（开关、⋯ 菜单、冲突提示）与列表视图完全一样
        </span>
      </div>

      <!-- ③ 全量列表 / 某个角色的 Mod（内容按过滤条件走，渲染完全复用）-->
      <div v-if="!characterView || character">
      <!-- ★ **"还没读到" ≠ "库里没有"**（用户 2026-10-07：「我要一进去就能出，要是要等待，
           就显示加载页面」）。首屏那一下 `get_state()` 可能还没回来（首次要扫库 +
           逐个 Mod 补修复状态），以前这里直接显示"还没有发现 Mod" ⇒ 看着像库是空的、
           过一会儿又自己冒出来。现在先给加载态。 -->
      <div v-if="!store.ready" class="empty-state">
        <Library :size="30" class="empty-icon" />
        <div class="empty-title">正在读取 Mod 库…</div>
        <div>状态读完后列表会自动出现（首次启动要扫一遍库）。</div>
      </div>
      <div v-else-if="!groups.length" class="empty-state">
        <Library :size="30" class="empty-icon" />
        <!-- 两种情况必须说清楚：库里真的没有 vs 搜索没匹配上（文案混用会让人以为 Mod 丢了） -->
        <div class="empty-title">{{ keyword ? "没有匹配的 Mod" : "还没有发现 Mod" }}</div>
        <template v-if="keyword">
          <div>当前搜索「{{ keyword }}」没有结果。换个关键字，或者清空搜索框看全部。</div>
        </template>
        <template v-else>
          <div>把 .zip / .7z / .rar 拖到窗口任意处即可导入；也可以在上面粘贴网址下载。</div>
          <div>如果你已经把 Mod 放进 服装 Mod目录了，点「重新扫描」。</div>
        </template>
      </div>
      <div v-else class="mt-3 space-y-4">
        <div v-for="g in groups" :key="g.name" class="rounded-lg border p-3" style="border-color: var(--border)">
          <div class="flex items-center justify-between mb-3">
            <h3 class="font-semibold">{{ g.name }}</h3>
            <span class="text-xs" style="color: var(--text-muted)">{{ g.mods.length }} 个 Mod · 已启用 {{ g.enabled }}</span>
          </div>
          <!-- 紧凑横向列表（用真实库数据验证后改的）：
               原来是「通栏组框 + 内部固定 168px 大卡片」—— 每个角色往往只有 1 个 Mod，
               于是右侧 4/5 全空、卡片还很高，一屏只看得下 4 个。
               改成一行一个 Mod：缩略图 + 名字 + 状态 + ⋯，一屏能看十几个。 -->
          <!-- 组内网格 + 横向卡片（GPT-6 Astra 方案）：
               原来是 40x40 的紧凑行 —— 只能看出"有个人"，看不出长裙/短裙、制服/礼服、
               有没有披风长靴，等于图片白放。现在封面 120x140（服装要竖看全身，不裁正方形），
               名字与状态放右侧；无封面也占同样尺寸，避免组内视觉节奏被破坏。 -->
          <div class="grid gap-3" style="grid-template-columns: repeat(auto-fill, minmax(320px, 1fr))">
            <div v-for="m in g.mods" :key="m.id"
                 class="relative flex gap-3 rounded-lg border p-2.5 cursor-pointer transition-colors"
                 :style="{ borderColor: selected.has(String(m.id)) ? 'var(--accent)' : 'var(--border)',
                           background: selected.has(String(m.id)) ? 'var(--accent-soft)' : 'var(--surface)' }"
                 @click="toggleMod(m)">
              <span class="shrink-0 rounded-md overflow-hidden flex items-center justify-center"
                    style="width: 120px; height: 140px; background: var(--surface-2)">
                <img v-if="covers[m.id]" :src="covers[m.id]" class="w-full h-full object-cover" alt="" />
                <span v-else class="flex flex-col items-center gap-1 empty-icon">
                  <ImageOff :size="20" />
                  <span class="text-xs">无封面</span>
                </span>
              </span>
              <span class="min-w-0 flex-1 flex flex-col">
                <span class="text-sm leading-5" style="display: -webkit-box; -webkit-line-clamp: 2;
                      -webkit-box-orient: vertical; overflow: hidden" :title="m.name">{{ m.name }}</span>
                <span class="mt-1.5 text-xs flex items-center gap-1.5 min-w-0"
                      :style="{ color: selected.has(String(m.id)) ? 'var(--accent)' : 'var(--text-muted)' }">
                  <span class="shrink-0">{{ selected.has(String(m.id)) ? "已启用" : "未启用" }}</span>
                  <!-- **香蕉网网站分类徽章**（2026-10-04 用户要求「把 mod 在香蕉网中的分类接入管理器的分类」）。
                       皮肤 / UI / 其它三个根分类里，只有 `Skins` 用强调色（它才是这个页面的主角），
                       其余用中性色。**只在有值时显示** —— 不是从香蕉网下来的 Mod 没有这个信息，
                       不留空占位，免得每张卡片都多一截没用的东西。 -->
                  <span v-if="m.site_category_root" class="badge shrink-0 truncate"
                        :style="m.site_category_root === 'Skins'
                                 ? 'background: var(--accent-soft); color: var(--accent)'
                                 : 'background: var(--surface-2); color: var(--text-muted)'"
                        :title="`香蕉网分类：${m.site_category}`">{{ siteRootLabel(m.site_category_root) }}</span>
                </span>
                <!-- ⚠️ 用户 2026-10-03：「现在没有之前那种**黄色的未识别的标记，可以点一下就切换的**」
                     —— 旧版在角色识别不确定（low/none）时会在卡片上打一个黄色标记，点它直接进选角色。
                     点击要 .stop，否则会先触发整卡的启用/停用。 -->
                <span v-if="!m.group || m.confidence === 'none' || m.confidence === 'low'"
                      class="badge mt-1 cursor-pointer" style="background: #f0b429; color: #3a2a00"
                      title="角色归属没认出来 —— 点这里选一个（识别错了会让同角色互斥失效，容易崩）"
                      @click.stop="menuAct('assign', m)">未识别 · 点此选角色</span>
                <!-- 类型待确认（例如把壁纸/加载页包当成了角色皮肤）也放这里，点一下改归属 -->
                <span v-else-if="m.kind === 'unknown'"
                      class="badge mt-1 cursor-pointer" style="background: #f0b429; color: #3a2a00"
                      title="看不出这是哪一类 Mod，点此指定角色归属（或设为未分类）"
                      @click.stop="menuAct('assign', m)">类型待确认</span>
              <!-- ⚠️ **C1：重复副本标记**（2026-10-03 补回归）。0.9.5 有
                   `⚠ 与「X」内容相同（重复副本）`；后端 `mod.duplicate_of` 一直在算，
                   而前端 grep 该字段 **0 命中** ⇒ 用户看不出哪些是重复的。 -->
              <span v-if="m.duplicate_of" class="ml-1" style="color: var(--warn)"
                    :title="`与「${m.duplicate_of}」内容相同（重复副本），留着会占空间`">⚠ 重复</span>
                <!-- 显式的启用开关（用户 2026-10-03 三次反馈"mod 开关还是没有"——
                     之前只有一行状态文字 + 点整卡切换，看不出那是个开关）。 -->
                <span class="mt-auto flex items-center justify-between gap-2">
                  <Switch :model-value="selected.has(String(m.id))"
                          @update:model-value="() => toggleMod(m)" />
                  <!-- ⚠️ **C2：⋯ 恢复"悬停即出"**（2026-10-03 补回归）。
                       0.9.5 用 `mouseenter` 打开（`app.js:635`），用户当年明确要求过
                       「**放上去就要出**」；换代后只剩 `@click`，要多点一次才出菜单。
                       现在两个都留着：鼠标移上去就展开，点击仍然有效（触屏/键盘用户）。 -->
                  <button class="btn btn-mini shrink-0" title="更多：更改所属角色 / 修复 / 回滚 / 重命名 / 换预览图 / 移出库 / 彻底删除"
                          @mouseenter="openMenu(m, $event)" @click="openMenu(m, $event)" @mouseleave="scheduleMenuClose()">⋯</button>
                </span>
              </span>
            </div>
          </div>
        </div>
      </div>
      </div>
    </Card>

    <CharacterAssignDialog ref="assignRef" />
    <!-- 2026-10-07：「mod 下载」卡片搬到「下载」页了（用户原话：「服装mod、辅助mod下面的
         **mod下载卡片挪到下载页**」）—— 发起下载与看进度现在都在同一页。 -->

    <ConflictDialog v-if="conflicts" :groups="conflicts"
                    @resolve="resolveConflicts" @cancel="conflicts = null" />

    <!-- ⋯ 就地小菜单（浮层，点空白处关闭） -->
    <div v-if="menu" class="fixed inset-0 z-40" @click="closeMenu" @mouseenter="scheduleMenuClose()"></div>
    <div v-if="menu" ref="menuEl" class="fixed z-50 card py-1 shadow-lg"
         style="min-width: 176px; max-height: calc(100vh - 16px); overflow-y: auto"
         :style="{ left: menu.x + 'px', top: menu.y + 'px' }" @mouseenter="cancelMenuClose()" @mouseleave="scheduleMenuClose()">
      <button class="w-full text-left px-3 py-1.5 text-sm" @click="menuAct('character')">更改所属角色…</button>
      <button class="w-full text-left px-3 py-1.5 text-sm" @click="menuAct('fix')">修复 Mod 文件</button>
      <!-- ⚠️ **不要再引用 `m`**（2026-10-03 修「点了更多页面就变纯白」）：
           `m` 只存在于 `menuAct()` 函数体内，**模板作用域里没有它** ——
           渲染这个浮层时会抛 `ReferenceError`，整页直接白掉。
           （服装页白、辅助页正常，因为辅助页是我照着新写的那份、没带这个错。）
           要用就用 `menu` —— 它带着 `id / name / kind`。 -->
      <button v-if="menu.kind !== 'assist'" class="w-full text-left px-3 py-1.5 text-sm"
              @click="menuAct('toAssist')">移到「辅助 Mod」</button>
      <button v-else class="w-full text-left px-3 py-1.5 text-sm"
              @click="menuAct('toSkin')">移到「服装 Mod」</button>
      <!-- ⚠️ **C4：回滚要按 `can_rollback` 置灰**（2026-10-03 补回归）：
             0.9.5 里没备份过就是灰的（点了也没用），现在无论有没有备份都可点。 -->
      <button class="w-full text-left px-3 py-1.5 text-sm" :disabled="!menu.can_rollback"
              :style="menu.can_rollback ? '' : 'opacity:.45;cursor:not-allowed'"
              :title="menu.can_rollback ? '' : '这个 Mod 还没有修复备份，没什么可回滚的'"
              @click="menuAct('rollback')">回滚</button>
      <button class="w-full text-left px-3 py-1.5 text-sm" @click="menuAct('open')">打开所在目录</button>
      <div style="height:1px;background:var(--border)" class="my-1"></div>
      <button class="w-full text-left px-3 py-1.5 text-sm" @click="menuAct('rename')">重命名…</button>
      <button class="w-full text-left px-3 py-1.5 text-sm" @click="menuAct('cover')">更换预览图…</button>
      <div style="height:1px;background:var(--border)" class="my-1"></div>
      <button class="w-full text-left px-3 py-1.5 text-sm" style="color: var(--danger)"
              @click="menuAct('delete')">移出 服装 Mod</button>
      <!-- ⚠️ 彻底删除（真删、恢复不了）：红字 + 更重一点的字体，且排在最后一个
           —— 危险动作不能放在顺手能点到的主位（用户定的 UI 准则）。 -->
      <button class="w-full text-left px-3 py-1.5 text-sm"
              style="color: var(--danger); font-weight: 600"
              @click="menuAct('purge')">彻底删除…</button>
    </div>
  </div>
</template>
