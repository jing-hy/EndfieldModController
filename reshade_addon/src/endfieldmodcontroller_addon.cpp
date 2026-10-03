// EndfieldModController ReShade add-on —— 统一 Mod 控制面板（"遥控器"）
//
// 用户 2026-10-01 的需求原话：「做统一面板，**需要注入到 reshade**，ui 尽量做好一点，
// **要标明原快捷键**，**要自动识别那个变量的名称，推测含义**」；
// 2026-10-02 追加两条（本文件当前形态的依据）：
//   ①「**不要用开关或滑块，都是一个键，做切换的按键就行**」——
//      面板不再画滑块/开关，每一项就是**一个按钮**，点一下 = 按一次这个 Mod 自己的原键
//      （Mod 内部自己切换档位；面板不假装知道状态，也不做"表面功夫"）。
//   ②「**你看看能不能通过其他路径注入模拟按键**」——
//      合成输入（SendInput）在终末地里被吞（见 vkey_inject.h 里的排查结论），
//      现在改为**在游戏进程内让 EFMI 的 GetAsyncKeyState 轮询读到"按下"**。
//
// 外部程序（控制器）负责把这几样东西放进 ReShade 的 base 目录
// （= d3d12.dll 所在处；xxmi_extra 注入方式下就是 `<数据根>\runtime\dlss5`）：
//
//   endfieldmodcontroller.addon64   本文件编译出来的面板
//   actions.tsv                     动作清单（含推测含义 / 原快捷键 / 角色分组）
//   user_ini_path.txt               EFMI 的 d3dx_user.ini 路径
//   panel_info.txt                  面板状态（是否已接管 / 生成时间）
//
// 操作路径：点按钮 → `vkey::press_all()` 把该动作的原键标成"按下 180ms" →
// EFMI（3DMigoto）每帧轮询 `GetAsyncKeyState` 读到它 → 走 Mod 自己那条 `[Key*]`
// 分支切换 → 立刻生效。
//
// 历史（**别往回走**）：这里原先走的是自造的 `Ctrl+Alt+Shift+F13..F24` 合成键协议 +
//   `controller.ini` 的 `[KeyMC_*]` + `[Present]` 写回变量。那条路依赖 SendInput，
//   在终末地里**从未成功过一次**（三批对照探针全 0），且带出过两个副作用
//   （F6/F7 撞 DLSS5 与第一人称的开关）。协议段与 controller.ini 仍留在后端生成里
//   （旧版本兼容），但**面板不再使用它**。
//
// ⚠ 面板**只能**待在这儿：ReShade 6.8 的日志写死了它只搜 `d3d12.dll` 所在目录
//   （`Searching for add-ons (*.addon, *.addon64) in '<base>'`）。放到别处 = 用户按
//   原来的键被锁了、新面板却不存在 —— 2026-10-01 出过这个事故，别再犯。
#include <Windows.h>

#define ImTextureID ImU64
#define IMGUI_DEFINE_MATH_OPERATORS
#include <imgui.h>

#include <reshade.hpp>

#include "vkey_inject.h"

#include <algorithm>
#include <cctype>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <map>
#include <mutex>
#include <sstream>
#include <string>
#include <vector>

namespace fs = std::filesystem;

// ---------------------------------------------------------------------------
// 数据
// ---------------------------------------------------------------------------

struct ActionEntry
{
    int id = 0;
    std::string label;
    std::string kind;            // toggle | cycle | command
    std::string mod_name;
    std::vector<std::string> values;
    std::string description;
    std::string current;
    std::string namespace_name;
    std::string var_name;
    std::string section;
    std::string run_command;
    std::string original_keys;
    int wire_id = 0;
    bool send_index = true;
    bool merged = false;
    // 2026-10-02：`original_keys` 解析出来的虚拟键（点按钮时伪造按下的就是它们）
    std::vector<int> vks;
    // 2026-10-01 新增列（Python 侧 core.generate_controller_mod 写入）
    std::string hint;            // 推测含义（中文；推不出时是变量名的英文短语）
    std::string key_label;       // 原快捷键可读写法（`VK_LEFT` → `←`）
    std::string char_group;      // 角色/分组，面板按它分栏
    std::string condition;       // 生效条件（例如「仅佩丽卡」）
};

static std::vector<ActionEntry> g_actions;
static std::recursive_mutex g_actions_mutex;
static fs::path g_base_path;
static fs::path g_user_ini_path;
static bool g_paths_loaded = false;
static bool g_takeover = false;
static std::string g_generated;
static int g_expected_actions = 0;
static std::mutex g_log_mutex;
static bool g_cjk_checked = false;
static bool g_cjk_ok = false;
static DWORD g_hook_retry_tick = 0;              // hook 未装上时的重试节流

static void addon_log(const std::string &message);
static fs::path addon_log_path();
static int collect_virtual_keys(const std::string &spec, int *out, int max_out);

// 中文字形检测：ReShade 默认字体（ProggyClean）只有 ASCII，装不了中文含义。
// 检测不到就整体降级成英文标签 —— **面板永远要能读**，不能因为字体变成一堆方块。
static const char *T(const char *zh, const char *en)
{
    return g_cjk_ok ? zh : en;
}

// ---------------------------------------------------------------------------
// 日志 / 路径
// ---------------------------------------------------------------------------

static fs::path get_base_path()
{
    wchar_t env_buf[32768];
    const DWORD env_len = GetEnvironmentVariableW(L"RESHADE_BASE_PATH_OVERRIDE", env_buf, ARRAYSIZE(env_buf));
    if (env_len > 0 && env_len < ARRAYSIZE(env_buf))
        return fs::path(env_buf);

    char buf[32768];
    size_t size = ARRAYSIZE(buf);
    reshade::get_reshade_base_path(buf, &size);
    if (size > 0)
        return fs::u8path(buf);
    return fs::current_path();
}

