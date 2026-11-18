"""A program's season schedule (data/schedules/<program>.json), shown on the Schedule page next to the games that have stored pitches."""
import json
import os

import store

DIR = os.path.join(store.DATA_DIR, 'schedules')


def load(program):
    """[{'date','time','at','opp','loc','tournament'}] in date order, or [] when the program has no schedule file."""
    try:
        d, _g = _raw(program)
        games = [x for x in (d.get('games') if isinstance(d, dict) else d) or [] if isinstance(x, dict) and x.get('date')]
    except Exception:
        return []
    for g, i in zip(games, _ids(games)):
        g['_id'] = i
    return sorted(games, key=lambda x: x['date'])      # stable: same-day games keep their file (first-pitch) order


def _same_opp(a, b):
    a, b = store.slugify(a) or '', store.slugify(b) or ''
    return bool(a and b and (a == b or a in b or b in a))


def split(program, played):
    """played = [{'date','opp',...}] games that have stored pitches. -> (matches, open) where matches maps id(played game) -> its scheduled
    game and `open` is every scheduled game with no stored pitches yet. A game is matched on date + opponent; a lone game on a date with one
    scheduled game still matches when the opponent is spelled differently."""
    sched = load(program)
    free = list(range(len(sched)))
    matches = {}
    for p in sorted(played, key=lambda x: x['date']):
        hit = next((i for i in free if sched[i]['date'] == p['date'] and _same_opp(sched[i]['opp'], p['opp'])), None)
        if hit is None:
            day = [i for i in free if sched[i]['date'] == p['date']]
            if len(day) == 1:
                hit = day[0]
        if hit is not None:
            free.remove(hit)
            matches[id(p)] = sched[hit]
    return matches, [sched[i] for i in free]


# ---- coach edits (head coach only; saved back to the same file) ----------------------------------------------------------------------------
def _ids(games):
    """date|time|opponent|k, where k counts the identical games before it (a TBA doubleheader has two of them)."""
    seen, out = {}, []
    for g in games:
        base = f"{g.get('date', '')}|{g.get('time', '')}|{g.get('opp', '')}"
        out.append(f"{base}|{seen.get(base, 0)}")
        seen[base] = seen.get(base, 0) + 1
    return out


def sid(g):
    return g.get('_id', '')


def _file(program):
    return os.path.join(DIR, f'{store.program_slug(program)}.json')


def _raw(program):
    p = _file(program)
    if not os.path.exists(p) and program in store.DEMO_PROGRAMS:      # the sample program's schedule ships in demo/
        p = os.path.join(store.DEMO_DIR, 'schedules', f'{store.program_slug(program)}.json')
    with open(p, encoding='utf-8') as f:
        d = json.load(f)
    return d, (d.get('games') if isinstance(d, dict) else d)


def _write(program, d):
    import github_sync
    text = json.dumps(d, indent=1, ensure_ascii=False)
    github_sync.atomic_write(_file(program), text)
    github_sync.put_file(f'data/schedules/{store.program_slug(program)}.json', text.encode('utf-8'))


def update(program, game_id, **f):
    """Changes fields of one scheduled game (opp, time, loc, at, date). Returns the updated game, or None when it isn't found or a value is invalid."""
    import datetime
    import re
    try:
        d, games = _raw(program)
    except Exception:
        return None
    games = [x for x in games if isinstance(x, dict) and x.get('date')]
    g = next((x for x, i in zip(games, _ids(games)) if i == game_id), None)
    if g is None:
        return None
    clean = {}
    if f.get('date') is not None:
        try:
            clean['date'] = datetime.date.fromisoformat(str(f['date']).strip()).isoformat()
        except ValueError:
            return None
    for k, n in (('opp', 60), ('time', 20), ('loc', 120)):
        if f.get(k) is not None:
            v = re.sub(r'\s+', ' ', str(f[k]).strip())[:n]
            if k == 'opp' and not v:
                return None
            clean[k] = v
    if f.get('at') is not None:
        if f['at'] not in ('Home', 'Away', 'Neutral', ''):
            return None
        clean['at'] = f['at']
    g.update(clean)
    _write(program, d)
    return g


def remove(program, game_id):
    try:
        d, games = _raw(program)
    except Exception:
        return False
    ok = [x for x in games if isinstance(x, dict) and x.get('date')]
    hit = next((x for x, i in zip(ok, _ids(ok)) if i == game_id), None)
    if hit is None:
        return False
    games[:] = [x for x in games if x is not hit]
    _write(program, d)
    return True


# ---- schedule upload (a school-athletics-site schedule printed to PDF) ----------------------------------------------------------------------
_MONTHS = {m: i for i, m in enumerate(('january', 'february', 'march', 'april', 'may', 'june', 'july', 'august', 'september', 'october',
                                       'november', 'december'), 1)}
_MON3 = {k[:3]: v for k, v in _MONTHS.items()}
_HEADS = {'date': 'date', 'time': 'time', 'at': 'at', 'opponent': 'opp', 'location': 'loc', 'tournament': 'tournament', 'result': 'result',
          'site': 'at', 'home/away': 'at', 'h/a': 'at', 'event': 'tournament'}


def _clean(s):
    import re
    return re.sub(r'\s+', ' ', (s or '').replace('\n', ' ')).strip()


