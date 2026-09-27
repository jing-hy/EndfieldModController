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

static DWORD WINAPI bootstrap_worker(LPVOID param) {
    (void)param;
    blog("worker start pid=%lu", (unsigned long)GetCurrentProcessId());

    // Wait for dxgi.dll, then load EFMI's d3d11.dll as early as possible.
    // If system d3d11.dll is not loaded yet, EFMI becomes the primary d3d11
    // proxy (the mode that previously rendered the overlay and mods).
    DWORD started = GetTickCount();
    DWORD last_report = 0;
    for (;;) {
        HMODULE dxgi = GetModuleHandleA("dxgi.dll");
        if (dxgi) {
            blog("dxgi ready h=%p elapsed=%lu", (void *)dxgi, (unsigned long)(GetTickCount() - started));
            break;
        }
        DWORD elapsed = GetTickCount() - started;
        if (elapsed >= 120000) {
            blog("wait timeout for dxgi elapsed=%lu", (unsigned long)elapsed);
            return 1;
        }
        if (elapsed - last_report >= 250) {
            last_report = elapsed;
            blog("waiting for dxgi elapsed=%lu", (unsigned long)elapsed);
        }
        Sleep(1);
    }

    char path[MAX_PATH];
    snprintf(path, MAX_PATH, "%s%cd3d11.dll", g_dir, (char)92);
    blog("loading EFMI dll=%s", path);
    HMODULE h = LoadLibraryExA(path, NULL, LOAD_WITH_ALTERED_SEARCH_PATH);
    DWORD err = GetLastError();
    blog("load result h=%p err=%lu", (void *)h, (unsigned long)err);
    return h ? 0 : 2;
}

BOOL APIENTRY DllMain(HMODULE h, DWORD reason, LPVOID reserved) {
    (void)reserved;
    if (reason == DLL_PROCESS_ATTACH) {
        g_dir[0] = 0;
        g_log[0] = 0;
        GetModuleFileNameA(h, g_dir, MAX_PATH);
        char *slash = strrchr(g_dir, (char)92);
        if (slash) *slash = 0;
        snprintf(g_log, MAX_PATH, "%s%cmc_bootstrap.log", g_dir, (char)92);
        InitializeCriticalSection(&g_cs);
        CreateThread(NULL, 0, bootstrap_worker, NULL, 0, NULL);
    }
    return TRUE;
}
