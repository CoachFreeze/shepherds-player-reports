"""Season box scores and play-by-play from a program's own athletics site (Sidearm), for games with or without tracking data.

Pipeline (the same order NW Baseball Stats uses): scrape -> parse (this file) -> store one JSON file per program and season under
data/boxscores/ -> add up season lines -> advanced stats against the level's own run environment -> win probability from the play-by-play.

The scraped page holds every table on the box score: line score, each team's batting and pitching lines, the composite batting line
(2B, 3B, HR, HBP, SF, SH, SB, CS ...) and the play-by-play by half-inning, with the score after every play. The play-by-play gives real
base-out states (no inference), so win probability and WPA here are exact up to how the official scorer wrote the play.

League constants are measured per level and season from every game in the files (both teams), so a D2 program is measured against D2
offense and a D1 program against D1.
"""
import datetime
import glob
import json
import os
import re

import cache
import store

BOX_DIR = os.path.join(store.BUILD_DIR, 'data', 'boxscores')

# programs whose box scores are loaded: names used on the box scores, home city (for home / away / neutral) and level
SOURCES_PATH = os.path.join(store.BUILD_DIR, 'data', 'sources.json')


def _load_sources():
    """Programs with an official site to read (data/sources.json), keyed by the program's id in the app: add a program there and the
    scrapers and Season Stats pick it up."""
    try:
        with open(SOURCES_PATH) as f:
            raw = json.load(f)
    except (OSError, ValueError):
        raw = {}
    out = {}
    for k, v in raw.items():
        if k.startswith('_') or not isinstance(v, dict):
            continue
        out[k] = dict(v, names=tuple(n.lower() for n in v.get('names') or ()), home=tuple(n.lower() for n in v.get('home') or ()))
    return out


PROGRAMS = _load_sources()

W = {'BB': 0.69, 'HBP': 0.72, '1B': 0.88, '2B': 1.24, '3B': 1.56, 'HR': 2.00}       # NWBB / FanGraphs-style linear weights
WOBA_SCALE = 1.25
RUNS_PER_WIN = 9.5
REPL_RUNS_600 = 20.0
POS_RUNS_600 = {'C': 5.0, 'SS': 4.0, '2B': 0.5, '3B': 0.0, 'CF': 0.0, 'LF': -6.5, 'RF': -6.0, '1B': -9.0, 'DH': -11.5, 'P': -7.0}

_SKIP = re.compile(r"( to [a-z0-9]+ for |pinch (hit|ran) for| replaces |position change|defensive substitution|pitching change|mound visit|"
                   r"timeout|no play|violation|failed pickoff|dropped foul|catch made|^/ for|^\.$|runs?, \d+ hits?)", re.I)
_POSMOVE = re.compile(r"^[^;]{1,40} to (p|c|1b|2b|3b|ss|lf|cf|rf|dh)\.?$", re.I)      # 'DIAZ to lf.' (a defensive move, no play)
_BAT = re.compile(r"\b(singled|doubled(?! off)|tripled|homered|intentionally walked|walked|hit by pitch|struck out|grounded out|flied out|lined out|"
                  r"popped up|popped out|fouled out|fouled into|reached|grounded into|hit into|lined into|flied into|sacrifice|infield fly|"
                  r"out at first|bunted|grounded|flied|lined|popped)\b", re.I)
_RUN = re.compile(r"\b(advanced|scored|stole|caught stealing|picked off|out at (?:second|third|home|first)|out on|doubled off)\b", re.I)
_OUTWORD = re.compile(r"\b(out at|out on|caught stealing|picked off|doubled off)\b", re.I)


def _skip(text):
    """A row that is not a play: substitutions, defensive moves, mound visits, the half's summary line."""
    if _SKIP.search(text):
        return True
    return bool(_POSMOVE.match(text)) and not (_BAT.search(text) or _RUN.search(text))


# ------------------------------------------------------------------ names
def _key(name):
    """A last-name key for matching play-by-play names to box-score names: 'Whitman, J.' / 'J. Whitman' / 'WHITMAN' -> 'whitman'."""
    n = re.sub(r'\s+', ' ', (name or '').strip()).strip('.').strip()
    if ',' in n:
        n = n.split(',')[0]
    else:
        parts = n.split(' ')
        if len(parts) > 1 and re.fullmatch(r'[A-Za-z]\.?', parts[0]):
            n = ' '.join(parts[1:])
    n = re.sub(r'\b(jr|sr|ii|iii|iv)\b\.?', '', n, flags=re.I)
    return re.sub(r'[^a-z]', '', n.lower())


def _first(name):
    n = (name or '').strip()
    if ',' in n:
        f = n.split(',', 1)[1].strip()
    else:
        parts = n.split(' ')
        f = parts[0] if len(parts) > 1 else ''
    return (f[:1] or '').lower()


def _pretty(name):
    """'MCGREW, Sean' -> 'Sean McGrew'; 'Gamberdella,Vincent' -> 'Vincent Gamberdella'."""
    import html as _h
    n = re.sub(r'\s+', ' ', _h.unescape(name or '').strip())
    m = re.match(r'^(Jr|Sr|II|III|IV)\.?,\s*(.+)$', n)                 # 'Jr., Matthew Ibrahim' -> 'Matthew Ibrahim Jr.'
    if m:
        n = f"{m.group(2)} {m.group(1)}{'.' if m.group(1) in ('Jr', 'Sr') else ''}"
    if ',' in n:
        last, first = [x.strip() for x in n.split(',', 1)]
        n = f'{first} {last}'.strip()
    return ' '.join(w.capitalize() if (w.isupper() and len(w) > 2) else w for w in n.split(' '))


