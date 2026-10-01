// EndfieldModController ReShade add-on —— 统一 Mod 控制面板
//
// 用户 2026-10-01 的需求原话：「做统一面板，**需要注入到 reshade**，ui 尽量做好一点，
// **开关式的就用滑块**，**要标明原快捷键**，**要自动识别那个变量的名称，推测含义**」。
//
// 外部程序（控制器）负责把这几样东西放进 ReShade 的 base 目录
// （= d3d12.dll 所在处；xxmi_extra 注入方式下就是 `<数据根>\runtime\dlss5`）：
//
//   endfieldmodcontroller.addon64   本文件编译出来的面板
//   actions.tsv                     动作清单（含推测含义 / 原快捷键 / 角色分组）
//   user_ini_path.txt               EFMI 的 d3dx_user.ini 路径
//   panel_info.txt                  面板状态（是否已接管 / 生成时间）
//
// 操作路径：点/拖控件 → 发合成键 `Ctrl+Alt+Shift+F<wire>`（数字键逐位）+ F23 暂存 +
// F24 提交 → EFMI 里 controller.ini 的 `[KeyMC_*]` 把它变成 `$mc_state_N` →
// `[Present]` 段按 `$controller_action` 写回 Mod 自己的变量（`$ear` 之类），立刻生效。
//
// ⚠ 面板**只能**待在这儿：ReShade 6.8 的日志写死了它只搜 `d3d12.dll` 所在目录
//   （`Searching for add-ons (*.addon, *.addon64) in '<base>'`）。放到别处 = 用户按
//   原来的键被锁了、新面板却不存在 —— 2026-10-01 出过这个事故，别再犯。
#include <Windows.h>

#define ImTextureID ImU64
#define IMGUI_DEFINE_MATH_OPERATORS
#include <imgui.h>

#include <reshade.hpp>

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
#include <thread>
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
static std::map<int, int> g_selected_index;      // action id -> 当前档位（用户改过之后）
static bool g_takeover = false;
static std::string g_generated;
static int g_expected_actions = 0;
static std::mutex g_log_mutex;
static bool g_cjk_checked = false;
static bool g_cjk_ok = false;

