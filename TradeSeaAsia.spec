from pathlib import Path
# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    [str(Path(SPECPATH) / 'src' / 'TradeSeaAsia.py')],
    pathex=[],
    binaries=[],
    datas=[(str(Path(SPECPATH) / 'src' / 'panel.qml'), '.')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
# Exclude DLLs from unrelated tool runtimes on PATH. In particular, Windows'
# ICU exports are incompatible with Poppler's version-suffixed ICU exports.
# Use Windows' own ICU and Universal CRT.
# Qt ships the matching, backward-compatible VC runtime used by this bundle.
from pathlib import Path
import PySide6
qt_dir = Path(PySide6.__file__).parent
runtime_names = {p.name.lower() for pattern in ('vcruntime140*.dll', 'msvcp140*.dll', 'concrt140.dll') for p in qt_dir.glob(pattern)}
a.binaries = [(dest, src, kind) for dest, src, kind in a.binaries
              if not ('codex-runtimes' in src.lower()
                      or Path(dest).name.lower() == 'ucrtbase.dll'
                      or Path(dest).name.lower().startswith(('api-ms-win-', 'ext-ms-win-'))
                      or dest.lower() in runtime_names)]
for name in sorted(runtime_names):
    a.binaries.append((name, str(qt_dir / name), 'BINARY'))
# The UI explicitly selects Basic. Do not ship unused platform/theme styles.
unused_styles = ('FluentWinUI3', 'Fusion', 'Imagine', 'Material', 'Universal', 'Windows', 'iOS', 'macOS', 'NativeStyle')
def unused_qt_style(dest):
    path = dest.replace('\\', '/').lower()
    return (any('/qml/qtquick/controls/' + style.lower() + '/' in path for style in unused_styles)
            or any(Path(dest).name.lower().startswith('qt6quickcontrols2' + style.lower()) for style in unused_styles))
a.binaries = [entry for entry in a.binaries if not unused_qt_style(entry[0])]
a.datas = [entry for entry in a.datas if not unused_qt_style(entry[0])]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='TradeSeaAsia',
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
)
