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


def record(user, program, filename, source, rows, players, upload_id='', new_players=(), opponent=''):
    """Never raises: logging must not be able to break an upload."""
    try:
        d = _load()
        d.append({'t': int(time.time()), 'user': user or '', 'program': program or '', 'file': filename, 'source': source,
                  'rows': rows, 'players': sorted(players), 'id': upload_id, 'opponent': opponent, 'new_players': sorted(new_players)})
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


def mark_removed(upload_id):
    d = _load()
    for e in d:
        if e.get('id') == upload_id:
            e['removed'] = int(time.time())
    text = json.dumps(d, separators=(',', ':'))
    with open(PATH, 'w', encoding='utf-8') as f:
        f.write(text)
    github_sync.put_file('data/upload_log.json', text.encode('utf-8'))


def rename_opponent(program, old, new):
    """Keeps the Opponent suggestions on the upload page in step with a renamed game."""
    d = _load()
    hit = False
    for e in d:
        if e.get('program') == program and e.get('opponent') == old:
            e['opponent'] = new
            hit = True
    if hit:
        text = json.dumps(d, separators=(',', ':'))
        with open(PATH, 'w', encoding='utf-8') as f:
            f.write(text)
        github_sync.put_file('data/upload_log.json', text.encode('utf-8'))
