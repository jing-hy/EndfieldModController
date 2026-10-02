<script setup>
// 设置页（对应旧 index.html 的 #tab-settings）。
// ⚠️ 所有表单项都走 `SettingPath / SettingSwitch / SettingSelect`，它们内部按"只发改动的那一个键"
//    调 save_config（旧版语义），所以这里不碰保存细节，只负责分组与按钮。
import { computed } from "vue";
import { call } from "../lib/bridge.js";
import { store, applyTheme, THEMES } from "../store.js";
import { settings, saveSetting } from "../lib/settings.js";
import Card from "../components/ui/Card.vue";
import Btn from "../components/ui/Btn.vue";
import Badge from "../components/ui/Badge.vue";
import SettingPath from "../components/ui/SettingPath.vue";
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

const paths = computed(() => store.state.paths || {});
const lineStatus = computed(() => store.state.download_lines || []);

async function changeTheme(v) { await saveSetting("theme", v); applyTheme(v); }
async function run(method, ...args) { try { return await call(method, ...args); } catch (e) { return null; } }
async function openPath(kind) { await run("open_path_in_explorer", kind); }
</script>

<template>
  <div class="space-y-4">
    <!-- 顶部动作区（旧版把这三个放最上面） -->
    <div class="flex flex-wrap gap-2">
      <Btn variant="danger" @click="run('reset_dependencies_and_redownload')">依赖清空重新下载</Btn>
      <Btn variant="primary" @click="run('export_diagnostics')">一键导出诊断包</Btn>
      <Btn variant="primary" @click="run('ensure_initialized')">一键检测全部</Btn>
      <Btn @click="run('game_clean_restore')">一键还原游戏本体</Btn>
    </div>

    <Card title="① 工作区与 Mod 库（相对主路径）">
      <SettingPath k="data_root" label="主路径" readonly placeholder="程序所在目录" hint="程序所在目录，下面这些都相对它" />
      <SettingPath k="runtime_dir" label="runtime 目录" placeholder="runtime" />
      <SettingPath k="library_dir" label="Mod 库目录" placeholder="library" />
      <SettingSwitch k="mod_backup_enabled" label="Mod 备份（默认开，关了就不备份）"
        hint="关掉后不再把 Mod 库里的 Mod 复制进备份仓；已有的备份一个都不会删（只增不减）。" />
      <SettingPath k="mod_backup_dir" label="Mod 备份目录" placeholder="mod-backup" hint="留空 = 主路径下的 mod-backup（只增不减）" />
      <SettingPath k="staging_mods_dir" label="Staging Mods 目录" placeholder="留空 = 自动：<主路径>/builtin/XXMI/EFMI/Mods" hint="EFMI 实际加载的位置" />
      <SettingPath k="dependency_manifest" label="依赖清单" placeholder="dependencies.json" />
    </Card>

    <Card title="② 游戏与启动器（留空即自动搜索）">
      <SettingPath k="official_launcher" label="官方启动器" placeholder="留空 = 自动搜索 Hypergryph Launcher" />
      <SettingPath k="game_exe" label="Endfield.exe" placeholder="留空 = 自动搜索游戏目录" />
      <SettingPath k="xxmi_launcher" label="XXMI Launcher" placeholder="留空 = 自动搜索" />
      <SettingPath k="migoto_loader" label="3DMigoto Loader（可选）" placeholder="留空 = 用内置 migoto_loader.exe" />
    </Card>

    <Card title="③ 组件与注入（留空 = 按主路径自动推导）">
      <SettingPath k="dlss5_dir" label="DLSS5 / 第一人称目录" placeholder="留空 = 自动：<主路径>/dlss5" />
      <SettingPath k="reshade_dll" label="ReShade 底座 d3d12.dll" placeholder="留空 = 自动：<主路径>/dlss5/d3d12.dll" />
      <SettingPath k="secondary_motion_dir" label="乳摇工具目录" placeholder="留空 = 自动：<主路径>/secondary_motion" hint="装到别处时填这里" />
      <SettingPath k="poser_dir" label="Endfield Poser 安装包" placeholder="留空 = 自动：<主路径>/poser" />
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
        hint="终末地自带 DLSS：喂帧组件（dlss5-feed）会与游戏自己的 DLSS 抢同一条 NGX 链路。开启时自检会自动把它停用（文件移进 runtime\dlss5\_disabled，可逆）。" />
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
</template>
