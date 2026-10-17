"""
Best-effort auto-backup of data/players.json straight to GitHub, so the live
roster survives Render's free-tier filesystem reset on every code redeploy
without a coach having to manually download/re-upload anything.

Needs two environment variables, set in Render's dashboard (never in code
or in chat -- the token is a secret):
  GITHUB_TOKEN  -- a fine-grained Personal Access Token scoped to just this
                   one repo, with "Contents: Read and write" permission.
  GITHUB_REPO   -- "owner/repo", e.g. "CoachFreeze/shepherds-player-reports"
Optional:
  GITHUB_BRANCH -- defaults to "main"

If either required variable is missing, sync() is a silent no-op -- the app
works exactly as it did before this existed, it just loses the auto-backup
safety net. Every call is wrapped so a GitHub hiccup (rate limit, network
blip, bad/expired token) can never break a coach's actual request -- a
failed backup is logged, never raised.

Deliberately touches ONLY data/players.json. coaches.json (password hashes)
is never written here, so this can't accidentally push a credential change
to the public repo just because a coach added a player.
"""
import base64
import json
import os

import requests

# SHEPSAVANT_* names win, so this app can have its own token/repo even when the same Render account
# already uses GITHUB_TOKEN / GITHUB_REPO for something else (e.g. another project).
GITHUB_TOKEN = os.environ.get('SHEPSAVANT_GITHUB_TOKEN') or os.environ.get('GITHUB_TOKEN')
GITHUB_REPO = os.environ.get('SHEPSAVANT_GITHUB_REPO') or os.environ.get('GITHUB_REPO')
GITHUB_BRANCH = os.environ.get('SHEPSAVANT_GITHUB_BRANCH') or os.environ.get('GITHUB_BRANCH', 'main')
GITHUB_DATA_PATH = 'data/players.json'  # the one file this module ever touches

API_BASE = 'https://api.github.com'

import time
LOG = []          # recent results, newest last: {'when','what','ok','detail'} -- shown on the admin status page


def _log(what, ok, detail=''):
    LOG.append({'when': time.strftime('%H:%M:%S UTC', time.gmtime()), 'what': what, 'ok': ok, 'detail': detail[:200]})
    del LOG[:-15]



def enabled():
    # SHEPSAVANT_GITHUB_BACKUP=off turns commits off (e.g. once a persistent disk holds the data, so saves stop redeploying).
    if (os.environ.get('SHEPSAVANT_GITHUB_BACKUP') or '').lower() in ('off', '0', 'false', 'no'):
        return False
    return bool(GITHUB_TOKEN and GITHUB_REPO)

# ---- batching: many saves in one request become ONE commit (every commit triggers a Render redeploy, so a bulk upload
# that committed once per file used to restart the site over and over mid-request -> "502 Bad Gateway").
import contextlib
import threading
_tl = threading.local()


def _pending():
    return getattr(_tl, 'pending', None)


@contextlib.contextmanager
def batch(message='Update data'):
    """Inside this block put_file / delete_file / players.json saves are only collected; on exit they go up as one commit.
    Nested use joins the outer batch. If the single commit fails, each file is saved on its own as before."""
    if _pending() is not None:
        yield
        return
    _tl.pending = {}
    try:
        yield
    finally:
        pend, _tl.pending = _tl.pending, None
        if pend:
            _flush(pend, message)


def _flush(pend, message):
    if not enabled():
        return
    try:
        h, base = _headers(), f'{API_BASE}/repos/{GITHUB_REPO}'
        ref = requests.get(f'{base}/git/ref/heads/{GITHUB_BRANCH}', headers=h, timeout=15)
        ref.raise_for_status()
        head = ref.json()['object']['sha']
        cm = requests.get(f'{base}/git/commits/{head}', headers=h, timeout=15)
        cm.raise_for_status()
        entries = []
        for path, content in pend.items():
            if content is None:                                   # delete
                entries.append({'path': path, 'mode': '100644', 'type': 'blob', 'sha': None})
                continue
            b = requests.post(f'{base}/git/blobs', headers=h, timeout=30,
                              json={'content': base64.b64encode(content).decode(), 'encoding': 'base64'})
            b.raise_for_status()
            entries.append({'path': path, 'mode': '100644', 'type': 'blob', 'sha': b.json()['sha']})
        tr = requests.post(f'{base}/git/trees', headers=h, timeout=30, json={'base_tree': cm.json()['tree']['sha'], 'tree': entries})
        tr.raise_for_status()
        nc = requests.post(f'{base}/git/commits', headers=h, timeout=30,
                           json={'message': message, 'tree': tr.json()['sha'], 'parents': [head]})
        nc.raise_for_status()
        up = requests.patch(f'{base}/git/refs/heads/{GITHUB_BRANCH}', headers=h, timeout=15, json={'sha': nc.json()['sha']})
        up.raise_for_status()
        _log(f'{len(pend)} files', True, 'saved to GitHub in one commit')
    except Exception as exc:
        print(f'WARNING: one-commit save failed ({exc}); saving files one by one')
        _log(f'{len(pend)} files', False, f'one-commit save failed: {exc}')
        for path, content in pend.items():
            if content is None:
                delete_file(path)
            else:
                put_file(path, content)



