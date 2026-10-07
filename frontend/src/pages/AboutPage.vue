<script setup>
import { computed } from "vue";
import { store } from "../store.js";
import Card from "../components/ui/Card.vue";

const REPO = "https://github.com/jing-hy/EndfieldModController";
const repo = computed(() => store.state.repo_url || REPO);
const issues = computed(() => store.state.issues_url || REPO + "/issues");
const releases = computed(() => store.state.releases_url || REPO + "/releases");
</script>

<template>
  <div class="space-y-4">
    <Card title="当前路线：三件套（DLSS5 + 第一人称 + 服装 Mod）">
      <ul class="list-disc pl-5 space-y-1.5 text-sm leading-6">
        <li>唯一 ReShade 底座 = 内置 <code>runtime\dlss5\d3d12.dll</code>（ReShade 6.8.0），里面同时挂着 <b>RenoDX-DLSS5</b> 与 <b>Endfield Enhancer（第一人称）</b>两个插件。</li>
        <li>由 XXMI 在启动游戏时注入两个 DLL：<code>runtime\dlss5\d3d12.dll</code> + <code>runtime\builtin\XXMI\EFMI\d3d11.dll</code>（服装 Mod 引擎）。</li>
        <li>同一进程只能有一个 ReShade，所以两个 <code>d3d12.dll</code> 不要同时注入 —— 本程序只注入一个。</li>
        <li>启动页的「三件套注入」开关直接改写 XXMI 的注入库：开 = 三件套齐活，关 = 只跑服装 Mod。</li>
        <li>外部选择 Mod 库里的 Mod，程序把选中项 staging 到 <code>EFMI\Mods\MC_*</code>（同角色互斥、原始快捷键屏蔽），原库只读。</li>
        <li>游戏目录保持干净：不写任何 ReShade/addon，注入全部由 XXMI 完成。</li>
      </ul>
    </Card>

    <Card title="进游戏后">
      <ul class="list-disc pl-5 space-y-1.5 text-sm leading-6">
        <li>按 <kbd class="kbd">Home</kbd> 打开 ReShade：插件页应同时有 <b>RenoDX-DLSS5</b> 与 <b>Endfield Enhancer</b>。</li>
        <li>DLSS5 页勾「启用 DLSS 神经渲染」+「启用超分」；风格选电影，总体/结构强度拉满，角色皮肤结构 ≥ 0。</li>
        <li>Enhancer 的 Camera 页：先开 Camera Controls → First Person = On → Third Person During Combat = <b>Off</b>（打 boss 才不会被踢出第一人称）→ EFMI/XXMI Compatibility = On。</li>
        <li>快捷键：<kbd class="kbd">F6</kbd> 神经渲染开关、<kbd class="kbd">F11</kbd> Mod 显示、<kbd class="kbd">,</kbd> 第一人称、<kbd class="kbd">F12</kbd> EFMI 帮助。</li>
      </ul>
    </Card>

    <Card title="Endfield Poser（摆姿 / MMD 播放，可选）">
      <ul class="list-disc pl-5 space-y-1.5 text-sm leading-6">
        <li>上游 <a class="text-accent" href="https://github.com/OedoSoldier/Endfield-Poser" target="_blank" rel="noopener">OedoSoldier/Endfield-Poser</a>（AGPL-3.0，二进制不随包分发）。</li>
        <li>它和乳摇（SecondaryMotion）用<b>同一套注入机制</b>：游戏目录里的 <code>d3dcompiler_47</code> proxy 会把 <code>plugin\*.dll</code> 全部加载进游戏进程，所以两个插件能共存；卸载其中一方时，只要另一方还在就保留 proxy。</li>
        <!-- ⚠️ **C15：这两条 0.9.5 的说明页里有，换代时丢了**（2026-10-03 补回归）——
             ① 用之前要在游戏内确认上游的用户协议（法律/礼貌上都该说）；
             ② 明确告诉用户**入口在哪**（启动页有「打开摆姿页」按钮）。 -->
        <li>使用前请在游戏内确认它的《用户协议》。</li>
        <li>要打开摆姿页，用<b>启动页</b>的「打开摆姿页（Poser）」按钮（游戏要在运行中）。</li>
        <li>游戏内快捷键：<kbd class="kbd">L</kbd> 显示/隐藏面板、<kbd class="kbd">P</kbd> 冻结/解冻、按住 <kbd class="kbd">Alt</kbd> 呼出光标、<kbd class="kbd">Ctrl</kbd>+<kbd class="kbd">F5</kbd>/<kbd class="kbd">F6</kbd>/<kbd class="kbd">F7</kbd>/<kbd class="kbd">F8</kbd> 播放/暂停/停止/回首帧；它还有一个独立摆姿页 <code>http://127.0.0.1:18923</code>。</li>
        <li>开关含义：关掉只把 <code>plugin\poser.dll</code> 改名（可逆、不动 proxy、不动其它插件）；要真正移除文件请点设置页的卸载（走它自己的卸载向导）。</li>
      </ul>
    </Card>

    <Card title="注意">
      <div class="rounded-lg p-3 mb-3"
           style="background: color-mix(in srgb, var(--warn) 10%, transparent); border-left: 3px solid var(--warn)">
        <div class="text-sm font-medium" style="color: var(--warn)">Mod 有 ToS / 账号风险</div>
        <div class="text-sm mt-1 leading-6">显卡压力也比单开大（UP 主建议 40 系以上）。请自行判断是否使用。</div>
      </div>
      <ul class="list-disc pl-5 space-y-1.5 text-sm leading-6">
        <li>游戏目录里的第三方 proxy（<code>d3dcompiler_47.dll</code> / <code>vulkan-1.dll</code>）属于别的工具（如 SecondaryMotion 摇乳管理器），与本方案无关，但会出现在「检查游戏目录注入」列表里。</li>
      </ul>
    </Card>

    <Card title="致谢">
      <ul class="list-disc pl-5 space-y-1.5 text-sm leading-6">
        <li><b>第一人称插件（Endfield Enhancer）</b>由 <b>B 站 UP 主 Hirahido</b> 制作，感谢授权与分享。</li>
        <li>路线参考 B 站教程 <code>BV1XMh76UEA5</code>《以防你不知道，你也可以终末地+XXMI+DLSS5+第一人称视角》。</li>
        <li>其余第三方组件（XXMI / EFMI / ReShade / RenoDX / DLSS5-Feeder / iMMERSE / ShakingBreastManager）见 README 第九节，均为各自作者所有。</li>
      </ul>
    </Card>

    <Card title="反馈与源码">
      <ul class="list-disc pl-5 space-y-1.5 text-sm leading-6">
        <li>项目地址：<a class="text-accent" :href="repo" target="_blank" rel="noopener">{{ repo }}</a></li>
        <li><b>问题反馈</b>（报错、游戏崩溃、Mod 不生效都发这里，崩溃时请附上程序生成的 zip + 现象）：<a class="text-accent" :href="issues" target="_blank" rel="noopener">{{ issues }}</a></li>
        <li><b>QQ 群</b>：<code>1045239747</code>（加群验证答案：<code>jing_hy</code>）—— 不方便用 GitHub / 想直接问，都可以在群里发诊断包；群里发时同样<b>附上现象</b>。</li>
        <li>版本发布（下载新版 exe / 便携包）：<a class="text-accent" :href="releases" target="_blank" rel="noopener">{{ releases }}</a></li>
      </ul>
    </Card>

    <!-- 「让 AI 帮你修」（2026-10-07 用户要求）——
         为什么放在这里：UP 在上学，报错只能等他有空，很多小问题其实**用 AI 对着源码就能修**，
         而仓库里已经有一份给 AI 看的 `AGENTS.md`（自动会被这类工具读到）。
         提示词直接给成可复制的整段，用户不用自己组织语言。 -->
    <Card title="也可以让 AI 帮你修">
      <div class="text-sm leading-6 space-y-2">
        <p>
          <b>UP 在上学期间不一定有时间修 bug</b>，提倡使用 AI 工具自行修复 —— 比如
          <a class="text-accent" href="https://deepseek.com/harness" target="_blank" rel="noopener">DSH（DeepSeek Harness）</a>，
          现在下载就送 6 块。
        </p>
        <p class="text-xs" style="color: var(--text-muted)">
          把下面这段发给它（最后一句换成你的实际问题、并附上诊断包）：
        </p>
        <pre class="text-xs p-2 rounded whitespace-pre-wrap leading-5"
             style="background: var(--surface-2); border: 1px solid var(--border)">我现在使用 emc 出现问题，请你帮我检查并修复。emc 为开源项目，仓库在 https://github.com/jing-hy/EndfieldModController ，请你先查阅 https://github.com/jing-hy/EndfieldModController/blob/main/AGENTS.md ，自行查找或向我询问 emc 本地位置和终末地位置。我遇到的具体问题是：（这里写你的问题）</pre>
        <p class="text-xs" style="color: var(--text-muted)">
          它照着那份说明定位、改、自测；如果确认是本程序的问题，修好可以提 PR 上来（没有 GitHub 账号就在群里发）。
        </p>
      </div>
    </Card>
  </div>
</template>
