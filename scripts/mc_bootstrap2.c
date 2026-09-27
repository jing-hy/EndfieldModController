/*
 * mc_bootstrap2.c — 进程内桥（变体 A+）
 *
 * 与 mc_bootstrap.c 的区别：那个只加载 EFMI 的 d3d11.dll；这个改成
 * 「先加载同目录的 ReShade64.dll 建立 D3D hook 体系，等 hook 装好，
 *   再加载 EFMI 的 d3d11.dll 挂到同一条链上」。
 *
 * 动机：历史「变体 A」(2026-09-26 18:32) 是 ReShade64.dll + d3d11.dll 双注入，
 * 那次落在当天唯一的长无崩溃窗口里；但当时的注入器要先等目标进程加载
 * d3d11/dxgi 才动手（最多 45s），实测太晚且失败。本桥保留早期可写窗口的
 * 优势，同时在进程内按 ReShade→EFMI 的顺序加载。
 *
 * 日志：<dll 所在目录>\mc_bootstrap2.log
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
    HMODULE hr, he;
    (void)param;

    blog("worker start pid=%lu", (unsigned long)GetCurrentProcessId());

    /* 1) 等 dxgi.dll 出现 —— 与 mc_bootstrap.c 相同：进程刚创建、反作弊还没上的窗口 */
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

    /* 2) ReShade 先注入，建立 D3D hook 体系 */
    hr = load_from_dir("ReShade64.dll");
    if (hr) {
        blog("reshade loaded, sleep 800ms to let hooks settle");
        Sleep(800);
    } else {
        blog("reshade NOT loaded (missing?), continue with EFMI anyway");
    }

    /* 3) 再加载 EFMI 的 d3d11.dll，挂到已有 hook 链上 */
    he = load_from_dir("d3d11.dll");

    blog("done reshade=%p efmi=%p", (void *)hr, (void *)he);
    return he ? 0 : 2;
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
        snprintf(g_log, MAX_PATH, "%s%cmc_bootstrap2.log", g_dir, (char)92);
        InitializeCriticalSection(&g_cs);
        CreateThread(NULL, 0, bootstrap_worker, NULL, 0, NULL);
    }
    return TRUE;
}
