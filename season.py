"""Seasons. A program's data is split by start dates (default: every January 1), so the team pages (Pitchers, Hitters, Dashboard, Game Reports, Scouting) show only the
current season and fall data can't mix with spring. Nothing is moved or deleted: older seasons stay one pick away, and player profiles keep every season.
The start dates live in data/seasons.json as {program: [{'start': 'YYYY-MM-DD', 'label': 'Spring 2027'}]}; a program with none uses the default."""
import datetime
import json
import os

import github_sync
import store

FILE = os.path.join(store.DATA_DIR, 'seasons.json')
FIRST_DEFAULT_YEAR = 2027


def _all():
    try:
        with open(FILE, encoding='utf-8') as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _iso(v):
    try:
        return datetime.date.fromisoformat(str(v or '')[:10]).isoformat()
    except ValueError:
        return None


def custom(program):
    """The start dates a head coach saved, or [] when the program uses the default."""
    rows = []
    for r in _all().get(store.program_slug(program), []):
        s = _iso(r.get('start'))
        if s:
            rows.append({'start': s, 'label': (r.get('label') or '').strip()[:40] or default_label(s)})
    return sorted(rows, key=lambda r: r['start'])


def default_label(start):
    d = datetime.date.fromisoformat(start)
    return f"{'Spring' if d.month <= 6 else 'Fall'} {d.year}"


def boundaries(program, today=None):
    today = today or datetime.date.today()
    rows = custom(program)
    if rows:
        return rows
    return [{'start': f'{y}-01-01', 'label': f'Spring {y}'} for y in range(FIRST_DEFAULT_YEAR, max(today.year, FIRST_DEFAULT_YEAR) + 1)]


def _first_label(b0):
    d = datetime.date.fromisoformat(b0)
    return f'Fall {d.year - 1}' if d.month <= 6 else 'Earlier'


def seasons(program, today=None):
    """[{'key','label','start','end'}] oldest first; start/end are ISO dates (end exclusive) or None. Seasons that haven't started yet are left out."""
    today = (today or datetime.date.today()).isoformat()
    bs = boundaries(program)
    out, prev, label = [], None, None
    starts = [b for b in bs]
    first_label = _first_label(starts[0]['start']) if starts else 'All'
    edges = [(None, first_label)] + [(b['start'], b['label']) for b in starts]
    for i, (s, lab) in enumerate(edges):
        if s and s > today:
            break
        e = edges[i + 1][0] if i + 1 < len(edges) else None
        out.append({'key': s or 'first', 'label': lab, 'start': s, 'end': e})
    if out:
        out[-1]['end'] = None               # the current season is open-ended
    return out


def current(program):
    return seasons(program)[-1]


def _choice(program):
    try:
        from flask import has_request_context, session
        if has_request_context():
            return (session.get('season') or {}).get(store.program_slug(program))
    except Exception:
        pass
    return None


def selected(program):
    ss = seasons(program)
    k = _choice(program)
    return next((s for s in ss if s['key'] == k), ss[-1])


def window(program):
    """(start, end) of the season the viewer picked (default: the current one), as a hashable pair; (None, None) when there is only one season."""
    s = selected(program)
    return (s['start'], s['end'])


def in_window(date, win):
    d = (date or '')[:10]
    if not win or not d:
        return True
    return (not win[0] or d >= win[0]) and (not win[1] or d < win[1])


def pick(program, key):
    from flask import session
    m = dict(session.get('season') or {})
    cur = current(program)['key']
    if key and key != cur and any(s['key'] == key for s in seasons(program)):
        m[store.program_slug(program)] = key
    else:
        m.pop(store.program_slug(program), None)
    session['season'] = m


def save(program, rows):
    d = _all()
    clean = []
    for r in rows:
        s = _iso(r.get('start'))
        if s:
            clean.append({'start': s, 'label': (r.get('label') or '').strip()[:40] or default_label(s)})
    d[store.program_slug(program)] = sorted({r['start']: r for r in clean}.values(), key=lambda r: r['start'])
    text = json.dumps(d, indent=1, ensure_ascii=False)
    os.makedirs(os.path.dirname(FILE), exist_ok=True)
    with open(FILE, 'w', encoding='utf-8') as f:
        f.write(text)
    github_sync.put_file('data/seasons.json', text.encode('utf-8'))


def presets_for(program, dates):
    """[(label, frm, to)] for the date-range bar on a player profile: one per season the player has data in, so growth can be compared year to year."""
    ds = sorted(d for d in dates if d)
    out = []
    ss = seasons(program)
    if len(ss) < 2 or not ds:
        return out
    for s in ss:
        if any(in_window(d, (s['start'], s['end'])) for d in ds):
            last = (datetime.date.fromisoformat(s['end']) - datetime.timedelta(days=1)).isoformat() if s['end'] else None
            out.append((s['label'], s['start'], last))
    return out