static fs::path addon_log_path()
{
    if (!g_base_path.empty())
        return g_base_path / L"modecontroller.addon.log";

    wchar_t temp[MAX_PATH] = {};
    const DWORD count = GetTempPathW(ARRAYSIZE(temp), temp);
    if (count > 0 && count < ARRAYSIZE(temp))
        return fs::path(temp) / L"modecontroller.addon.log";
    return fs::current_path() / L"modecontroller.addon.log";
}

static void addon_log(const std::string &message)
{
    std::lock_guard<std::mutex> lock(g_log_mutex);
    SYSTEMTIME now = {};
    GetLocalTime(&now);
    char timestamp[64] = {};
    std::snprintf(
        timestamp,
        sizeof(timestamp),
        "%04d-%02d-%02d %02d:%02d:%02d.%03d",
        now.wYear, now.wMonth, now.wDay,
        now.wHour, now.wMinute, now.wSecond, now.wMilliseconds);
    std::ofstream file(addon_log_path(), std::ios::app | std::ios::binary);
    if (!file.is_open())
    {
        wchar_t temp[MAX_PATH] = {};
        const DWORD count = GetTempPathW(ARRAYSIZE(temp), temp);
        if (count > 0 && count < ARRAYSIZE(temp))
            file.open(fs::path(temp) / L"modecontroller.addon.log", std::ios::app | std::ios::binary);
    }
    if (!file.is_open())
        return;
    file << timestamp << " [addon] " << message << "\r\n";
}

static std::string trim(std::string value)
{
    const auto not_space = [](unsigned char ch) { return !std::isspace(ch); };
    value.erase(value.begin(), std::find_if(value.begin(), value.end(), not_space));
    value.erase(std::find_if(value.rbegin(), value.rend(), not_space).base(), value.end());
    return value;
}

static std::vector<std::string> split(const std::string &text, char delimiter)
{
    std::vector<std::string> parts;
    std::stringstream stream(text);
    std::string item;
    while (std::getline(stream, item, delimiter))
        parts.push_back(item);
    return parts;
}

// ---------------------------------------------------------------------------
// 载入清单
// ---------------------------------------------------------------------------

static void load_actions()
{
    std::lock_guard<std::recursive_mutex> lock(g_actions_mutex);
    g_actions.clear();
    g_takeover = false;
    g_expected_actions = 0;
    g_generated.clear();

    // 面板状态（控制器每次部署时写）
    const fs::path info_path = g_base_path / L"panel_info.txt";
    std::ifstream info_file(info_path);
    if (info_file.is_open())
    {
        std::string line;
        while (std::getline(info_file, line))
        {
            const std::string text = trim(line);
            const auto eq = text.find('=');
            if (eq == std::string::npos)
                continue;
            const std::string key = trim(text.substr(0, eq));
            const std::string value = trim(text.substr(eq + 1));
            if (key == "takeover")
                g_takeover = (value == "1" || value == "true");
            else if (key == "actions")
                g_expected_actions = std::atoi(value.c_str());
            else if (key == "generated")
                g_generated = value;
        }
    }

    const fs::path actions_path = g_base_path / L"actions.tsv";
    addon_log("load_actions: " + actions_path.string());
    std::ifstream file(actions_path);
    if (!file.is_open())
    {
        addon_log("load_actions: actions.tsv 打不开");
        return;
    }

    std::string line;
    bool header = true;
    while (std::getline(file, line))
    {
        if (header)
        {
            header = false;
            continue;
        }
        if (line.empty())
            continue;

        const auto fields = split(line, '\t');
        if (fields.size() < 5)
            continue;

        ActionEntry entry;
        try
        {
            entry.id = std::stoi(trim(fields[0]));
        }
        catch (...)
        {
            continue;
        }
        entry.label = trim(fields[1]);
        entry.kind = trim(fields[2]);
        entry.mod_name = trim(fields[3]);
        entry.values = split(trim(fields[4]), ',');
        if (fields.size() > 5) entry.description = trim(fields[5]);
        if (fields.size() > 6) entry.current = trim(fields[6]);
        if (fields.size() > 7) entry.namespace_name = trim(fields[7]);
        if (fields.size() > 8) entry.var_name = trim(fields[8]);
        if (fields.size() > 9) entry.section = trim(fields[9]);
        if (fields.size() > 10) entry.run_command = trim(fields[10]);
        if (fields.size() > 11) entry.original_keys = trim(fields[11]);
        if (fields.size() > 12)
        {
            try { entry.wire_id = std::stoi(trim(fields[12])); }
            catch (...) { entry.wire_id = 0; }
        }
        if (fields.size() > 13)
        {
            const std::string send_index = trim(fields[13]);
            entry.send_index = (send_index == "1" || send_index == "true" || send_index == "yes");
        }
        if (fields.size() > 14)
        {
            const std::string merged = trim(fields[14]);
            entry.merged = (merged == "1" || merged == "true" || merged == "yes");
        }
        // ↓ 只追加、不重排：旧版 actions.tsv 没有这几列也不会错位
        if (fields.size() > 15) entry.hint = trim(fields[15]);
        if (fields.size() > 16) entry.key_label = trim(fields[16]);
        if (fields.size() > 17) entry.char_group = trim(fields[17]);
        if (fields.size() > 18) entry.condition = trim(fields[18]);

        if (entry.kind.empty())
            entry.kind = "toggle";

        // 2026-10-02：解析出"点这个按钮要按哪个键"（面板只发 Mod 自己的原键，见文件头）。
        int parsed[16] = {};
        const int parsed_count = collect_virtual_keys(entry.original_keys, parsed, 16);
        entry.vks.assign(parsed, parsed + parsed_count);
        if (parsed_count == 0)
            addon_log("load_actions: id=" + std::to_string(entry.id)
                      + " 没有可用原键，original_keys='" + entry.original_keys + "'");

        g_actions.push_back(std::move(entry));
    }

    int usable = 0;
    for (const auto &action : g_actions)
        if (!action.vks.empty())
            ++usable;

    addon_log("load_actions: loaded " + std::to_string(g_actions.size()) + " actions, usable="
              + std::to_string(usable) + ", takeover="
              + (g_takeover ? "1" : "0") + ", generated=" + g_generated);
}

