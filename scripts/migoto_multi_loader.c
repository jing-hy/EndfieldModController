
#include <windows.h>
#include <tlhelp32.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>

#define TARGET_EXE "Endfield.exe"
#define INI_NAME "d3dx.ini"
#define ORDER_NAME "inject_order.txt"

static char g_base_dir[MAX_PATH];
static char g_ini_path[MAX_PATH];
static CRITICAL_SECTION g_log_cs;
static volatile LONG g_running = 1;
static volatile LONG g_stage = 0;
static volatile DWORD g_stage_pid = 0;

static const char *g_stage_names[] = {
    "idle", "OpenProcess", "VirtualAllocEx", "WriteProcessMemory",
    "CreateRemoteThread", "WaitForSingleObject", "GetExitCodeThread",
    "VirtualFreeEx", "CloseHandle", "get_process_path", "update_ini_target"
};

static void dbg(const char *fmt, ...) {
    char message[1024];
    char line[1200];
    char path[MAX_PATH];
    va_list args;
    va_start(args, fmt);
    vsnprintf(message, sizeof(message), fmt, args);
    va_end(args);
    SYSTEMTIME st;
    GetLocalTime(&st);
    snprintf(line, sizeof(line), "[%02d:%02d:%02d.%03d] %s",
             st.wHour, st.wMinute, st.wSecond, st.wMilliseconds, message);
    EnterCriticalSection(&g_log_cs);
    if (g_base_dir[0])
        snprintf(path, sizeof(path), "%s/loader_debug.log", g_base_dir);
    else
        snprintf(path, sizeof(path), "loader_debug.log");
    FILE *f = fopen(path, "a");
    if (f) { fputs(line, f); fputc(10, f); fclose(f); }
    LeaveCriticalSection(&g_log_cs);
}

static void set_stage(int stage, DWORD pid) {
    InterlockedExchange(&g_stage, stage);
    g_stage_pid = pid;
}

static DWORD WINAPI watchdog_thread(LPVOID param) {
    (void)param;
    while (InterlockedCompareExchange(&g_running, 1, 1) != 0) {
        Sleep(1000);
        LONG stage = InterlockedCompareExchange(&g_stage, 0, 0);
        if (stage > 0 && stage < (LONG)(sizeof(g_stage_names) / sizeof(g_stage_names[0])))
            dbg("WATCHDOG still inside %s pid=%lu", g_stage_names[stage], (unsigned long)g_stage_pid);
    }
    return 0;
}

static BOOL is_admin(void) {
    BOOL r = FALSE;
    PSID g = NULL;
    SID_IDENTIFIER_AUTHORITY a = SECURITY_NT_AUTHORITY;
    if (AllocateAndInitializeSid(&a, 2, SECURITY_BUILTIN_DOMAIN_RID, DOMAIN_ALIAS_RID_ADMINS, 0, 0, 0, 0, 0, 0, &g)) {
        CheckTokenMembership(NULL, g, &r);
        FreeSid(g);
    }
    return r;
}

static DWORD find_process(const char *n) {
    HANDLE s = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    if (s == INVALID_HANDLE_VALUE) return 0;
    PROCESSENTRY32 p;
    p.dwSize = sizeof(p);
    DWORD pid = 0;
    if (Process32First(s, &p)) {
        do {
            if (_stricmp(p.szExeFile, n) == 0) { pid = p.th32ProcessID; break; }
        } while (Process32Next(s, &p));
    }
    CloseHandle(s);
    return pid;
}

static int find_all_processes(const char *n, DWORD *pids, int max_count) {
    HANDLE s = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    if (s == INVALID_HANDLE_VALUE) return 0;
    PROCESSENTRY32 p;
    p.dwSize = sizeof(p);
    int count = 0;
    if (Process32First(s, &p)) {
        do {
            if (_stricmp(p.szExeFile, n) == 0) {
                if (count < max_count) pids[count] = p.th32ProcessID;
                ++count;
            }
        } while (Process32Next(s, &p));
    }
    CloseHandle(s);
    return count;
}

