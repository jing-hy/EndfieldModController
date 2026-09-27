// ModeController ReShade add-on PoC
//
// This add-on draws the unified mod control UI using ReShade's ImGui overlay.
// It does not inject itself and it does not write into the game directory.
// The external app prepares:
//   - actions.tsv              (action list for this overlay)
//   - user_ini_path.txt        (path to EFMI's d3dx_user.ini)
//
// On an action click the add-on writes the generated controller action queue
// into d3dx_user.ini and sends F10 so EFMI reloads and the controller mod runs.

#include <Windows.h>

#define ImTextureID ImU64
#define IMGUI_DEFINE_MATH_OPERATORS
#include <imgui.h>

#include <reshade.hpp>

#include <algorithm>
#include <cctype>
#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <map>
#include <mutex>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

namespace fs = std::filesystem;

struct ActionEntry
{
    int id = 0;
    std::string label;
    std::string kind;
    std::string mod_name;
    std::vector<std::string> values;
    std::string description;
    std::string current_value;
    std::string namespace_name;
    std::string var_name;
    std::string section;
    std::string run_command;
    std::string original_keys;
    int wire_id = 0;
    bool send_index = true;
    bool merged = false;
};
static std::vector<ActionEntry> g_actions;
static std::recursive_mutex g_actions_mutex;
static fs::path g_base_path;
static fs::path g_user_ini_path;
static bool g_paths_loaded = false;
static std::map<int, std::string> g_selected_values;
static std::map<int, bool> g_toggle_states;
static std::mutex g_log_mutex;
static void addon_log(const std::string &message);
static fs::path addon_log_path();

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

static void load_actions()
{
    std::lock_guard<std::recursive_mutex> lock(g_actions_mutex);
    g_actions.clear();
    g_selected_values.clear();
    g_toggle_states.clear();

    const fs::path actions_path = g_base_path / L"actions.tsv";
    addon_log("load_actions: " + actions_path.string());
    std::ifstream file(actions_path);
    if (!file.is_open())
        return;

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
        if (fields.size() > 6) entry.current_value = trim(fields[6]);
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
        g_actions.push_back(std::move(entry));
    }
    addon_log("load_actions: loaded " + std::to_string(g_actions.size()) + " actions");
}
static void load_paths()
{
    std::lock_guard<std::recursive_mutex> lock(g_actions_mutex);
    g_paths_loaded = false;
    g_user_ini_path.clear();

    // External app can set this env var; it is the least fragile option.
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
        addon_log("load_paths: user_ini_path.txt missing or empty");
    }
}

static bool write_user_var(const std::string &namespace_name, const std::string &var_name, const std::string &value)
{
    if (!g_paths_loaded || g_user_ini_path.empty())
        return false;

    std::vector<std::string> lines;
    {
        std::ifstream file(g_user_ini_path);
        std::string line;
        while (std::getline(file, line))
            lines.push_back(line);
    }

    const std::string target_key = "$\\" + namespace_name + "\\" + var_name;
    const std::string target_line = target_key + " = " + value;
    bool replaced = false;
    bool in_constants = false;
    std::vector<std::string> out;
    out.reserve(lines.size() + 2);
    for (const auto &line : lines)
    {
        const std::string stripped = trim(line);
        if (!stripped.empty() && stripped.front() == '[' && stripped.back() == ']')
        {
            in_constants = _stricmp(stripped.c_str(), "[Constants]") == 0;
            out.push_back(line);
            continue;
        }
        if (in_constants && !stripped.empty() && stripped.front() == '$')
        {
            const auto eq = stripped.find('=');
            if (eq != std::string::npos)
            {
                std::string key = trim(stripped.substr(0, eq));
                if (_stricmp(key.c_str(), target_key.c_str()) == 0)
                {
                    out.push_back(target_line);
                    replaced = true;
                    continue;
                }
            }
        }
        out.push_back(line);
    }
    if (!replaced)
    {
        std::vector<std::string> inserted;
        bool did_insert = false;
        for (const auto &line : out)
        {
            inserted.push_back(line);
            if (!did_insert && _stricmp(trim(line).c_str(), "[Constants]") == 0)
            {
                inserted.push_back(target_line);
                did_insert = true;
            }
        }
        if (!did_insert)
        {
            inserted.push_back("");
            inserted.push_back("[Constants]");
            inserted.push_back(target_line);
        }
        out = std::move(inserted);
    }

    const fs::path tmp_path = g_user_ini_path.wstring() + L".mc.tmp";
    {
        std::ofstream file(tmp_path, std::ios::binary | std::ios::trunc);
        if (!file.is_open())
            return false;
        for (const auto &line : out)
            file << line << "\r\n";
    }
    std::error_code ec;
    fs::rename(tmp_path, g_user_ini_path, ec);
    if (ec)
        return false;
    return true;
}

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

    SendInput(ARRAYSIZE(down), down, sizeof(INPUT));
    Sleep(70);
    SendInput(ARRAYSIZE(up), up, sizeof(INPUT));
    Sleep(20);
}