static void load_paths()
{
    std::lock_guard<std::recursive_mutex> lock(g_actions_mutex);
    g_paths_loaded = false;
    g_user_ini_path.clear();

    // 外部程序可以设这个环境变量（最不容易出错的方式）
    wchar_t env_buf[32768];
    const DWORD env_len = GetEnvironmentVariableW(L"MODECONTROLLER_USER_INI", env_buf, ARRAYSIZE(env_buf));
    if (env_len > 0 && env_len < ARRAYSIZE(env_buf))
    {
        g_user_ini_path = fs::path(env_buf);
        g_paths_loaded = true;
        addon_log("load_paths: env=" + g_user_ini_path.string());
        return;
    }

    const fs::path path_file = g_base_path / L"user_ini_path.txt";
    std::ifstream file(path_file);
    if (!file.is_open())
        return;
    std::string path;
    std::getline(file, path);
    path = trim(path);
    if (!path.empty())
    {
        g_user_ini_path = fs::u8path(path);
        g_paths_loaded = true;
        addon_log("load_paths: file=" + g_user_ini_path.string());
    }
    else
    {
        addon_log("load_paths: user_ini_path.txt 是空的");
    }
}

// ---------------------------------------------------------------------------
// 按键注入（2026-10-02 换路：不再发合成输入）
//
// 这一节原来是一整套 `SendInput` 合成键协议（`Ctrl+Alt+Shift+F13..F24` 逐位编码 +
// F23 暂存 + F24 提交，还带两批对照探针）。它**在终末地里实测从未成功过一次**
// （三批对照探针全 0 触发，而手按 Mod 自带键一切正常）—— 根因与"为什么必须换路"
// 写在 `vkey_inject.h` 顶部。整套 SendInput 代码已删，只留下这条结论。
//
// 现在的做法：**点一个按钮 = 按一次这个 Mod 自己那一项的原键**
// （actions.tsv 的 `original_keys`，例如 `no_ctrl no_shift right`）。
// 键不是"发"出去的，而是在**游戏进程内**让 EFMI 的 `GetAsyncKeyState` 轮询
// 读到"这个键被按住了" —— 见 vkey_inject.h。
//
// 为什么发原键（用户 2026-10-01 的原话：「让面板走 mod 的按键」）：
//   * 复用 Mod 作者已经验证过的链路，面板不需要自造协议、不需要锁键；
//   * 用户手按原来的键照常工作 —— 面板只是多一个"遥控器"。
// ---------------------------------------------------------------------------


// 历史留档（选键时的两条硬教训，**换路之后依然成立**）：
//   ① **协议键别用键盘上存在的键**。旧协议的数字位曾是 `VK_F1 + n`，撞上了 DLSS5 的
//      NR 开关（F6）与第一人称切换（F7）—— 用户实测「按开关外套会切第一人称 /
//      按切换头发开关了 DLSS5」。那些 addon **只轮询主键、根本不看修饰键**，
//      所以"我加了 Ctrl+Alt+Shift"并不构成保护。
//   ② 现在既然发的是 **Mod 自己的原键**，撞车面就回到"和手按一模一样"，
//      面板既不新增键位、也不锁键。
// 
static WORD vk_from_name(const std::string &raw)
{
    std::string name = trim(raw);
    // 只取第一个（`a, b` 这种写法里逗号后面的是另一个键）
    const auto comma = name.find(',');
    if (comma != std::string::npos)
        name = trim(name.substr(0, comma));
    // 统一成小写
    for (auto &c : name)
        c = static_cast<char>(::tolower(static_cast<unsigned char>(c)));
    // 去掉 vk_ 前缀
    if (name.rfind("vk_", 0) == 0)
        name = name.substr(3);

    struct Entry { const char *name; WORD vk; };
    static const Entry table[] = {
        {"back", VK_BACK}, {"backspace", VK_BACK}, {"tab", VK_TAB}, {"return", VK_RETURN},
        {"enter", VK_RETURN}, {"escape", VK_ESCAPE}, {"space", VK_SPACE},
        {"left", VK_LEFT}, {"right", VK_RIGHT}, {"up", VK_UP}, {"down", VK_DOWN},
        {"insert", VK_INSERT}, {"delete", VK_DELETE}, {"home", VK_HOME}, {"end", VK_END},
        {"prior", VK_PRIOR}, {"next", VK_NEXT}, {"pgup", VK_PRIOR}, {"pgdn", VK_NEXT},
        {"pageup", VK_PRIOR}, {"pagedown", VK_NEXT},
        {"shift", VK_SHIFT}, {"control", VK_CONTROL}, {"ctrl", VK_CONTROL}, {"menu", VK_MENU},
        {"alt", VK_MENU}, {"lshift", VK_LSHIFT}, {"rshift", VK_RSHIFT},
        {"lcontrol", VK_LCONTROL}, {"rcontrol", VK_RCONTROL},
        {"lmenu", VK_LMENU}, {"rmenu", VK_RMENU},
        {"lwin", VK_LWIN}, {"rwin", VK_RWIN}, {"apps", VK_APPS},
        {"scroll", VK_SCROLL}, {"pause", VK_PAUSE}, {"caps", VK_CAPITAL},
        {"numlock", VK_NUMLOCK}, {"multiply", VK_MULTIPLY}, {"add", VK_ADD},
        {"subtract", VK_SUBTRACT}, {"decimal", VK_DECIMAL}, {"divide", VK_DIVIDE},
        {"lbution", VK_LBUTTON}, {"lbutton", VK_LBUTTON}, {"rbutton", VK_RBUTTON},
        {"mbutton", VK_MBUTTON}, {"xbutton1", VK_XBUTTON1}, {"xbutton2", VK_XBUTTON2},
        {"oem_1", VK_OEM_1}, {"oem_plus", VK_OEM_PLUS}, {"oem_comma", VK_OEM_COMMA},
        {"oem_minus", VK_OEM_MINUS}, {"oem_period", VK_OEM_PERIOD}, {"oem_2", VK_OEM_2},
        {"oem_3", VK_OEM_3}, {"oem_4", VK_OEM_4}, {"oem_5", VK_OEM_5}, {"oem_6", VK_OEM_6},
        {"oem_7", VK_OEM_7}, {"oem_8", VK_OEM_8},
    };
    for (const auto &e : table)
        if (name == e.name)
            return e.vk;
    if (name.size() >= 2 && name[0] == 'f') {          // f1..f24
        const int n = std::atoi(name.c_str() + 1);
        if (n >= 1 && n <= 24)
            return static_cast<WORD>(VK_F1 + n - 1);
    }
    if (name.size() == 1) {                            // 单字符 a-z / 0-9
        const char c = name[0];
        if (c >= 'a' && c <= 'z') return static_cast<WORD>('A' + c - 'a');
        if (c >= '0' && c <= '9') return static_cast<WORD>(c);
    }
    if (name.rfind("numpad", 0) == 0) {                // numpad0..9
        const int n = std::atoi(name.c_str() + 6);
        if (n >= 0 && n <= 9) return static_cast<WORD>(VK_NUMPAD0 + n);
    }
    return 0;
}

