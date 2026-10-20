"""Coach notes on scouted players (opposing hitters and pitchers). Private to the program that wrote them; shown under the player's
bio on the scouting page and printed with the scouting sheet."""
import datetime
import json
import os

import github_sync
import store

PATH = os.path.join(store.DATA_DIR, 'scout_notes.json')
MAX = 4000


def _load():
    try:
        with open(PATH, encoding='utf-8') as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def get(program, key):
    """{'t': text, 'by': who, 'at': iso date} or None."""
    return (_load().get(program) or {}).get(key)


def all_for(program):
    return _load().get(program) or {}


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
    github_sync.put_file('data/scout_notes.json', body.encode('utf-8'))