def player_id(name):
    """Stable id for a box-score player inside one program: 'whitman-james' (suffixes like Jr. dropped, so every spelling agrees)."""
    import html as _h
    n = re.sub(r'\s+', ' ', _h.unescape(name or '').strip())
    n = re.sub(r'^(Jr|Sr|II|III|IV)\.?,\s*', '', n, flags=re.I)        # 'Jr., Matthew Ibrahim'
    n = re.sub(r'(?<=[\s,])(jr|sr|ii|iii|iv)\.?(?=[\s,]|$)', '', n, flags=re.I)
    n = re.sub(r'\s*,\s*,', ',', n).strip(' ,')
    n = re.sub(r'\s+', ' ', n).replace(' ,', ',')
    if ',' in n:
        last, first = [x.strip() for x in n.split(',', 1)]
    else:
        parts = n.split(' ')
        first, last = (' '.join(parts[:-1]), parts[-1]) if len(parts) > 1 else ('', n)
    return re.sub(r'[^a-z0-9]+', '-', f'{last}-{first}'.lower()).strip('-')


class _Roster:
    """Matches play-by-play names to the box-score names of one team in one game."""

    def __init__(self, names):
        self.names = [n for n in names if n]
        self.by = {}
        for n in self.names:
            ks = {_key(n)}
            if ',' not in n and ' ' in n.strip():                     # 'Trevor Goldenetz' -> 'goldenetz' too
                ks.add(_key(re.sub(r'\b(jr|sr|ii|iii|iv)\b\.?', '', n, flags=re.I).strip(' .').split(' ')[-1]))
            for k in ks:
                self.by.setdefault(k, []).append(n)

    def find(self, pbp_name):
        k = _key(pbp_name)
        if not k:
            return None
        nm = re.sub(r'\b(jr|sr|ii|iii|iv)\b\.?', '', (pbp_name or ''), flags=re.I).strip(' .')
        last = _key(nm.split(' ')[-1]) if (',' not in nm and ' ' in nm) else None     # 'Luke Caruso' -> 'caruso'
        hits = None
        for kk in [k] + ([last] if last else []):
            hits = self.by.get(kk) or [n for k2, ns in self.by.items() if len(kk) >= 4 and (k2.startswith(kk) or kk.startswith(k2)) for n in ns]
            if hits:
                break
        if not hits:                                                     # a scorer's typo: 'Carillo' for 'Carrillo'
            import difflib
            best = difflib.get_close_matches(last or k, list(self.by), n=1, cutoff=0.84)
            hits = self.by.get(best[0]) if best else None
        if not hits:
            return None
        hits = list(dict.fromkeys(hits))
        if len(hits) > 1:
            f = _first(pbp_name)
            hits = [n for n in hits if _first(n) == f] or hits
        return hits[0]


# ------------------------------------------------------------------ parsing one scraped game
def _int(v):
    try:
        return int(float(str(v).replace('*', '').strip()))
    except (TypeError, ValueError):
        return 0


def _ip_outs(v):
    w, _, f = str(v or '0').partition('.')
    return _int(w) * 3 + _int(f[:1] or 0)


def _is_us(label, program):
    lab = (label or '').lower()
    return any(n in lab for n in PROGRAMS[program]['names'])


def _team_of(label):
    return re.split(r'\s+-\s+(?:Top|Bottom|Pitching|Composite)|\s+\d+\s*-?\s*Composite|\s+\d+$', label or '')[0].strip()