// 把 3DMigoto 的 `key = ...` 表达式解析成**要伪造按下的虚拟键**列表。
//
// 语法（3DMigoto 的 `key` 行，actions.tsv 里多个 key 行用 `;` 连接）：
//   * `no_ctrl` / `no_shift` / `no_alt` / `no_modifiers` / `no_win` = "按这个键时不许
//     按着这些" ⇒ 是**限制**而非要按的键，忽略。
//     （真修饰键状态由我们的 hook 原样透传给 EFMI，所以用户真按着 Ctrl 时，
//      行为与他手按完全一致：不触发。）
//   * `alt` / `ctrl` / `shift` / `win` = 需要**按住**的修饰键（例如庄方宜的 `ALT 0`）
//     ⇒ 一并伪造。
//   * 其余 token = 主键（`vk_right` / `right` / `backspace` / `0` / `a`）。
//   * 一行里的多个 token **全部伪造**：无论 EFMI 那侧是"任一命中"还是"必须同时按住"
//     的语义，我们这条都成立。
//
// 修复记录（2026-10-02）：旧实现直接把整串丢给 `vk_from_name`，而它只看**逗号前的第一段**
// ⇒ `no_ctrl no_shift right` 里第一段是 `no_ctrl` ⇒ 一个键都解析不出来，
// 面板只能回退到那套无效的合成协议键（addon 日志里成片的
// 「原按键无法解析 'no_ctrl no_shift right'，回退协议键」就是这么来的）。
static int collect_virtual_keys(const std::string &spec, int *out, int max_out)
{
    int count = 0;
    size_t line_start = 0;
    bool done = false;
    while (!done && count < max_out)
    {
        size_t line_end = spec.find(';', line_start);
        if (line_end == std::string::npos)
        {
            line_end = spec.size();
            done = true;
        }
        const std::string line = spec.substr(line_start, line_end - line_start);
        line_start = line_end + 1;

        size_t pos = 0;
        while (pos < line.size() && count < max_out)
        {
            while (pos < line.size() &&
                   (std::isspace(static_cast<unsigned char>(line[pos])) || line[pos] == '+'))
                ++pos;
            size_t token_end = pos;
            while (token_end < line.size() &&
                   !std::isspace(static_cast<unsigned char>(line[token_end])) && line[token_end] != '+')
                ++token_end;
            if (token_end == pos)
                break;
            const std::string token = line.substr(pos, token_end - pos);
            pos = token_end;

            std::string low = token;
            for (auto &ch : low)
                ch = static_cast<char>(::tolower(static_cast<unsigned char>(ch)));
            if (low.rfind("no_", 0) == 0)
                continue;                       // "不许按"的限制，不是要按的键

            const WORD vk = vk_from_name(token);
            if (vk == 0)
                continue;                       // 认不出的键名（例如 Mod 自定义别名）
            bool duplicate = false;
            for (int i = 0; i < count; ++i)
                if (out[i] == static_cast<int>(vk)) { duplicate = true; break; }
            if (!duplicate)
                out[count++] = static_cast<int>(vk);
        }
    }
    return count;
}

// ---------------------------------------------------------------------------
// 面板发键：**F13..F24 内部通道**（2026-10-02 第二版，不带任何修饰键）
//
// 用户原话：「不要用开关或滑块，都是一个键，做切换的按键就行」+「再测一下 f13 到 f24，
// **不要用 alt 这种辅助键**」。所以：
//   * 面板**不去伪造 Mod 的原键**（那些是 `→` / `0` / `Alt+0` 这类真实键：游戏自己在用，
//     别的 addon 也在轮询它们 —— 当年 F6/F7 撞车就是这么来的）；
//   * 改发 `controller.ini` 里那套内部频道的键：**动作号的十进制各位 = F13..F22**，
//     最后按 **F24 提交**，全程不带 ctrl/alt/shift。F13 以上的键标准键盘上不存在，
//     除了我们的 `[KeyMC_*]` 段没人会接。
//   * EFMI 每帧轮询，所以必须**一个键一个键地发**（同时按下两位数字会被当成一次组合、
//     数字位错乱）⇒ 这里做成"待发序列 + 下一步时间点"，由 draw_overlay 每帧推进。
//     不阻塞 UI、不用线程；发送期间再点按钮就把动作**追加到队尾**（连点 = 连切几档）。
// ---------------------------------------------------------------------------
static std::vector<int> g_pending_keys;      // 还要发的键（可能排了多个动作）
static size_t g_pending_index = 0;
static DWORD g_pending_next_tick = 0;
static long long g_sent_actions = 0;         // 面板一共发出过多少个动作（状态行显示）

static const DWORD KEY_HOLD_MS = 160;        // 单键按下时长（跨帧：30fps 下也有 4~5 帧）
static const DWORD KEY_GAP_MS = 140;         // 键与键之间的间隔（确保上一键先被看到"释放"）

