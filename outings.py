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
CURRENT_OPPONENT = None   # opponent name for Scrimmage / Game uploads
CURRENT_SESSION = None    # Bullpen / Intrasquad / Scrimmage / Game, stamped on new rows the same way
CURRENT_UPLOAD = None     # set by the upload route so every new pitch row remembers which upload added it
MAX_OUTINGS = 10          # the player overview aggregates this many most recent outings


def _path(slug):
    return os.path.join(OUTINGS_DIR, f'{slug}.json')


_DATE_FORMATS = ('%Y-%m-%d', '%m/%d/%Y', '%m/%d/%y', '%Y/%m/%d', '%m-%d-%Y', '%b %d, %Y', '%B %d, %Y', '%d-%b-%Y')


def iso_date(d):
    """Any date a tracking system might export -> YYYY-MM-DD (unparseable text is returned unchanged)."""
    import datetime
    s = str(d or '').strip()
    for cand in (s, s[:10], s.split(' ')[0].split('T')[0]):
        for fmt in _DATE_FORMATS:
            try:
                return datetime.datetime.strptime(cand, fmt).strftime('%Y-%m-%d')
            except ValueError:
                pass
    return s


def _normalize_dates(data):
    for o in data.get('outings', []):
        o['id'] = o['date'] = iso_date(o.get('id') or o.get('date'))
        for r in o.get('rows', []):
            if r.get('Date'):
                r['Date'] = iso_date(r['Date'])
    merged = {}
    for o in data.get('outings', []):             # the same day stored under two spellings becomes one outing
        m = merged.get(o['id'])
        if m is None:
            merged[o['id']] = o
        else:
            have = {_uid(x) for x in m['rows']}
            m['rows'] += [x for x in o['rows'] if _uid(x) not in have]
            m['live_ab'] = bool(m.get('live_ab') or o.get('live_ab'))
    if 'outings' in data:
        data['outings'] = sorted(merged.values(), key=lambda x: x['date'], reverse=True)
    return data


def load(slug, real_only=False):
    p = _path(slug)
    if not os.path.exists(p):
        dp = os.path.join(store.DEMO_DIR, 'outings', f'{slug}.json')     # bundled sample program (read-only)
        if not real_only and os.path.exists(dp) and store.is_demo(slug):
            p = dp
        else:
            return {'outings': []}
    with open(p, encoding='utf-8') as f:
        return _normalize_dates(json.load(f))


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
    data = load(slug, real_only=True)       # never start from the bundled sample data
    by_id = {o['id']: o for o in data['outings']}
    touched = []
    for r in rows:
        oid = iso_date(r.get('Date') or 'unknown')[:10]
        o = by_id.get(oid)
        if o is None:
            o = {'id': oid, 'date': oid, 'live_ab': bool(live_ab), 'rows': []}
            by_id[oid] = o
            data['outings'].append(o)
        have = {_uid(x) for x in o['rows']}
        if _uid(r) not in have:
            nr = dict(r)
            if nr.get('Date'):
                nr['Date'] = iso_date(nr['Date'])
            if CURRENT_UPLOAD:
                nr['_upload'] = CURRENT_UPLOAD
            if CURRENT_SESSION:
                nr['SessionType'] = CURRENT_SESSION
            if CURRENT_OPPONENT:
                nr['Opponent'] = CURRENT_OPPONENT
            o['rows'].append(nr)
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
    data = load(old_slug, real_only=True)
    delete(old_slug, push)
    _save(new_slug, data, push)


RETAG_TYPES = [('4-Seam', 'Fastball'), ('Sinker', 'Sinker'), ('Cutter', 'Cutter'), ('Slider', 'Slider'), ('Sweeper', 'Sweeper'),
               ('Curveball', 'Curveball'), ('Changeup', 'ChangeUp'), ('Splitter', 'Splitter')]     # (label shown, value stored in TaggedPitchType)
_STORED = dict(RETAG_TYPES)
_STORED['Untagged'] = ''          # only reachable when undoing a retag of a pitch Trackman left untagged


def label_for(raw):
    """The friendly chip label for whatever Trackman tagged (TwoSeamFastBall -> Sinker, ChangeUp -> Changeup...)."""
    import extract
    k = str(raw or '').lower().replace(' ', '').replace('-', '').replace('_', '')
    return extract.TRACKMAN_FINE_TYPE_MAP.get(k) or (raw if raw and raw != 'Undefined' else 'Untagged')


def retag(slug, date, changes, who='', push=True):
    """changes: {pitch uid: label from RETAG_TYPES}. The first retag of a pitch remembers Trackman's original tag
    (OrigTaggedPitchType) so it can always be undone, and later uploads of the same CSV never overwrite a correction
    (add_rows keeps the stored row). Returns how many pitches changed."""
    data = load(slug, real_only=True)
    n = 0
    for o in data['outings']:
        if o['id'] != date:
            continue
        for r in o['rows']:
            new_label = changes.get(_uid(r))
            if new_label is None or new_label not in _STORED:
                continue
            new = _STORED[new_label]
            cur_lab = label_for(r.get('TaggedPitchType'))
            if new_label == cur_lab:
                continue
            r.setdefault('OrigTaggedPitchType', r.get('TaggedPitchType') or '')
            r['TaggedPitchType'] = new
            r['RetaggedBy'] = who
            if label_for(r['OrigTaggedPitchType']) == new_label:       # put back to Trackman's own tag: not a correction any more
                r['TaggedPitchType'] = r['OrigTaggedPitchType']
                for k in ('OrigTaggedPitchType', 'RetaggedBy'):
                    r.pop(k, None)
            n += 1
    if n:
        _save(slug, data, push)
    return n