def parse_game(raw, program):
    """One scraped page -> {'gid','date','opp','at','us_home','us','them','ls','bat','pit','pbp','ump','reg'} or None if it can't be read."""
    title = raw.get('title') or ''
    m = re.search(r'on (\d{1,2})/(\d{1,2})/(\d{4})', title)
    if not m:
        return None
    date = datetime.date(int(m.group(3)), int(m.group(1)), int(m.group(2))).isoformat()
    T = raw.get('tables') or []
    halves = [(lab, rows) for lab, rows in T if rows and rows[0] and rows[0][0] in ('Play Description', 'Plays') and re.search(r' - (Top|Bottom) of ', lab)]
    if not halves:
        return None
    top_team = next((_team_of(l) for l, _ in halves if ' - Top of ' in l), '')
    bot_team = next((_team_of(l) for l, _ in halves if ' - Bottom of ' in l), '')
    us_home = _is_us(bot_team, program) or not _is_us(top_team, program)
    opp = top_team if us_home else bot_team
    opp = re.sub(r'\s*\(\d+-\d+(-\d+)?\)\s*$', '', opp).strip() or 'Opponent'
    notes = ' '.join(raw.get('notes') or [])
    site = ''
    sm = re.search(r'Site\s*(.+?)(?:\s+VIEW|\s+Weather|\s+Notes|$)', notes) or re.search(r'Location:\s*(.+?)(?:Venue:|Umpires:|$)', notes)
    if sm:
        site = sm.group(1).strip()
    home_city = PROGRAMS[program]['home']
    if site and any(c in site.lower() for c in home_city):
        at = 'Home'
    elif not us_home:
        at = 'Away'
    else:
        at = 'Neutral' if site else 'Home'
    ump = ''
    um = re.search(r'(?:Home Plate|HP):\s*([A-Za-z.\'\- ]+?)(?:,|\s+First|\s+1B|\s+Third|\s+3B|\s*$)', notes)
    if um:
        ump = um.group(1).strip()
    # line score: the first table whose rows are [team, inning runs ..., R, H, E]
    ls, rhe = {'top': [], 'bot': []}, {'top': {}, 'bot': {}}
    for lab, rows in T:
        if len(rows) >= 3 and rows[0] and rows[0][0] == 'Team' and len(rows[0]) > 6 and (rows[0][1] == '1' or 'innning' in rows[0][1] or rows[0][1].startswith('1')):
            hdr = [h.split()[-1] if h else h for h in rows[0]]
            n_tail = sum(1 for h in hdr[-3:] if h in ('R', 'H', 'E'))
            for side, row in (('top', rows[1]), ('bot', rows[2])):
                # R, H, E are always the last cells; everything between the team name and them is an inning, even when the
                # header lists fewer innings than the row has (an extra inning, or an 'X' for an unplayed bottom half)
                tail = row[len(row) - n_tail:] if n_tail else []
                for h, v in zip([h for h in hdr[-3:] if h in ('R', 'H', 'E')], tail):
                    rhe[side][h] = _int(v)
                for v in row[1:len(row) - n_tail]:
                    v = (v or '').strip()
                    ls[side].append(v if v not in ('', '-') else None)
            while ls['top'] and ls['bot'] and ls['top'][-1] is None and ls['bot'][-1] in (None, 'X'):
                ls['top'].pop()
                ls['bot'].pop()
            break
    # batting: the composite tables (POS, Player, AB, R, H, RBI, 2B, 3B, HR, BB, SB, CS, HBP, SH, SF, SO, KL, GDP, PO, A)
    comp = [(lab, rows) for lab, rows in T if rows and len(rows[0]) > 12 and rows[0][0].upper() == 'POS' and rows[0][1] == 'Player']
    pitt = [(lab, rows) for lab, rows in T if rows and len(rows[0]) > 8 and rows[0][0] == 'Player' and rows[0][1] == 'IP']
    if len(comp) < 2 or len(pitt) < 2:
        return None

    def side_of(lab, idx):
        if _is_us(lab, program):
            return 'us'
        t = _team_of(lab)
        if t and (t in top_team or top_team in t or t in bot_team or bot_team in t):
            return 'us' if ((t in bot_team or bot_team in t) == us_home) else 'opp'
        return ('opp' if us_home else 'us') if idx == 0 else ('us' if us_home else 'opp')     # visitor first, home second

    bat = {'us': [], 'opp': []}
    for i, (lab, rows) in enumerate(comp[:2]):
        hdr = [h.upper() for h in rows[0]]
        s = side_of(lab, i)
        for r in rows[1:]:
            if len(r) < len(hdr) or not r[1] or r[1].lower().startswith('total'):
                continue
            pos = r[0].strip()
            name = r[1].strip()
            if pos and name.lower().startswith(pos.lower() + ' '):
                name = name[len(pos) + 1:].strip()
            d = {'name': name, 'pos': pos.upper()}
            for h, v in zip(hdr[2:], r[2:]):
                d[h] = _int(v)
            bat[s].append(d)
    pit = {'us': [], 'opp': []}
    for i, (lab, rows) in enumerate(pitt[:2]):
        hdr = rows[0]
        s = side_of(lab, i)
        for j, r in enumerate(rows[1:]):
            if not r or not r[0] or r[0].lower().startswith('total'):
                continue
            nm = r[0]
            dec = ''
            dm = re.search(r'\((W|L|S)\b[^)]*\)', nm)
            if dm:
                dec = dm.group(1)
            nm = re.sub(r'\s*\([^)]*\)\s*$', '', nm).strip()
            d = {'name': nm, 'dec': dec, 'gs': 1 if j == 0 else 0}
            for h, v in zip(hdr[1:], r[1:]):
                d[h] = _ip_outs(v) if h == 'IP' else _int(v)
            pit[s].append(d)
    if not bat['us'] or not pit['us']:
        return None
    hdr = halves[0][1][0]
    pbp = []
    for lab, rows in halves:
        im = re.search(r' - (Top|Bottom) of (\d+)', lab)
        tb = 0 if im.group(1) == 'Top' else 1
        inn = int(im.group(2))
        for r in rows[1:]:
            if not r or not r[0]:
                continue
            pbp.append({'inn': inn, 'tb': tb, 't': r[0], 'v': _int(r[1]) if len(r) > 1 else None, 'h': _int(r[2]) if len(r) > 2 else None})
    pbp.sort(key=lambda x: (x['inn'], x['tb']))                  # tables come in game order already; this only guards a stray ordering
    vis_runs = rhe['top'].get('R')
    home_runs = rhe['bot'].get('R')
    if vis_runs is None or home_runs is None:
        last = [x for x in pbp if x['v'] is not None]
        vis_runs, home_runs = (last[-1]['v'], last[-1]['h']) if last else (0, 0)
    us, them = (home_runs, vis_runs) if us_home else (vis_runs, home_runs)
    innings = max([x['inn'] for x in pbp] or [9])
    return {'date': date, 'opp': opp, 'at': at, 'us_home': us_home, 'site': site, 'us': us, 'them': them,
            'ls': {'us': ls['bot'] if us_home else ls['top'], 'opp': ls['top'] if us_home else ls['bot']},
            'rhe': {'us': rhe['bot'] if us_home else rhe['top'], 'opp': rhe['top'] if us_home else rhe['bot']},
            'bat': bat, 'pit': pit, 'pbp': pbp, 'ump': ump, 'innings': innings, 'url': raw.get('url'), 'abbr': hdr[1:3]}


