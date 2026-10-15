"""
Team rosters. A coach uploads their roster (PDF printed from the school's athletics site, Excel, or CSV); it is parsed,
matched to the players and hitters already in the app, and stored per program in data/rosters/<program>.json.

What a roster is used for:
  * fills in bio details for pitchers already on the dashboard (position, height, weight, class, hometown...)
  * tells the hitting beta which batters belong to which program (Trackman has no team column for batters)
  * is kept for later: a player whose data arrives after the roster is recognised by name
"""
import csv
import difflib
import io
import json
import os
import re

import github_sync
import store

ROSTER_DIR = os.path.join(store.DATA_DIR, 'rosters')
_SUFFIXES = {'jr', 'sr', 'ii', 'iii', 'iv', 'v'}


# ------------------------------------------------------------------ names
def _clean_name(n):
    n = re.sub(r'\s+', ' ', (n or '').replace(' ', ' ')).strip()
    n = re.sub(r',\s*(jr|sr|ii|iii|iv)\.?$', r' \1', n, flags=re.I)
    if ',' in n:                                     # "Last, First" -> "First Last"
        last, first = [x.strip() for x in n.split(',', 1)]
        n = f'{first} {last}'.strip()
    return n


def name_key(n):
    toks = [re.sub(r"[^a-z']", '', t.lower()) for t in _clean_name(n).split()]
    toks = [t for t in toks if t and t.strip("'") not in _SUFFIXES]
    return ' '.join(toks)


def match_name(name, candidates):
    """candidates: [(name, payload)]. Returns (payload, 'exact'|'likely', matched name) or None."""
    k = name_key(name)
    if not k:
        return None
    toks = k.split()
    best = None
    for cname, payload in candidates:
        ck = name_key(cname)
        ct = ck.split()
        if ck == k:
            return payload, 'exact', cname
        if len(toks) >= 2 and len(ct) >= 2 and toks[-1] == ct[-1] and toks[0][:1] == ct[0][:1] and (len(toks[0]) == 1 or len(ct[0]) == 1):
            best = best or (payload, 'likely', cname)        # "H. Tate" vs "Hudson Tate"
        else:
            r = difflib.SequenceMatcher(None, k, ck).ratio()
            if r >= 0.9 and (not best or r > best[3]):
                best = (payload, 'likely', cname, r)
    return best[:3] if best else None


# --------------------------------------------------------------- positions
def _pos_token(t):
    s = re.sub(r'[^a-z ]', ' ', t.lower())
    s = re.sub(r'\s+', ' ', s).strip()
    if not s:
        return None
    if 'right' in s and 'pitch' in s:
        return 'RHP'
    if 'left' in s and 'pitch' in s:
        return 'LHP'
    if 'pitch' in s or s in ('p', 'rhp', 'lhp'):
        return {'rhp': 'RHP', 'lhp': 'LHP'}.get(s, 'P')
    if 'catch' in s or s == 'c':
        return 'C'
    if 'outfield' in s or s in ('of', 'lf', 'cf', 'rf'):
        return 'OF'
    if any(x in s for x in ('infield', 'shortstop', 'second', 'third', 'first base', 'base')) or s in ('if', 'inf', 'ss', '1b', '2b', '3b', 'mi'):
        return 'INF'
    if 'utility' in s or s in ('util', 'utl', 'u'):
        return 'UTL'
    if 'designated' in s or s == 'dh':
        return 'DH'
    return None


def parse_positions(raw, throws=None):
    """'Infield/Right-Handed Pitcher' -> positions ['INF','RHP'], roles, and the single position the app shows."""
    raw = re.sub(r'-\s+', '-', raw or '')
    toks = []
    for part in raw.split('/'):
        t = _pos_token(part)
        if t == 'P':
            t = 'LHP' if throws == 'L' else 'RHP'
        if t and t not in toks:
            toks.append(t)
    pitch = [t for t in toks if t in ('RHP', 'LHP')]
    hit = [t for t in toks if t not in ('RHP', 'LHP')]
    if pitch and hit:
        show = 'TWP'
    elif pitch:
        show = pitch[0]
    else:
        show = {'UTL': 'INF', 'DH': 'INF'}.get(hit[0], hit[0]) if hit else None
    return {'positions': toks, 'pitch': bool(pitch), 'hit': bool(hit), 'show': show}


def _height_in(v):
    v = str(v or '').strip()
    m = re.match(r"^(\d)\s*[-'’ ]\s*(\d{1,2})\"?$", v)
    if m:
        return int(m.group(1)) * 12 + int(m.group(2))
    if re.match(r'^\d{2}(\.\d)?$', v) and 55 <= float(v) <= 84:
        return float(v)
    return None


