#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p build
g++ -std=c++17 -shared -static -static-libgcc -static-libstdc++ \
    src/endfieldmodcontroller_addon.cpp \
    -o build/endfieldmodcontroller.addon \
    -I vendor/reshade/include \
    -I vendor/imgui \
    -DWIN32_LEAN_AND_MEAN -DNOMINMAX -D_CRT_SECURE_NO_WARNINGS \
    -luser32 -lkernel32
echo "built: $(pwd)/build/endfieldmodcontroller.addon"
