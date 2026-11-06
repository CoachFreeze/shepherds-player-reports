"""Free-text notes a coach types on a game scorebook page (one box per team per game). Private to the program."""
import datetime
import json
import os

import github_sync
import store

PATH = os.path.join(store.DATA_DIR, 'game_notes.json')
MAX = 6000


def _load():
    try:
        with open(PATH, encoding='utf-8') as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def get(program, key):
    return (_load().get(program) or {}).get(key)


def save(program, key, text, user=''):
    d = _load()
    text = (text or '').replace('\r\n', '\n').strip()[:MAX]
    prog = d.setdefault(program, {})
    if text:
        prog[key] = {'t': text, 'by': user, 'at': datetime.date.today().isoformat()}
    else:
        prog.pop(key, None)
    if not prog:
        d.pop(program, None)
    body = json.dumps(d, separators=(',', ':'), ensure_ascii=False, sort_keys=True)
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    github_sync.atomic_write(PATH, body)
    github_sync.put_file('data/game_notes.json', body.encode('utf-8'))


def move(program, pairs):
    """Re-keys notes when a game's id changes (its opponent was renamed). pairs = [(old gid, new gid)]. Never overwrites an existing note."""
    d = _load()
    prog = d.get(program) or {}
    changed = False
    for old, new in pairs:
        for side in ('us', 'opp'):
            k, nk = f'{old}--{side}', f'{new}--{side}'
            if k in prog and nk not in prog:
                prog[nk] = prog.pop(k)
                changed = True
    if not changed:
        return
    body = json.dumps(d, separators=(',', ':'), ensure_ascii=False, sort_keys=True)
    github_sync.atomic_write(PATH, body)
    github_sync.put_file('data/game_notes.json', body.encode('utf-8'))