static bool sequence_busy()
{
    return g_pending_index < g_pending_keys.size();
}

// 内部通道：把动作号排进 F13..F24 的发送队列（面板当前走这条路，见 press_action）
static void enqueue_action_keys(int wire_id)
{
    if (wire_id <= 0)
        return;
    const std::string digits = std::to_string(wire_id);
    for (const char ch : digits)
        if (ch >= '0' && ch <= '9')
            g_pending_keys.push_back(VK_F13 + (ch - '0'));   // 数字 n → F13+n
    g_pending_keys.push_back(VK_F24);                        // 提交
    if (!sequence_busy())
        g_pending_next_tick = GetTickCount();                // 空队列：第一步立刻发
}

// 每帧推进一步（由 draw_overlay 调用）。发送期间这里不做别的。
static void pump_key_sequence()
{
    if (!sequence_busy())
        return;
    const DWORD now = GetTickCount();
    if (static_cast<LONG>(now - g_pending_next_tick) < 0)
        return;                                              // 还没到下一步
    const int vk = g_pending_keys[g_pending_index++];
    vkey::press(vk, KEY_HOLD_MS);
    if (!sequence_busy())
    {
        ++g_sent_actions;
        g_pending_keys.clear();
        g_pending_index = 0;
        addon_log("key_sequence: 一组动作已发完（F13..F24 通道，不带修饰键）");
        return;
    }
    g_pending_next_tick = now + KEY_HOLD_MS + KEY_GAP_MS;
}

// 面板发键走哪条路（2026-10-02）：
//   true  = **内部通道**（当前）：发 `F13..F24`（动作号逐位 + F24 提交），由 controller.ini
//           用 `run =` 呼叫**注入在 Mod 自己 ini 里**的命令列表来切档。**不碰任何真实按键**，
//           所以不会连带触发别的 Mod / 别的插件（同一个真实键被多个 Mod 绑定时尤其重要）。
//   false = **发原键**（兜底，用户实测可用）：直接伪造这个 Mod 自己的按键。
// 想快速切回去就把这里改成 false 重新编译一次（其余代码不用动）。
static constexpr bool kUseInternalChannel = true;

static bool action_usable(const ActionEntry &action)
{
    if (kUseInternalChannel)
        return action.wire_id > 0;      // 内部通道只要求"有动作号"
    return !action.vks.empty();          // 发原键要求"解析得出原键"
}

// 点一下按钮。两条路都**只**在游戏进程内伪造 EFMI 读到的键状态，不发任何输入事件。
//
// 2026-10-02 的三次迭代（留着，别再绕）：
//   ① 发 `F13..F24` + 在本文件里改 Mod 变量 ⇒ **失败**：`[CommandList]` 的变量赋值只认本 ini
//      声明过的 `$name`，跨命名空间引用（`$\mods\...\coat = 1`）被静默丢弃（同段里本命名空间的
//      `$mc_action_seen` 却正常自增 —— 假绿灯）；
//   ② 改成发 Mod 原键 ⇒ 能用（用户实测"这个可以"），但会连带触发绑同一个真实键的别的 Mod；
//   ③ 现在这版：`F13..F24` + **把"切下一档"注入进 Mod 自己的 ini**，controller.ini 只负责
//      `run = CommandList\<Mod 命名空间>\MC_Panel<动作号>` 呼叫它（跨命名空间**调用**是支持的）。
static void press_action(const ActionEntry &action)
{
    if (!action_usable(action))
    {
        addon_log("press_action: 这一项面板发不了 id=" + std::to_string(action.id)
                  + " wire=" + std::to_string(action.wire_id)
                  + " original_keys='" + action.original_keys + "'");
        return;
    }

    if (kUseInternalChannel)
    {
        addon_log("press_action: id=" + std::to_string(action.id) + " wire=" + std::to_string(action.wire_id)
                  + "（内部通道 F13..F24）");
        enqueue_action_keys(action.wire_id);
        return;
    }

    std::string keys;
    for (size_t i = 0; i < action.vks.size(); ++i)
    {
        if (i != 0)
            keys += ",";
        keys += std::to_string(action.vks[i]);
    }
    addon_log("press_action: id=" + std::to_string(action.id) + " 发原键 vk=[" + keys + "]"
              + " original_keys='" + action.original_keys + "'");
    vkey::press_all(action.vks.data(), action.vks.size());
    ++g_sent_actions;
}

// （`queue_action` 已删：2026-10-01 那版在后台线程里 `Sleep(80)` + `SendInput`，
//   一次动作要 0.9 秒；现在 `press_action` 是同步的微秒级操作，不需要线程，
//   也**不再自动关面板**——旧实现每次操作都 `runtime->open_overlay(false, …)`，
//   用户的实际感受是「按一个键就会退出 ReShade 页面」，想在面板里连点几下都做不到。）


// ---------------------------------------------------------------------------
// 绘制
// ---------------------------------------------------------------------------

static void check_cjk_font()
{
    if (g_cjk_checked)
        return;
    g_cjk_checked = true;
    ImFont *font = ImGui::GetFont();
    if (font == nullptr)
    {
        g_cjk_ok = false;
        addon_log("font: GetFont() == null → 用英文标签");
        return;
    }
    // 「中」「耳」两个字都在 = 字体带中文
    g_cjk_ok = font->IsGlyphInFont(0x4E2D) && font->IsGlyphInFont(0x8033);
    addon_log(std::string("font: cjk glyphs = ") + (g_cjk_ok ? "yes" : "no"));
}

static std::string action_title(const ActionEntry &action)
{
    if (!action.hint.empty())
        return action.hint;
    if (!action.var_name.empty())
        return "$" + action.var_name;
    if (!action.label.empty())
        return action.label;
    return std::string(T("动作 ", "action ")) + std::to_string(action.id);
}