static void addon_log(const std::string &message);
static fs::path addon_log_path();

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
    g_selected_index.clear();
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
        g_actions.push_back(std::move(entry));
    }

    // 用清单里的 current 初始化滑块位置（current 是**档位序号**）
    for (const auto &action : g_actions)
    {
        int index = 0;
        if (!action.current.empty())
        {
            try { index = std::stoi(action.current); }
            catch (...) { index = 0; }
        }
        if (!action.values.empty())
            index = std::max(0, std::min(index, static_cast<int>(action.values.size()) - 1));
        g_selected_index[action.id] = index;
    }

    addon_log("load_actions: loaded " + std::to_string(g_actions.size()) + " actions, takeover="
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
// 合成键协议（沿用既有实现；改的是 UI，不是协议）
// ---------------------------------------------------------------------------

static std::mutex g_key_mutex;

static void send_key_combo(WORD vk)
{
    INPUT down[4] = {};
    INPUT up[4] = {};
    const WORD modifiers[] = { VK_CONTROL, VK_MENU, VK_SHIFT };
    for (int i = 0; i < 3; ++i)
    {
        down[i].type = INPUT_KEYBOARD;
        down[i].ki.wVk = modifiers[i];
        up[i].type = INPUT_KEYBOARD;
        up[i].ki.wVk = modifiers[i];
        up[i].ki.dwFlags = KEYEVENTF_KEYUP;
    }
    down[3].type = INPUT_KEYBOARD;
    down[3].ki.wVk = vk;
    up[3].type = INPUT_KEYBOARD;
    up[3].ki.wVk = vk;
    up[3].ki.dwFlags = KEYEVENTF_KEYUP;

    // ⚠️ 按下时长（2026-10-01 现场定案）：EFMI **每帧轮询** `GetAsyncKeyState` 读键，
    // 而帧率会波动（装了 debug 日志时能掉到十几帧 → 一帧 70~100ms）。
    // 原来只按下 70ms，**整帧被错过就丢一个数字位**，于是"动作号变成 0、面板看起来没反应"
    // （现场：`mc_state_1 = 1` 说明有时是成功的，`mc_last_wire = 0` 说明有时动作号丢了）。
    // 这里把按下保持到 160ms、键间隔 60ms —— 一次动作慢一点（约 0.9 秒），但**可靠**。
    SendInput(ARRAYSIZE(down), down, sizeof(INPUT));
    Sleep(160);
    SendInput(ARRAYSIZE(up), up, sizeof(INPUT));
    Sleep(60);
}

static void send_digit_key(int digit)
{
    if (digit < 0 || digit > 9)
        return;
    // 数字位用 **F13..F22**（= VK_F13 + digit）：这些键**键盘上根本不存在**，
    // 任何游戏、任何 addon 都不会去绑它们 —— 见下面 send_action_keys 的注释。
    send_key_combo(static_cast<WORD>(VK_F13 + digit));
}

// 2026-10-01 修：**协议键必须用键盘上不存在的键**。
//
// 用户实测报告（打通面板后立刻撞了）：
//   ①「按开关外套的时候会切换第一人称」—— 第一人称 addon 的 `ShortcutFirstPerson=112`
//      就是 **VK_F7**，而我们旧协议的数字位 6 = `VK_F1 + 6` = F7 → 一点面板就切第一人称；
//   ②「按切换头发会开关 dlss5」—— DLSS5 addon 的 NR 开关是 **F6**，数字位 5 = F6 → 中招。
//   这些 addon 是**自己读键状态**的（不看修饰键），所以带 Ctrl+Alt+Shift 也照样触发。
//   现在数字位整体挪到 **F13..F22**、暂存 **F23**、提交 **F24**：
//   * F13 以上的键在标准键盘上不存在，插件/游戏/系统都不会绑定；
//   * EFMI（3DMigoto）里 `key = ctrl alt shift VK_F13` 能正常解析（它支持到 VK_F24）；
//   * 与 `patch_mod_hotkeys` 锁键用的 `no_modifiers VK_F24` **不冲突**：那条要求
//     "一个修饰键都不许按"，而我们的提交键必须带 Ctrl+Alt+Shift —— 两者互斥，不会误触。
static void send_action_keys(int wire_id, int value_index)
{
    const std::string wire = std::to_string(wire_id > 0 ? wire_id : 1);
    const std::string value = std::to_string(value_index >= 0 ? value_index : 0);
    for (const char ch : wire)
        if (ch >= '0' && ch <= '9')
            send_digit_key(ch - '0');
    send_key_combo(VK_F23); // 暂存动作号
    for (const char ch : value)
        if (ch >= '0' && ch <= '9')
            send_digit_key(ch - '0');
    send_key_combo(VK_F24); // 提交动作号 + 档位
}

static void queue_action(reshade::api::effect_runtime *runtime, const ActionEntry &action, int value_index)
{
    (void)runtime;
    addon_log("queue_action: id=" + std::to_string(action.id) + " wire=" + std::to_string(action.wire_id)
              + " value=" + std::to_string(value_index));

    // 2026-10-01 修：**不要再自动关面板**。
    // 旧实现每次操作都 `runtime->open_overlay(false, …)`，用户的实际感受是
    // 「按一个键就会退出 ReShade 页面」—— 想在面板里连点几个开关根本做不到。
    // 现在面板保持打开；合成键走 SendInput，EFMI 是**轮询** `GetAsyncKeyState` 读键状态的，
    // 与 ReShade 的输入拦截（拦的是窗口消息）不是一条路，所以照样能读到。
    const int wire_id = action.wire_id > 0 ? action.wire_id : action.id;
    std::thread([wire_id, value_index]()
    {
        std::lock_guard<std::mutex> lock(g_key_mutex);
        Sleep(80);
        addon_log("key_protocol: sending wire=" + std::to_string(wire_id) + " value=" + std::to_string(value_index));
        send_action_keys(wire_id, value_index);
        addon_log("key_protocol: done");
    }).detach();
}

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

static int current_index(const ActionEntry &action)
{
    const auto it = g_selected_index.find(action.id);
    if (it != g_selected_index.end())
        return it->second;
    int index = 0;
    if (!action.current.empty())
    {
        try { index = std::stoi(action.current); }
        catch (...) { index = 0; }
    }
    return index;
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
        text += std::string(T("原键 ", "key ")) + action.key_label;
    }
    if (!action.condition.empty())
    {
        if (!text.empty())
            text += "   ";
        text += std::string(T("条件 ", "only when ")) + action.condition;
    }
    if (text.empty() && !action.section.empty())
        text = action.section;
    return text;
}

