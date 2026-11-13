"""Height, weight and class year for scouted players, typed in by the coaches who scout them. Private to the program that wrote them
(same keys as scoutnotes). Height drives the arm-angle estimate on a scouted pitcher's page."""
import datetime
import json
import os

import github_sync
import store

PATH = os.path.join(store.DATA_DIR, 'scout_bios.json')
YEARS = ('Fr', 'So', 'Jr', 'Sr', 'Gr')


def _load():
    try:
        with open(PATH, encoding='utf-8') as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def get(program, key):
    """{'h': inches, 'w': lbs, 'y': 'Jr', 'by', 'at'} or {}."""
    return (_load().get(program) or {}).get(key) or {}


def _num(v, lo, hi):
    try:
        x = float(str(v).strip())
    except Exception:
        return None
    return x if lo <= x <= hi else None


def parse(form):
    """Form fields ft, inch, wt, yr -> cleaned dict (missing or silly values are dropped)."""
    ft, inch = _num(form.get('ft'), 4, 7), _num(form.get('inch'), 0, 11.5)
    h = (ft * 12 + (inch or 0)) if ft is not None else None
    if h is not None and not 54 <= h <= 90:
        h = None
    w = _num(form.get('wt'), 100, 400)
    y = form.get('yr') if form.get('yr') in YEARS else None
    out = {}
    if h:
        out['h'] = round(h * 2) / 2
    if w:
        out['w'] = int(round(w))
    if y:
        out['y'] = y
    return out


def save(program, key, fields, user=''):
    d = _load()
    prog = d.setdefault(program, {})
    if fields:
        prog[key] = dict(fields, by=user, at=datetime.date.today().isoformat())
        if fields.get('y'):
            prog[key]['ys'] = school_year()
    else:
        prog.pop(key, None)
    if not prog:
        d.pop(program, None)
    body = json.dumps(d, separators=(',', ':'), ensure_ascii=False, sort_keys=True)
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    github_sync.atomic_write(PATH, body)
    github_sync.put_file('data/scout_bios.json', body.encode('utf-8'))


def norm_year(raw):
    """Roster class text ('Jr.', 'R-Sr', 'Redshirt Sophomore', 'Graduate', '5th Year') -> Fr / So / Jr / Sr / Gr, or None."""
    import re
    t = re.sub(r'[^a-z0-9 ]', ' ', str(raw or '').lower())
    t = re.sub(r'\b(rs|r|redshirt|red|shirt|hs|medical|med)\b', ' ', t)
    t = ' '.join(t.split())
    if not t:
        return None
    for pre, y in (('fr', 'Fr'), ('so', 'So'), ('jr', 'Jr'), ('ju', 'Jr'), ('sr', 'Sr'), ('se', 'Sr'), ('gr', 'Gr'), ('5', 'Gr'), ('6', 'Gr')):
        if t.startswith(pre):
            return y
    return None


def school_year(d=None):
    """The school year a date falls in, named by the spring it ends in (Aug 2026 - Jul 2027 -> 2027). Class years roll over on Aug 1."""
    d = d or datetime.date.today()
    if isinstance(d, str):
        try:
            d = datetime.date.fromisoformat(d[:10])
        except ValueError:
            return school_year()
    return d.year + (1 if d.month >= 8 else 0)


def advance(y, ys, now=None):
    """(label or None, years moved). A class year recorded in school year `ys` moves up one each school year; None once he is past Gr."""
    if y not in YEARS:
        return None, 0
    steps = max(0, (now or school_year()) - (ys or school_year()))
    idx = YEARS.index(y) + steps
    return (YEARS[idx] if idx < len(YEARS) else None), steps


def from_roster(name, program=None, ctx=None):
    """What a stored roster says about this player (matched by name): {'h','w','y','ys'} with only the fields it has.
    The coach's own uploaded opponent rosters come first, then any team roster on the dashboard. ctx caches the lookups for a long list."""
    import roster as roster_mod
    import scoutroster
    hit = None
    try:
        if program:
            mine = ctx['scout'] if ctx and 'scout' in ctx else scoutroster.all_for(program)
            f = scoutroster.find(program, name, mine)
            if f:
                hit = (f[0], f[1].get('updated'))
        if not hit:
            rosters = ctx['rosters'] if ctx and 'rosters' in ctx else roster_mod.all_rosters()
            f = roster_mod.find_anywhere(name, rosters)
            if f:
                hit = (f[1], (rosters.get(f[0]) or {}).get('updated'))
    except Exception:
        hit = None
    if not hit:
        return {}
    p, upd = hit
    out = {}
    if p.get('height_in'):
        out['h'] = p['height_in']
    if p.get('weight_lbs'):
        out['w'] = p['weight_lbs']
    y = norm_year(p.get('class_year'))
    if y:
        out['y'], out['ys'] = y, school_year(upd)
    for k, f in (('pos', 'position'), ('home', 'hometown'), ('thr', 'throws'), ('bat', 'bats')):
        if p.get(f):
            out[k] = p[f]
    return out


def resolved(program, key, name, ctx=None):
    """What a scouting page shows. A coach's own typing wins for height and weight; a roster fills what he left empty. Class year is
    brought up to the current school year, and a newer roster beats an older typed year.
    {'h','w','y','src': {field: 'roster'}, 'y_note': 'was Jr in 2026', 'gone': True once he is past Gr}"""
    mine = get(program, key)
    rost = from_roster(name, program, ctx)
    out = {k: mine[k] for k in ('h', 'w') if mine.get(k)}
    out['by'], out['at'] = mine.get('by'), mine.get('at')
    out['src'] = {}
    for k in ('h', 'w'):
        if k not in out and rost.get(k):
            out[k], out['src'][k] = rost[k], 'roster'
    for k in ('pos', 'home', 'thr', 'bat'):
        if rost.get(k):
            out[k] = rost[k]
    base, bys, from_roster_y = None, None, False
    if mine.get('y'):
        base, bys = mine['y'], mine.get('ys') or school_year(mine.get('at'))
    if rost.get('y') and (base is None or rost['ys'] > bys):
        base, bys, from_roster_y = rost['y'], rost['ys'], True
    out['y'], out['gone'], out['y_note'] = None, False, ''
    if base:
        label, steps = advance(base, bys)
        if label:
            out['y'] = label
            if steps:
                out['y_note'] = f'was {base} in {bys - 1}-{str(bys)[2:]}'
        else:
            out['gone'], out['y_note'] = True, f'was {base} in {bys - 1}-{str(bys)[2:]}, so likely gone'
        if from_roster_y and label:
            out['src']['y'] = 'roster'
    return out
