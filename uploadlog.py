"""A running log of every CSV upload: who uploaded it, for which program, what kind of file, how much it held."""
import json
import os
import time

import github_sync
import store

PATH = os.path.join(store.DATA_DIR, 'upload_log.json')
MAX_ENTRIES = 2000


def _load():
    try:
        with open(PATH, encoding='utf-8') as f:
            d = json.load(f)
        return d if isinstance(d, list) else []
    except Exception:
        return []


def record(user, program, filename, source, rows, players):
    """Never raises: logging must not be able to break an upload."""
    try:
        d = _load()
        d.append({'t': int(time.time()), 'user': user or '', 'program': program or '', 'file': filename, 'source': source,
                  'rows': rows, 'players': sorted(players)})
        d = d[-MAX_ENTRIES:]
        text = json.dumps(d, separators=(',', ':'))
        os.makedirs(os.path.dirname(PATH), exist_ok=True)
        with open(PATH, 'w', encoding='utf-8') as f:
            f.write(text)
        github_sync.put_file('data/upload_log.json', text.encode('utf-8'))
    except Exception as exc:
        print(f'WARNING: upload not logged: {exc}')


def entries(program=None):
    """Newest first; program=None means everyone's."""
    d = [e for e in _load() if program is None or e.get('program') == program]
    return list(reversed(d))