def save_season(program, year, games, record=None, source=None):
    """Writes one season file from parsed games (parse_game), given in the order the site's stats page lists them. Doubleheaders are
    numbered in that order (the site lists game 1 first), so ids stay the same from one run to the next. Returns the stored season."""
    games = sorted(games, key=lambda g: g['date'])                 # stable: same-day games keep the site's order
    seen = {}
    for g in games:
        base = f"{g['date']}--{store.slugify(g['opp']) or 'opp'}"
        seen[base] = seen.get(base, 0) + 1
        g['gid'] = base + (f"-g{seen[base]}" if seen[base] > 1 else '')
    for base, n in seen.items():                                 # doubleheaders: number both games
        if n > 1:
            for g in games:
                if g['gid'] == base:
                    g['gid'] = base + '-g1'
    out = {'program': program, 'season': int(year), 'record': record, 'level': PROGRAMS[program]['level'],
           'source': source or PROGRAMS[program].get('site'), 'updated': datetime.date.today().isoformat(), 'games': games}
    os.makedirs(os.path.join(BOX_DIR, program), exist_ok=True)
    tmp = os.path.join(BOX_DIR, program, f'.{int(year)}.json.tmp')
    with open(tmp, 'w') as f:
        json.dump(out, f, separators=(',', ':'))
    os.replace(tmp, os.path.join(BOX_DIR, program, f'{int(year)}.json'))
    return out


def import_season(path_or_obj):
    """A whole scraped season ({'program','season','record','site','games': [raw pages]}) -> the stored season file."""
    D = path_or_obj if isinstance(path_or_obj, dict) else json.load(open(path_or_obj))
    program = D['program']
    games = []
    for raw in D.get('games') or []:
        g = parse_game(raw, program)
        if g:
            games.append(g)
    return save_season(program, D['season'], games, D.get('record'), D.get('site'))


def stored_season_raw(program, year):
    """The stored season file as written (no cache), or None."""
    p = os.path.join(BOX_DIR, program, f'{int(year)}.json')
    if not os.path.exists(p):
        return None
    with open(p) as f:
        return json.load(f)


def update_roster(program, year, players):
    """Merges one season's roster lines (scrapers.sidearm.roster) into roster.json, matched to the box-score players by name.
    Keeps jersey number, position, class, height, weight and B/T only. Returns (matched, unmatched)."""
    import html as _h
    S = stored_season_raw(program, year)
    ids = set()
    for g in (S or {}).get('games', []):
        for x in g['bat']['us'] + g['pit']['us']:
            ids.add(player_id(x['name']))
    p = os.path.join(BOX_DIR, program, 'roster.json')
    R = {}
    if os.path.exists(p):
        with open(p) as f:
            R = json.load(f)
    hit = miss = 0
    for pl in players:
        if not pl.get('name'):
            continue
        pid = player_id(pl['name'])
        if ids and pid not in ids:
            last, _, first = pid.partition('-')
            c = [i for i in ids if (i.split('-')[0].startswith(last) or last.startswith(i.split('-')[0])) and i.split('-', 1)[-1][:1] == first[:1]]
            if len(c) == 1:
                pid = c[0]
                hit += 1
            else:
                miss += 1
        else:
            hit += 1
        R.setdefault(pid, {'name': _h.unescape(pl['name']), 'years': {}})['years'][str(year)] = {
            'num': re.sub(r'[^0-9]', '', pl.get('num') or ''), 'pos': pl.get('pos') or '', 'cls': pl.get('cls') or '',
            'ht': re.sub(r'\s+', '', pl.get('ht') or '').replace("''", '"'), 'wt': pl.get('wt') or '', 'bt': pl.get('bt') or ''}
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'w') as f:
        json.dump(R, f, separators=(',', ':'), sort_keys=True)
    return hit, miss


# ------------------------------------------------------------------ loading
def _files():
    return sorted(glob.glob(os.path.join(BOX_DIR, '*', '[0-9][0-9][0-9][0-9].json')))


def programs():
    return sorted({os.path.basename(os.path.dirname(p)) for p in _files()} & set(PROGRAMS))


def has(program):
    return (program or '') in PROGRAMS and os.path.isdir(os.path.join(BOX_DIR, program or '')) and bool(glob.glob(os.path.join(BOX_DIR, program, '[0-9][0-9][0-9][0-9].json')))


def years(program):
    return sorted(int(os.path.basename(p)[:-5]) for p in glob.glob(os.path.join(BOX_DIR, program, '[0-9][0-9][0-9][0-9].json')))


@cache.memo
def season(program, year):
    p = os.path.join(BOX_DIR, program, f'{int(year)}.json')
    if not os.path.exists(p):
        return None
    with open(p) as f:
        return json.load(f)


def level(program):
    return PROGRAMS.get(program, {}).get('level', 'D1')


# ------------------------------------------------------------------ play-by-play -> plate appearances and base-out states
def _result(clause):
    c = clause.lower()
    if 'homered' in c or 'home run' in c:
        return 'HR'
    if 'tripled' in c:
        return '3B'
    if re.search(r'\bdoubled\b(?! off)', c):
        return '2B'
    if 'singled' in c:
        return '1B'
    if 'intentionally walked' in c:
        return 'IBB'
    if 'walked' in c:
        return 'BB'
    if 'hit by pitch' in c:
        return 'HBP'
    if 'struck out' in c:
        return 'K'
    if "fielder's choice" in c or 'fielders choice' in c:
        return 'FC'
    if 'interference' in c and ('catcher' in c or 'reached' in c) and 'out' not in c:
        return 'CI'
    if 'reached' in c and 'error' in c:
        return 'ROE'
    if 'sacrifice fly' in c or ('sacrifice' in c and ('fly' in c or 'flied' in c)):
        return 'SF'
    if 'sacrifice' in c:
        return 'SH'
    if 'double play' in c or 'grounded into' in c or 'hit into' in c or 'lined into' in c or 'flied into' in c:
        return 'DP'
    if 'reached' in c:
        return 'ROE'
    return 'OUT'


