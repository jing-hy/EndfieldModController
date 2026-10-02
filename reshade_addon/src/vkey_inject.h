// vkey_inject.h —— 进程内"虚拟按键"注入（不经 Windows 输入队列）
//
// 为什么需要它（2026-10-01 ~ 10-02 的排查结论，别再往回走）：
//
//   面板最初用 `SendInput` 发键，实测**在终末地里完全无效**（用户手按 Mod 自带的键一切正常）。
//   现场证据：三批对照探针（带修饰键的 F13..F24 / F1..F12 / 不带修饰键的 F13..F24）
//   **全部 0 触发**，而 `SendInput` 返回值正常 ⇒ 合成输入在进入游戏进程之前就被吞掉了
//   （典型的低级键盘钩子/反作弊输入过滤，它同时也会让 win32k 的异步键状态表不更新）。
//   ⇒ **任何"发合成输入事件"的路子（SendInput / keybd_event / PostMessage）都会被同一个
//     机制拦掉，不值得再试。**
//
//   换一条路：**3DMigoto/EFMI 不是靠消息读键的，它每帧轮询 `GetAsyncKeyState`**
//   （实测依据：`EFMI\d3d11.dll` 的导入表里 `GetAsyncKeyState` 有且只有这一处键盘读取入口，
//     没有 raw input、没有 DirectInput 键盘、也没有 SendInput）。
//   面板 addon 与 EFMI **在同一个进程里** ⇒ 只要把 EFMI 那一处 `GetAsyncKeyState`
//   的调用点接到我们的函数上，就能让 EFMI"以为某个键被按下了"：
//   不产生任何输入事件、不碰任何代码段（只改 EFMI 模块自己的导入表指针），
//   因此输入过滤层根本看不到这件事。
//
// 采用 **IAT hook**（只改目标模块的导入地址表）而不是 inline hook：
//   * 影响面最小 —— 只有 EFMI 的读键受影响，游戏本体与其他 addon 完全不知道；
//   * 不需要可执行内存、不修改任何代码字节（对反作弊扫描最不敏感）。
//
// 自测（`scripts/test_addon_hook.py`）：造一个假的 `d3d11.dll`（同样只通过 IAT 调
// `GetAsyncKeyState` 轮询）+ 一个宿主 exe，验证"按下被读到 / 单次触发语义 / 到点自动释放"。
#pragma once

#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif

#include <Windows.h>
#include <TlHelp32.h>

#include <algorithm>
#include <atomic>
#include <cstring>
#include <cwctype>
#include <string>
#include <vector>

