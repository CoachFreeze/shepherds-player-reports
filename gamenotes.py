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
    with open(PATH, 'w', encoding='utf-8') as f:
        f.write(body)
    github_sync.put_file('data/game_notes.json', body.encode('utf-8'))
