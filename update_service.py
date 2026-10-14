"""Bounded, background-only GitHub release checks; never installs files."""
import json
import re
import sqlite3
import threading
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from packaging.version import Version, InvalidVersion

APP_NAME = 'HD2AudioViewer'
APP_VERSION = '0.1.0'
APP_REPO = 'EyeMelody/HD2AudioViewer'
DB_REPO = 'raidingforpants/helldivers_audio_db'

def database_version(path):
    try:
        with sqlite3.connect(path.as_uri()+'?mode=ro', uri=True) as con:
            return str(con.execute('PRAGMA user_version').fetchone()[0])
    except sqlite3.Error:
        return '未知'

def check_release(repo, current, opener=urlopen):
    try:
        request = Request(f'https://api.github.com/repos/{repo}/releases/latest', headers={
            'Accept':'application/vnd.github+json', 'User-Agent':APP_NAME,
            'X-GitHub-Api-Version':'2022-11-28'})
        with opener(request, timeout=6) as response:
            data = json.loads(response.read(1024*1024))
        latest = str(data['tag_name'])
        newer = Version(latest) > Version(current)
        # Construct the destination ourselves; do not trust remote arbitrary URLs.
        from urllib.parse import quote
        url = f'https://github.com/{repo}/releases/tag/{quote(latest, safe="")}'
        return {'message':f'发现新版本：{latest}' if newer else f'已是最新版本（{latest}）',
                'newer':newer, 'url':url, 'latest':latest}
    except HTTPError as exc:
        if exc.code == 404:
            message = '尚无可访问的正式 Release（仓库可能尚未创建或为私有）。'
        elif exc.code in (403,429):
            message = 'GitHub 请求受限或访问被拒绝，请稍后重试。'
        else:
            message = f'检查失败：GitHub HTTP {exc.code}'
    except (InvalidVersion, KeyError, ValueError):
        message = '无法识别发布版本，未能判断是否需要更新。'
    except Exception:
        message = '检查失败：网络连接或请求超时，请稍后重试。'
    return {'message':message, 'newer':False}

class UpdateChecks:
    def __init__(self, events, db_path, checker=check_release):
        self.events, self.checker = events, checker
        self.current = {'software':APP_VERSION, 'database':database_version(db_path)}
        self.repos = {'software':APP_REPO, 'database':DB_REPO}
        self.running = set()
        self.results = {}

    def start(self, kind):
        # Called only from Tk's thread, including completion handling.
        if kind in self.running:
            return
        self.running.add(kind)
        self.results[kind] = {'message':'正在后台检查……', 'newer':False}
        def work():
            try:
                result = self.checker(self.repos[kind], self.current[kind])
            except Exception:
                result = {'message':'检查失败，请稍后重试。', 'newer':False}
            self.events.put(('update_result', (kind, result)))
        threading.Thread(target=work, daemon=True, name='version-'+kind).start()

    def complete(self, kind, result):
        self.running.discard(kind)
        self.results[kind] = result
