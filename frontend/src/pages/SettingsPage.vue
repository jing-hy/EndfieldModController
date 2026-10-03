<script setup>
// 设置页（对应旧 index.html 的 #tab-settings）。
// ⚠️ 所有表单项都走 `SettingPath / SettingSwitch / SettingSelect`，它们内部按"只发改动的那一个键"
//    调 save_config（旧版语义），所以这里不碰保存细节，只负责分组与按钮。
import { computed, onMounted, ref } from "vue";
import { call } from "../lib/bridge.js";
import { useLogAutoScroll } from "../lib/autoscroll.js";
import { store, applyTheme, THEMES, refreshState } from "../store.js";
import { settings, saveSetting } from "../lib/settings.js";
import Card from "../components/ui/Card.vue";
import Btn from "../components/ui/Btn.vue";
import Badge from "../components/ui/Badge.vue";
import SettingPath from "../components/ui/SettingPath.vue";
import SettingPathBrowse from "../components/ui/SettingPathBrowse.vue";
import SettingSwitch from "../components/ui/SettingSwitch.vue";
import { showModalDialog, showToast } from "../lib/dialog.js";
import SettingSelect from "../components/ui/SettingSelect.vue";

const RE_INJECTION = [
  { value: "xxmi_extra", label: "经 XXMI 注入库注入（本方案，推荐）" },
  { value: "none", label: "不注入（只跑服装 Mod）" },
  { value: "external", label: "外部注入（旧方案，已废弃）" },
];
const DL_BOOST = [
  { value: "auto", label: "自动（只在慢/抖动时临时并发）" },
  { value: "always", label: "强制并发（连接很差时用）" },
  { value: "never", label: "关闭（只用单连接）" },
];
const DL_LINE = [
  { value: "auto", label: "自动（直连优先，不通才临时换镜像）" },
  { value: "direct", label: "仅直连" },
  { value: "mirror", label: "只用镜像（直连被墙时）" },
];
const THEME_OPTIONS = [
  { value: "light", label: "浅色" }, { value: "dark", label: "深色" },
  { value: "amber", label: "琥珀" }, { value: "cyan", label: "青蓝" },
  { value: "violet", label: "紫罗兰" }, { value: "emerald", label: "翡翠" },
];

// state 里没有 paths：运行目录由 data_root + config 里的相对/绝对路径拼出来
const paths = computed(() => {
  const c = store.state.config || {};
  const root = store.state.data_root || "";
  return { controller: root, reshade: c.reshade_dll || "", staging: c.staging_mods_dir || "", mod_backup: c.mod_backup_dir || "" };
});
// ⚠️ **线路状况**（2026-10-03 修回归：原先硬编码 `computed(() => [])` ⇒ 那一格永远不渲染，
// 用户"下载卡住时不知道为什么"的排查入口就这么没了）。
// 数据源 = `get_download_settings()` 的 `lines`（每条线路的历史速度/可用性/被封锁状态）
// 与 `status`（当前策略/线路模式/是否正在并发加速/上次结果）。
// 展示沿用现有 `Badge` 组件（tone: success/muted/warning/danger），与页面其余部分一致。
const lineStatus = ref([]);
const dlStatus = ref(null);
const lastDownload = computed(() => {
  const s = dlStatus.value && dlStatus.value.last;
  if (!s || (!s.mbps && !s.line)) return "";
  const parts = [];
  if (s.line) parts.push(String(s.line));
  if (s.mbps) parts.push(`${Number(s.mbps).toFixed(2)} MB/s`);
  if (s.threads && Number(s.threads) > 1) parts.push(`临时并发 ${s.threads} 连接`);
  if (s.ok === false) parts.push("失败");
  return parts.join(" · ");
});

async function loadDownloadStatus() {
  try {
    const d = await call("get_download_settings");
    if (!d || typeof d !== "object") return;
    dlStatus.value = d;
    const lines = (d.lines || []).map((l) => ({
      name: String(l.line || ""),
      ok: l.ok === true,
      blocked: !!l.blocked,
      mbps: Number(l.mbps || 0),
      fails: Number(l.fails || 0),
    })).filter((l) => l.name);
    // 有速度的排前面（用户最关心"哪条线路能跑"）
    lines.sort((a, b) => (b.mbps - a.mbps) || (Number(a.blocked) - Number(b.blocked)));
    lineStatus.value = lines;
  } catch (e) { /* 拿不到就不显示，不影响设置页其它部分 */ }
}