def _parse_date(s, year_hint=None):
    """'January 28, 2027 (Thursday)' / 'Feb 5, 2027' / '2/5/2027' -> 'YYYY-MM-DD' or None."""
    import datetime
    import re
    s = _clean(s).lower()
    m = re.search(r'\b([a-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s*(\d{4})?', s)
    mo = d = y = None
    if m and (m.group(1) in _MONTHS or m.group(1)[:3] in _MON3):
        mo, d, y = _MONTHS.get(m.group(1)) or _MON3[m.group(1)[:3]], int(m.group(2)), m.group(3)
    else:
        m = re.search(r'\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b', s)
        if m:
            mo, d, y = int(m.group(1)), int(m.group(2)), m.group(3)
    if not mo:
        return None
    y = int(y) if y else year_hint
    if y and y < 100:
        y += 2000
    try:
        return datetime.date(y, mo, d).isoformat() if y else None
    except ValueError:
        return None


def _parse_time(s):
    """'12 p.m.' -> '12:00 PM', '1:30 p.m.' -> '1:30 PM', '30 minutes after Game 1' -> 'After Game 1', else 'TBA'/'' as written."""
    import re
    s = _clean(s)
    low = s.lower()
    if not s:
        return 'TBA'
    if 'after' in low:
        g = re.search(r'game\s*(\d)', low)
        return f'After Game {g.group(1)}' if g else 'After Game 1'
    m = re.search(r'(\d{1,2})(?::(\d{2}))?\s*([ap])\.?\s*m\.?', low)
    if m:
        return f"{int(m.group(1))}:{m.group(2) or '00'} {m.group(3).upper()}M"
    if 'tba' in low or 'tbd' in low:
        return 'TBA'
    return s[:20]


def _clean_opp(s):
    """'William Carey University (Miss.)' -> 'William Carey University'; drops 'vs.'/'at' prefixes and seed or rank marks."""
    import re
    s = _clean(s)
    s = re.sub(r'^(?:vs\.?|at|@)\s+', '', s, flags=re.I)
    s = re.sub(r'^(?:#|No\.\s*)\d+\s+', '', s)
    s = re.sub(r'\s*\((?:[A-Z][a-z]{1,5}\.?|[A-Z]{2}|Calif\.|Fla\.|Miss\.|Ariz\.|Ore\.|Wash\.|Idaho|Utah|Texas|Ohio|Iowa)\)\s*', ' ', s)
    s = re.sub(r'\s*\*+$', '', s)
    return _clean(s)


def _at(s, opp_raw):
    low = _clean(s).lower()
    if low.startswith(('home', 'vs')) or low == 'h':
        return 'Home'
    if low.startswith(('away', 'at', '@')) or low == 'a':
        return 'Away'
    if low.startswith(('neutral', 'n')):
        return 'Neutral'
    o = _clean(opp_raw).lower()
    return 'Away' if o.startswith(('at ', '@')) else ('Home' if o.startswith('vs') else '')


def parse_pdf(data):
    """[{'date','time','at','opp','loc','tournament'}] from a team schedule printed to PDF (Date / Time / At / Opponent / Location / ...
    columns, as school athletics sites print it). Raises ValueError when no schedule table is found."""
    import io
    import re
    import pdfplumber
    rows = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        text = '\n'.join((p.extract_text() or '') for p in pdf.pages[:1])
        cols = None
        for page in pdf.pages:
            for t in page.extract_tables() or []:
                for r in t:
                    cells = [_clean(c) for c in r]
                    keys = [_HEADS.get(c.lower()) for c in cells]
                    if 'date' in keys and 'opp' in keys:
                        cols = keys
                        continue
                    if cols and len(cells) == len(cols):
                        rec = {k: (r[i] or '') for i, k in enumerate(cols) if k}
                        if rows and not re.search(r'\d', rec.get('date') or ''):
                            for k, v in rec.items():                     # a game split across a page break: the rest of the row above
                                if _clean(v):
                                    rows[-1][k] = (rows[-1].get(k) or '') + ' ' + v
                            continue
                        rows.append(rec)
    if not rows:
        raise ValueError("Couldn't find a schedule table in that PDF. It should have Date and Opponent columns.")
    m = re.search(r'\b(20\d\d)\b', text)
    year_hint = int(m.group(1)) if m else None
    games = []
    for r in rows:
        date = _parse_date(r.get('date'), year_hint)
        opp = _clean_opp(r.get('opp'))
        if not date or not opp:
            continue
        games.append({'date': date, 'time': _parse_time(r.get('time')), 'at': _at(r.get('at'), r.get('opp')), 'opp': opp[:60],
                      'loc': _clean(r.get('loc'))[:120], 'tournament': _clean(r.get('tournament'))[:80]})
    if not games:
        raise ValueError("That PDF has a schedule table, but no games with a date and an opponent could be read from it.")
    return games


def save_upload(program, games, source):
    """Replaces the program's schedule with the uploaded one. Returns the number of games saved."""
    import datetime
    spring = [g for g in games if int(g['date'][5:7]) <= 6]
    season = (max(spring, key=lambda g: g['date']) if spring else max(games, key=lambda g: g['date']))['date'][:4]
    d = {'program': store.program_slug(program), 'season': season, 'source': os.path.basename(source or '')[:120],
         'updated': datetime.date.today().isoformat(), 'games': sorted(games, key=lambda g: g['date'])}
    os.makedirs(DIR, exist_ok=True)
    _write(program, d)
    return len(games)
