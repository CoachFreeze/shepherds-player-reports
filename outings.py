"""
Per-pitcher outing storage for the redesigned dashboard.

Each Long Beach State pitcher has one file, data/outings/<slug>.json:
  {"outings": [{"id": "2026-10-09", "date": "2026-10-09", "live_ab": true, "rows": [<Trackman rows>]}, ...]}

Trackman rows are kept whole so every report can be rebuilt from them at any time (new features,
renames, corrected heights). Re-uploading the same CSV never double counts: pitches are keyed by PitchUID.
Files are committed to GitHub (github_sync.put_file) so they survive Render's filesystem resets.
"""
import json
import os

import github_sync
import store

OUTINGS_DIR = os.path.join(store.DATA_DIR, 'outings')
MAX_OUTINGS = 10          # the player overview aggregates this many most recent outings


def _path(slug):
    return os.path.join(OUTINGS_DIR, f'{slug}.json')


def load(slug):
    p = _path(slug)
    if not os.path.exists(p):
        dp = os.path.join(store.DEMO_DIR, 'outings', f'{slug}.json')     # bundled sample program (read-only)
        if os.path.exists(dp) and store.is_demo(slug):
            p = dp
        else:
            return {'outings': []}
    with open(p, encoding='utf-8') as f:
        return json.load(f)


def _save(slug, data, push=True):
    os.makedirs(OUTINGS_DIR, exist_ok=True)
    text = json.dumps(data, separators=(',', ':'), ensure_ascii=False)
    with open(_path(slug), 'w', encoding='utf-8') as f:
        f.write(text)
    if push:
        github_sync.put_file(f'data/outings/{slug}.json', text.encode('utf-8'))


def _uid(r):
    return r.get('PitchUID') or f"{r.get('Date')}|{r.get('PitchNo')}|{r.get('Time')}"


def add_rows(slug, rows, live_ab=False, push=True):
    """Adds one pitcher's Trackman rows, split by calendar date. Returns the list of outing ids touched."""
    data = load(slug)
    by_id = {o['id']: o for o in data['outings']}
    touched = []
    for r in rows:
        oid = (r.get('Date') or 'unknown').strip()[:10]
        o = by_id.get(oid)
        if o is None:
            o = {'id': oid, 'date': oid, 'live_ab': bool(live_ab), 'rows': []}
            by_id[oid] = o
            data['outings'].append(o)
        have = {_uid(x) for x in o['rows']}
        if _uid(r) not in have:
            o['rows'].append(dict(r))
        if oid not in touched:
            touched.append(oid)
    for oid in touched:                               # a later upload of the same date can flag it Live AB
        by_id[oid]['live_ab'] = by_id[oid]['live_ab'] or bool(live_ab)
        by_id[oid]['rows'].sort(key=lambda x: (x.get('Time') or '', int(x.get('PitchNo') or 0) if str(x.get('PitchNo') or '').isdigit() else 0))
    data['outings'].sort(key=lambda o: o['date'], reverse=True)
    _save(slug, data, push)
    return touched


def outings(slug):
    """Most recent first."""
    return load(slug)['outings']


def recent(slug, n=MAX_OUTINGS):
    return outings(slug)[:n]


def delete(slug, push=True):
    p = _path(slug)
    if os.path.exists(p):
        os.remove(p)
        if push:
            github_sync.delete_file(f'data/outings/{slug}.json')


def move(old_slug, new_slug, push=True):
    data = load(old_slug)
    delete(old_slug, push)
    _save(new_slug, data, push)