async function clearDownloadLines() {
  const r = await run("clear_download_lines");
  if (r && r.ok === false) return;      // run() 已 toast
  showToast("线路记录已清空（下次下载会重新测速）", "success");
  await loadDownloadStatus();
}
// 详细状态：一个面板接住各类状态查询，结果落在纯黑日志框里（可复制）
const probeText = ref("点上面的按钮查询：DLSS5 / Poser / 组件版本 / 完整性 / 初始化自检。");
const probeBusy = ref(false);
const PROBES = [
  { m: "dlss5_status", label: "DLSS5 状态" },
  { m: "poser_status", label: "Poser 状态" },
  { m: "component_versions", label: "组件版本" },
  { m: "check_integrity", label: "完整性检查" },
  { m: "first_run_state", label: "初始化自检" },
];
async function probe(method) {
  probeBusy.value = true;
  probeText.value = `正在查询 ${method} …`;
  try {
    const r = await call(method);
    probeText.value = JSON.stringify(r, null, 2);
  } catch (e) {
    probeText.value = `查询失败：${(e && e.message) || e}`;
  } finally {
    probeBusy.value = false;
  }
}

async function changeTheme(v) { await saveSetting("theme", v); applyTheme(v); }
// ⚠️⚠️ **`run()` 绝不能静默**（2026-10-03 用户：「**现在导出诊断包的弹窗也没了**」）。
// 原实现是 `try { return await call(...) } catch { return null }` ——
// 异常被无声吞掉、返回的 `{ok:false}` 也没人检查，于是**本页 18 个按钮**（见模板）
// 全都变成"点了什么反应都没有"：用户既不知道成没成、也不知道为什么没成。
// 现在统一兜底：**失败一定给一条 danger toast**（成功则由各按钮自己给更具体的反馈）。
async function run(method, ...args) {
  try {
    const result = await call(method, ...args);
    if (result && result.ok === false) {
      showToast(String(result.message || result.reason || "操作失败"), "danger");
    }
    return result;
  } catch (e) {
    showToast(String((e && e.message) || e || "操作失败"), "danger");
    return null;
  }
}

// 「导出诊断包」—— **必须告诉用户包在哪**（用户 2026-10-03：「导出诊断包的弹窗也没了」）。
// 后端 `export_diagnostics()` 返回 `{ok, path}`；这里拿到路径后弹窗 + 一键打开所在文件夹。
async function exportDiagnostics() {
  const result = await run("export_diagnostics");
  if (!result || result.ok === false || !result.path) {
    return;   // 失败的 toast 已由 run() 给过
  }
  const path = String(result.path);
  const open = await showModalDialog({
    title: "诊断包已导出",
    message:
      `已生成：\n${path}\n\n` +
      "把它发到 GitHub Issues 或 QQ 群（1045239747，验证答案 jing_hy）就能帮你定位问题。\n\n" +
      "包里含运行日志、配置、注入快照与游戏侧日志，**不含你的 Mod 内容**。",
    okText: "打开所在文件夹", cancelText: "知道了",
  });
  if (open) {
    try { await call("open_path_in_explorer", path); } catch (e) { /* 打不开就算了 */ }
  }
}