static void send_digit_key(int digit)
{
    if (digit < 0 || digit > 9)
        return;
    send_key_combo(static_cast<WORD>(VK_F1 + digit));
}

static void send_action_keys(int wire_id, int value_index)
{
    const std::string wire = std::to_string(wire_id > 0 ? wire_id : 1);
    const std::string value = std::to_string(value_index >= 0 ? value_index : 0);
    for (const char ch : wire)
        if (ch >= '0' && ch <= '9')
            send_digit_key(ch - '0');
    send_key_combo(VK_F11); // stage action id
    for (const char ch : value)
        if (ch >= '0' && ch <= '9')
            send_digit_key(ch - '0');
    send_key_combo(VK_F12); // commit action + value
}

static void queue_action(reshade::api::effect_runtime *runtime, const ActionEntry &action, const std::string &value)
{
    addon_log("queue_action: id=" + std::to_string(action.id) + " wire=" + std::to_string(action.wire_id) + " value=" + (value.empty() ? "0" : value));

    int value_index = 0;
    if (action.send_index)
    {
        try { value_index = std::stoi(value.empty() ? "0" : value); }
        catch (...) { value_index = 0; }
    }
    else
    {
        const auto it = std::find(action.values.begin(), action.values.end(), value);
        if (it != action.values.end())
            value_index = static_cast<int>(std::distance(action.values.begin(), it));
    }

    if (runtime != nullptr)
        runtime->open_overlay(false, reshade::api::input_source::keyboard);

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

static std::string action_preview_value(const ActionEntry &action)
{
    const auto it = g_selected_values.find(action.id);
    if (it != g_selected_values.end())
        return it->second;
    if (!action.current_value.empty())
        return action.current_value;
    if (!action.values.empty())
        return action.values.front();
    return "1";
}

static void draw_action_control(reshade::api::effect_runtime *runtime, const ActionEntry &action)
{
    ImGui::PushID(action.id);
    ImGui::TextUnformatted(action.label.c_str());
    if (!action.description.empty())
        ImGui::TextDisabled("%s", action.description.c_str());

    if (action.kind == "command")
    {
        if (ImGui::Button(u8"执行", ImVec2(120, 0)))
            queue_action(runtime, action, "0");
    }
    else if (action.kind == "cycle" && !action.values.empty())
    {
        const std::string current = action_preview_value(action);
        int current_index = 0;
        for (int i = 0; i < static_cast<int>(action.values.size()); ++i)
        {
            if (action.values[static_cast<size_t>(i)] == current)
            {
                current_index = i;
                break;
            }
        }

        const char *preview = action.values[static_cast<size_t>(current_index)].c_str();
        ImGui::SetNextItemWidth(280.0f);
        if (ImGui::BeginCombo("##value", preview))
        {
            for (int i = 0; i < static_cast<int>(action.values.size()); ++i)
            {
                const bool selected = (i == current_index);
                ImGui::PushID(i);
                if (ImGui::Selectable(action.values[static_cast<size_t>(i)].c_str(), selected))
                {
                    g_selected_values[action.id] = action.values[static_cast<size_t>(i)];
                    queue_action(runtime, action, std::to_string(i));
                }
                if (selected)
                    ImGui::SetItemDefaultFocus();
                ImGui::PopID();
            }
            ImGui::EndCombo();
        }
    }
    else
    {
        bool checked = false;
        const auto state_it = g_toggle_states.find(action.id);
        if (state_it != g_toggle_states.end())
            checked = state_it->second;
        else if (!action.current_value.empty())
            checked = (action.current_value != "0");
        else if (!action.values.empty())
            checked = (action.values.front() != "0");

        if (ImGui::Checkbox(u8"启用", &checked))
        {
            g_toggle_states[action.id] = checked;
            queue_action(runtime, action, checked ? "1" : "0");
        }
    }

    if (!action.namespace_name.empty() || !action.var_name.empty())
        ImGui::TextDisabled(u8"变量: %s / %s", action.namespace_name.c_str(), action.var_name.c_str());
    if (!action.section.empty())
        ImGui::TextDisabled(u8"来源: %s", action.section.c_str());
    if (!action.run_command.empty())
        ImGui::TextDisabled(u8"命令: %s", action.run_command.c_str());
    if (!action.original_keys.empty())
        ImGui::TextDisabled(u8"原快捷键: %s", action.original_keys.c_str());

    ImGui::Separator();
    ImGui::PopID();
}

static std::string action_prefix(const ActionEntry &action)
{
    std::string label = action.label;
    const auto bracket = label.find(" (");
    if (bracket != std::string::npos)
        label = label.substr(0, bracket);
    label = trim(label);
    while (!label.empty() && (std::isdigit(static_cast<unsigned char>(label.back())) || label.back() == ' '))
        label.pop_back();
    label = trim(label);
    if (label.size() < 3)
        return "";
    return label;
}

static void draw_prefix_menu(reshade::api::effect_runtime *runtime, const std::string &prefix, const std::vector<const ActionEntry *> &actions)
{
    ImGui::PushID(prefix.c_str());
    ImGui::SetNextItemWidth(320.0f);
    if (ImGui::BeginCombo(prefix.c_str(), u8"选择..."))
    {
        for (const ActionEntry *action : actions)
        {
            if (action->values.empty())
            {
                const std::string label = action->label;
                if (ImGui::Selectable(label.c_str(), false))
                    queue_action(runtime, *action, "0");
                continue;
            }
            for (int index = 0; index < static_cast<int>(action->values.size()); ++index)
            {
                const std::string label = action->label + " = " + action->values[static_cast<size_t>(index)];
                if (ImGui::Selectable(label.c_str(), false))
                    queue_action(runtime, *action, std::to_string(index));
            }
        }
        ImGui::EndCombo();
    }
    ImGui::PopID();
}

static void draw_overlay(reshade::api::effect_runtime *runtime)
{
    runtime->block_input_next_frame();

    static bool overlay_logged = false;
    if (!overlay_logged)
    {
        overlay_logged = true;
        addon_log("draw_overlay first frame");
    }

    if (!g_paths_loaded)
    {
        ImGui::TextWrapped(u8"正在等待 ModeController 外部程序准备路径...");
        if (ImGui::Button(u8"重新加载"))
        {
            load_paths();
            load_actions();
        }
        return;
    }

    std::lock_guard<std::recursive_mutex> lock(g_actions_mutex);
    if (g_actions.empty())
    {
        ImGui::TextWrapped(u8"没有可用操作，请先在外部 ModeController 中生成控制器。");
        if (ImGui::Button(u8"重新加载"))
            load_actions();
        return;
    }

    ImGui::TextUnformatted(u8"统一 Mod 控制");
    ImGui::SameLine();
    if (ImGui::SmallButton(u8"刷新"))
    {
        load_paths();
        load_actions();
    }
    ImGui::Separator();

    std::map<std::string, std::vector<const ActionEntry *>> groups;
    for (const auto &action : g_actions)
        groups[action.mod_name].push_back(&action);

    for (const auto &group : groups)
    {
        std::string group_description;
        for (const ActionEntry *action : group.second)
        {
            if (!action->description.empty())
            {
                group_description = action->description;
                break;
            }
        }

        if (!ImGui::CollapsingHeader(group.first.c_str(), ImGuiTreeNodeFlags_DefaultOpen))
            continue;
        if (!group_description.empty())
            ImGui::TextDisabled("%s", group_description.c_str());

        for (const ActionEntry *action : group.second)
            draw_action_control(runtime, *action);
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
