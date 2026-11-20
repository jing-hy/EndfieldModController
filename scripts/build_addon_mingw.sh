#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-only
set -euo pipefail
cd "$(dirname "$0")/../reshade_addon"
./build_mingw.sh
cp build/endfieldmodcontroller.addon ../dist/endfieldmodcontroller.addon
echo "copied to dist/endfieldmodcontroller.addon"
