# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for BLEDeck Windows app.
Run from the windows_app/ directory:
    pyinstaller bledeck.spec
Output: dist/BLEDeck/BLEDeck.exe  (plus supporting files — move the whole folder)
"""

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        ('icon.ico', '.'),
    ],
    hiddenimports=[
        # bleak WinRT backend (not auto-discovered by PyInstaller)
        'bleak.backends.winrt',
        'bleak.backends.winrt.scanner',
        'bleak.backends.winrt.client',
        'bleak.backends.winrt.utils',
        'bleak.backends.winrt.characteristic',
        'bleak.backends.winrt.descriptor',
        'bleak.backends.winrt.service',
        # pynput Win32 backend
        'pynput.keyboard._win32',
        'pynput.mouse._win32',
        # PyQt5 / qasync
        'PyQt5.sip',
        'qasync',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'numpy',
        'PIL',
        'scipy',
        'pandas',
        'pytest',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='BLEDeck',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,          # no terminal window
    icon='icon.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='BLEDeck',
)
