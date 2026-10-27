"""Automatic data backups.

Once a day (checked hourly by a background thread) the whole data folder is zipped to <data>/backups/ (the newest 14 are kept).
If GitHub sync is configured, the same zip is also pushed to a separate branch (BACKUP_BRANCH), so it survives a Render redeploy
and never touches the main branch (a commit there would redeploy the site). Everything is best-effort: a failed backup is logged, never raised.
"""
import base64
import io
import os
import threading
import time
import zipfile

import requests

import github_sync
import store

BACKUP_DIR = os.path.join(store.DATA_DIR, 'backups')
BACKUP_BRANCH = os.environ.get('SHEPSAVANT_BACKUP_BRANCH', 'data-backups')
KEEP = 14
INTERVAL = 24 * 3600
_SKIP_TOP = {'backups', '__pycache__'}
_SKIP_PREFIX = ('mlb_',)                     # reference tables that can be rebuilt
LOG = []


def _log(ok, detail):
    LOG.append({'when': time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime()), 'ok': ok, 'detail': detail[:200]})
    del LOG[:-10]


def _zip_bytes():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for root, dirs, files in os.walk(store.DATA_DIR):
            rel_root = os.path.relpath(root, store.DATA_DIR)
            if rel_root == '.':
                dirs[:] = [d for d in dirs if d not in _SKIP_TOP]
            for f in files:
                if rel_root == '.' and f.startswith(_SKIP_PREFIX):
                    continue
                full = os.path.join(root, f)
                try:
                    z.write(full, os.path.join('data', os.path.relpath(full, store.DATA_DIR)))
                except OSError:
                    pass
    return buf.getvalue()


def list_backups():
    try:
        names = sorted((n for n in os.listdir(BACKUP_DIR) if n.endswith('.zip')), reverse=True)
    except OSError:
        return []
    return [{'name': n, 'size': os.path.getsize(os.path.join(BACKUP_DIR, n)), 'mtime': int(os.path.getmtime(os.path.join(BACKUP_DIR, n)))} for n in names]


def _push(data, name):
    """Copy the zip to the backup branch (created from the main branch on first use). Returns a short result string."""
    if not github_sync.enabled():
        return 'GitHub not configured: kept on the server only'
    h, base, br = github_sync._headers(), f'{github_sync.API_BASE}/repos/{github_sync.GITHUB_REPO}', BACKUP_BRANCH
    g = requests.get(f'{base}/git/ref/heads/{br}', headers=h, timeout=15)
    if g.status_code == 404:
        m = requests.get(f'{base}/git/ref/heads/{github_sync.GITHUB_BRANCH}', headers=h, timeout=15)
        m.raise_for_status()
        c = requests.post(f'{base}/git/refs', headers=h, timeout=15, json={'ref': f'refs/heads/{br}', 'sha': m.json()['object']['sha']})
        c.raise_for_status()
    else:
        g.raise_for_status()
    url = f'{base}/contents/backups/{name}'
    cur = requests.get(url, headers=h, params={'ref': br}, timeout=15)
    payload = {'message': f'Backup {name}', 'branch': br, 'content': base64.b64encode(data).decode()}
    if cur.status_code == 200:
        payload['sha'] = cur.json()['sha']
    r = requests.put(url, headers=h, json=payload, timeout=120)
    r.raise_for_status()
    return f'also saved to the "{br}" branch on GitHub'


PUSH_EVERY = 7 * 24 * 3600                    # the GitHub copy is weekly (each one adds ~15 MB to the repo's history); the on-server copy is daily


def _push_due():
    try:
        return time.time() - os.path.getmtime(os.path.join(BACKUP_DIR, '.last_push')) > PUSH_EVERY
    except OSError:
        return True


def run_backup(push=True, force_push=False):
    """Makes one backup now. Returns (ok, message)."""
    try:
        data = _zip_bytes()
        os.makedirs(BACKUP_DIR, exist_ok=True)
        name = 'shepsavant-' + time.strftime('%Y-%m-%d', time.gmtime()) + '.zip'
        with open(os.path.join(BACKUP_DIR, name), 'wb') as f:
            f.write(data)
        for old in list_backups()[KEEP:]:
            try:
                os.remove(os.path.join(BACKUP_DIR, old['name']))
            except OSError:
                pass
        msg = f'{name} ({len(data) // 1024} KB) saved'
        if push and (force_push or _push_due()):
            try:
                msg += '; ' + _push(data, name)
                open(os.path.join(BACKUP_DIR, '.last_push'), 'w').close()
            except Exception as exc:
                msg += f'; GitHub copy failed: {exc}'
        _log(True, msg)
        return True, msg
    except Exception as exc:
        _log(False, str(exc))
        return False, str(exc)


def _due():
    b = list_backups()
    return not b or time.time() - b[0]['mtime'] > INTERVAL


def _loop():
    time.sleep(90)                                  # let the site finish starting first
    while True:
        try:
            if _due():
                run_backup()
        except Exception as exc:
            _log(False, str(exc))
        time.sleep(3600)


_started = False


def start():
    """Starts the background thread once per process."""
    global _started
    if _started or os.environ.get('SHEPSAVANT_AUTO_BACKUP', '').lower() in ('off', '0', 'false', 'no'):
        return
    _started = True
    threading.Thread(target=_loop, daemon=True, name='auto-backup').start()
