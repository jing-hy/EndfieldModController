cmake_minimum_required(VERSION 3.20)
project(endfieldmodcontroller_addon LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

if(NOT DEFINED RESHADE_INCLUDE_DIR)
    set(RESHADE_INCLUDE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/vendor/reshade/include")
endif()
if(NOT DEFINED IMGUI_INCLUDE_DIR)
    set(IMGUI_INCLUDE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/vendor/imgui")
endif()

add_library(endfieldmodcontroller_addon SHARED
    src/endfieldmodcontroller_addon.cpp
)

target_include_directories(endfieldmodcontroller_addon PRIVATE
    "${RESHADE_INCLUDE_DIR}"
    "${IMGUI_INCLUDE_DIR}"
)

target_compile_definitions(endfieldmodcontroller_addon PRIVATE
    WIN32_LEAN_AND_MEAN
    NOMINMAX
    _CRT_SECURE_NO_WARNINGS
)

set_target_properties(endfieldmodcontroller_addon PROPERTIES
    PREFIX ""
    OUTPUT_NAME "endfieldmodcontroller"
    SUFFIX ".addon"
)

if(WIN32)
    target_link_libraries(endfieldmodcontroller_addon PRIVATE user32 kernel32)
endif()

if(MINGW)
    target_link_options(endfieldmodcontroller_addon PRIVATE -static -static-libgcc -static-libstdc++)
endif()