static BOOL file_contains(const char *path, const char *needle) {
    FILE *f = fopen(path, "rb");
    if (!f)
        return FALSE;
    fseek(f, 0, SEEK_END);
    long size = ftell(f);
    if (size <= 0) { fclose(f); return FALSE; }
    fseek(f, 0, SEEK_SET);
    char *buf = (char *)malloc((size_t)size + 1);
    if (!buf) { fclose(f); return FALSE; }
    size_t read = fread(buf, 1, (size_t)size, f);
    buf[read] = 0;
    fclose(f);
    BOOL found = strstr(buf, needle) != NULL;
    free(buf);
    return found;
}

static BOOL file_modified_after(const char *path, const FILETIME *start) {
    HANDLE h = CreateFileA(path, GENERIC_READ,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
        NULL, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
    if (h == INVALID_HANDLE_VALUE)
        return FALSE;
    FILETIME write_time;
    BOOL ok = GetFileTime(h, NULL, NULL, &write_time);
    CloseHandle(h);
    return ok && CompareFileTime(&write_time, start) > 0;
}

static DWORD WINAPI verify_efmi_thread(LPVOID param) {
    DWORD pid = (DWORD)(ULONG_PTR)param;
    char log_path[MAX_PATH];
    char user_ini[MAX_PATH];
    snprintf(log_path, MAX_PATH, "%s/d3d11_log.txt", g_base_dir);
    snprintf(user_ini, MAX_PATH, "%s/d3dx_user.ini", g_base_dir);
    FILETIME start_time;
    GetSystemTimeAsFileTime(&start_time);
    DWORD started = GetTickCount();
    DWORD last_report = 0;
    BOOL log_seen = FALSE, probe_seen = FALSE;
    for (;;) {
        DWORD elapsed = GetTickCount() - started;
        DWORD log_size = 0;
        HANDLE h = CreateFileA(log_path, GENERIC_READ,
            FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
            NULL, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
        if (h != INVALID_HANDLE_VALUE) {
            log_size = GetFileSize(h, NULL);
            CloseHandle(h);
        }
        if (!log_seen && log_size > 0) {
            log_seen = TRUE;
            dbg("EFMI log appeared pid=%lu size=%lu elapsed=%lu", (unsigned long)pid, (unsigned long)log_size, (unsigned long)elapsed);
        }
        if (!probe_seen && file_modified_after(user_ini, &start_time) && file_contains(user_ini, "mc_probe_loaded")) {
            probe_seen = TRUE;
            dbg("EFMI user ini probe saved pid=%lu elapsed=%lu", (unsigned long)pid, (unsigned long)elapsed);
        }
        if (log_seen || probe_seen) {
            dbg("EFMI initialization verified pid=%lu log=%d probe=%d elapsed=%lu",
                (unsigned long)pid, (int)log_seen, (int)probe_seen, (unsigned long)elapsed);
            break;
        }
        if (elapsed >= 120000) {
            dbg("EFMI verification timeout pid=%lu log=%d probe=%d elapsed=%lu",
                (unsigned long)pid, (int)log_seen, (int)probe_seen, (unsigned long)elapsed);
            break;
        }
        if (elapsed - last_report >= 5000) {
            last_report = elapsed;
            dbg("EFMI waiting pid=%lu elapsed=%lu log_size=%lu", (unsigned long)pid, (unsigned long)elapsed, (unsigned long)log_size);
        }
        Sleep(500);
    }
    return 0;
}

static BOOL get_process_path(DWORD pid, char *path, DWORD size) {
    HANDLE p = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, pid);
    if (!p) return FALSE;
    DWORD pathSize = size;
    BOOL result = QueryFullProcessImageNameA(p, 0, path, &pathSize);
    CloseHandle(p);
    return result;
}

static BOOL find_module(DWORD pid, const char *name, char *path, DWORD size) {
    BOOL found = FALSE;
    for (int attempt = 0; attempt < 4 && !found; ++attempt) {
        HANDLE snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, pid);
        if (snapshot == INVALID_HANDLE_VALUE) {
            Sleep(1);
            continue;
        }
        MODULEENTRY32 module;
        module.dwSize = sizeof(module);
        if (Module32First(snapshot, &module)) {
            do {
                if (_stricmp(module.szModule, name) == 0) {
                    if (path && size)
                        snprintf(path, size, "%s", module.szExePath);
                    found = TRUE;
                    break;
                }
            } while (Module32Next(snapshot, &module));
        }
        CloseHandle(snapshot);
        if (!found) Sleep(1);
    }
    return found;
}

