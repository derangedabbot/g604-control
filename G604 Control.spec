# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['g604_editor.py'],
    pathex=[],
    binaries=[('/opt/homebrew/lib/libhidapi.0.15.0.dylib', '.')],
    datas=[('diagram.png', '.')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='G604 Control',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['appicon.icns'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='G604 Control',
)
app = BUNDLE(
    coll,
    name='G604 Control.app',
    icon='appicon.icns',
    bundle_identifier='com.antonp.g604control',
)
