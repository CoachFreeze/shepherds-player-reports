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

GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN')
GITHUB_REPO = os.environ.get('GITHUB_REPO')
GITHUB_BRANCH = os.environ.get('GITHUB_BRANCH', 'main')
GITHUB_DATA_PATH = 'data/players.json'  # the one file this module ever touches

API_BASE = 'https://api.github.com'


def enabled():
    return bool(GITHUB_TOKEN and GITHUB_REPO)


def sync_players_json(players_dict):
    """Commits the current players dict to GitHub as data/players.json.
    Best-effort and silent: never raises, so a GitHub issue never blocks
    the coach action (adding a player, overriding a comp, etc.) that
    triggered it. Prints a warning to the server log on failure so it's
    at least visible in Render's logs if it starts failing persistently."""
    if not enabled():
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
    except Exception as exc:
        print(f'WARNING: GitHub auto-backup of players.json raised: {exc}')