namespace vkey
{

// ---------------------------------------------------------------------------
// 日志回调（由 addon 提供；测试宿主可传自己的实现）
// ---------------------------------------------------------------------------

using LogFn = void (*)(const char *message);

inline LogFn &log_fn()
{
    static LogFn fn = nullptr;
    return fn;
}

inline void set_logger(LogFn fn) { log_fn() = fn; }

inline void log(const std::string &text)
{
    if (log_fn() != nullptr)
        log_fn()(text.c_str());
}

// ---------------------------------------------------------------------------
// 虚拟按键状态表
//
// 按 VK 直接索引（0..255，GetAsyncKeyState 的定义域），无锁读写：
//   * UI 线程只写 `expire` / `fresh`；
//   * EFMI 的渲染线程在 hook 里只读 `expire`、用 `InterlockedExchange` 消费 `fresh`。
// 键状态本来就是这样"最后写入者胜"的语义，不需要更强的一致性。
// ---------------------------------------------------------------------------

constexpr int kMaxVirtualKey = 256;

inline volatile LONG *expire_table()
{
    static volatile LONG table[kMaxVirtualKey] = {};
    return table;
}

inline volatile LONG *fresh_table()
{
    static volatile LONG table[kMaxVirtualKey] = {};
    return table;
}

inline std::atomic<long long> &stat_calls()   // hook 被 EFMI 调用的次数
{
    static std::atomic<long long> value{0};
    return value;
}

inline std::atomic<long long> &stat_hits()    // 其中"我们伪造的键"被读到的次数
{
    static std::atomic<long long> value{0};
    return value;
}

inline std::atomic<long long> &stat_presses() // 面板发了多少次按键
{
    static std::atomic<long long> value{0};
    return value;
}

// 让 *vk* 在接下来 `duration_ms` 毫秒里"看起来是被按住的"。
// 时长按"跨帧"选（2026-10-01 现场：装了 debug 日志时帧时间能到 70~100ms，
// 只按下 70ms 会整帧被错过）—— 180ms 在 30fps 下也有 5 帧以上。
inline void press(int vk, DWORD duration_ms = 180)
{
    if (vk <= 0 || vk >= kMaxVirtualKey)
        return;
    fresh_table()[vk] = 1;
    expire_table()[vk] = static_cast<LONG>(GetTickCount()) + static_cast<LONG>(duration_ms);
}

// 一次"按键动作"（= 用户点一下面板按钮）：可能同时伪造修饰键与主键，
// 但计数按**动作**算一次。
inline void press_all(const int *vks, size_t count, DWORD duration_ms = 180)
{
    const LONG until = static_cast<LONG>(GetTickCount()) + static_cast<LONG>(duration_ms);
    bool any = false;
    for (size_t i = 0; i < count; ++i)
    {
        const int vk = vks[i];
        if (vk <= 0 || vk >= kMaxVirtualKey)
            continue;
        fresh_table()[vk] = 1;
        expire_table()[vk] = until;
        any = true;
    }
    if (any)
        stat_presses().fetch_add(1, std::memory_order_relaxed);
}

// 当前是否有虚拟键处于按下状态（只给面板显示用）。
inline bool any_active()
{
    const LONG now = static_cast<LONG>(GetTickCount());
    volatile LONG *table = expire_table();
    for (int vk = 1; vk < kMaxVirtualKey; ++vk)
    {
        const LONG until = table[vk];
        if (until != 0 && static_cast<LONG>(now - until) < 0)
            return true;
    }
    return false;
}

// ---------------------------------------------------------------------------
// hook 本体
// ---------------------------------------------------------------------------

using GetAsyncKeyStateFn = SHORT(WINAPI *)(int);

inline GetAsyncKeyStateFn &real_get_async_key_state()
{
    static GetAsyncKeyStateFn fn = nullptr;
    return fn;
}

inline SHORT WINAPI hook_get_async_key_state(int vKey)
{
    stat_calls().fetch_add(1, std::memory_order_relaxed);

    if (vKey > 0 && vKey < kMaxVirtualKey)
    {
        const LONG until = expire_table()[vKey];
        if (until != 0)
        {
            const LONG now = static_cast<LONG>(GetTickCount());
            if (static_cast<LONG>(now - until) < 0)
            {
                stat_hits().fetch_add(1, std::memory_order_relaxed);
                // 第一次读到：低位也置位（`& 1` 语义的"这一帧刚按下"），
                // 之后只保留高位（`& 0x8000` 语义的"正按住"）——
                // 两种写法都只触发**一次**，不会在 180ms 窗口里被 toggle 多次。
                if (InterlockedExchange(const_cast<volatile LONG *>(&fresh_table()[vKey]), 0) != 0)
                    return static_cast<SHORT>(0x8001);
                return static_cast<SHORT>(0x8000);
            }
            expire_table()[vKey] = 0;   // 窗口结束：立刻恢复成真实状态
        }
    }

    GetAsyncKeyStateFn real = real_get_async_key_state();
    return real != nullptr ? real(vKey) : static_cast<SHORT>(0);
}

// ---------------------------------------------------------------------------
// 安装（IAT hook）
// ---------------------------------------------------------------------------

struct HookStatus
{
    bool installed = false;
    bool module_found = false;
    bool import_found = false;
    int patched = 0;
    std::wstring module_path;
    std::string target_function = "GetAsyncKeyState";
};

inline HookStatus &status()
{
    static HookStatus value;
    return value;
}

// 被改写的那一格 IAT 与它原来的值 —— 卸载时必须改回去：
// addon 一旦被卸载（ReShade 允许在运行时禁用 add-on），EFMI 若还指着我们的函数，
// 下一次读键就会跳进已卸载的代码。
inline void **&patched_slot()
{
    static void **slot = nullptr;
    return slot;
}

inline void *&original_target()
{
    static void *value = nullptr;
    return value;
}

inline bool contains_ci(const std::wstring &haystack, const wchar_t *needle)
{
    if (haystack.empty())
        return false;
    std::wstring lower = haystack;
    for (auto &ch : lower)
        ch = static_cast<wchar_t>(::towlower(ch));
    std::wstring target = needle;
    for (auto &ch : target)
        ch = static_cast<wchar_t>(::towlower(ch));
    return lower.find(target) != std::wstring::npos;
}

// 只给日志用：把宽路径压成窄串（非 ASCII 一律问号，日志里够读了）。
inline std::string narrow(const std::wstring &text)
{
    std::string out;
    for (const wchar_t ch : text)
        out += (ch < 128) ? static_cast<char>(ch) : '?';
    return out;
}

// 进程里所有同名模块（返回完整路径）。
inline std::vector<std::wstring> modules_named(const wchar_t *basename)
{
    std::vector<std::wstring> found;
    HANDLE snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, GetCurrentProcessId());
    if (snapshot == INVALID_HANDLE_VALUE)
        return found;
    MODULEENTRY32W entry = {};
    entry.dwSize = sizeof(entry);
    if (Module32FirstW(snapshot, &entry))
    {
        do
        {
            if (_wcsicmp(entry.szModule, basename) == 0)
                found.emplace_back(entry.szExePath);
        } while (Module32NextW(snapshot, &entry));
    }
    CloseHandle(snapshot);
    return found;
}