def _player(num, name, pos, bt, ht, wt, major, yr, home, hs, prev):
    bt = (bt or '').strip().upper()
    m = re.match(r'^([RLSB])\s*/\s*([RL])$', bt)
    bats, throws = (('S' if m.group(1) == 'B' else m.group(1)), m.group(2)) if m else (None, None)
    pp = parse_positions(pos, throws)
    w = re.sub(r'[^0-9]', '', str(wt or ''))
    return {
        'name': _clean_name(name), 'number': re.sub(r'[^0-9]', '', str(num or '')) or None, 'pos_raw': re.sub(r'\s+', ' ', re.sub(r'-\s+', '-', pos or '')).strip(),
        'positions': pp['positions'], 'pitch': pp['pitch'], 'hit': pp['hit'], 'position': pp['show'],
        'bats': bats, 'throws': throws, 'height_in': _height_in(ht), 'weight_lbs': int(w) if w and 90 <= int(w) <= 400 else None,
        'major': (major or '').strip() or None, 'class_year': (yr or '').strip() or None,
        'hometown': (home or '').strip() or None, 'high_school': (hs or '').strip() or None, 'prev_school': (prev or '').strip() or None,
    }


# ----------------------------------------------------------------- parsers
def parse_pdf(data):
    """School-athletics-site roster printed to PDF (columns: # IMAGE NAME POS. B/T HT. WT. MAJOR YR. HOMETOWN HIGH SCHOOL PREVIOUS SCHOOL)."""
    import pdfplumber
    heads = {'#': 'num', 'IMAGE': 'img', 'NAME': 'name', 'POS.': 'pos', 'B/T': 'bt', 'HT.': 'ht', 'WT.': 'wt', 'MAJOR': 'major',
             'YR.': 'yr', 'HOMETOWN': 'home', 'HIGH': 'hs', 'PREVIOUS': 'prev'}
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        pages = [pg.extract_words(keep_blank_chars=False) for pg in pdf.pages]
    edges = None
    for ws in pages:
        found = {}
        for w in ws:
            k = heads.get(w['text'].upper())
            if k and k not in found:
                found[k] = (w['x0'], w['top'])
        if 'name' in found and 'pos' in found and 'bt' in found:
            edges = sorted(((x - 3, k) for k, (x, _) in found.items()), key=lambda t: t[0])
            head_top = found['name'][1]
            break
    if not edges:
        raise ValueError("Couldn't find the roster table in that PDF.")

    def col_of(x):
        c = None
        for ex, k in edges:
            if x >= ex:
                c = k
        return c

    out, done = [], False
    for pi, ws in enumerate(pages):
        if done:
            break
        ws = [w for w in ws if (pi > 0 or w['top'] > head_top + 4)]
        stop = next((w['top'] for w in ws if w['text'] == 'Coaching'), None)
        if stop is not None:
            ws = [w for w in ws if w['top'] < stop - 6]
            done = True
        ws.sort(key=lambda w: (round(w['top']), w['x0']))
        recs, last = [], None
        for w in ws:
            if last is None or w['top'] - last > 15:
                recs.append([])
            recs[-1].append(w)
            last = w['top']
        for ri, r in enumerate(recs):
            cells = {}
            for w in sorted(r, key=lambda w: (round(w['top'] / 3), w['x0'])):
                cells.setdefault(col_of(w['x0']), []).append(w['text'])
            j = {k: ' '.join(v) for k, v in cells.items() if k}
            has_core = any(j.get(k) for k in ('num', 'bt', 'ht', 'wt', 'yr'))
            if pi > 0 and ri == 0 and not has_core and j.get('name') and out:
                for k, v in j.items():                           # a player split across a page break
                    out[-1][k] = (out[-1].get(k, '') + ' ' + v).strip()
                continue
            if not has_core or (j.get('num') and not j['num'].isdigit()):
                continue                                         # page titles, staff tables, repeated headers
            out.append(j)
    return [_player(j.get('num'), j['name'], j.get('pos'), j.get('bt'), j.get('ht'), j.get('wt'), j.get('major'), j.get('yr'),
                    j.get('home'), j.get('hs'), j.get('prev')) for j in out if j.get('name')]