def _bb_type(clause):
    c = clause.lower()
    if 'bunt' in c:
        return 'BU'
    if 'popped' in c or 'infield fly' in c or 'fouled out' in c and ('c ' in c or 'to c' in c):
        return 'PU'
    if 'lined' in c or 'line drive' in c:
        return 'LD'
    if 'flied' in c or 'fly' in c or 'fouled out' in c:
        return 'FB'
    if 'grounded' in c or 'ground' in c or 'through the' in c or 'up the middle' in c:
        return 'GB'
    return None


_BASE = {'first': 1, 'second': 2, 'third': 3, 'home': 4}


def _dest(clause):
    c = clause.lower()
    if re.search(r'\bscored\b|stole home|advanced to home', c):
        return 4
    m = re.findall(r'(?:advanced to|stole|to|reached) (first|second|third)', c)
    return _BASE[m[-1]] if m else None


def _subject(clause, rx):
    m = rx.search(clause)
    return clause[:m.start()].strip(' ,.') if m else clause.strip()


def _outs_in(clause, is_batter):
    c = clause.lower()
    if is_batter:
        return 0
    return 1 if _OUTWORD.search(c) else 0


@cache.memo
def plays(program, year, gid):
    """Plate appearances and runner events for one game, in order, with the base-out state before each and win probability:
    [{'inn','tb','bat','text','kind':'pa'|'run','res','bb','batter','pitcher','outs','bases','margin_home','we_before','we_after','wpa'}]."""
    S = season(program, year)
    g = next((x for x in (S or {}).get('games', []) if x['gid'] == gid), None)
    if not g:
        return None
    return _plays(g, rates_for(level(program), year))


def _plays(g, p):
    import winprob
    us_home = g['us_home']
    side_bat = {0: 'us' if not us_home else 'opp', 1: 'us' if us_home else 'opp'}
    rost = {s: _Roster([b['name'] for b in g['bat'][s]]) for s in ('us', 'opp')}
    prost = {s: _Roster([q['name'] for q in g['pit'][s]]) for s in ('us', 'opp')}
    cur_p = {s: (g['pit'][s][0]['name'] if g['pit'][s] else None) for s in ('us', 'opp')}
    reg = 7 if g['innings'] <= 7 and max(len(g['ls']['us']), len(g['ls']['opp'])) <= 7 else 9
    out = []
    key = None
    bases = [None, None, None]
    outs = 0
    vis = home = 0
    for row in g['pbp']:
        if (row['inn'], row['tb']) != key:
            key = (row['inn'], row['tb'])
            bases, outs = [None, None, None], 0
        bat = side_bat[row['tb']]
        fld = 'opp' if bat == 'us' else 'us'
        text = (row['t'] or '').strip()
        low = text.lower()
        pm = re.match(r"(.+?) to p for (.+?)\.?$", text) or re.search(r'pitching change:\s*(.+?) replaces (.+?)\.?$', text, re.I)
        if pm:
            who = prost[fld].find(pm.group(1))
            if who:
                cur_p[fld] = who
            continue
        if not text or _skip(text):
            if row['v'] is not None:
                vis, home = row['v'], row['h']
            continue
        clauses = [c.strip() for c in re.split(r';', re.sub(r'\([^)]*\)', '', text)) if c.strip()]
        first = clauses[0]
        mb, mr = _BAT.search(first), _RUN.search(first)
        is_pa = bool(mb) and (not mr or mb.start() <= mr.start())
        fl = first.lower()
        if is_pa and 'out at first' in fl and ('picked off' in fl or 'caught stealing' in fl):
            is_pa = False
        before = dict(outs=outs, bases=tuple(b is not None for b in bases), vis=vis, home=home)
        mh = (home - vis)
        we_b = winprob.home_we(row['inn'], row['tb'], min(outs, 2), _bits(before['bases']), mh, reg, p)
        ev = {'inn': row['inn'], 'tb': row['tb'], 'bat': bat, 'text': text, 'kind': 'pa' if is_pa else 'run', 'outs': outs,
              'bases': before['bases'], 'we_home': we_b}
        new_outs = 0
        runner_clauses = clauses[1:] if is_pa else clauses
        res = None
        if is_pa:
            res = _result(first)
            name = _subject(first, _BAT)
            ev.update(res=res, bb=_bb_type(first), batter=rost[bat].find(name) or _pretty(name), pitcher=cur_p[fld],
                      batter_raw=name)
            if res == 'DP':
                new_outs += 2 if not any(_OUTWORD.search(c) for c in runner_clauses) else 1
            elif res in ('OUT', 'SF', 'SH') or (res == 'K' and 'reached' not in fl):
                if not (res == 'SH' and ('reached' in fl or 'error' in fl or 'safe' in fl)):
                    new_outs += 1
            batter_out_running = res not in ('OUT', 'SF', 'SH', 'DP', 'K') and bool(re.search(r'\bout (at|on)\b', fl))
            if batter_out_running:                       # 'singled to rf, out at second rf to ss'
                new_outs += 1
            if 'triple play' in low:
                new_outs = 3
        # runners: remove scorers / outs first, then move the rest (lead runner first), then place the batter
        moves = []
        for c in runner_clauses:
            nm = _subject(c, _RUN)
            d = _dest(c)
            is_out = bool(_OUTWORD.search(c))
            if is_out and not (is_pa and res == 'DP' and new_outs >= 2 and 'out on the play' in c.lower() and False):
                new_outs += 1
            moves.append((nm, 0 if is_out else d))
        if is_pa and res == 'DP':
            new_outs = min(new_outs, 3)

        def find_base(nm):
            k = _key(nm)
            for i in (2, 1, 0):
                if bases[i] is not None and k and (_key(bases[i]) == k or _key(bases[i]).startswith(k) or k.startswith(_key(bases[i]))):
                    return i
            return None
        placed = []
        for nm, d in moves:
            i = find_base(nm)
            if i is None:
                occ = [j for j in (2, 1, 0) if bases[j] is not None and (d is None or d == 0 or j + 1 < d)]
                i = occ[0] if occ else None
            if i is None:
                continue
            runner = bases[i]
            bases[i] = None
            if d and d < 4:
                placed.append((d, runner))
        for d, runner in sorted(placed, reverse=True):
            j = d - 1
            while j < 3 and bases[j] is not None:
                j += 1
            if j < 3:
                bases[j] = runner
        if is_pa:
            bd = {'1B': 1, '2B': 2, '3B': 3, 'HR': 4, 'BB': 1, 'IBB': 1, 'HBP': 1, 'ROE': 1, 'FC': 1, 'CI': 1}.get(res)
            if res == 'K' and 'reached' in fl:
                bd = 1
            if res == 'SH' and ('reached' in fl or 'error' in fl or 'safe' in fl):
                bd = 1
            own = _dest(first)
            if bd and own and own > bd:
                bd = own
            if batter_out_running:
                bd = None
            if bd and bd < 4:
                if res in ('BB', 'IBB', 'HBP', 'CI') or (bd == 1):
                    j = 0                                       # force: push anyone in the way
                    carry = ev['batter']
                    while j < 3 and carry is not None:
                        carry, bases[j] = bases[j], carry
                        j += 1
                else:
                    j = bd - 1
                    while j < 3 and bases[j] is not None:
                        j += 1
                    if j < 3:
                        bases[j] = ev['batter']
                    for k2 in range(bd - 1):                    # a double or triple clears the bases behind the batter
                        if bases[k2] is not None and k2 < bd - 1:
                            bases[k2] = None
        outs = min(3, outs + new_outs)
        if row['v'] is not None:
            vis, home = row['v'], row['h']
        if outs >= 3:
            bases = [None, None, None]
        ev['runs'] = (home - before['home']) + (vis - before['vis'])
        mh2 = home - vis
        if outs >= 3:
            we_a = winprob.home_we(row['inn'], row['tb'], 3, 0, mh2, reg, p)
        else:
            we_a = winprob.home_we(row['inn'], row['tb'], outs, _bits(tuple(b is not None for b in bases)), mh2, reg, p)
        ev['we_home_after'] = we_a
        sign = 1 if (bat == 'us') == us_home else -1                     # batting team is home -> +
        ev['wpa'] = sign * (we_a - we_b)                                 # change for the batting team
        ev['outs_after'] = outs
        out.append(ev)
    # the game's final: snap the last point to the result
    if out:
        fin = 1.0 if (g['us'] > g['them']) == us_home and g['us'] != g['them'] else (0.5 if g['us'] == g['them'] else 0.0)
        last = out[-1]
        sign = 1 if (last['bat'] == 'us') == us_home else -1
        last['we_home_after'] = fin
        last['wpa'] = sign * (fin - last['we_home'])
    for ev in out:
        f = (lambda v: v if us_home else 1 - v)
        ev['we_us'] = f(ev['we_home'])
        ev['we_us_after'] = f(ev['we_home_after'])
    return out


