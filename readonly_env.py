"""Read-only build: no Wwise discovery or setup."""
from pathlib import Path
import sys
BASE = Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).parent
# Prefer the original project's external-resource layout; retain onedir support.
ASSETS = BASE if (BASE/'azure.tcl').is_file() else Path(getattr(sys,'_MEIPASS',BASE))
DIR = str(BASE)
CACHE = str(BASE/'preview_cache')
TMP = CACHE
VGMSTREAM = str(ASSETS/'vgmstream-win64'/'vgmstream-cli.exe')
