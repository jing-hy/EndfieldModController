// fake_efmi_d3d11.dll —— 自测用的"假 EFMI"。
//
// 它只做一件事：**通过导入表的 `GetAsyncKeyState` 轮询按键状态** ——
// 与真 EFMI（3DMigoto 的 `d3d11.dll`，见 vkey_inject.h 顶部的实测依据）读键的方式一致。
// 于是"面板在游戏进程里伪造按键"这条链路可以在**离线**环境里被验证：
// 编译本文件 → 被 hook_host.exe 加载 → 由 vkey::press() 注入 → 看本 dll 读到了什么。
#include <Windows.h>

extern "C" __declspec(dllexport) int FakeFrameRead(int vk)
{
    const SHORT state = GetAsyncKeyState(vk);
    int bits = 0;
    if (state & 0x8000) bits |= 1;   // 正按住（`& 0x8000` 语义）
    if (state & 0x0001) bits |= 2;   // 自上次读取后按下过（`& 1` 语义）
    return bits;
}

extern "C" __declspec(dllexport) void *FakeThunkAddress()
{
    // 返回编译器为 `GetAsyncKeyState` 生成的 thunk 地址（间接跳转 [IAT]），
    // 供宿主验证"这份 dll 确实是经由导入表调用它的"。
    return reinterpret_cast<void *>(&GetAsyncKeyState);
}