// 所有候选模块；把路径含 EFMI 的排前面（真 EFMI 就是从那儿加载的）。
// 环境变量 `MODECONTROLLER_HOOK_MODULE` 可以指定完整路径或模块名 —— 离线自测用的通道，
// 正式链路不设它。
inline std::vector<std::wstring> candidates(const wchar_t *basename)
{
    std::vector<std::wstring> found;
    wchar_t override_path[1024] = {};
    const DWORD override_len = GetEnvironmentVariableW(L"MODECONTROLLER_HOOK_MODULE", override_path, 1024);
    if (override_len > 0 && override_len < 1024)
    {
        found.emplace_back(override_path);
        return found;
    }
    found = modules_named(basename);
    std::stable_sort(found.begin(), found.end(),
                     [](const std::wstring &left, const std::wstring &right)
                     {
                         return (contains_ci(left, L"EFMI") ? 0 : 1) < (contains_ci(right, L"EFMI") ? 0 : 1);
                     });
    return found;
}

// 遍历 *module* 的导入表，把 `func_name` 的 IAT 项换成 *replacement*。
// **不限定来源 DLL**：EFMI 的 d3d11.dll 里对 GetAsyncKeyState 的导入可能在
// USER32.dll 也可能经 api-set 转发，认名字比认 DLL 名稳。
// *slot_out*（可选）回传被改写的那一格地址，卸载时要靠它改回去。
inline bool patch_import(HMODULE module, const char *func_name, void *replacement, void **original,
                         void ***slot_out = nullptr)
{
    auto base = reinterpret_cast<BYTE *>(module);
    auto dos = reinterpret_cast<IMAGE_DOS_HEADER *>(base);
    if (dos->e_magic != IMAGE_DOS_SIGNATURE)
        return false;
    auto nt = reinterpret_cast<IMAGE_NT_HEADERS *>(base + dos->e_lfanew);
    if (nt->Signature != IMAGE_NT_SIGNATURE)
        return false;

    const IMAGE_DATA_DIRECTORY &dir =
        nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT];
    if (dir.VirtualAddress == 0)
        return false;

    auto descriptor = reinterpret_cast<IMAGE_IMPORT_DESCRIPTOR *>(base + dir.VirtualAddress);
    for (; descriptor->Name != 0; ++descriptor)
    {
        auto lookup = reinterpret_cast<IMAGE_THUNK_DATA *>(
            base + (descriptor->OriginalFirstThunk != 0 ? descriptor->OriginalFirstThunk
                                                        : descriptor->FirstThunk));
        auto iat = reinterpret_cast<IMAGE_THUNK_DATA *>(base + descriptor->FirstThunk);
        for (; lookup->u1.AddressOfData != 0; ++lookup, ++iat)
        {
            if (IMAGE_SNAP_BY_ORDINAL(lookup->u1.Ordinal))
                continue;
            auto import = reinterpret_cast<IMAGE_IMPORT_BY_NAME *>(base + lookup->u1.AddressOfData);
            if (std::strcmp(reinterpret_cast<const char *>(import->Name), func_name) != 0)
                continue;

            void *current = reinterpret_cast<void *>(iat->u1.Function);
            if (current == replacement)
            {
                if (original != nullptr && *original == nullptr)
                    *original = current;
                return true;                 // 已经是我们自己（重复安装）
            }

            DWORD old_protect = 0;
            if (!VirtualProtect(&iat->u1.Function, sizeof(void *), PAGE_READWRITE, &old_protect))
                return false;
            if (original != nullptr)
                *original = current;
            if (slot_out != nullptr)
                *slot_out = reinterpret_cast<void **>(&iat->u1.Function);
            iat->u1.Function = reinterpret_cast<ULONG_PTR>(replacement);
            DWORD ignored = 0;
            VirtualProtect(&iat->u1.Function, sizeof(void *), old_protect, &ignored);
            FlushInstructionCache(GetCurrentProcess(), &iat->u1.Function, sizeof(void *));
            return true;
        }
    }
    return false;
}