static BOOL str_contains_ci(const char *haystack, const char *needle) {
    if (!needle || !*needle)
        return TRUE;
    size_t needle_len = strlen(needle);
    for (; *haystack; ++haystack) {
        if (_strnicmp(haystack, needle, needle_len) == 0)
            return TRUE;
    }
    return FALSE;
}

static BOOL find_module_path_substr(DWORD pid, const char *name, const char *needle, char *path, DWORD size) {
    HANDLE snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, pid);
    if (snapshot == INVALID_HANDLE_VALUE)
        return FALSE;
    BOOL found = FALSE;
    MODULEENTRY32 module;
    module.dwSize = sizeof(module);
    if (Module32First(snapshot, &module)) {
        do {
            if (_stricmp(module.szModule, name) == 0 && str_contains_ci(module.szExePath, needle)) {
                if (path && size)
                    snprintf(path, size, "%s", module.szExePath);
                found = TRUE;
                break;
            }
        } while (Module32Next(snapshot, &module));
    }
    CloseHandle(snapshot);
    return found;
}

static BOOL wait_for_injection_modules(DWORD pid, DWORD timeout_ms) {
    DWORD started = GetTickCount();
    DWORD last_report = 0;
    BOOL d3d11_seen = FALSE, dxgi_seen = FALSE;
    char d3d11_path[MAX_PATH] = "";
    char dxgi_path[MAX_PATH] = "";
    for (;;) {
        if (!d3d11_seen) {
            d3d11_seen = find_module_path_substr(pid, "d3d11.dll", "system32", d3d11_path, sizeof(d3d11_path));
            if (d3d11_seen)
                dbg("module ready pid=%lu d3d11.dll path=%s", (unsigned long)pid, d3d11_path);
        }
        if (!dxgi_seen) {
            dxgi_seen = find_module_path_substr(pid, "dxgi.dll", "system32", dxgi_path, sizeof(dxgi_path));
            if (dxgi_seen)
                dbg("module ready pid=%lu dxgi.dll path=%s", (unsigned long)pid, dxgi_path);
        }
        if (d3d11_seen && dxgi_seen)
            return TRUE;

        DWORD elapsed = GetTickCount() - started;
        if (elapsed >= timeout_ms) {
            dbg("module wait timeout pid=%lu elapsed=%lu d3d11=%d dxgi=%d",
                (unsigned long)pid, (unsigned long)elapsed, (int)d3d11_seen, (int)dxgi_seen);
            return FALSE;
        }
        if (elapsed - last_report >= 250) {
            last_report = elapsed;
            dbg("module wait pid=%lu elapsed=%lu d3d11=%d dxgi=%d",
                (unsigned long)pid, (unsigned long)elapsed, (int)d3d11_seen, (int)dxgi_seen);
        }
        Sleep(2);
    }
}

static BOOL update_ini_target(const char *ini_path, const char *process_path) {
    FILE *f = fopen(ini_path, "r");
    if (!f) return FALSE;
    fseek(f, 0, SEEK_END);
    long file_size = ftell(f);
    fseek(f, 0, SEEK_SET);
    char *content = (char *)malloc((size_t)file_size + 1);
    if (!content) { fclose(f); return FALSE; }
    size_t read_size = fread(content, 1, (size_t)file_size, f);
    content[read_size] = 0;
    fclose(f);

    char *new_content = (char *)malloc((size_t)file_size + MAX_PATH + 128);
    if (!new_content) { free(content); return FALSE; }
    new_content[0] = 0;
    char *line_start = content;
    char *line_end;
    BOOL modified = FALSE;
    while ((line_end = strchr(line_start, '\n')) != NULL || *line_start != 0) {
        char line[4096];
        size_t line_len;
        if (line_end) {
            line_len = (size_t)(line_end - line_start);
        } else {
            line_len = strlen(line_start);
        }
        if (line_len >= sizeof(line)) line_len = sizeof(line) - 1;
        memcpy(line, line_start, line_len);
        line[line_len] = 0;
        char *p = line;
        while (*p == ' ' || *p == '\t') p++;
        if (_strnicmp(p, "target", 6) == 0) {
            char *eq = strchr(p, '=');
            if (eq) {
                char new_line[MAX_PATH + 32];
                snprintf(new_line, sizeof(new_line), "target = %s", process_path);
                strcat(new_content, new_line);
                modified = TRUE;
            } else {
                strcat(new_content, line);
            }
        } else {
            strcat(new_content, line);
        }
        if (line_end) {
            strcat(new_content, "\r\n");
            line_start = line_end + 1;
        } else {
            break;
        }
    }
    free(content);
    if (!modified) { free(new_content); return FALSE; }
    f = fopen(ini_path, "w");
    if (!f) { free(new_content); return FALSE; }
    fputs(new_content, f);
    fclose(f);
    free(new_content);
    return TRUE;
}