static std::string detail_line(const ActionEntry &action)
{
    std::string text;
    if (!action.var_name.empty())
        text += std::string(T("变量 ", "var ")) + "$" + action.var_name;
    if (!action.key_label.empty())
    {
        if (!text.empty())
            text += "   ";
        // 这一行原本是「手按 ←」= 你不用面板、直接按这个键也能切换。
        // 锁键模式（默认）下原键已被改写成 `VK_F24`，手按**不再生效**，所以如实改成「原键 ←（已锁）」，
        // 免得用户以为还能手按（面板走内部通道，照常能用 —— 见文件头那段）。
        text += g_takeover
            ? std::string(T("原键 ", "was ")) + action.key_label + std::string(T("（已锁）", " (locked)"))
            : std::string(T("手按 ", "manual ")) + action.key_label;
    }
    if (!action.condition.empty())
    {
        if (!text.empty())
            text += "   ";
        // 条件就是"为什么按了没反应"的答案（例如 `($mode == 3)`）——原样显示，比藏起来有用。
        text += std::string(T("条件 ", "only when ")) + action.condition;
    }
    if (text.empty() && !action.section.empty())
        text = action.section;
    return text;
}

// 面板上的一项 = **一个按钮**。
//
// 用户 2026-10-02 原话：「**不要用开关或滑块，都是一个键，做切换的按键就行**」。
// 点一下 = 按一次这个 Mod 自己的原键，下一步切到哪一档由 Mod 内部决定。
//
// 为什么不做开关/滑块：面板**读不到** Mod 的真实状态（那些变量活在 3DMigoto 的内存里，
// 只有游戏退出时才会写回 `d3dx_user.ini`），所以任何"开 / 关"显示都是编的 ——
// 用户对"表面功夫"的容忍度是零（「那些滑块要真的有用」）。按钮没有状态，就不会说谎。
static void draw_action_button(const ActionEntry &action, int shared_key_count)
{
    ImGui::PushID(action.id);

    if (ImGui::BeginTable("row", 2, ImGuiTableFlags_SizingFixedFit, ImVec2(0.0f, 0.0f), 0.0f))
    {
        ImGui::TableSetupColumn("button", ImGuiTableColumnFlags_WidthFixed, 250.0f, 0);
        ImGui::TableSetupColumn("detail", ImGuiTableColumnFlags_WidthStretch, 0.0f, 0);
        ImGui::TableNextRow(0, 0.0f);
        ImGui::TableNextColumn();

        const bool usable = action_usable(action);
        if (!usable)
            ImGui::BeginDisabled();
        if (ImGui::Button(action_title(action).c_str(), ImVec2(230.0f, 0.0f)))
            press_action(action);
        if (!usable)
            ImGui::EndDisabled();

        ImGui::TableNextColumn();
        if (!usable)
        {
            ImGui::TextDisabled("%s", T("（这一项没有动作号，发不了 —— 在控制器里重新生成一次控制器）",
                                        "(no action id: regenerate the controller mod)"));
        }
        else
        {
            const std::string detail = detail_line(action);
            if (!shared_key_count || shared_key_count <= 1)
            {
                if (!detail.empty())
                    ImGui::TextDisabled("%s", detail.c_str());
            }
            else
            {
                // 同一个键被这个 Mod 的多项共用（3DMigoto 里一个键可以分别命中若干
                // `if` 条件不同的段）——点哪一项发出去的都是同一个键，说清楚，
                // 免得用户以为"点这一项没反应、点那一项才有"。
                const std::string note = std::to_string(shared_key_count);
                ImGui::TextDisabled("%s%s%s", detail.c_str(), detail.empty() ? "" : "   ",
                                    (std::string(T("（本 Mod 共 ", "(")) + note +
                                     T(" 项共用这个键，按一下切到下一档）",
                                       " actions share this key; one press cycles)")).c_str());
            }
        }

        ImGui::EndTable();
    }

    ImGui::PopID();
}

// 顶部状态行：注入到底接上 EFMI 没有、被读到多少次、面板发了多少次。
// 这一行是**可自动验证的证据**：点按钮后 "命中" 会涨 ⇒ hook 确实走在 EFMI 的读键路径上；
// 一直是 0 ⇒ 面板得换一条路（日志里有原因）。
static void draw_injection_status()
{
    const vkey::HookStatus &state = vkey::status();
    if (state.installed)
    {
        ImGui::TextDisabled("%s%lld%s%lld%s%s", T("注入 OK · EFMI 命中 ", "injection OK · hits "),
                            vkey::stat_hits().load(std::memory_order_relaxed),
                            T(" · 面板已发 ", " · sent "),
                            g_sent_actions,
                            T(" 次", ""),
                            sequence_busy() ? T(" · 发送中…", " · sending…") : "");
    }
    else
    {
        ImGui::TextColored(ImVec4(0.95f, 0.55f, 0.25f, 1.0f), "%s",
                           T("注入没生效 —— 面板按键不会起作用（原因见 modecontroller.addon.log）",
                             "injection not active: panel keys will not work (see modecontroller.addon.log)"));
    }
}

// ---------------------------------------------------------------------------
// 界面大小（用户 2026-10-03 要求：「reshade 的 mod 控制页能不能加一个调整 UI 大小」）
//
//   用 ImGui 的 `FontGlobalScale` 缩放文字，同时按比例放大控件尺寸（`ScaleAllSizes`，
//   只在数值变化时调一次，否则每帧累积会越缩越小）。
//   值存在 addon 目录的 `ui_scale.txt` 里，下次进游戏仍然生效。
//
// 另附「重置面板布局」：ReShade 把面板窗口的尺寸/位置写进 `ReShade.ini` 的
//   `[OVERLAY] Window=...`（形如 `[Window][###addons],Pos=8,,8,Size=895,,1584,...`）。
//   那个尺寸一旦被拖得比屏幕还高，标签栏就会被挤出可视区、看起来"标签全没了"——
//   清掉这个键，ReShade 下次启动就用回默认布局。
// ---------------------------------------------------------------------------
static float g_ui_scale = 1.0f;
static bool g_layout_reset_done = false;   // 本次会话是否刚点过"重置面板布局"
static float g_ui_scale_applied = 0.0f;

