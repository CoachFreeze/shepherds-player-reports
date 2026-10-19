"""Keeping the data clean: where each hitter belongs, and taking a whole CSV back out."""
import csv
import json
import os

import github_sync
import outings
import store

HITTER_PATH = os.path.join(store.DATA_DIR, 'hitter_overrides.json')
HIDDEN = '_hidden'
OPP_PREFIX = 'opp-'     # outing files for opposing pitchers: kept only so our own hitters' at-bats count; never shown as players


# ------------------------------------------------------------ hitter placement
def hitter_overrides():
    try:
        with open(HITTER_PATH, encoding='utf-8') as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def set_hitter_overrides(changes):
    """changes: {hitter key: program slug | HIDDEN | '' (clear)}. One write for the whole batch."""
    d = hitter_overrides()
    for k, v in changes.items():
        if v:
            d[k] = v
        else:
            d.pop(k, None)
    text = json.dumps(d, separators=(',', ':'), sort_keys=True)
    os.makedirs(os.path.dirname(HITTER_PATH), exist_ok=True)
    with open(HITTER_PATH, 'w', encoding='utf-8') as f:
        f.write(text)
    github_sync.put_file('data/hitter_overrides.json', text.encode('utf-8'))


# ------------------------------------------------------------ removing a CSV
def _outing_slugs():
    d = outings.OUTINGS_DIR
    return sorted(f[:-5] for f in os.listdir(d) if f.endswith('.json')) if os.path.isdir(d) else []


def _purge(match, allowed=None):
    """Drops every stored pitch row for which match(row) is true. allowed(slug) limits which pitchers are touched.
    Returns {'rows': n, 'pitchers': [slugs touched], 'emptied': [slugs with nothing left]}."""
    total, touched, emptied = 0, [], []
    for slug in _outing_slugs():
        if allowed and not allowed(slug):
            continue
        data = outings.load(slug, real_only=True)
        n = 0
        for o in data['outings']:
            keep = [r for r in o['rows'] if not match(r)]
            n += len(o['rows']) - len(keep)
            o['rows'] = keep
        if not n:
            continue
        data['outings'] = [o for o in data['outings'] if o['rows']]
        total += n
        touched.append(slug)
        if data['outings']:
            outings._save(slug, data)
        else:
            outings.delete(slug)
            emptied.append(slug)
    return {'rows': total, 'pitchers': touched, 'emptied': emptied}


def remove_upload(upload_id, allowed=None):
    return _purge(lambda r: r.get('_upload') == upload_id, allowed)


def csv_uids(path):
    """The pitch ids a CSV would have stored (Full Swing files are translated first, exactly as on upload)."""
    import fullswing
    if fullswing.is_fullswing(path):
        rows, _ = fullswing.convert_rows(fullswing._read(path))
    else:
        with open(path, newline='', encoding='utf-8-sig', errors='ignore') as f:
            rows = list(csv.DictReader(f))
    return {outings._uid(r) for r in rows}


def remove_uids(uids, allowed=None):
    return _purge(lambda r: outings._uid(r) in uids, allowed)


def drop_empty_players(slugs):
    """Deletes player records for pitchers that have no data left. Returns the names removed."""
    names = []
    for s in slugs:
        p = store.get_real_player(s)
        if p and not outings.load(s, real_only=True)['outings']:
            names.append(p.get('name') or s)
            store.delete_player(s)
    return names


def store_opponent_rows(path, program, our_names, exclude=()):
    """Scrimmage / Game: every pitch thrown by someone who is not one of our checked pitchers is stored under an
    'opp-<name>' file tagged with our program. Those rows hold our hitters' at-bats; the pitcher never becomes a player."""
    import extract as e
    ours = {store.slugify(n) for n in our_names}
    ex = set(exclude)
    by = {}
    for r in e.load_trackman_rows(path):
        nm = (r.get('Pitcher') or '').strip()
        last, _, first = nm.partition(', ')
        disp = f'{first} {last}'.strip() if first else nm
        if not nm or store.slugify(disp) in ours or outings._uid(r) in ex or (r.get('PitchUID') or r.get('PitchNo')) in ex:
            continue
        by.setdefault(store.slugify(disp), []).append(r)
    n = 0
    for s, rows in by.items():
        slug = OPP_PREFIX + s
        outings.add_rows(slug, rows, live_ab=True)
        data = outings.load(slug, real_only=True)
        data['program'] = program
        outings._save(slug, data)
        n += len(rows)
    return n
