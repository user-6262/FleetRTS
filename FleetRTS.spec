# -*- mode: python ; coding: utf-8 -*-
# Build (from repo root):  pyinstaller FleetRTS.spec
# Output: dist/FleetRTS/FleetRTS.exe  — zip that folder for friends (onedir is more reliable than onefile for pygame).
import pathlib

block_cipher = None


def _repo_root() -> pathlib.Path:
    spec_parent = pathlib.Path(SPECPATH).resolve().parent
    candidates = [spec_parent, pathlib.Path.cwd(), *spec_parent.parents]
    for base in candidates:
        if (base / "core" / "main.py").is_file() and (base / "pyproject.toml").is_file():
            return base
    raise SystemExit(
        "FleetRTS.spec: could not find repo root (need core/main.py + pyproject.toml). "
        f"cwd={pathlib.Path.cwd()} spec={SPECPATH!r}"
    )


ROOT = _repo_root()

a = Analysis(
    [str(ROOT / "core" / "main.py")],
    pathex=[str(ROOT), str(ROOT / "core")],
    binaries=[],
    datas=[
        (str(ROOT / "core" / "data.json"), "core"),
        (str(ROOT / "assets" / "sound"), "assets/sound"),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="FleetRTS",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    # Set True temporarily if a friend hits a startup error and you need a console log.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="FleetRTS",
)
