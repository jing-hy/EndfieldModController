#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
set -euo pipefail
cd "$(dirname "$0")/../reshade_addon"
./build_mingw.sh
cp build/endfieldmodcontroller.addon ../dist/endfieldmodcontroller.addon
echo "copied to dist/endfieldmodcontroller.addon"
