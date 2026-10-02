// hook_host.exe —— vkey_inject 的离线自测宿主。
//
// 它扮演的是"游戏进程"：加载假 EFMI（fake_efmi_d3d11.dll），装上 hook，
// 然后用 `vkey::press()` 注入按键，逐条断言假 EFMI 读到的东西。
//
// 覆盖的行为（每一条都对应线上必须成立的一件事）：
//   ① 目标模块找得到、导入表里确实有 GetAsyncKeyState、hook 装得上；
//   ② 注入后**第一帧**读到"正按住 + 刚按下"，后续帧只读到"正按住"
//      （低位只出现一次 ⇒ 不会在一个按下窗口里把 toggle 触发多次）；
//   ③ 窗口结束（180ms 级别）后**自动释放**，不需要谁来收尾；
//   ④ 一次动作可以同时伪造修饰键 + 主键（`ALT 0` 这类）；
//   ⑤ 只影响目标模块：宿主**自己**的 GetAsyncKeyState 完全不受影响（真实状态）；
//   ⑥ 没注入的键原样透传真实状态。
#include "../src/vkey_inject.h"

#include <Windows.h>

#include <cstdio>
#include <string>

using FrameReadFn = int (*)(int);
using ThunkFn = void *(*)(void);

static int g_failures = 0;
static int g_checks = 0;

static void check(bool ok, const char *what)
{
    ++g_checks;
    if (!ok)
        ++g_failures;
    std::printf("%s %s\n", ok ? "[PASS]" : "[FAIL]", what);
}

int main(int argc, char **argv)
{
    if (argc < 2)
    {
        std::printf("[FAIL] 用法: hook_host.exe <fake_efmi_d3d11.dll 绝对路径>\n");
        return 2;
    }

    // argv 是窄字符，转成宽字符路径加载
    std::wstring wide;
    for (const char *p = argv[1]; *p != 0; ++p)
        wide += static_cast<wchar_t>(static_cast<unsigned char>(*p));

    HMODULE fake = LoadLibraryW(wide.c_str());
    if (fake == nullptr)
    {
        std::printf("[FAIL] 加载假 EFMI 失败: %lu\n", GetLastError());
        return 2;
    }

    auto frame_read = reinterpret_cast<FrameReadFn>(GetProcAddress(fake, "FakeFrameRead"));
    auto thunk_of = reinterpret_cast<ThunkFn>(GetProcAddress(fake, "FakeThunkAddress"));
    if (frame_read == nullptr || thunk_of == nullptr)
    {
        std::printf("[FAIL] 假 EFMI 的导出函数取不到\n");
        return 2;
    }
    check(thunk_of() != nullptr, "假 EFMI 确实经由导入表调用 GetAsyncKeyState");

    // ①②③ 安装
    check(vkey::install(), "vkey::install() 返回成功");
    check(vkey::status().installed, "hook 状态 = 已安装");
    check(vkey::status().import_found, "在目标模块导入表里找到 GetAsyncKeyState");

    // 基线
    check(frame_read(VK_RIGHT) == 0, "未注入时读到『没按下』");

    const long long calls_before = vkey::stat_calls().load();

    // ② 注入 → 第一帧 / 后续帧
    vkey::press(VK_RIGHT, 400);
    const int first = frame_read(VK_RIGHT);
    check((first & 1) != 0, "注入后第一帧读到『正按住』");
    check((first & 2) != 0, "注入后第一帧读到『刚按下』");

    const int second = frame_read(VK_RIGHT);
    check((second & 1) != 0, "后续帧持续读到『正按住』（跨帧有效）");
    check((second & 2) == 0, "『刚按下』只出现一次（窗口内不会反复触发）");

    check(vkey::stat_calls().load() > calls_before, "hook 被调用次数在增长（调用确实走了我们的函数）");
    check(vkey::stat_hits().load() == 2, "命中计数按每次读取累加（两次读取 = 2 次命中）");

    // ⑤ 只影响目标模块：宿主自己的 GetAsyncKeyState 不受影响
    check((::GetAsyncKeyState(VK_RIGHT) & 0x8000) == 0,
          "宿主自己的 GetAsyncKeyState 不受影响（注入只作用于目标模块）");

    // ④ 修饰键 + 主键一起伪造
    int combo[2] = {VK_MENU, '0'};
    vkey::press_all(combo, 2, 400);
    check((frame_read(VK_MENU) & 1) != 0, "组合键：修饰键（Alt）被读到按下");
    check((frame_read('0') & 1) != 0, "组合键：主键（0）被读到按下");

    // ⑥ 没注入的键原样透传
    const SHORT real_f24 = ::GetAsyncKeyState(VK_F24);
    check((frame_read(VK_F24) & 3) == (real_f24 & 3), "未注入的键原样透传真实状态");

    // ③ 自动释放
    Sleep(600);
    check(frame_read(VK_RIGHT) == 0, "窗口结束后自动释放（不需要收尾）");
    check(frame_read(VK_MENU) == 0, "组合键窗口结束后自动释放");
    check(!vkey::any_active(), "没有任何按键还处于注入状态");

    // ⑦ 卸载：导入表必须改回原样（否则 addon 被卸载后 EFMI 会跳进已卸载的代码）
    check(vkey::uninstall(), "卸载时能恢复导入表");
    check(!vkey::status().installed, "卸载后状态 = 未安装");
    const SHORT real_after = ::GetAsyncKeyState(VK_RIGHT);
    check((frame_read(VK_RIGHT) & 3) == (real_after & 3), "卸载后目标模块读到的又是真实状态（走回真实 API）");

    std::printf("\n%d 项断言，%d 项失败\n", g_checks, g_failures);
    return g_failures == 0 ? 0 : 1;
}
