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
        <li>按 <code>Home</code> 打开 ReShade：插件页应同时有 <b>RenoDX-DLSS5</b> 与 <b>Endfield Enhancer</b>。</li>
        <li>DLSS5 页勾「启用 DLSS 神经渲染」+「启用超分」；风格选电影，总体/结构强度拉满，角色皮肤结构 ≥ 0。</li>
        <li>Enhancer 的 Camera 页：先开 Camera Controls → First Person = On → Third Person During Combat = <b>Off</b>（打 boss 才不会被踢出第一人称）→ EFMI/XXMI Compatibility = On。</li>
        <li>快捷键：<code>F6</code> 神经渲染开关、<code>F11</code> Mod 显示、<code>,</code> 第一人称、<code>F12</code> EFMI 帮助。</li>
      </ul>
    </Card>

    <Card title="Endfield Poser（摆姿 / MMD 播放，可选）">
      <ul class="list-disc pl-5 space-y-1.5 text-sm leading-6">
        <li>上游 <a class="text-accent" href="https://github.com/OedoSoldier/Endfield-Poser" target="_blank" rel="noopener">OedoSoldier/Endfield-Poser</a>（AGPL-3.0，二进制不随包分发）。</li>
        <li>它和乳摇（SecondaryMotion）用<b>同一套注入机制</b>：游戏目录里的 <code>d3dcompiler_47</code> proxy 会把 <code>plugin\*.dll</code> 全部加载进游戏进程，所以两个插件能共存；卸载其中一方时，只要另一方还在就保留 proxy。</li>
        <li>游戏内快捷键：<code>L</code> 显示/隐藏面板、<code>P</code> 冻结/解冻、按住 <code>Alt</code> 呼出光标、<code>Ctrl+F5/F6/F7/F8</code> 播放/暂停/停止/回首帧；它还有一个独立摆姿页 <code>http://127.0.0.1:18923</code>。</li>
        <li>开关含义：关掉只把 <code>plugin\poser.dll</code> 改名（可逆、不动 proxy、不动其它插件）；要真正移除文件请点设置页的卸载（走它自己的卸载向导）。</li>
      </ul>
    </Card>

    <Card title="注意">
      <ul class="list-disc pl-5 space-y-1.5 text-sm leading-6">
        <li>Mod 有 ToS / 账号风险；显卡压力也比单开大（UP 主建议 40 系以上）。</li>
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
  </div>
</template>
