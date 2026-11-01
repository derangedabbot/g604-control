#!/bin/bash
# Пересборка приложения G604 Control в самостоятельный .app
# Требуется: Python 3.14 с Tk (/usr/local/bin/python3) и hidapi (brew install hidapi)
set -e
cd "$(dirname "$0")"

if [ ! -x .build-venv/bin/pyinstaller ]; then
    /usr/local/bin/python3 -m venv .build-venv
    .build-venv/bin/python -m pip install --quiet --upgrade pip pyinstaller
fi

rm -rf build dist
.build-venv/bin/pyinstaller --noconfirm --clean --windowed \
    --name "G604 Control" \
    --icon appicon.icns \
    --add-data "diagram.png:." \
    --add-binary "/opt/homebrew/lib/libhidapi.0.15.0.dylib:." \
    --osx-bundle-identifier com.antonp.g604control \
    g604_editor.py

rm -rf build
rm -rf "G604 Control.app"
cp -R "dist/G604 Control.app" "G604 Control.app"
rm -rf dist
/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString ${VERSION:-0.5}" \
    "G604 Control.app/Contents/Info.plist" 2>/dev/null || true
codesign --force --deep -s - "G604 Control.app" >/dev/null 2>&1 || true
echo "Готово: G604 Control.app"