// 「依赖清空并重新下载」——用户 2026-10-03 要求：
//   ① 出弹窗确认；② 清空完弹个提示；③ 跳转到依赖页走正常下载流程（含日志）。
// 后端 `reset_dependencies_and_redownload` 只做前两步（还原游戏本体 + 清 runtime/assets
// 并写回路径），它自己的文档里就写着"前端负责第三步的跳转与触发"——之前前端没实现。
async function resetDependencies() {
  const ok = await showModalDialog({
    title: "依赖清空并重新下载",
    message: [
      "会依次做三件事：",
      "① 从备份区还原终末地本体（没做过净化就跳过）；",
      "② 清掉 runtime 与 assets，然后重新下载并展开；",
      "③ 跳到「依赖」页开始一键下载。",
      "",
      "你的 Mod 库和程序本体不受影响。",
      "清完到装好之间，组件列表会先变空，属于正常现象。",
    ].join("\n"),
    // 破坏性动作：按钮文字自解释，默认聚焦在安全项上
    okText: "清空并重新下载",
    cancelText: "取消，什么都不做",
    focusCancel: true,
  });
  if (!ok) return;

  const result = await run("reset_dependencies_and_redownload");
  if (!result || result.ok === false) {
    showToast((result && result.message) || "清空失败，详情见设置页的运行日志", "danger");
    return;
  }

  // 清空完的"动态"提示（用户原话：「清空完弹个动态」）
  showToast("已清空 runtime 与 assets，正在跳到依赖页重新下载…", "success");
  // 跳依赖页并让那边自动开跑（依赖页 onMounted 会读这个标志）
  store.autoStartDeps = true;
  store.tab = "dependencies";
}
// 「自动检测」—— 一键找 XXMI / 3DMigoto Loader / 官方启动器 / 游戏本体 / 乳摇工具
//（2026-10-03 补回归：0.9.5 有这个按钮，且每次刷新还会静默回填 detected_*；
//  换代后全丢了，`grep detected_` 在现前端 0 命中 ⇒ 内置了 XXMI 那三个框也一直空着）。
// 回填逻辑收在后端 `autodetect_paths()`：只填**空**字段，不覆盖你手填过的路径。
async function autodetectPaths() {
  const r = await run("autodetect_paths");
  if (!r || r.ok === false) return;              // run() 已经 toast 过
  await store.refreshState();
  const filled = Object.keys(r.filled || {});
  const skipped = Object.keys(r.skipped || {});
  if (filled.length) {
    showToast(`已自动填入：${filled.join("、")}`, "success");
  } else if (skipped.length) {
    showToast(`检测到 ${skipped.length} 项，但都已填过（不覆盖你的设置）`, "info");
  } else {
    showToast("没有检测到可自动填入的路径", "info");
  }
}

onMounted(() => {
  // 线路状况进页面就查一次（0.9.5 的 refreshDownloadStatus 也是打开设置页时刷新）
  loadDownloadStatus();
});

// ⚠️ **不能把 kind 当路径传**（2026-10-03 修）。
// 后端 `open_path_in_explorer(target)` / `open_path(target)` 期望的是**真实路径**，
// 而模板传进来的是 `"controller"` / `"reshade"` / `"staging"` 这类**标签** ⇒
// `Path("controller")` 解析到当前工作目录下、必然"路径不存在" ⇒ 三个按钮全废。
// 对照组：0.9.5 也是先 `call('log')` 拿到 `info.dirs` 再打开。
// `log()` 正好返回 {library, staging, runtime, controller, reshade} 的真实路径。
async function openPath(kind) {
  let path = "";
  try {
    const dirs = await call("log");
    path = String((dirs && dirs[kind]) || "");
  } catch (e) { /* 拿不到就走下面的报错 */ }
  if (!path) {
    showToast(`拿不到「${kind}」的路径`, "danger");
    return;
  }
  const r = await run("open_path_in_explorer", path);
  if (r && r.ok === false) showToast(String(r.message || "打不开这个目录"), "danger");
}

// 诊断详情那块日志自动滚到底（不抢鼠标、没新内容不动）
// ⚠️ 2026-10-03 **删掉了这里的两行残留**：
//     const logBox = ref(null);
//     useLogAutoScroll(logBox, () => logLines.value);
// 本页模板里**根本没有** `logBox` 对应的日志框（只有下面这个 `probeBox`），
// 而 `logLines` 也从没在本页定义过（那个名字属于依赖页，2026-10-03 已统一挪进 store）。
// 于是每次进设置页都会抛 `ReferenceError: logLines is not defined`
// —— 用 headless 抓控制台抓到的（页面还能显示，但脚本在那一步就断了）。
const probeBox = ref(null);
useLogAutoScroll(probeBox, () => probeText);
</script>