static BOOL inject(DWORD pid, const char *dll_path) {
    dbg("inject start pid=%lu dll=%s", (unsigned long)pid, dll_path);
    DWORD rights = PROCESS_CREATE_THREAD | PROCESS_QUERY_INFORMATION | PROCESS_VM_OPERATION | PROCESS_VM_WRITE | PROCESS_VM_READ;
    set_stage(1, pid);
    HANDLE p = OpenProcess(rights, FALSE, pid);
    dbg("OpenProcess pid=%lu handle=%p err=%lu", (unsigned long)pid, (void *)p, (unsigned long)GetLastError());
    if (!p) {
        dbg("OpenProcess failed pid=%lu err=%lu", (unsigned long)pid, (unsigned long)GetLastError());
        set_stage(0, pid);
        return FALSE;
    }
    size_t len = strlen(dll_path) + 1;
    set_stage(2, pid);
    LPVOID mem = VirtualAllocEx(p, NULL, len, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    dbg("VirtualAllocEx pid=%lu mem=%p err=%lu", (unsigned long)pid, mem, (unsigned long)GetLastError());
    if (!mem) {
        dbg("VirtualAllocEx failed pid=%lu err=%lu", (unsigned long)pid, (unsigned long)GetLastError());
        CloseHandle(p);
        set_stage(0, pid);
        return FALSE;
    }
    BOOL ok = FALSE;
    set_stage(3, pid);
    BOOL wrote = WriteProcessMemory(p, mem, dll_path, len, NULL);
    dbg("WriteProcessMemory pid=%lu wrote=%d err=%lu", (unsigned long)pid, (int)wrote, (unsigned long)GetLastError());
    if (wrote) {
        set_stage(4, pid);
        HANDLE t = CreateRemoteThread(p, NULL, 0, (LPTHREAD_START_ROUTINE)GetProcAddress(GetModuleHandleA("kernel32.dll"), "LoadLibraryA"), mem, 0, NULL);
        dbg("CreateRemoteThread pid=%lu handle=%p err=%lu", (unsigned long)pid, (void *)t, (unsigned long)GetLastError());
        if (t) {
            set_stage(5, pid);
            DWORD wait_started = GetTickCount();
            DWORD exit_code = 0;
            DWORD last_active_log = 0;
            for (;;) {
                if (!GetExitCodeThread(t, &exit_code)) {
                    dbg("GetExitCodeThread failed pid=%lu err=%lu", (unsigned long)pid, (unsigned long)GetLastError());
                    break;
                }
                if (exit_code != STILL_ACTIVE)
                    break;
                DWORD elapsed = GetTickCount() - wait_started;
                if (elapsed >= 10000) {
                    dbg("remote LoadLibrary still active pid=%lu elapsed=%lu (checking module)", (unsigned long)pid, (unsigned long)elapsed);
                    break;
                }
                if (elapsed - last_active_log >= 500) {
                    last_active_log = elapsed;
                    dbg("remote LoadLibrary active pid=%lu elapsed=%lu", (unsigned long)pid, (unsigned long)elapsed);
                }
                Sleep(10);
            }
            dbg("GetExitCodeThread pid=%lu exit_code=%lu elapsed=%lu", (unsigned long)pid, (unsigned long)exit_code, (unsigned long)(GetTickCount() - wait_started));
            // 0xFFFFFFFF is not STILL_ACTIVE; anti-cheat can terminate a remote
            // LoadLibrary thread with that value without loading our DLL.  Only
            // accept a real module handle, and additionally verify that the DLL is
            // actually mapped in the target process.
            ok = (exit_code != 0 && exit_code != STILL_ACTIVE && exit_code != 0xFFFFFFFFu);
            if (!ok) {
                const char *base = strrchr(dll_path, (char)92);
                if (!base) base = strrchr(dll_path, '/');
                base = base ? base + 1 : dll_path;
                BOOL mapped = find_module_path_substr(pid, base, "migoto", NULL, 0);
                if (mapped) {
                    ok = TRUE;
                    dbg("module mapped despite exit_code=%lu pid=%lu name=%s", (unsigned long)exit_code, (unsigned long)pid, base);
                } else {
                    dbg("remote LoadLibrary did not map module pid=%lu exit_code=%lu name=%s err=%lu", (unsigned long)pid, (unsigned long)exit_code, base, (unsigned long)GetLastError());
                }
            }
            CloseHandle(t);
        } else {
            dbg("CreateRemoteThread failed pid=%lu err=%lu", (unsigned long)pid, (unsigned long)GetLastError());
        }
    } else {
        dbg("WriteProcessMemory failed pid=%lu err=%lu", (unsigned long)pid, (unsigned long)GetLastError());
    }
    set_stage(7, pid);
    VirtualFreeEx(p, mem, 0, MEM_RELEASE);
    set_stage(8, pid);
    CloseHandle(p);
    set_stage(0, pid);
    dbg("inject done pid=%lu ok=%d", (unsigned long)pid, (int)ok);
    return ok;
}
static BOOL inject_one(DWORD pid, const char *name) {
    char path[MAX_PATH];
    char line[512];
    snprintf(path, MAX_PATH, "%s/%s", g_base_dir, name);
    if (GetFileAttributesA(path) == INVALID_FILE_ATTRIBUTES) {
        snprintf(line, sizeof(line), "missing: %s", path);
        dbg(line);
        return FALSE;
    }
    BOOL ok = inject(pid, path);
    printf("Inject pid=%lu %s -> %s\n", (unsigned long)pid, path, ok ? "OK" : "FAILED");
    fflush(stdout);
    snprintf(line, sizeof(line), "inject pid=%lu %s -> %s", (unsigned long)pid, path, ok ? "ok" : "FAILED");
    dbg(line);
    return ok;
}

static BOOL inject_pid_all(DWORD pid, char names[][260], int name_count) {
    for (int i = 0; i < name_count; ++i) {
        if (!inject_one(pid, names[i]))
            return FALSE;
        Sleep(120);
    }
    return TRUE;
}

int main(void) {
    printf("\n[3DMigoto Loader]\n\n");
    fflush(stdout);
    if (!is_admin()) {
        MessageBoxA(NULL, "This loader must run as administrator.", "3DMigoto Loader", MB_ICONERROR);
        return 1;
    }
    GetModuleFileNameA(NULL, g_base_dir, MAX_PATH);
    char *s = strrchr(g_base_dir, (char)92);
    if (s) *s = 0;
    snprintf(g_ini_path, MAX_PATH, "%s/%s", g_base_dir, INI_NAME);
    InitializeCriticalSection(&g_log_cs);
    CreateThread(NULL, 0, watchdog_thread, NULL, 0, NULL);
    dbg("loader started");

    char old_log[MAX_PATH];
    char prev_log[MAX_PATH];
    snprintf(old_log, MAX_PATH, "%s/d3d11_log.txt", g_base_dir);
    snprintf(prev_log, MAX_PATH, "%s/d3d11_log.prev.txt", g_base_dir);
    if (GetFileAttributesA(old_log) != INVALID_FILE_ATTRIBUTES) {
        DeleteFileA(prev_log);
        if (MoveFileA(old_log, prev_log))
            dbg("rotated d3d11_log.txt -> d3d11_log.prev.txt");
    }

    char names[64][260];
    int name_count = 0;
    char order_path[MAX_PATH];
    snprintf(order_path, MAX_PATH, "%s/%s", g_base_dir, ORDER_NAME);
    FILE *f = fopen(order_path, "r");
    if (f) {
        char line[260];
        while (fgets(line, sizeof(line), f) && name_count < 64) {
            size_t n = strlen(line);
            while (n && (line[n-1] == '\r' || line[n-1] == '\n' || line[n-1] == ' ' || line[n-1] == '\t')) line[--n] = 0;
            char *p = line;
            while (*p == ' ' || *p == '	') p++;
            if (*p) snprintf(names[name_count++], sizeof(names[0]), "%s", p);
        }
        fclose(f);
    }
    if (name_count == 0) {
        snprintf(names[name_count++], sizeof(names[0]), "%s", "d3d11.dll");
    }
    for (int i = 0; i < name_count; ++i) dbg(names[i]);
    BOOL bootstrap_mode = (name_count == 1 && _stricmp(names[0], "mc_bootstrap.dll") == 0);
    if (bootstrap_mode)
        dbg("bootstrap mode enabled: inject immediately, bootstrap waits for d3d11/dxgi in-process");

    DWORD injected[256] = {0};
    int injected_count = 0;
    DWORD started = GetTickCount();
    while (GetTickCount() - started < 300000) {
        DWORD pids[64] = {0};
        int count = find_all_processes(TARGET_EXE, pids, 64);
        if (count > 64) count = 64;
        for (int i = 0; i < count; ++i) {
            DWORD pid = pids[i];
            BOOL already = FALSE;
            for (int j = 0; j < injected_count; ++j) {
                if (injected[j] == pid) { already = TRUE; break; }
            }
            if (already) continue;
            char line[256];
            snprintf(line, sizeof(line), "found %s pid=%lu", TARGET_EXE, (unsigned long)pid);
            dbg(line);
            // Bootstrap mode: inject a tiny in-process DLL immediately while the
            // process is still writable.  That DLL waits inside the target for
            // system d3d11.dll + dxgi.dll, then LoadLibrary's EFMI's d3d11.dll.
            // This avoids both early-injection HookD3D11 failure and late-injection
            // anti-cheat VirtualAllocEx denial.
            BOOL modules_ready = FALSE;
            if (bootstrap_mode) {
                dbg("starting bootstrap injection pid=%lu", (unsigned long)pid);
            } else {
                modules_ready = wait_for_injection_modules(pid, 45000);
                if (!modules_ready)
                    dbg("module wait failed, injecting anyway pid=%lu", (unsigned long)pid);
                dbg("starting injection pid=%lu modules_ready=%d", (unsigned long)pid, (int)modules_ready);
            }
            BOOL inject_ok = FALSE;
            int max_attempts = bootstrap_mode ? 20 : 1;
            for (int attempt = 0; attempt < max_attempts && !inject_ok; ++attempt) {
                if (attempt > 0) {
                    dbg("bootstrap injection retry pid=%lu attempt=%d", (unsigned long)pid, attempt + 1);
                    Sleep(50);
                }
                inject_ok = inject_pid_all(pid, names, name_count);
            }
            // Record the pid after the retry window so a failed/stalled injection cannot
            // loop forever and load multiple copies of the same DLL into the game.
            if (injected_count < 256) injected[injected_count++] = pid;
            if (inject_ok) {
                char injected_path[MAX_PATH] = "";
                BOOL loaded = find_module_path_substr(pid, "d3d11.dll", "migoto", injected_path, sizeof(injected_path));
                dbg("fully injected pid=%lu bootstrap=%d efmi_loaded_now=%d path=%s",
                    (unsigned long)pid, (int)bootstrap_mode, (int)loaded, injected_path);
                CreateThread(NULL, 0, verify_efmi_thread, (LPVOID)(ULONG_PTR)pid, 0, NULL);
            } else {
                snprintf(line, sizeof(line), "injection failed and recorded pid=%lu", (unsigned long)pid);
                dbg(line);
            }
        }
        Sleep(25);
    }
    dbg("loader timeout");
    InterlockedExchange(&g_running, 0);
    Sleep(1100);
    return 0;
}
