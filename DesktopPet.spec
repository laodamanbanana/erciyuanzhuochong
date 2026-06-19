# -*- mode: python ; coding: utf-8 -*-
import os, sys, shutil

a = Analysis(
    ['pet_main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('素材', '素材'),
        ('AI/__init__.py', 'AI'),
        ('AI/pet_ai.py', 'AI'),
        ('AI/ai_config.json', 'AI'),
    ],
    hiddenimports=['pygame', 'ctypes', 'json', 'requests', 'threading', 'datetime'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='DesktopPet',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='website/images/icon.ico',
)