static fs::path ui_scale_path()
{
    return g_base_path / L"ui_scale.txt";
}

static void load_ui_scale()
{
    std::ifstream file(ui_scale_path());
    if (!file.is_open())
        return;
    std::string text;
    std::getline(file, text);
    try
    {
        const float value = std::stof(text);
        if (value >= 0.5f && value <= 3.0f)
            g_ui_scale = value;
    }
    catch (...)
    {
        // 文件坏了就用默认值，不影响面板
    }
}

static void save_ui_scale()
{
    std::ofstream file(ui_scale_path(), std::ios::trunc);
    if (!file.is_open())
        return;
    file << g_ui_scale;
    addon_log("ui_scale saved: " + std::to_string(g_ui_scale));
}

// 自己缩样式：addon 不链接 ImGui（它由 ReShade 提供），而 ReShade 并没有导出
// `ImGuiStyle::ScaleAllSizes` —— 用它会链接失败（undefined reference）。所以这里手写一份，
// 只动最影响观感的字段，并按**基准值**重算，避免每次缩放累积误差。
static void scale_style(float scale)
{
    ImGuiStyle &style = ImGui::GetStyle();
    style.WindowPadding     = ImVec2(8.0f * scale, 8.0f * scale);
    style.FramePadding      = ImVec2(4.0f * scale, 3.0f * scale);
    style.CellPadding       = ImVec2(4.0f * scale, 2.0f * scale);
    style.ItemSpacing       = ImVec2(8.0f * scale, 4.0f * scale);
    style.ItemInnerSpacing  = ImVec2(4.0f * scale, 4.0f * scale);
    style.IndentSpacing     = 21.0f * scale;
    style.ScrollbarSize     = 14.0f * scale;
    style.GrabMinSize       = 10.0f * scale;
    style.FrameBorderSize   = 1.0f * scale;
    style.WindowBorderSize  = 1.0f * scale;
    style.ChildBorderSize   = 1.0f * scale;
    style.PopupBorderSize   = 1.0f * scale;
    style.WindowRounding    = 0.0f;
    style.FrameRounding     = 3.0f * scale;
    style.GrabRounding      = 3.0f * scale;
    style.ScrollbarRounding = 3.0f * scale;
    style.WindowMinSize     = ImVec2(32.0f * scale, 32.0f * scale);
}

// 每帧开头调一次；数值没变时什么都不做。
static void apply_ui_scale()
{
    if (g_ui_scale_applied == g_ui_scale)
        return;
    ImGui::GetIO().FontGlobalScale = g_ui_scale;   // 文字大小
    scale_style(g_ui_scale);                        // 控件尺寸（间距/内边距/滚动条等）
    g_ui_scale_applied = g_ui_scale;
    addon_log("ui_scale applied: " + std::to_string(g_ui_scale));
}

// 把 `ReShade.ini` 的 `[OVERLAY]` 段里那行 `Window=...` 清掉，让 ReShade 用回默认布局。
static bool reset_overlay_layout()
{
    const fs::path ini = g_base_path / L"ReShade.ini";
    std::ifstream in(ini);
    if (!in.is_open())
    {
        addon_log("reset_overlay_layout: 打不开 " + ini.string());
        return false;
    }
    std::vector<std::string> lines;
    std::string line;
    bool in_overlay = false;
    bool cleared = false;
    while (std::getline(in, line))
    {
        if (!line.empty() && line[0] == '[')
        {
            in_overlay = (line.rfind("[OVERLAY]", 0) == 0);
            lines.push_back(line);
            continue;
        }
        // Window= 这行是 ReShade 存窗口布局用的；清成空值即可恢复默认
        if (in_overlay && line.rfind("Window=", 0) == 0)
        {
            lines.push_back("Window=");
            cleared = true;
            continue;
        }
        lines.push_back(line);
    }
    in.close();
    if (!cleared)
    {
        addon_log("reset_overlay_layout: 没找到 [OVERLAY] Window= 行");
        return false;
    }
    std::ofstream out(ini, std::ios::trunc | std::ios::binary);
    if (!out.is_open())
    {
        addon_log("reset_overlay_layout: 写不回 " + ini.string());
        return false;
    }
    for (const auto &item : lines)
        out << item << "\r\n";
    addon_log("reset_overlay_layout: 已清空 [OVERLAY] Window=（重启游戏后生效）");
    return true;
}

