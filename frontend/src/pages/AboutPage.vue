<!-- SPDX-License-Identifier: AGPL-3.0-only -->
<script setup>
// 说明（原「说明」页）。2026-11-28 起不再是页面 —— 它作为设置浮窗里的一层内容，
// 由设置最下面的「说明」按钮打开（同一浮窗内切换，左上角可返回）。
// 内容按版本分支：完整版讲三件套；轻量版只讲换装 / 插件，并说明两版怎么切换。
import { computed } from "vue";
import { store } from "../store.js";
import Card from "../components/ui/Card.vue";
import { t } from "../lib/i18n.js";

const REPO = "https://github.com/jing-hy/EndfieldModController";
const repo = computed(() => store.state.repo_url || REPO);
const issues = computed(() => store.state.issues_url || REPO + "/issues");
const releases = computed(() => store.state.releases_url || REPO + "/releases");
const isLite = computed(() => ((store.state && store.state.edition) || "full") === "lite");
</script>

<template>
  <div class="space-y-4">
    <Card v-if="!isLite" :title="t('当前路线：三件套（DLSS5 + 第一人称 + 服装 Mod）')">
      <ul class="list-disc pl-5 space-y-1.5 text-sm leading-6">
        <li>{{ t("唯一 ReShade 底座 = 内置") }} <code>runtime\dlss5\d3d12.dll</code>{{ t("（ReShade 6.8.0），里面同时挂着") }} <b>RenoDX-DLSS5</b> {{ t("与") }} <b>{{ t("Endfield Enhancer（第一人称）") }}</b>{{ t("两个插件。") }}</li>
        <li>{{ t("由 XXMI 在启动游戏时注入两个 DLL：") }}<code>runtime\dlss5\d3d12.dll</code> + <code>runtime\builtin\XXMI\EFMI\d3d11.dll</code>{{ t("（服装 Mod 引擎）。") }}</li>
        <li>{{ t("同一进程只能有一个 ReShade，所以两个") }} <code>d3d12.dll</code> {{ t("不要同时注入 —— 本程序只注入一个。") }}</li>
        <li>{{ t("启动页的「三件套注入」开关直接改写 XXMI 的注入库：开 = 三件套齐活，关 = 只跑服装 Mod。") }}</li>
        <li>{{ t("外部选择 Mod 库里的 Mod，程序把选中项 staging 到") }} <code>EFMI\Mods\MC_*</code>{{ t("（同角色互斥、原始快捷键屏蔽），原库只读。") }}</li>
        <li>{{ t("游戏目录保持干净：不写任何 ReShade/addon，注入全部由 XXMI 完成。") }}</li>
      </ul>
    </Card>

    <Card v-else :title="t('轻量版：只保留换装与插件')">
      <ul class="list-disc pl-5 space-y-1.5 text-sm leading-6">
        <li><b>{{ t("轻量版不含 ReShade") }}</b>{{ t("：不下载、不安装、不注入 ReShade / DLSS5 / 第一人称 / 统一面板，相关开关与路径都不出现在界面上。") }}</li>
        <li>{{ t("游戏目录里已有的 ReShade 残留会在每次启动时被移走（只移动、有备份、可还原）；XXMI 注入库也只保留 EFMI 的服装 Mod loader。") }}</li>
        <li>{{ t("服装 Mod（XXMI / EFMI）、乳摇（ShakingBreastManager）、Endfield Poser 与完整版完全一致。") }}</li>
        <li>{{ t("想用 DLSS5 / 第一人称 / 统一面板，换回完整版的 exe 即可 —— 数据根与配置共用，设置原样保留。") }}</li>
      </ul>
    </Card>

    <Card v-if="!isLite" :title="t('进游戏后')">
      <ul class="list-disc pl-5 space-y-1.5 text-sm leading-6">
        <li>{{ t("按") }} <kbd class="kbd">Home</kbd> {{ t("打开 ReShade：插件页应同时有") }} <b>RenoDX-DLSS5</b> {{ t("与") }} <b>Endfield Enhancer</b>{{ t("。") }}</li>
        <li>{{ t("DLSS5 页勾「启用 DLSS 神经渲染」+「启用超分」；风格选电影，总体/结构强度拉满，角色皮肤结构 ≥ 0。") }}</li>
        <li>{{ t("Enhancer 的 Camera 页：先开 Camera Controls → First Person = On → Third Person During Combat =") }} <b>Off</b>{{ t("（打 boss 才不会被踢出第一人称）→ EFMI/XXMI Compatibility = On。") }}</li>
        <li>{{ t("快捷键：") }}<kbd class="kbd">F6</kbd> {{ t("神经渲染开关、") }}<kbd class="kbd">F11</kbd> {{ t("Mod 显示、") }}<kbd class="kbd">,</kbd> {{ t("第一人称、") }}<kbd class="kbd">F12</kbd> {{ t("EFMI 帮助。") }}</li>
      </ul>
    </Card>

    <Card :title="t('Endfield Poser（摆姿 / MMD 播放，可选）')">
      <ul class="list-disc pl-5 space-y-1.5 text-sm leading-6">
        <li>{{ t("上游") }} <a class="text-accent" href="https://github.com/OedoSoldier/Endfield-Poser" target="_blank" rel="noopener">OedoSoldier/Endfield-Poser</a>{{ t("（AGPL-3.0，二进制不随包分发）。") }}</li>
        <li>{{ t("它和乳摇（SecondaryMotion）用") }}<b>{{ t("同一套注入机制") }}</b>{{ t("：游戏目录里的") }} <code>d3dcompiler_47</code> proxy {{ t("会把") }} <code>plugin\*.dll</code> {{ t("全部加载进游戏进程，所以两个插件能共存；卸载其中一方时，只要另一方还在就保留 proxy。") }}</li>
        <li>{{ t("使用前请在游戏内确认它的《用户协议》。") }}</li>
        <li>{{ t("要打开摆姿页，用") }}<b>{{ t("启动页") }}</b>{{ t("的「打开摆姿页（Poser）」按钮（游戏要在运行中）。") }}</li>
        <li>{{ t("游戏内快捷键：") }}<kbd class="kbd">L</kbd> {{ t("显示/隐藏面板、") }}<kbd class="kbd">P</kbd> {{ t("冻结/解冻、按住") }} <kbd class="kbd">Alt</kbd> {{ t("呼出光标、") }}<kbd class="kbd">Ctrl</kbd>+<kbd class="kbd">F5</kbd>/<kbd class="kbd">F6</kbd>/<kbd class="kbd">F7</kbd>/<kbd class="kbd">F8</kbd> {{ t("播放/暂停/停止/回首帧；它还有一个独立摆姿页") }} <code>http://127.0.0.1:18923</code>{{ t("。") }}</li>
        <li>{{ t("开关含义：关掉只把") }} <code>plugin\poser.dll</code> {{ t("改名（可逆、不动 proxy、不动其它插件）；要真正移除文件请点设置页的卸载（走它自己的卸载向导）。") }}</li>
      </ul>
    </Card>

    <Card :title="t('注意')">
      <div class="rounded-lg p-3 mb-3"
           style="background: color-mix(in srgb, var(--warn) 10%, transparent); border-left: 3px solid var(--warn)">
        <div class="text-sm font-medium" style="color: var(--warn)">{{ t("Mod 有 ToS / 账号风险") }}</div>
        <div class="text-sm mt-1 leading-6">{{ t("显卡压力也比单开大（UP 主建议 40 系以上）。请自行判断是否使用。") }}</div>
      </div>
      <ul class="list-disc pl-5 space-y-1.5 text-sm leading-6">
        <li>{{ t("游戏目录里的第三方 proxy（") }}<code>d3dcompiler_47.dll</code> / <code>vulkan-1.dll</code>{{ t("）属于别的工具（如 SecondaryMotion 摇乳管理器），与本方案无关，但会出现在「检查游戏目录注入」列表里。") }}</li>
      </ul>
    </Card>

    <Card v-if="!isLite" :title="t('致谢')">
      <ul class="list-disc pl-5 space-y-1.5 text-sm leading-6">
        <li><b>{{ t("第一人称插件（Endfield Enhancer）") }}</b>{{ t("由") }} <b>{{ t("B 站 UP 主 Hirahido") }}</b> {{ t("制作，感谢授权与分享。") }}</li>
        <li>{{ t("路线参考 B 站教程") }} <code>BV1XMh76UEA5</code>{{ t("《以防你不知道，你也可以终末地+XXMI+DLSS5+第一人称视角》。") }}</li>
        <li>{{ t("其余第三方组件（XXMI / EFMI / ReShade / RenoDX / DLSS5-Feeder / iMMERSE / ShakingBreastManager）见 README 第九节，均为各自作者所有。") }}</li>
      </ul>
    </Card>

    <Card :title="t('完整版与轻量版怎么切换')">
      <ul class="list-disc pl-5 space-y-1.5 text-sm leading-6">
        <li>{{ t("两个 exe") }} <b>{{ t("放在同一个目录") }}</b>{{ t("（或把另一个版本的 exe 放进来）即可：") }}<code>config.json</code>{{ t("、") }}<code>runtime\</code>{{ t("、") }}<code>library\</code>{{ t("、Mod 备份与下载记录全部共用，不用重装、不用重新下载 Mod。") }}</li>
        <li>{{ t("轻量版启动时会把游戏目录里的 ReShade 残留移走（有备份），并把 XXMI 注入库收敛成只有服装 Mod 的 loader；换回完整版后，完整版的自检会按你原来的开关重新铺好 ReShade / DLSS5。") }}</li>
        <li>{{ t("轻量版") }}<b>{{ t("不会改写") }}</b>{{ t("配置里的 ReShade 开关值 —— 所以切回完整版时，你之前的开关状态与能力原样保留。") }}</li>
        <li>{{ t("两个版本各自更新：轻量版只检查轻量版的更新包，完整版只检查完整版的，互不覆盖。") }}</li>
      </ul>
    </Card>

    <Card :title="t('反馈与源码')">
      <ul class="list-disc pl-5 space-y-1.5 text-sm leading-6">
        <li>{{ t("项目地址：") }}<a class="text-accent" :href="repo" target="_blank" rel="noopener">{{ repo }}</a></li>
        <li><b>{{ t("问题反馈") }}</b>{{ t("（报错、游戏崩溃、Mod 不生效都发这里，崩溃时请附上程序生成的 zip + 现象）：") }}<a class="text-accent" :href="issues" target="_blank" rel="noopener">{{ issues }}</a></li>
        <li><b>{{ t("QQ 群") }}</b>{{ t("：") }}<code>1045239747</code>{{ t("（加群验证答案：") }}<code>jing_hy</code>{{ t("）—— 不方便用 GitHub / 想直接问，都可以在群里发诊断包；群里发时同样") }}<b>{{ t("附上现象") }}</b>{{ t("。") }}</li>
        <li>{{ t("版本发布（下载新版 exe / 便携包）：") }}<a class="text-accent" :href="releases" target="_blank" rel="noopener">{{ releases }}</a></li>
      </ul>
    </Card>

    <Card :title="t('也可以让 AI 帮你修')">
      <div class="text-sm leading-6 space-y-2">
        <p>
          <b>{{ t("UP 在上学期间不一定有时间修 bug") }}</b>{{ t("，提倡使用 AI 工具自行修复 —— 比如") }}
          <a class="text-accent" href="https://deepseek.com/harness" target="_blank" rel="noopener">{{ t("DSH（DeepSeek Harness）") }}</a>{{ t("，现在下载就送 6 块。") }}
        </p>
        <p class="text-xs" style="color: var(--text-muted)">
          {{ t("把下面这段发给它（最后一句换成你的实际问题、并附上诊断包）：") }}
        </p>
        <pre class="text-xs p-2 rounded whitespace-pre-wrap leading-5"
             style="background: var(--surface-2); border: 1px solid var(--border)">{{ t("我现在使用 emc 出现问题，请你帮我检查并修复。emc 为开源项目，仓库在 https://github.com/jing-hy/EndfieldModController ，请你先查阅 https://github.com/jing-hy/EndfieldModController/blob/main/AGENTS.md ，自行查找或向我询问 emc 本地位置和终末地位置。我遇到的具体问题是：（这里写你的问题）") }}</pre>
        <p class="text-xs" style="color: var(--text-muted)">
          {{ t("它照着那份说明定位、改、自测；如果确认是本程序的问题，修好可以提 PR 上来（没有 GitHub 账号就在群里发）。") }}
        </p>
      </div>
    </Card>
  </div>
</template>