def sync_players_json(players_dict):
    """Commits the current players dict to GitHub as data/players.json.
    Best-effort and silent: never raises, so a GitHub issue never blocks
    the coach action (adding a player, overriding a comp, etc.) that
    triggered it. Prints a warning to the server log on failure so it's
    at least visible in Render's logs if it starts failing persistently."""
    if not enabled():
        _log('players.json', False, 'GitHub sync is not configured (token/repo env vars missing)')
        return
    if _pending() is not None:
        _pending()[GITHUB_DATA_PATH] = json.dumps(players_dict, indent=2, sort_keys=True).encode()
        return
    try:
        headers = {
            'Authorization': f'Bearer {GITHUB_TOKEN}',
            'Accept': 'application/vnd.github+json',
        }
        url = f'{API_BASE}/repos/{GITHUB_REPO}/contents/{GITHUB_DATA_PATH}'

        # GitHub's update-file API requires the current file's blob sha, to
        # avoid silently clobbering a concurrent edit -- a 404 here just
        # means the file doesn't exist at this path yet, which is fine for
        # the very first sync (the PUT below creates it).
        get_resp = requests.get(url, headers=headers, params={'ref': GITHUB_BRANCH}, timeout=10)
        sha = get_resp.json().get('sha') if get_resp.status_code == 200 else None

        content_str = json.dumps(players_dict, indent=2, sort_keys=True)
        payload = {
            'message': 'Auto-backup: roster data updated',
            'content': base64.b64encode(content_str.encode()).decode(),
            'branch': GITHUB_BRANCH,
        }
        if sha:
            payload['sha'] = sha

        put_resp = requests.put(url, headers=headers, json=payload, timeout=10)
        if put_resp.status_code not in (200, 201):
            print(f'WARNING: GitHub auto-backup of players.json failed: '
                  f'{put_resp.status_code} {put_resp.text[:300]}')
            _log('players.json', False, f'{put_resp.status_code} {put_resp.text[:150]}')
        else:
            _log('players.json', True, 'saved to GitHub')
    except Exception as exc:
        print(f'WARNING: GitHub auto-backup of players.json raised: {exc}')
        _log('players.json', False, str(exc))


def _headers():
    return {'Authorization': f'Bearer {GITHUB_TOKEN}', 'Accept': 'application/vnd.github+json'}


def delete_file(repo_path):
    """Best-effort delete of one file in the repo (e.g. data/reports/x.html). Silent no-op
    without credentials or if the file isn't in the repo."""
    if not enabled():
        return
    if _pending() is not None:
        _pending()[repo_path] = None
        return
    try:
        url = f'{API_BASE}/repos/{GITHUB_REPO}/contents/{repo_path}'
        g = requests.get(url, headers=_headers(), params={'ref': GITHUB_BRANCH}, timeout=10)
        if g.status_code != 200:
            return
        r = requests.delete(url, headers=_headers(), timeout=10, json={
            'message': f'Remove {repo_path}', 'sha': g.json()['sha'], 'branch': GITHUB_BRANCH})
        if r.status_code not in (200, 201):
            print(f'WARNING: GitHub delete of {repo_path} failed: {r.status_code} {r.text[:200]}')
    except Exception as exc:
        print(f'WARNING: GitHub delete of {repo_path} raised: {exc}')


def put_file(repo_path, content_bytes):
    """Best-effort create/update of one file in the repo."""
    if not enabled():
        return
    if _pending() is not None:
        _pending()[repo_path] = bytes(content_bytes)
        return
    try:
        url = f'{API_BASE}/repos/{GITHUB_REPO}/contents/{repo_path}'
        g = requests.get(url, headers=_headers(), params={'ref': GITHUB_BRANCH}, timeout=10)
        payload = {'message': f'Update {repo_path}', 'branch': GITHUB_BRANCH,
                   'content': base64.b64encode(content_bytes).decode()}
        if g.status_code == 200:
            payload['sha'] = g.json()['sha']
        r = requests.put(url, headers=_headers(), json=payload, timeout=30)
        if r.status_code not in (200, 201):
            print(f'WARNING: GitHub put of {repo_path} failed: {r.status_code} {r.text[:200]}')
            _log(repo_path, False, f'{r.status_code} {r.text[:150]}')
        else:
            _log(repo_path, True, 'saved to GitHub')
    except Exception as exc:
        print(f'WARNING: GitHub put of {repo_path} raised: {exc}')
        _log(repo_path, False, str(exc))
