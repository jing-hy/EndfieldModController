<script setup>
// 设置页（对应旧 index.html 的 #tab-settings）。
// ⚠️ 所有表单项都走 `SettingPath / SettingSwitch / SettingSelect`，它们内部按"只发改动的那一个键"
//    调 save_config（旧版语义），所以这里不碰保存细节，只负责分组与按钮。
import { computed, ref } from "vue";
import { call } from "../lib/bridge.js";
import { store, applyTheme, THEMES } from "../store.js";
import { settings, saveSetting } from "../lib/settings.js";
import Card from "../components/ui/Card.vue";
import Btn from "../components/ui/Btn.vue";
import Badge from "../components/ui/Badge.vue";
import SettingPath from "../components/ui/SettingPath.vue";
import SettingPathBrowse from "../components/ui/SettingPathBrowse.vue";
import SettingSwitch from "../components/ui/SettingSwitch.vue";
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
const lineStatus = computed(() => []);
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
async function run(method, ...args) { try { return await call(method, ...args); } catch (e) { return null; } }
async function openPath(kind) { await run("open_path_in_explorer", kind); }
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
            <Btn @click="run('export_diagnostics')">导出诊断包</Btn>
          </div>
        </div>
      </div>
    </div>

    <!-- 两列（GPT-6 Astra 评审：五个大区连续纵向排列要滚很久，右侧又大片空白）：
         左 = 各设置分组（要改的）；右 = 运行状态与详细状态（要看的，滚动时吸顶）。 -->
    <div class="grid gap-4" style="grid-template-columns: minmax(0, 1fr) minmax(300px, 380px)">
      <div class="space-y-4 min-w-0">

    <Card title="维护操作（会改动文件，请确认后再点）">
      <div class="flex flex-wrap gap-2">
        <Btn @click="run('game_clean_restore')">还原游戏本体</Btn>
        <Btn variant="danger" @click="run('reset_dependencies_and_redownload')">依赖清空并重新下载</Btn>
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
      <div v-if="lineStatus.length" class="flex flex-wrap gap-1.5 pt-1">
        <Badge v-for="l in lineStatus" :key="l.name" :tone="l.ok ? 'success' : 'muted'">
          {{ l.name }} {{ l.ok ? "可用" : "不可用" }}
        </Badge>
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
        <Btn @click="run('export_diagnostics')">导出诊断包</Btn>
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
      <div class="space-y-4 min-w-0" style="align-self: start; position: sticky; top: 12px">
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
          <div class="log-box h-56 mt-3">{{ probeText }}</div>
        </Card>
      </div>
    </div>
  </div>
</template>