<template>
  <div class="space-y-4">
    <!-- 顶部：状态优先 + 主操作唯一。评审指出原来四个按钮里两个都是实心蓝、破坏性操作混在中间。 -->
    <div class="card">
      <div class="card-body">
        <div class="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div class="text-sm font-medium">改完即保存</div>
            <div class="text-xs mt-0.5" style="color: var(--text-muted)">
              下面每一项改动<b>立刻生效并写入 config.json</b>，不需要点保存；留空的项按「自动」处理。
            </div>
          </div>
          <div class="flex flex-wrap gap-2">
            <Btn variant="primary" @click="run('ensure_initialized')">一键检测全部</Btn>
            <Btn @click="exportDiagnostics">导出诊断包</Btn>
          </div>
        </div>
      </div>
    </div>

    <!-- 两列（GPT-6 Astra 评审：五个大区连续纵向排列要滚很久，右侧又大片空白）：
         左 = 各设置分组（要改的）；右 = 运行状态与详细状态（要看的，滚动时吸顶）。 -->
    <div class="two-col grid gap-4">
      <div class="space-y-4 min-w-0">

    <Card title="维护操作（会改动文件，请确认后再点）">
      <div class="flex flex-wrap gap-2">
        <Btn id="game-restore-btn" @click="run('game_clean_restore')">还原游戏本体</Btn>
        <Btn variant="danger" @click="resetDependencies">依赖清空并重新下载</Btn>
      </div>
      <div class="text-xs mt-2" style="color: var(--text-muted)">
        「还原游戏本体」只从备份区把非原版文件搬回去，不动你的 Mod 库；
        「依赖清空并重新下载」会清掉 runtime 与 assets（<b>保留 Mod 库与 exe</b>）后重新拉取。
      </div>
    </Card>

    <Card title="① 工作区与 Mod 库（相对主路径）">
      <SettingPath k="data_root" label="主路径" readonly placeholder="程序所在目录" hint="程序所在目录，下面这些都相对它" />
      <SettingPath k="runtime_dir" label="runtime 目录" placeholder="runtime" />
      <SettingPathBrowse k="library_dir" label="Mod 库目录" placeholder="library" kind="dir" />
      <SettingSwitch k="mod_backup_enabled" label="Mod 备份（默认开，关了就不备份）"
        hint="关掉后不再把 Mod 库里的 Mod 复制进备份仓；已有的备份一个都不会删（只增不减）。" />
      <SettingPath k="mod_backup_dir" label="Mod 备份目录" placeholder="mod-backup" hint="留空 = 主路径下的 mod-backup（只增不减）" />
      <SettingPathBrowse k="staging_mods_dir" label="Staging Mods 目录" placeholder="留空 = 自动：<主路径>/builtin/XXMI/EFMI/Mods" kind="dir" hint="EFMI 实际加载的位置" />
      <SettingPath k="dependency_manifest" label="依赖清单" placeholder="dependencies.json" />
    </Card>

    <Card title="② 游戏与启动器（留空即自动搜索）">
      <!-- ⚠️ **自动检测**（2026-10-03 补回归）：0.9.5 有这个按钮，且每次刷新状态还会
           静默回填 `detected_*`；换代到 Vue 后两条都丢了 ⇒ 即使内置了 XXMI，
           下面几个框也会一直空着。回填逻辑在后端 `autodetect_paths()`：
           **只填空字段，不覆盖你手填过的**。 -->
      <div class="flex items-center justify-between gap-2 pb-1.5">
        <span class="text-xs" style="color: var(--text-muted)">
          不确定路径就点右边，它会找 XXMI / 3DMigoto Loader / 官方启动器 / 游戏本体
        </span>
        <Btn size="sm" @click="autodetectPaths">自动检测</Btn>
      </div>
      <SettingPathBrowse k="official_launcher" label="官方启动器" placeholder="留空 = 自动搜索 Hypergryph Launcher" kind="file" />
      <SettingPathBrowse k="game_exe" label="Endfield.exe" placeholder="留空 = 自动搜索游戏目录" kind="file" />
      <SettingPathBrowse k="xxmi_launcher" label="XXMI Launcher" placeholder="留空 = 自动搜索" kind="file" />
      <SettingPathBrowse k="migoto_loader" label="3DMigoto Loader（可选）" placeholder="留空 = 用内置 migoto_loader.exe" kind="file" />
    </Card>

    <Card title="③ 组件与注入（留空 = 按主路径自动推导）">
      <SettingPathBrowse k="dlss5_dir" label="DLSS5 / 第一人称目录" placeholder="留空 = 自动：<主路径>/dlss5" kind="dir" />
      <SettingPathBrowse k="reshade_dll" label="ReShade 底座 d3d12.dll" placeholder="留空 = 自动：<主路径>/dlss5/d3d12.dll" kind="file" />
      <SettingPathBrowse k="secondary_motion_dir" label="乳摇工具目录" placeholder="留空 = 自动：<主路径>/secondary_motion" kind="dir" hint="装到别处时填这里" />
      <SettingPathBrowse k="poser_dir" label="Endfield Poser 安装包" placeholder="留空 = 自动：<主路径>/poser" kind="dir" />
      <SettingSelect k="reshade_injection" label="ReShade 注入方式" :options="RE_INJECTION" />
    </Card>

    <Card title="④ 下载与网络">
      <SettingPath k="download_proxy" label="下载代理" placeholder="留空即自动（环境变量 → 系统代理 → 直连）" />
      <SettingSelect k="download_boost" label="下载加速" :options="DL_BOOST" />
      <SettingSelect k="download_line" label="下载线路" :options="DL_LINE" />
      <!-- ⚠️ **线路状况**（2026-10-03 修回归：0.9.5 有，换代后变成硬编码空数组）。
           作用：下载卡住时，这里是"哪条线路能跑、跑到多少"的唯一入口。
           展示沿用现有 Badge / Btn（size="sm"），与页面其余部分风格一致。 -->
      <div class="pt-1">
        <div class="flex items-center justify-between gap-2">
          <span class="text-xs" style="color: var(--text-muted)">
            线路状况{{ lastDownload ? `　上次下载：${lastDownload}` : "（暂无记录，下次下载后会显示实测速度）" }}
          </span>
          <Btn v-if="lineStatus.length" size="sm" @click="clearDownloadLines">清除线路记录</Btn>
        </div>
        <div v-if="lineStatus.length" class="flex flex-wrap gap-1.5 pt-1.5">
          <Badge v-for="l in lineStatus" :key="l.name"
                 :tone="l.blocked ? 'danger' : (l.ok ? 'success' : (l.mbps > 0 ? 'warning' : 'muted'))">
            {{ l.name }}
            {{ l.blocked ? "已封锁" : (l.mbps > 0 ? `${l.mbps.toFixed(2)} MB/s` : (l.ok ? "可用" : "未测速")) }}
            <template v-if="l.fails">（失败 {{ l.fails }} 次）</template>
          </Badge>
        </div>
      </div>
    </Card>

    <Card title="⑤ 开关">
      <SettingSwitch k="use_builtin_runtime" label="使用内置 XXMI/EFMI" />
      <SettingSwitch k="auto_update_dependencies" label="启动前自动更新依赖" />
      <SettingSwitch k="require_admin" label="启动时请求管理员权限" />
      <SettingSwitch k="auto_disable_feed_on_native_dlss" label="游戏自带 DLSS 时自动停用喂帧组件"
        hint="终末地自带 DLSS 时，喂帧组件会与游戏自己的 DLSS 抢同一条 NGX 链路。开启时自检会把它停用（移进 runtime\dlss5\_disabled，可逆）—— 但只有游戏确实跑在 D3D12 时才停：被 XXMI/EFMI 强制 -force_d3d11 时游戏建不出自己的 DLSS，喂帧组件是 DLSS5 的必需环节，此时会保持启用。" />
      <SettingSwitch k="inject_reshade_ui" label="注入统一控制面板（自研 ReShade addon）"
        hint="放进 ReShade 真正读取的目录（d3d12.dll 所在处）。关掉后不注入面板；此时「整合 Mod 快捷键」会拒绝锁键。" />
      <SettingSwitch k="prefer_internal_dependencies" label="依赖包优先用控制器维护的那份"
        hint="RabbitFX 这类依赖：同一时间只允许一份生效。开启时优先用控制器自己维护的 _deps 那份，屏蔽你手动放进库的。" />
      <SettingSwitch k="reshade_panel_font" label="面板自动用系统中文字体"
        hint="ReShade 默认字体只有 ASCII，面板里的中文会显示成方块。开启时（仅在 Font 还为空时）自动指向系统中文字体，写前会备份。" />
    </Card>

    <Card title="⑥ 外观">
      <div class="flex items-center gap-3 py-1.5">
        <span class="w-56 shrink-0 text-sm">主题色</span>
        <select class="field flex-1" :value="settings.theme" @change="changeTheme($event.target.value)">
          <option v-for="o in THEME_OPTIONS" :key="o.value" :value="o.value">{{ o.label }}</option>
        </select>
      </div>
    </Card>

    <Card title="启动与诊断">
      <div class="flex flex-wrap gap-2">
        <Btn variant="primary" @click="run('launch_official_gui')">启动官方 XXMI / EFMI 界面</Btn>
        <Btn @click="run('read_launch_log')">查看启动日志</Btn>
        <Btn @click="exportDiagnostics">导出诊断包</Btn>
        <Btn @click="run('poser_log_tail')">打开 Poser 日志</Btn>
        <Btn @click="run('force_close_game')">强制结束残留游戏</Btn>
      </div>
      <div class="flex flex-wrap gap-2 mt-2">
        <Btn @click="run('clean_game_injections')">清理残留注入</Btn>
        <Btn @click="run('restore_game_injections')">撤销清理</Btn>
        <Btn @click="run('check_component_updates')">检查组件更新</Btn>
        <Btn variant="primary" @click="run('start_full_update')">一键安装/更新全部组件</Btn>
        <Btn @click="run('check_app_update')">检查程序更新</Btn>
        <Btn @click="run('download_reshade')">更新 ReShade 底座</Btn>
      </div>
      <div class="flex flex-wrap gap-2 mt-2">
        <Btn @click="run('game_clean_audit')">游戏目录体检</Btn>
        <Btn variant="primary" @click="run('game_clean_backup_and_clean')">备份并净化游戏目录</Btn>
        <Btn @click="run('game_clean_restore')">从备份还原游戏目录</Btn>
        <span class="text-xs self-center" style="color: var(--text-muted)">只移动不删除：先把非原版文件整体备份，再让本体回到原版状态。</span>
      </div>
    </Card>

    <Card title="运行目录">
      <div class="space-y-1.5 text-sm">
        <div v-for="row in [
          { label: 'Controller：', value: paths.controller, kind: 'controller' },
          { label: 'ReShade：', value: paths.reshade, kind: 'reshade' },
          { label: 'Staging：', value: paths.staging, kind: 'staging' },
        ]" :key="row.kind" class="flex items-center gap-2">
          <span class="w-24 shrink-0" style="color: var(--text-muted)">{{ row.label }}</span>
          <code class="flex-1 truncate" style="color: var(--text-muted)">{{ row.value || "—" }}</code>
          <Btn size="sm" :disabled="!row.value" @click="openPath(row.kind)">打开</Btn>
        </div>
        <div class="flex items-center gap-2">
          <span class="w-24 shrink-0" style="color: var(--text-muted)">Mod 备份仓：</span>
          <code class="flex-1 truncate" style="color: var(--text-muted)">{{ paths.mod_backup || "—" }}</code>
          <Btn size="sm" @click="run('open_mod_backup_dir')">打开</Btn>
        </div>
      </div>
    </Card>
      </div>


      <!-- 右栏：状态（滚动时吸顶） -->
      <div class="space-y-4 min-w-0" style="align-self: start; position: sticky; top: 68px">
        <Card title="运行状态">
          <div class="space-y-1.5 text-sm">
            <div class="flex items-center gap-2">
              <span class="w-32 shrink-0" style="color: var(--text-muted)">控制器</span>
              <Badge :tone="store.state.controller_ready ? 'success' : 'warn'">
                {{ store.state.controller_ready ? "已生成 controller.ini" : "还没生成（点启动页「生成控制器」）" }}
              </Badge>
            </div>
            <div class="flex items-center gap-2">
              <span class="w-32 shrink-0" style="color: var(--text-muted)">渲染 API</span>
              <Badge tone="muted">{{ store.state.render_api || "unknown" }}</Badge>
            </div>
            <div class="flex items-center gap-2">
              <span class="w-32 shrink-0" style="color: var(--text-muted)">ReShade 面板</span>
              <Badge :tone="store.state.reshade_addon_ready ? 'success' : 'warn'">
                {{ store.state.reshade_addon_ready ? "已就位" : "未就位" }}
              </Badge>
            </div>
            <div class="flex items-center gap-2">
              <span class="w-32 shrink-0" style="color: var(--text-muted)">统一快捷键面板</span>
              <span class="text-xs" style="color: var(--text-muted)">{{ (store.state.hotkey_panel || {}).message || "—" }}</span>
            </div>
            <div class="flex items-center gap-2">
              <span class="w-32 shrink-0" style="color: var(--text-muted)">Mod 备份仓</span>
              <span class="text-xs" style="color: var(--text-muted)">
                {{ (store.state.mod_backup || {}).count || 0 }} 个 · {{ (store.state.mod_backup || {}).size_text || "0 B" }}
              </span>
            </div>
            <div v-if="store.state.warming" class="text-xs" style="color: var(--text-muted)">后台预热中…（预热完会自动刷新）</div>
          </div>
        </Card>

        <Card title="详细状态">
          <div class="flex flex-wrap gap-2">
            <Btn v-for="p in PROBES" :key="p.m" :disabled="probeBusy" @click="probe(p.m)">{{ p.label }}</Btn>
          </div>
          <div ref="probeBox" class="log-box h-56 mt-3">{{ probeText }}</div>
        </Card>
      </div>
    </div>
  </div>
</template>