def _bits(on):
    return (1 if on[0] else 0) | (2 if on[1] else 0) | (4 if on[2] else 0)


# ------------------------------------------------------------------ the level's run environment
@cache.memo
def level_env(lvl, year):
    """League constants for one level and season from every loaded game at that level (both teams)."""
    t = {k: 0 for k in ('PA', 'AB', 'H', '2B', '3B', 'HR', 'BB', 'HBP', 'SF', 'SH', 'SO', 'R', 'outs', 'ER', 'pK', 'pBB', 'pHBP', 'g')}
    for prog, cfg in PROGRAMS.items():
        if cfg['level'] != lvl:
            continue
        S = season(prog, year)
        for g in (S or {}).get('games', []):
            t['g'] += 1
            for s in ('us', 'opp'):
                for b in g['bat'][s]:
                    for k in ('AB', 'H', '2B', '3B', 'HR', 'BB', 'HBP', 'SF', 'SH', 'SO', 'R'):
                        t[k] += b.get(k, 0)
                for q in g['pit'][s]:
                    t['outs'] += q.get('IP', 0)
                    t['ER'] += q.get('ER', 0)
    if not t['g']:
        return None
    t['PA'] = t['AB'] + t['BB'] + t['HBP'] + t['SF'] + t['SH']
    single = t['H'] - t['2B'] - t['3B'] - t['HR']
    woba_d = t['AB'] + t['BB'] + t['SF'] + t['HBP']
    woba = (W['BB'] * t['BB'] + W['HBP'] * t['HBP'] + W['1B'] * single + W['2B'] * t['2B'] + W['3B'] * t['3B'] + W['HR'] * t['HR']) / woba_d
    ip = t['outs'] / 3
    era = 9 * t['ER'] / ip if ip else 5.5
    fip_core = (13 * t['HR'] + 3 * (t['BB'] + t['HBP']) - 2 * t['SO']) / ip if ip else 0
    obp = (t['H'] + t['BB'] + t['HBP']) / (t['AB'] + t['BB'] + t['HBP'] + t['SF'])
    slg = (single + 2 * t['2B'] + 3 * t['3B'] + 4 * t['HR']) / t['AB']
    return {'level': lvl, 'year': year, 'games': t['g'], 'woba': woba, 'r_pa': t['R'] / t['PA'], 'era': era, 'fip_const': era - fip_core,
            'avg': t['H'] / t['AB'], 'obp': obp, 'slg': slg, 'ops': obp + slg, 'k_pct': t['SO'] / t['PA'], 'bb_pct': t['BB'] / t['PA'],
            'rpg': t['R'] / t['g'], 'pa': t['PA']}


