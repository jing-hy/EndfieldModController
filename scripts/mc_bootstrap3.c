/*
 * mc_bootstrap3.c — 进程内桥（变体 B+：3DMigoto 先、ReShade 后）
 *
 * 与 mc_bootstrap2.c 的区别：那个是「ReShade 先、EFMI 后」（实测：ReShade 建立 hook 后
 * 3DMigoto 的 Mod 加载全部失效，Processing=0）。
 * 这个反过来：**先让 3DMigoto 建立 d3d11 hook（Mod 才能加载），再把 ReShade 挂上去**。
 *
 * 背景实测（2026-09-27）：
 *   - 只有 3DMigoto（无 ReShade）：Mod 正常（customRes=63~67、ShapeKey 生效），游戏 116 秒不崩
 *   - ReShade 作为 d3d12.dll 代理先加载：3DMigoto 连 Mod 扫描都没做（Processing=0、customRes=0）
 *   - ReShade 先 + EFMI 后（mc_bootstrap2）：55 秒崩 nvgpucomp64
 *
 * 日志：<dll 所在目录>\mc_bootstrap3.log
 */
#include <windows.h>
#include <stdio.h>
#include <stdarg.h>
#include <string.h>

static char g_dir[MAX_PATH];
static char g_log[MAX_PATH];
static CRITICAL_SECTION g_cs;

static void blog(const char *fmt, ...) {
    char msg[1024];
    char line[1200];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(msg, sizeof(msg), fmt, ap);
    va_end(ap);
    SYSTEMTIME st;
    GetLocalTime(&st);
    snprintf(line, sizeof(line), "[%02d:%02d:%02d.%03d] %s",
             st.wHour, st.wMinute, st.wSecond, st.wMilliseconds, msg);
    EnterCriticalSection(&g_cs);
    FILE *f = fopen(g_log, "a");
    if (f) { fputs(line, f); fputc(10, f); fclose(f); }
    LeaveCriticalSection(&g_cs);
}

static HMODULE load_from_dir(const char *name) {
    char path[MAX_PATH];
    HMODULE h;
    snprintf(path, MAX_PATH, "%s%c%s", g_dir, (char)92, name);
    blog("loading %s", path);
    h = LoadLibraryExA(path, NULL, LOAD_WITH_ALTERED_SEARCH_PATH);
    blog("load result %s h=%p err=%lu", name, (void *)h, (unsigned long)GetLastError());
    return h;
}

static DWORD WINAPI bootstrap_worker(LPVOID param) {
    DWORD started = GetTickCount();
    DWORD last_report = 0;
    HMODULE hd3d, hrs;
    (void)param;

    blog("worker start pid=%lu", (unsigned long)GetCurrentProcessId());

    /* 1) 等 dxgi.dll —— 进程刚创建、反作弊尚未挂载的可写窗口 */
    for (;;) {
        if (GetModuleHandleA("dxgi.dll")) {
            blog("dxgi ready elapsed=%lu", (unsigned long)(GetTickCount() - started));
            break;
        }
        if (GetTickCount() - started >= 120000) {
            blog("wait timeout for dxgi elapsed=%lu", (unsigned long)(GetTickCount() - started));
            return 1;
        }
        if (GetTickCount() - started - last_report >= 250) {
            last_report = GetTickCount() - started;
            blog("waiting for dxgi elapsed=%lu", (unsigned long)last_report);
        }
        Sleep(1);
    }

    /* 2) 3DMigoto 先 —— 让它独占 d3d11 hook，Mod 才能正常加载 */
    hd3d = load_from_dir("d3d11.dll");
    if (hd3d) {
        blog("3dmigoto loaded first, sleep 1500ms to let its hooks settle");
        Sleep(1500);
    } else {
        blog("3dmigoto FAILED to load");
    }

    /* 3) ReShade 后 —— 挂到已有 hook 链上（提供游戏内 UI / 第一人称宿主） */
    hrs = load_from_dir("ReShade64.dll");

    blog("done 3dmigoto=%p reshade=%p", (void *)hd3d, (void *)hrs);
    return hd3d ? 0 : 2;
}

BOOL APIENTRY DllMain(HMODULE h, DWORD reason, LPVOID reserved) {
    (void)reserved;
    if (reason == DLL_PROCESS_ATTACH) {
        char *slash;
        g_dir[0] = 0;
        g_log[0] = 0;
        GetModuleFileNameA(h, g_dir, MAX_PATH);
        slash = strrchr(g_dir, (char)92);
        if (slash) *slash = 0;
        snprintf(g_log, MAX_PATH, "%s%cmc_bootstrap3.log", g_dir, (char)92);
        InitializeCriticalSection(&g_cs);
        CreateThread(NULL, 0, bootstrap_worker, NULL, 0, NULL);
    }
    return TRUE;
}