static void draw_overlay(reshade::api::effect_runtime *runtime)
{
    runtime->block_input_next_frame();
    check_cjk_font();
    apply_ui_scale();          // 界面大小（用户可在面板里调）

    // hook 没装上就每 2 秒重试一次：正常时序里 EFMI 的 d3d11.dll 先加载、面板后加载，
    // 但"用户中途换过注入方式 / 面板先起来"的情况下，靠重试能自愈。
    if (!vkey::status().installed && (GetTickCount() - g_hook_retry_tick) > 2000)
    {
        g_hook_retry_tick = GetTickCount();
        vkey::install();
    }

    // 每帧推进一步按键序列（F13..F24 内部通道，见文件里 pump_key_sequence 的说明）
    pump_key_sequence();

    static bool overlay_logged = false;
    if (!overlay_logged)
    {
        overlay_logged = true;
        addon_log("draw_overlay first frame");
    }

    std::lock_guard<std::recursive_mutex> lock(g_actions_mutex);

    ImGui::TextUnformatted(T("统一 Mod 控制", "Unified Mod Control"));
    ImGui::SameLine();
    if (ImGui::SmallButton(T("刷新", "Reload")))
    {
        load_paths();
        load_actions();
    }
    // ── 界面设置（默认折叠，不占地方）────────────────────────────────────
    if (ImGui::CollapsingHeader(T("界面设置", "UI settings")))
    {
        ImGui::SetNextItemWidth(220.0f);
        if (ImGui::SliderFloat(T("界面大小", "UI scale"), &g_ui_scale, 0.75f, 2.0f, "%.2fx"))
            save_ui_scale();
        ImGui::SameLine();
        if (ImGui::SmallButton(T("改回 1.00x", "Reset to 1.00x")))
        {
            g_ui_scale = 1.0f;
            save_ui_scale();
        }
        ImGui::TextDisabled("%s", T("调整面板文字与控件的大小，改完立刻生效、下次进游戏也记得。",
                                    "Scales the panel text and controls; applied immediately and remembered."));

        ImGui::Spacing();
        if (ImGui::Button(T("重置面板布局", "Reset panel layout")))
            g_layout_reset_done = reset_overlay_layout();
        ImGui::TextDisabled("%s", T("面板标签栏被挤出屏幕 / 看不见时点它（改完要重启游戏生效）。",
                                    "Use when the panel tabs are pushed off-screen (takes effect after restarting the game)."));
        if (g_layout_reset_done)
            ImGui::TextColored(ImVec4(0.45f, 0.85f, 0.45f, 1.0f), "%s",
                               T("已重置 —— 重启游戏后标签栏就回来了。", "Reset done - restart the game to see the tabs again."));
    }
    draw_injection_status();

    if (!g_paths_loaded)
        ImGui::TextDisabled("%s", T("（未找到 d3dx_user.ini 路径：先运行控制器的一键启动）",
                                    "(user_ini_path.txt missing: run the launcher once)"));
    else
        ImGui::TextDisabled("%s", kUseInternalChannel
            ? T("点一下按钮 = 切到下一档（走面板内部通道，不碰游戏真实按键）",
                "Click a button = one step (via the panel's internal channel; real game keys untouched)")
            : T("点一下按钮 = 按一次这个 Mod 自己的按键（Mod 内部切到下一档）",
                "Click a button = press the mod's own key (cycles one step)"));

    if (g_takeover)
    {
        // 锁键模式 = **预期状态**（2026-10-02 重新启用「Mod 快捷键锁定」，默认开）：
        // Mod 的 `key` 行被改写成 `no_modifiers VK_F24`，手按原键不再生效，
        // 操作集中到本面板 —— 这样多个 Mod 抢同一个键时就不会互相干扰。
        // 面板走的是内部通道（F13..F24 + 注入在 Mod ini 里的切档列表），**不受锁键影响**。
        ImGui::TextColored(ImVec4(0.45f, 0.85f, 0.45f, 1.0f), "%s",
                           T("Mod 自带按键已锁定（防止 Mod 之间抢同一个键）—— 请用本面板切换。"
                             "想改回手动按键：在控制器里关掉「Mod 快捷键锁定」。",
                             "Mod hotkeys are locked (so mods can't fight over the same keys) — "
                             "use this panel. Turn off 'lock mod hotkeys' in the controller to revert."));
    }

    if (!g_generated.empty() || g_expected_actions > 0)
    {
        ImGui::TextDisabled("%s%zu %s%s", T("清单 ", "actions "), g_actions.size(),
                            T(" 项 · 生成于 ", " · generated "), g_generated.c_str());
    }

    ImGui::Separator();

    if (g_actions.empty())
    {
        ImGui::TextWrapped("%s", T("没有可用操作。请先在控制器里勾选 Mod 并点「生成控制器」/「一键启动」。",
                                   "No actions yet. Select mods and run 'Prepare'/'One-click launch' first."));
        return;
    }

    if (!g_cjk_ok)
        ImGui::TextDisabled("%s", T("", "Font has no CJK glyphs: showing English labels."));

    // 角色 → Mod → 动作
    std::map<std::string, std::map<std::string, std::vector<const ActionEntry *>>> tree;
    for (const auto &action : g_actions)
    {
        const std::string group = action.char_group.empty()
            ? std::string(T("未分类", "Ungrouped"))
            : action.char_group;
        tree[group][action.mod_name].push_back(&action);
    }

    for (const auto &group : tree)
    {
        if (!ImGui::CollapsingHeader(group.first.c_str(), ImGuiTreeNodeFlags_DefaultOpen))
            continue;

        for (const auto &mod : group.second)
        {
            ImGui::Indent(14.0f);
            std::string header = mod.first;
            if (!mod.second.empty() && !mod.second.front()->description.empty())
                header += "  ·  " + mod.second.front()->description;
            ImGui::TextDisabled("%s", header.c_str());
            ImGui::Spacing();

            // 同一个 `key` 行被这个 Mod 的多项共用是常态（一个键分别命中若干条件不同的段），
            // 统计出次数是为了在按钮旁边说清楚"点哪一项发的都是同一个键"。
            std::map<std::string, int> shared_keys;
            for (const ActionEntry *action : mod.second)
                shared_keys[action->original_keys] += 1;

            for (const ActionEntry *action : mod.second)
                draw_action_button(*action, shared_keys[action->original_keys]);

            ImGui::Spacing();
            ImGui::Unindent(14.0f);
        }
    }
}

BOOL APIENTRY DllMain(HMODULE hModule, DWORD reason, LPVOID)
{
    switch (reason)
    {
    case DLL_PROCESS_ATTACH:
        g_base_path = get_base_path();
        addon_log("DllMain attach: base=" + g_base_path.string());
        // 键注入的日志并进同一份 addon 日志，排查时一个文件看全。
        vkey::set_logger([](const char *message) { addon_log(message); });
        load_actions();
        addon_log("actions loaded: " + std::to_string(g_actions.size()));
        load_paths();
        load_ui_scale();      // 界面大小（用户上次调的）
        // 接上 EFMI 的读键路径（失败也不影响面板显示；draw_overlay 会每 2 秒重试）
        vkey::install();
        if (!reshade::register_addon(hModule))
            return FALSE;
        reshade::register_overlay("ModeController", draw_overlay);
        break;
    case DLL_PROCESS_DETACH:
        addon_log("DllMain detach");
        // 先拆 hook 再卸 overlay：addon 被卸载后 EFMI 绝不能还指着我们的函数
        vkey::uninstall();
        reshade::unregister_overlay("ModeController", draw_overlay);
        reshade::unregister_addon(hModule);
        break;
    }
    return TRUE;
}