@cache.memo
def rates_for(lvl, year):
    """Plate-appearance outcome chances at one level and season from the play-by-play (for win probability), or None."""
    n = {'K': 0, 'BB': 0, 'HBP': 0, '1B': 0, '2B': 0, '3B': 0, 'HR': 0, 'ROE': 0, 'OUT': 0}
    for prog, cfg in PROGRAMS.items():
        if cfg['level'] != lvl:
            continue
        for yr in (year - 1, year):                                   # two seasons pooled keeps the table steady
            S = season(prog, yr)
            for g in (S or {}).get('games', []):
                for row in g['pbp']:
                    t = row['t'] or ''
                    if _skip(t):
                        continue
                    first = re.split(r';', re.sub(r'\([^)]*\)', '', t))[0]
                    mb, mr = _BAT.search(first), _RUN.search(first)
                    if not mb or (mr and mr.start() < mb.start()):
                        continue
                    r = _result(first)
                    k = {'IBB': 'BB', 'CI': 'HBP', 'FC': 'OUT', 'SF': 'OUT', 'SH': 'OUT', 'DP': 'OUT'}.get(r, r)
                    n[k] = n.get(k, 0) + 1
    tot = sum(n.values())
    if tot < 2000:
        return None
    return {k: v / tot for k, v in n.items()}


# ------------------------------------------------------------------ season lines
def _pos(counts):
    if not counts:
        return None
    p = max(counts.items(), key=lambda kv: kv[1])[0]
    p = p.split('/')[0].upper()
    return {'PH': 'DH', 'PR': 'DH', 'DH': 'DH'}.get(p, p) if p in POS_RUNS_600 or p in ('PH', 'PR') else None


@cache.memo
def season_lines(program, year):
    """{'bat': [...], 'pit': [...], 'env', 'record', 'rd', 'games'} for our team in one season."""
    S = season(program, year)
    if not S:
        return None
    lvl = level(program)
    env = level_env(lvl, year)
    B, P = {}, {}
    wpa_b, wpa_p = {}, {}
    hr_allowed = {}
    for g in S['games']:
        for b in g['bat']['us']:
            pid = player_id(b['name'])
            x = B.setdefault(pid, {'id': pid, 'name': _pretty(b['name']), 'raw': b['name'], 'G': 0, 'pos': {}})
            x['G'] += 1
            for k in ('AB', 'R', 'H', 'RBI', '2B', '3B', 'HR', 'BB', 'SB', 'CS', 'HBP', 'SH', 'SF', 'SO', 'KL', 'GDP'):
                x[k] = x.get(k, 0) + b.get(k, 0)
            if b.get('pos'):
                x['pos'][b['pos']] = x['pos'].get(b['pos'], 0) + 1
        for q in g['pit']['us']:
            if q['name'].strip().lower() in ('team', 'totals'):
                continue
            pid = player_id(q['name'])
            x = P.setdefault(pid, {'id': pid, 'name': _pretty(q['name']), 'raw': q['name'], 'G': 0, 'GS': 0, 'W': 0, 'L': 0, 'SV': 0})
            x['G'] += 1
            x['GS'] += q.get('gs', 0)
            x['W'] += q.get('dec') == 'W'
            x['L'] += q.get('dec') == 'L'
            x['SV'] += q.get('dec') == 'S'
            for k in ('IP', 'H', 'R', 'ER', 'BB', 'SO', 'WP', 'BK', 'HBP', 'IBB', 'AB', 'BF', 'FO', 'GO', 'NP'):
                x[k] = x.get(k, 0) + q.get(k, 0)
        evs = plays(program, year, g['gid']) or []
        for ev in evs:
            if ev['kind'] != 'pa':
                continue
            if ev['bat'] == 'us':
                pid = player_id(ev['batter'])
                wpa_b[pid] = wpa_b.get(pid, 0.0) + ev['wpa']
            elif ev.get('pitcher'):
                pid = player_id(ev['pitcher'])
                wpa_p[pid] = wpa_p.get(pid, 0.0) - ev['wpa']
                if ev['res'] == 'HR':
                    hr_allowed[pid] = hr_allowed.get(pid, 0) + 1
    bat = []
    for pid, x in B.items():
        pa = x.get('AB', 0) + x.get('BB', 0) + x.get('HBP', 0) + x.get('SF', 0) + x.get('SH', 0)
        if not pa:
            continue
        ab = x.get('AB', 0)
        h = x.get('H', 0)
        single = h - x.get('2B', 0) - x.get('3B', 0) - x.get('HR', 0)
        tb = single + 2 * x.get('2B', 0) + 3 * x.get('3B', 0) + 4 * x.get('HR', 0)
        obp_d = ab + x.get('BB', 0) + x.get('HBP', 0) + x.get('SF', 0)
        x.update(PA=pa, TB=tb)
        x['AVG'] = h / ab if ab else None
        x['OBP'] = (h + x.get('BB', 0) + x.get('HBP', 0)) / obp_d if obp_d else None
        x['SLG'] = tb / ab if ab else None
        x['OPS'] = (x['OBP'] or 0) + (x['SLG'] or 0) if ab else None
        x['ISO'] = (x['SLG'] - x['AVG']) if ab else None
        bip = ab - x.get('SO', 0) - x.get('HR', 0) + x.get('SF', 0)
        x['BABIP'] = (h - x.get('HR', 0)) / bip if bip > 0 else None
        x['K%'] = x.get('SO', 0) / pa
        x['BB%'] = x.get('BB', 0) / pa
        wd = ab + x.get('BB', 0) + x.get('SF', 0) + x.get('HBP', 0)
        x['wOBA'] = ((W['BB'] * x.get('BB', 0) + W['HBP'] * x.get('HBP', 0) + W['1B'] * single + W['2B'] * x.get('2B', 0)
                      + W['3B'] * x.get('3B', 0) + W['HR'] * x.get('HR', 0)) / wd) if wd else None
        x['POS'] = _pos(x['pos'])
        if env and x['wOBA'] is not None:
            wraa = (x['wOBA'] - env['woba']) / WOBA_SCALE * pa
            x['wRAA'] = wraa
            x['wRC+'] = 100 * ((wraa / pa + env['r_pa']) / env['r_pa'])
            x['WAR'] = (wraa + POS_RUNS_600.get(x['POS'] or '3B', 0.0) * pa / 600 + REPL_RUNS_600 * pa / 600) / RUNS_PER_WIN
        x['WPA'] = wpa_b.get(pid)
        for k in ('wRAA', 'wRC+', 'WAR'):
            x.setdefault(k, None)
        x.pop('pos', None)
        bat.append(x)
    pit = []
    for pid, x in P.items():
        outs = x.get('IP', 0)
        ip = outs / 3
        x['HR'] = hr_allowed.get(pid, 0)
        x['IPs'] = f"{outs // 3}.{outs % 3}"
        x['ERA'] = 9 * x.get('ER', 0) / ip if ip else None
        x['WHIP'] = (x.get('BB', 0) + x.get('H', 0)) / ip if ip else None
        bf = x.get('BF', 0) or (outs + x.get('H', 0) + x.get('BB', 0) + x.get('HBP', 0))
        x['BF'] = bf
        x['K%'] = x.get('SO', 0) / bf if bf else None
        x['BB%'] = x.get('BB', 0) / bf if bf else None
        x['K-BB%'] = (x['K%'] - x['BB%']) if bf else None
        bip = x.get('AB', 0) - x.get('SO', 0) - x['HR']
        x['BABIP'] = (x.get('H', 0) - x['HR']) / bip if bip > 0 else None
        if ip and env:
            x['FIP'] = (13 * x['HR'] + 3 * (x.get('BB', 0) + x.get('HBP', 0)) - 2 * x.get('SO', 0)) / ip + env['fip_const']
            x['WAR'] = ip / 9 * ((env['era'] + 0.20 - x['FIP']) / RUNS_PER_WIN + 0.010 * x['GS'] / x['G'])
        x['WPA'] = wpa_p.get(pid)
        x.setdefault('FIP', None)
        x.setdefault('WAR', None)
        pit.append(x)
    w = sum(1 for g in S['games'] if g['us'] > g['them'])
    l_ = sum(1 for g in S['games'] if g['us'] < g['them'])
    t_ = len(S['games']) - w - l_
    rs, ra = sum(g['us'] for g in S['games']), sum(g['them'] for g in S['games'])
    return {'bat': sorted(bat, key=lambda x: -x['PA']), 'pit': sorted(pit, key=lambda x: -x.get('IP', 0)), 'env': env, 'level': lvl,
            'record': (w, l_, t_), 'rs': rs, 'ra': ra, 'games': S['games'], 'year': year, 'source': S.get('source'),
            'updated': S.get('updated') or S.get('imported')}


