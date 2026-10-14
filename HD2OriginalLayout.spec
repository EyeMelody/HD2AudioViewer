# Original upstream layout: onefile runtime, external user-facing resources.
from PyInstaller.utils.hooks import collect_all
tk_datas, tk_bins, tk_hidden = collect_all('tkinterdnd2')
a = Analysis(['original_readonly.py'], pathex=[], binaries=tk_bins, datas=tk_datas,
             hiddenimports=tk_hidden, hookspath=[], runtime_hooks=[], excludes=[],
             noarchive=False, optimize=0)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [],
          name='audio_modder', icon='ui_assets/app.ico', debug=False,
          bootloader_ignore_signals=False, strip=False, upx=True, console=False,
          disable_windowed_traceback=False)