static void draw_action_control(reshade::api::effect_runtime *runtime, const ActionEntry &action)
{
    ImGui::PushID(action.id);

    const int count = static_cast<int>(action.values.size());
    const bool is_command = (action.kind == "command" || count == 0);

    if (ImGui::BeginTable("row", 2, ImGuiTableFlags_SizingFixedFit, ImVec2(0.0f, 0.0f), 0.0f))
    {
        ImGui::TableSetupColumn("name", ImGuiTableColumnFlags_WidthStretch, 0.0f, 0);
        ImGui::TableSetupColumn("control", ImGuiTableColumnFlags_WidthFixed, 300.0f, 0);
        ImGui::TableNextRow(0, 0.0f);

        ImGui::TableNextColumn();
        ImGui::TextUnformatted(action_title(action).c_str());
        const std::string detail = detail_line(action);
        if (!detail.empty())
            ImGui::TextDisabled("%s", detail.c_str());

        ImGui::TableNextColumn();
        if (is_command)
        {
            if (ImGui::Button(T("执行", "Run"), ImVec2(150.0f, 0.0f)))
                queue_action(runtime, action, 0);
        }
        else
        {
            int index = current_index(action);
            const bool as_switch = (count == 2);
            // 「开关式的就用滑块」：两档 → 滑块两端写"关/开"；多档 → 滑块上显示当前档位名
            const std::string format = as_switch
                ? std::string(T("关 ——— 开", "off ——— on"))
                : (index >= 0 && index < count ? action.values[static_cast<size_t>(index)] : std::string("%d"));

            ImGui::SetNextItemWidth(200.0f);
            if (ImGui::SliderInt("##value", &index, 0, std::max(0, count - 1), format.c_str(), ImGuiSliderFlags_None))
            {
                g_selected_index[action.id] = index;
                queue_action(runtime, action, index);
            }
            ImGui::SameLine();
            if (as_switch)
                ImGui::TextDisabled("%s", index != 0 ? T("已开", "ON") : T("已关", "OFF"));
            else
                ImGui::TextDisabled("%d/%d", index + 1, count);
        }

        ImGui::EndTable();
    }

    ImGui::PopID();
}

static void draw_overlay(reshade::api::effect_runtime *runtime)
{
    runtime->block_input_next_frame();
    check_cjk_font();

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

    if (!g_paths_loaded)
        ImGui::TextDisabled("%s", T("（未找到 d3dx_user.ini 路径：先运行控制器的一键启动）",
                                    "(user_ini_path.txt missing: run the launcher once)"));
    else
        ImGui::TextDisabled("%s", g_takeover
            ? T("已接管：Mod 自带的按键被锁住，操作都在这个面板里",
                "Takeover ON: the mods' own hotkeys are locked; use this panel")
            : T("未接管：Mod 自带的按键照常生效（这个面板只是对照表）",
                "Takeover OFF: mods keep their own hotkeys (panel is read-only info)"));
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
            for (const ActionEntry *action : mod.second)
                draw_action_control(runtime, *action);
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
        load_actions();
        addon_log("actions loaded: " + std::to_string(g_actions.size()));
        load_paths();
        if (!reshade::register_addon(hModule))
            return FALSE;
        reshade::register_overlay("ModeController", draw_overlay);
        break;
    case DLL_PROCESS_DETACH:
        addon_log("DllMain detach");
        reshade::unregister_overlay("ModeController", draw_overlay);
        reshade::unregister_addon(hModule);
        break;
    }
    return TRUE;
}