# ------------------------------------------------------------------ rosters: jersey numbers, positions and class
@cache.memo
def roster(program):
    """{player id: {'name', 'years': {'2026': {'num','pos','cls','ht','wt','bt'}}}} from the program's roster pages."""
    p = os.path.join(BOX_DIR, program or '', 'roster.json')
    if not os.path.exists(p):
        return {}
    with open(p) as f:
        return json.load(f)


def bio(program, pid, year=None):
    """The roster line for one player in `year` (or his nearest season before it, else his latest), or {}."""
    e = roster(program).get(pid)
    if not e:
        return {}
    ys = sorted(e['years'], key=int)
    pick = None
    if year is not None:
        before = [y for y in ys if int(y) <= int(year)]
        pick = before[-1] if before else None
    pick = pick or ys[-1]
    return dict(e['years'][pick], year=int(pick))


def player_seasons(program, pid):
    """{'name', 'bat': [(year, line)], 'pit': [(year, line)]} across every loaded season."""
    out = {'name': None, 'bat': [], 'pit': []}
    for yr in years(program):
        L = season_lines(program, yr)
        for side in ('bat', 'pit'):
            x = next((r for r in L[side] if r['id'] == pid), None) if L else None
            if x:
                out['name'] = out['name'] or x['name']
                out[side].append((yr, x))
    return out


def game_log(program, year, pid):
    """Per-game lines for one player in one season: [(game, batting line or None, pitching line or None)]."""
    S = season(program, year)
    rows = []
    for g in (S or {}).get('games', []):
        b = next((x for x in g['bat']['us'] if player_id(x['name']) == pid), None)
        q = next((x for x in g['pit']['us'] if player_id(x['name']) == pid), None)
        if b or q:
            rows.append((g, b, q))
    return rows


def find_game(program, gid):
    yr = int(gid[:4])
    for y in (yr, yr - 1, yr + 1):
        S = season(program, y)
        for g in (S or {}).get('games', []):
            if g['gid'] == gid:
                return y, g
    return None, None


def games_between(program, start, end):
    """Every box-score game with start <= date < end (ISO strings or None)."""
    out = []
    for yr in years(program):
        S = season(program, yr)
        for g in (S or {}).get('games', []):
            if (not start or g['date'] >= start) and (not end or g['date'] < end):
                out.append(g)
    return out