_ALIASES = {
    'name': ('name', 'player', 'player name', 'full name'), 'first': ('first', 'first name'), 'last': ('last', 'last name'),
    'num': ('#', 'no', 'no.', 'number', 'jersey', 'jersey number', 'jersey #'), 'pos': ('pos', 'pos.', 'position', 'positions'),
    'bt': ('b/t', 'bt', 'bats/throws', 'bats / throws'), 'bats': ('bats', 'bat'), 'throws': ('throws', 'throw'),
    'ht': ('ht', 'ht.', 'height'), 'wt': ('wt', 'wt.', 'weight'), 'major': ('major', 'academic major'),
    'yr': ('yr', 'yr.', 'year', 'class', 'cl', 'cl.', 'eligibility'), 'home': ('hometown', 'home town', 'hometown/high school'),
    'hs': ('high school', 'highschool', 'hs'), 'prev': ('previous school', 'prior school', 'last school', 'previous'),
}


def parse_rows(rows):
    """rows: list of lists (header first), from CSV or Excel."""
    rows = [[str(c).strip() if c is not None else '' for c in r] for r in rows if any(str(c).strip() for c in r if c is not None)]
    if len(rows) < 2:
        raise ValueError('That file has no player rows.')
    hdr = [h.lower() for h in rows[0]]
    idx = {}
    for k, names in _ALIASES.items():
        for i, h in enumerate(hdr):
            if h in names and k not in idx:
                idx[k] = i
    if 'name' not in idx and not ('first' in idx and 'last' in idx):
        raise ValueError("Couldn't find a Name column. The first row should be headers like Name, Pos, B/T, Ht, Wt, Yr.")
    out = []
    for r in rows[1:]:
        def g(k):
            return r[idx[k]] if k in idx and idx[k] < len(r) else ''
        name = g('name') or f"{g('first')} {g('last')}"
        if not name.strip():
            continue
        bt = g('bt') or (f"{g('bats')[:1]}/{g('throws')[:1]}" if g('bats') or g('throws') else '')
        out.append(_player(g('num'), name, g('pos'), bt, g('ht'), g('wt'), g('major'), g('yr'), g('home'), g('hs'), g('prev')))
    return out


def parse_file(filename, data):
    fn = (filename or '').lower()
    if fn.endswith('.pdf'):
        rows = parse_pdf(data)
    elif fn.endswith(('.xlsx', '.xlsm')):
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        rows = parse_rows([list(r) for r in wb.active.iter_rows(values_only=True)])
    elif fn.endswith(('.csv', '.txt')):
        text = data.decode('utf-8-sig', errors='replace')
        rows = parse_rows(list(csv.reader(io.StringIO(text))))
    else:
        raise ValueError('Upload a PDF, Excel (.xlsx) or CSV roster.')
    if not rows:
        raise ValueError('No players found in that file.')
    return rows


# ----------------------------------------------------------------- storage
def _path(program):
    return os.path.join(ROSTER_DIR, f'{program}.json')


def load(program):
    try:
        with open(_path(program), encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def save(program, players, source=None, season=None):
    import datetime
    os.makedirs(ROSTER_DIR, exist_ok=True)
    data = {'program': program, 'season': season, 'source': source, 'updated': datetime.date.today().isoformat(), 'players': players}
    text = json.dumps(data, separators=(',', ':'), ensure_ascii=False)
    with open(_path(program), 'w', encoding='utf-8') as f:
        f.write(text)
    github_sync.put_file(f'data/rosters/{program}.json', text.encode('utf-8'))
    return data


def all_rosters():
    out = {}
    if os.path.isdir(ROSTER_DIR):
        for fn in sorted(os.listdir(ROSTER_DIR)):
            if fn.endswith('.json'):
                r = load(fn[:-5])
                if r:
                    out[fn[:-5]] = r
    return out


def find_anywhere(name, rosters=None):
    """(program, roster player, confidence) for a name, across every stored roster; None if no roster has him."""
    rosters = rosters if rosters is not None else all_rosters()
    best = None
    for prog, r in rosters.items():
        m = match_name(name, [(p['name'], p) for p in r['players']])
        if m and (best is None or (m[1] == 'exact' and best[2] != 'exact')):
            best = (prog, m[0], m[1])
    return best


def apply_to_players(program, players, existing):
    """Fills bio fields for already-added players. existing: {slug: bio}. Only empty fields are filled, so a coach's own
    edits are never overwritten. Returns the number of players updated."""
    n = 0
    for p in players:
        m = match_name(p['name'], [(b.get('name', ''), s) for s, b in existing.items() if b.get('program', 'shepherds') == program])
        if m:
            store.apply_roster_bio(m[0], p)
            n += 1
    return n