// 幂等安装。返回是否已接上 EFMI 的读键路径。
//
// **逐个候选试**（2026-10-02 加固）：进程里可能同时存在多份同名模块（游戏目录 / 数据根 /
// system32），而"哪一份才是 EFMI 正在用的"没有百分之百可靠的路径判据 —— 所以这里
// **按能力挑**：谁的导入表里有 `GetAsyncKeyState` 就接谁（含 EFMI 路径的排前面）。
inline bool install(const wchar_t *basename = L"d3d11.dll")
{
    HookStatus &state = status();
    if (state.installed)
        return true;

    const std::vector<std::wstring> listed = candidates(basename);
    if (listed.empty())
    {
        std::string narrow_name;
        for (const wchar_t *p = basename; p != nullptr && *p != 0; ++p)
            narrow_name += (*p < 128) ? static_cast<char>(*p) : '?';
        log("vkey: 进程里没有找到 " + narrow_name + "（EFMI 未注入？）");
        return false;
    }
    state.module_found = true;

    for (const std::wstring &path : listed)
    {
        HMODULE module = GetModuleHandleW(path.c_str());
        if (module == nullptr)
            module = LoadLibraryW(path.c_str());
        if (module == nullptr)
        {
            log("vkey: 模块句柄拿不到，跳过 -> " + narrow(path));
            continue;
        }

        void *original = nullptr;
        void **slot = nullptr;
        if (!patch_import(module, "GetAsyncKeyState", reinterpret_cast<void *>(&hook_get_async_key_state),
                          &original, &slot))
        {
            log("vkey: 该模块的导入表里没有 GetAsyncKeyState，跳过 -> " + narrow(path));
            continue;
        }

        state.module_path = path;
        state.import_found = true;
        state.patched += 1;
        state.installed = true;
        patched_slot() = slot;
        original_target() = original;
        if (real_get_async_key_state() == nullptr && original != nullptr &&
            original != reinterpret_cast<void *>(&hook_get_async_key_state))
            real_get_async_key_state() = reinterpret_cast<GetAsyncKeyStateFn>(original);

        log("vkey: 已接上 EFMI 读键路径 -> " + narrow(path));
        return true;
    }

    log("vkey: 所有同名模块的导入表里都没有 GetAsyncKeyState（这条路走不通，需要另想办法）");
    return false;
}

// 卸载：把导入表改回原样。addon 被禁用/卸载前必须调用 —— 否则 EFMI 会调到已卸载的代码。
inline bool uninstall()
{
    void **slot = patched_slot();
    if (slot == nullptr)
        return false;
    DWORD old_protect = 0;
    if (VirtualProtect(slot, sizeof(void *), PAGE_READWRITE, &old_protect))
    {
        *slot = original_target();
        DWORD ignored = 0;
        VirtualProtect(slot, sizeof(void *), old_protect, &ignored);
        FlushInstructionCache(GetCurrentProcess(), slot, sizeof(void *));
        patched_slot() = nullptr;
        status().installed = false;
        log("vkey: 已把 GetAsyncKeyState 导入恢复原样（卸载）");
        return true;
    }
    log("vkey: 卸载时恢复导入失败（VirtualProtect 拒绝）");
    return false;
}

} // namespace vkey
