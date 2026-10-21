"""Full Game Report (beta): rebuilds one game from the stored Game / Scrimmage pitches.
Both teams' pitches are needed: our pitchers' files hold the opponent's at-bats, the opposing pitchers' files ('opp-...') hold ours.
Uses the Trackman columns Inning, Top/Bottom, PAofInning, Outs, PlayResult, KorBB, RunsScored when they are there."""
import html
import os

import extract as e
import hitting as H
import outings as outings_mod
import pitchfx
import store

GAME_TYPES = ('Game', 'Scrimmage')


# ------------------------------------------------------------------ collecting
def _int(v, d=0):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return d


def _tb(r):
    return 0 if (r.get('Top/Bottom') or '').strip().lower().startswith('t') else 1


def _order(r):
    return (_int(r.get('Inning')), _tb(r), _int(r.get('PAofInning')), _int(r.get('PitchofPA')), r.get('Time') or '')


def _our_files(program):
    out = []
    d = outings_mod.OUTINGS_DIR
    if not os.path.isdir(d):
        return out
    for f in sorted(os.listdir(d)):
        if not f.endswith('.json'):
            continue
        slug = f[:-5]
        data = outings_mod.load(slug, real_only=True)
        if slug.startswith('opp-'):
            if data.get('program') == program:
                out.append((slug, 'opp', data))
        else:
            pl = store.get_real_player(slug)
            if pl and pl.get('program') == program:
                out.append((slug, 'us', data))
    return out


def collect(program):
    """{gid: {'gid','date','opp','label','n','rows':[{'r','pit','slug'}]}} for every game with stored pitches."""
    groups = {}
    for slug, side, data in _our_files(program):
        for o in data.get('outings', []):
            for r in o['rows']:
                if r.get('SessionType') not in GAME_TYPES:
                    continue
                opp = r.get('Opponent') or 'Unlabeled opponent'
                k = (o['date'][:10], store.slugify(opp) or 'unlabeled', (r.get('GameUID') or '').strip())
                g = groups.setdefault(k, {'date': o['date'][:10], 'opp': opp, 'rows': []})
                g['rows'].append({'r': r, 'pit': side, 'slug': slug})
    per = {}
    for k in groups:
        per.setdefault(k[:2], []).append(k)
    out = {}
    for k2, ks in per.items():
        ks.sort(key=lambda k: min((x['r'].get('Time') or '') for x in groups[k]['rows']))
        for i, k in enumerate(ks):
            g = groups[k]
            gid = f"{k[0]}--{k[1]}" + (f"-g{i + 1}" if len(ks) > 1 else '')
            g.update({'gid': gid, 'n': len(g['rows']), 'label': store.program_label(program)})
            out[gid] = g
    return out


# ------------------------------------------------------------------- grading
OUTCOME = {'HomeRun': 100, 'Triple': 95, 'Double': 90, 'Single': 78, 'Walk': 68, 'HBP': 62, 'Sacrifice': 60, 'Error': 50,
           'FieldersChoice': 40, 'Out': 22, 'K swinging': 8, 'K looking': 4}
ABBR = {'HomeRun': 'HR', 'Triple': '3B', 'Double': '2B', 'Single': '1B', 'Walk': 'BB', 'HBP': 'HBP', 'Sacrifice': 'SAC', 'Error': 'ROE',
        'FieldersChoice': 'FC', 'Out': 'Out', 'K swinging': 'K', 'K looking': 'Kc', 'In play': 'BIP'}
HITS = ('Single', 'Double', 'Triple', 'HomeRun')
BANDS = [(90, 'A+'), (82, 'A'), (75, 'A-'), (68, 'B+'), (60, 'B'), (52, 'B-'), (45, 'C+'), (38, 'C'), (30, 'C-'), (22, 'D')]


def letter(score):
    for lo, g in BANDS:
        if score >= lo:
            return g
    return 'F'


def _result(rows):
    last = rows[-1]
    pr = (last.get('PlayResult') or '').strip()
    kb = (last.get('KorBB') or '').strip()
    call = (last.get('PitchCall') or '').strip()
    if kb == 'Strikeout':
        return 'K swinging' if 'Swinging' in call or 'Foul' in call else 'K looking'
    if kb == 'Walk':
        return 'Walk'
    if call == 'HitByPitch':
        return 'HBP'
    if pr in OUTCOME:
        return pr
    if call == 'InPlay':
        return 'In play'
    return None                   # the at-bat was cut off (data ends mid-PA)


def build(rows):
    """rows: [{'r': trackman row, 'pit': 'us'|'opp'}] for one game (our pitcher rows = opponent's at-bats).
    Returns the whole report model."""
    rows = sorted(rows, key=lambda x: _order(x['r']))
    # --- plate appearances
    pas, cur, key = [], None, None
    for x in rows:
        r = x['r']
        k = (_int(r.get('Inning')), _tb(r), _int(r.get('PAofInning')), (r.get('Batter') or '').strip(), x['pit'])
        if k != key:
            cur = {'inn': k[0], 'tb': k[1], 'batter': k[3], 'bat': 'opp' if x['pit'] == 'us' else 'us', 'pit_side': x['pit'], 'rows': [],
                   'pitcher': (r.get('Pitcher') or '').strip(), 'slug': x['slug'], 'outs': _int(r.get('Outs')),
                   'side': {'Right': 'R', 'Left': 'L'}.get(r.get('BatterSide'))}
            pas.append(cur)
            key = k
        cur['rows'].append(r)
    # --- score and outs as we go
    score = {'us': 0, 'opp': 0}
    line = {}                                                  # (inn, tb) -> runs
    for pa in pas:
        last = pa['rows'][-1]
        pa['result'] = _result(pa['rows'])
        pa['runs'] = sum(_int(r.get('RunsScored')) for r in pa['rows'])
        oop = _int(last.get('OutsOnPlay'))
        pa['outs_made'] = oop if oop else (1 if pa['result'] in ('K swinging', 'K looking') else 0)
        pa['margin'] = score[pa['bat']] - score['opp' if pa['bat'] == 'us' else 'us']
        score[pa['bat']] += pa['runs']
        line[(pa['inn'], pa['tb'])] = line.get((pa['inn'], pa['tb']), 0) + pa['runs']
        pa['n_pitches'] = len(pa['rows'])
        pa['count'] = f"{_int(last.get('Balls'))}-{_int(last.get('Strikes'))}"
        ev, la = e._fnum(last.get('ExitSpeed')), e._fnum(last.get('Angle'))
        pa['ev'], pa['la'] = ev, la
        pa['xba'] = H.hit_prob(ev, la) if (pa['result'] in ('In play',) + tuple(OUTCOME) and (last.get('PitchCall') == 'InPlay') and ev is not None and la is not None) else None
        pa['hit_type'] = (last.get('TaggedHitType') or last.get('AutoHitType') or '').replace('Undefined', '')
        _grade(pa)
    teams = {'us': _team(pas, 'us'), 'opp': _team(pas, 'opp')}
    # --- home / away
    us_home = any(x['pit'] == 'us' and _tb(x['r']) == 0 for x in rows) or any(x['pit'] == 'opp' and _tb(x['r']) == 1 for x in rows)
    innings = max([p['inn'] for p in pas] or [0])
    ls = {'us': [], 'opp': []}
    for i in range(1, innings + 1):
        for side in ('us', 'opp'):
            tb = 1 if (side == 'us') == us_home else 0
            seen = any(p['inn'] == i and p['tb'] == tb for p in pas)
            ls[side].append(line.get((i, tb), 0) if seen else None)
    return {'pas': pas, 'teams': teams, 'score': score, 'linescore': ls, 'innings': innings, 'us_home': us_home,
            'pitchers': {'us': _pitchers(pas, 'us'), 'opp': _pitchers(pas, 'opp')}}


def _grade(pa):
    res = pa['result']
    if not res:
        pa.update(grade=None, score=None, why='At-bat cut off in the data')
        return
    notes = []
    base = OUTCOME.get(res)
    q = None
    if res == 'In play':
        base = 50 if pa['xba'] is None else None
        res_label = 'ball in play'
    if pa['xba'] is not None:
        q = pa['xba'] * 100
        if res == 'HomeRun':
            q = 100
        if base is None:
            base = 22 if pa['outs_made'] else 78
    s = base if q is None else 0.5 * base + 0.5 * q
    if q is not None and base is not None:
        gap = pa['xba'] - (1.0 if res in HITS else 0.0)
        if res in HITS and pa['xba'] < 0.3:
            notes.append('hit, but soft contact')
        elif res not in HITS and res not in ('Sacrifice', 'Error') and pa['xba'] >= 0.6:
            notes.append('hard contact, no result')
    n = pa['n_pitches']
    if n >= 6 and res != 'HomeRun':
        s += min(8 if res not in ('K swinging', 'K looking') else 4, 2 * (n - 5))
        notes.append(f'{n}-pitch at-bat')
    if pa['runs'] and res not in ('K swinging', 'K looking', 'Out'):
        s += 5 * min(pa['runs'], 2)
        notes.append(f"{pa['runs']} RBI" if res != 'HomeRun' else f"{pa['runs']} run HR")
    strikes = int(pa['count'].split('-')[1])
    if strikes == 2 and res in HITS + ('Walk', 'HBP', 'Sacrifice'):
        s += 4
        notes.append('two-strike success')
    if pa['inn'] >= 7 and abs(pa['margin']) <= 2:
        s = 50 + (s - 50) * 1.15
        notes.append('late and close')
    if pa['outs'] == 2 and res in HITS + ('Walk',):
        notes.append('two-out')
    if pa['outs'] < 2 and res == 'Out' and not pa['runs'] and pa['xba'] is not None and pa['xba'] < 0.15:
        s -= 3
    s = max(0, min(100, round(s)))
    pa['score'] = s
    pa['grade'] = letter(s)
    pa['why'] = ', '.join(notes)


# ------------------------------------------------------------- lineups / lines
def _team(pas, side):
    """Lineup card for the team batting as `side`: nine slots by order of appearance, substitutes slot in by turn."""
    mine = [p for p in pas if p['bat'] == side and p['batter']]
    slots, who = [], {}
    for k, pa in enumerate(mine):
        b = pa['batter']
        if b in who:
            who[b]['pas'].append(pa)
            continue
        if len(slots) < 9:
            ent = {'name': b, 'side': pa['side'], 'pas': [pa], 'sub_for': None, 'first_inn': pa['inn']}
            slots.append([ent])
        else:
            si = k % 9
            prev = slots[si][-1]
            ent = {'name': b, 'side': pa['side'], 'pas': [pa], 'sub_for': prev['name'], 'first_inn': pa['inn']}
            slots[si].append(ent)
        who[b] = ent
    card = []
    for i, ents in enumerate(slots):
        for j, ent in enumerate(ents):
            card.append(_totals(ent, i + 1, j > 0))
    return {'slots': card, 'n': len(slots), 'pas': mine}


def _totals(ent, slot, is_sub):
    ps = [p for p in ent['pas'] if p['result']]
    ab = [p for p in ps if p['result'] not in ('Walk', 'HBP', 'Sacrifice')]
    h = [p for p in ps if p['result'] in HITS]
    xs = [p['xba'] for p in ps if p['xba'] is not None]
    scores = [p['score'] for p in ps if p['score'] is not None]
    evs = [p['ev'] for p in ps if p['ev'] is not None]
    avg = sum(scores) / len(scores) if scores else None
    ent = dict(ent, slot=slot, is_sub=is_sub, ab=len(ab), h=len(h), bb=sum(1 for p in ps if p['result'] == 'Walk'),
               k=sum(1 for p in ps if p['result'].startswith('K ')), rbi=sum(p['runs'] for p in ps if p['result'] != 'Out' or p['runs']),
               hr=sum(1 for p in ps if p['result'] == 'HomeRun'), bip=len(xs),
               xba=(sum(xs) / len(xs)) if xs else None, ev=(sum(evs) / len(evs)) if evs else None,
               avg=avg, avg_grade=letter(avg) if avg is not None else None, pa_n=len(ent['pas']))
    return ent


def _ip(outs):
    return f"{outs // 3}.{outs % 3}"


def _pitchers(pas, side):
    """Pitchers for `side` in order of appearance, with a box-score line."""
    mine = [p for p in pas if p['pit_side'] == side and p['pitcher']]
    order, by = [], {}
    for pa in mine:
        k = pa['pitcher']
        if k not in by:
            by[k] = {'name': k, 'slug': pa['slug'], 'pas': [], 'first_inn': pa['inn'], 'rows': []}
            order.append(k)
        by[k]['pas'].append(pa)
        by[k]['rows'].extend(pa['rows'])
    out = []
    for k in order:
        d = by[k]
        ps = [p for p in d['pas'] if p['result']]
        rows = d['rows']
        strikes = sum(1 for r in rows if (r.get('PitchCall') or '') not in ('BallCalled', 'BallinDirt', 'BallIntentional', 'HitByPitch'))
        outs = sum(p['outs_made'] for p in d['pas'])
        velos = [e._fnum(r.get('RelSpeed')) for r in rows]
        velos = [v for v in velos if v]
        fb = [e._fnum(r.get('RelSpeed')) for r in rows if any(t in (pitchfx._label(r) or '').lower() for t in ('seam', 'sinker', 'cutter')) and e._fnum(r.get('RelSpeed'))]
        out.append({'name': _flip(k), 'raw': k, 'slug': d['slug'], 'first_inn': d['first_inn'], 'bf': len(d['pas']), 'np': len(rows),
                    'strike_pct': round(100 * strikes / len(rows)) if rows else None, 'ip': _ip(outs),
                    'h': sum(1 for p in ps if p['result'] in HITS), 'bb': sum(1 for p in ps if p['result'] in ('Walk', 'HBP')),
                    'k': sum(1 for p in ps if p['result'].startswith('K ')), 'r': sum(p['runs'] for p in d['pas']),
                    'hr': sum(1 for p in ps if p['result'] == 'HomeRun'),
                    'fb_avg': (sum(fb) / len(fb)) if fb else None, 'top': max(velos) if velos else None, 'rows': rows,
                    'throws': ((rows[0].get('PitcherThrows') or '')[:1].upper() if rows else ''), 'pas': d['pas']})
    return out


def _flip(n):
    last, _, first = (n or '').partition(', ')
    return f'{first} {last}'.strip() if first else (n or '')


# ------------------------------------------------------------ arsenal vs prior
def _swings(rows):
    sw = [r for r in rows if (r.get('PitchCall') or '') in ('StrikeSwinging', 'InPlay') or (r.get('PitchCall') or '').startswith('Foul')]
    wh = [r for r in sw if r.get('PitchCall') == 'StrikeSwinging']
    return (100 * len(wh) / len(sw)) if len(sw) >= 3 else None


def _stats(rows):
    v = [e._fnum(r.get('RelSpeed')) for r in rows]
    v = sorted(x for x in v if x)
    if not v:
        return None
    return {'n': len(rows), 'avg': sum(v) / len(v), 'lo': v[0], 'hi': v[-1], 'whiff': _swings(rows)}


def arsenal(pitcher, game_date, program, side):
    """[{type,color,today:{...},prev:{...}|None,usage,prev_usage}] for one pitcher. Previous data = every other date on file for him."""
    if side == 'us':
        data = outings_mod.load(pitcher['slug'], real_only=True)
    else:
        data = outings_mod.load(pitcher['slug'], real_only=True)
    prev_rows = [r for o in data.get('outings', []) if o['date'][:10] != game_date for r in o['rows']]
    today_rows = pitcher['rows']

    def grp(rs):
        g = {}
        for r in rs:
            t = pitchfx._label(r)
            if t:
                g.setdefault(t, []).append(r)
        return g
    tg, pg = grp(today_rows), grp(prev_rows)
    tn, pn = sum(len(v) for v in tg.values()), sum(len(v) for v in pg.values())
    out = []
    for t, rs in sorted(tg.items(), key=lambda kv: -len(kv[1])):
        today = _stats(rs)
        if not today:
            continue
        prev = _stats(pg.get(t, [])) if len(pg.get(t, [])) >= 5 else None
        out.append({'type': t, 'color': e.MINI_PITCH_COLORS.get(t, '#555'), 'today': today, 'prev': prev,
                    'usage': 100 * len(rs) / tn if tn else None, 'prev_usage': (100 * len(pg.get(t, [])) / pn) if (pn and prev) else None})
    return out, len(prev_rows)


def arsenal_svg(rows, uid='ar'):
    """Velocity ranges: grey = his earlier range for the pitch (tick = average), dark = this game (dot = average)."""
    if not rows:
        return ''
    vals = []
    for a in rows:
        vals += [a['today']['lo'], a['today']['hi']]
        if a['prev']:
            vals += [a['prev']['lo'], a['prev']['hi']]
    lo, hi = int(min(vals)) - 1, int(max(vals)) + 2
    L, R, rowh = 118, 300, 30
    W = L + R + 270
    H_ = 26 + rowh * len(rows)

    def X(v):
        return L + (v - lo) / (hi - lo) * R
    s = [f'<svg viewBox="0 0 {W} {H_}" width="100%" style="max-width:{W}px;font-family:Barlow,sans-serif" role="img" aria-label="Pitch velocity this game versus earlier">']
    step = 2 if hi - lo <= 16 else 5
    for v in range((lo // step + 1) * step, hi, step):
        s.append(f'<line x1="{X(v):.1f}" y1="16" x2="{X(v):.1f}" y2="{H_ - 4}" stroke="#e6e9ea" stroke-width="1"/><text x="{X(v):.1f}" y="11" font-size="10" fill="#8a949b" text-anchor="middle">{v}</text>')
    s.append(f'<text x="{L + R + 14}" y="11" font-size="10" fill="#8a949b">USAGE</text><text x="{L + R + 84}" y="11" font-size="10" fill="#8a949b">AVG VELO</text><text x="{L + R + 170}" y="11" font-size="10" fill="#8a949b">WHIFF</text>')
    for i, a in enumerate(rows):
        y = 18 + rowh * i + rowh / 2
        t, p = a['today'], a['prev']
        s.append(f'<circle cx="8" cy="{y:.1f}" r="5" fill="{a["color"]}"/><text x="20" y="{y + 4:.1f}" font-size="12.5" font-weight="600" fill="#22303a">{html.escape(a["type"])}</text>')
        if p:
            s.append(f'<rect x="{X(p["lo"]):.1f}" y="{y - 8:.1f}" width="{max(X(p["hi"]) - X(p["lo"]), 3):.1f}" height="16" rx="8" fill="#d5dadd"/><rect x="{X(p["avg"]) - 1:.1f}" y="{y - 10:.1f}" width="2" height="20" fill="#7d888f"/>')
        s.append(f'<rect x="{X(t["lo"]):.1f}" y="{y - 4:.1f}" width="{max(X(t["hi"]) - X(t["lo"]), 4):.1f}" height="8" rx="4" fill="{a["color"]}"/><circle cx="{X(t["avg"]):.1f}" cy="{y:.1f}" r="5" fill="#fff" stroke="{a["color"]}" stroke-width="2.5"/>')
        us = f'{a["usage"]:.0f}%' + (f' <tspan fill="#8a949b">({a["prev_usage"]:.0f}%)</tspan>' if a['prev_usage'] is not None else '')
        s.append(f'<text x="{L + R + 14}" y="{y + 4:.1f}" font-size="12" fill="#22303a">{us}</text>')
        if p:
            d = t['avg'] - p['avg']
            col = '#2f8a57' if d > 0.4 else ('#c0443c' if d < -0.4 else '#6b7680')
            s.append(f'<text x="{L + R + 84}" y="{y + 4:.1f}" font-size="12" fill="#22303a">{t["avg"]:.1f} <tspan fill="{col}" font-weight="700">{d:+.1f}</tspan></text>')
        else:
            s.append(f'<text x="{L + R + 84}" y="{y + 4:.1f}" font-size="12" fill="#22303a">{t["avg"]:.1f} <tspan fill="#8a949b">no prior</tspan></text>')
        if t['whiff'] is not None:
            pw = f' <tspan fill="#8a949b">({p["whiff"]:.0f}%)</tspan>' if p and p['whiff'] is not None else ''
            s.append(f'<text x="{L + R + 170}" y="{y + 4:.1f}" font-size="12" fill="#22303a">{t["whiff"]:.0f}%{pw}</text>')
        else:
            s.append(f'<text x="{L + R + 170}" y="{y + 4:.1f}" font-size="12" fill="#8a949b">—</text>')
    s.append('</svg>')
    return ''.join(s)


# ----------------------------------------------------------------- scorebook
_BALLS = ('BallCalled', 'BallinDirt', 'BallIntentional', 'Ball')


def _pos(direction, dist, hit_type):
    """Rough fielder from the batted-ball direction (negative = third-base side) and distance. Approximate by design."""
    if direction is None:
        return None
    infield = (dist is not None and dist < 140) or hit_type in ('GroundBall', 'Bunt')
    if infield:
        return '5' if direction < -18 else '6' if direction < -2 else '4' if direction < 18 else '3'
    return '7' if direction < -15 else '8' if direction < 15 else '9'


def notation(pa):
    """Scorebook shorthand for the plate appearance, e.g. K, 6-3, F8, 1B."""
    res = pa['result']
    last = pa['rows'][-1]
    ht = (last.get('TaggedHitType') or last.get('AutoHitType') or '').strip()
    pos = _pos(e._fnum(last.get('Direction')), e._fnum(last.get('Distance')), ht)
    short = {'HomeRun': 'HR', 'Triple': '3B', 'Double': '2B', 'Single': '1B', 'Walk': 'BB', 'HBP': 'HBP', 'K swinging': 'K', 'K looking': 'K'}
    if res in short:
        return short[res]
    if res is None:
        return ''
    pre = {'GroundBall': 'G', 'LineDrive': 'L', 'FlyBall': 'F', 'Popup': 'P'}.get(ht, '')
    if res == 'Out':
        if ht == 'GroundBall':
            return ('3U' if pos == '3' else f'{pos}-3') if pos else 'GO'
        return f'{pre}{pos}' if (pre and pos) else 'Out'
    if res == 'Sacrifice':
        return 'SH' if ht == 'Bunt' else (f'SF{pos}' if pos else 'SAC')
    if res == 'Error':
        return f'E{pos}' if pos else 'E'
    if res == 'FieldersChoice':
        return f'FC{pos}' if pos and ht == 'GroundBall' else 'FC'
    return 'BIP'


def _tally(pa):
    b = s = 0
    for r in pa['rows']:
        c = (r.get('PitchCall') or '')
        if c in _BALLS:
            b += 1
        elif c in ('StrikeCalled', 'StrikeSwinging') or c.startswith('Foul'):
            if c.startswith('Foul') and s >= 2:
                continue
            s += 1
    if pa['result'] == 'K swinging' or pa['result'] == 'K looking':
        s = 2
    if pa['result'] == 'Walk':
        b = 3
    return min(b, 3), min(s, 2)


_BASES = {'Single': 1, 'Walk': 1, 'HBP': 1, 'Error': 1, 'FieldersChoice': 1, 'Double': 2, 'Triple': 3, 'HomeRun': 4}


def cell_svg(pa, ink='#2a2118', gold='#b5763a'):
    """One scorebook cell: diamond with the base path, notation, ball / strike boxes, out circle, grade."""
    W, Hh = 70, 62
    cx, cy, r = 35, 33, 17
    pts = {'h': (cx, cy + r), 'f': (cx + r, cy), 's': (cx, cy - r), 't': (cx - r, cy)}
    o = [f'<svg viewBox="0 0 {W} {Hh}" width="{W}" height="{Hh}" xmlns="http://www.w3.org/2000/svg" style="display:block">']
    o.append(f'<path d="M{pts["h"][0]} {pts["h"][1]} L{pts["f"][0]} {pts["f"][1]} L{pts["s"][0]} {pts["s"][1]} L{pts["t"][0]} {pts["t"][1]} Z" fill="none" stroke="#c9bfae" stroke-width="1.2"/>')
    res = pa['result']
    nb = _BASES.get(res, 0)
    if nb == 4:
        o.append(f'<path d="M{pts["h"][0]} {pts["h"][1]} L{pts["f"][0]} {pts["f"][1]} L{pts["s"][0]} {pts["s"][1]} L{pts["t"][0]} {pts["t"][1]} Z" fill="{ink}" opacity=".85"/>')
    elif nb:
        seq = [pts['h'], pts['f'], pts['s'], pts['t']][:nb + 1]
        o.append('<path d="M' + ' L'.join(f'{x} {y}' for x, y in seq) + f'" fill="none" stroke="{ink}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>')
    elif pa['runs'] and res not in (None,):
        pass
    nt = notation(pa)
    big = len(nt) <= 3
    if nt:
        col = '#fff' if nb == 4 else ink
        if nt == 'K' and res == 'K looking':
            o.append(f'<text x="{cx}" y="{cy + 6}" text-anchor="middle" font-size="19" font-weight="800" fill="{col}" transform="translate({2 * cx} 0) scale(-1 1)" font-family="Barlow,Arial,sans-serif">K</text>')
        else:
            fs = 17 if big else 12
            o.append(f'<text x="{cx}" y="{cy + 6}" text-anchor="middle" font-size="{fs}" font-weight="800" fill="{col}" font-family="Barlow,Arial,sans-serif">{html.escape(nt)}</text>')
    b, s = _tally(pa)
    for i in range(3):
        o.append(f'<rect x="{W - 29 + i * 8}" y="3" width="6" height="6" fill="{ink if i < b else "none"}" stroke="#a79c8a" stroke-width=".8"/>')
    for i in range(2):
        o.append(f'<rect x="{W - 21 + i * 8}" y="11" width="6" height="6" fill="{ink if i < s else "none"}" stroke="#a79c8a" stroke-width=".8"/>')
    o.append(f'<text x="3" y="11" font-size="9" fill="#8a7f6e" font-family="Barlow,Arial,sans-serif">{pa["n_pitches"]}p</text>')
    if pa['outs_made']:
        n = min(3, pa['outs'] + pa['outs_made'])
        o.append(f'<circle cx="{W - 10}" cy="{Hh - 10}" r="7.5" fill="none" stroke="{ink}" stroke-width="1.4"/><text x="{W - 10}" y="{Hh - 6.6}" text-anchor="middle" font-size="10" font-weight="800" fill="{ink}" font-family="Barlow,Arial,sans-serif">{n}</text>')
    if pa.get('grade'):
        gc = {'A': '#2f8a57', 'B': '#4a93a8', 'C': '#d9a028', 'D': '#d9702c', 'F': '#c0443c'}[pa['grade'][0]]
        o.append(f'<rect x="3" y="{Hh - 15}" width="22" height="12" rx="3" fill="{gc}"/><text x="14" y="{Hh - 6}" text-anchor="middle" font-size="9" font-weight="800" fill="#fff" font-family="Barlow,Arial,sans-serif">{pa["grade"]}</text>')
    if pa['runs'] and pa['result'] not in ('K swinging', 'K looking', 'Out', None):
        o.append(f'<text x="3" y="22" font-size="8.5" font-weight="700" fill="{gold}" font-family="Barlow,Arial,sans-serif">{pa["runs"]} RBI</text>')
    if pa['result'] and pa['outs'] + pa['outs_made'] >= 3:
        o.append(f'<line x1="0" y1="{Hh - .5}" x2="{W}" y2="{Hh - .5}" stroke="{ink}" stroke-width="2.4"/>')
    o.append('</svg>')
    return ''.join(o)


def scorebook(m, side):
    """Grid for one team batting: rows = lineup spots (substitutes share the spot), columns = innings (extra columns when a spot bats twice)."""
    pas = m['teams'][side]['pas']
    for i, p in enumerate(pas):
        p['seq'] = i
    slots = {}
    for ent in m['teams'][side]['slots']:
        slots.setdefault(ent['slot'], []).append(ent)
    cols = []                                     # (inning, k)
    cell = {}
    for sl, ents in slots.items():
        per = {}
        for ent in ents:
            for p in ent['pas']:
                per.setdefault(p['inn'], []).append(p)
        for inn, ps in per.items():
            ps.sort(key=lambda p: p['seq'])
            for k, p in enumerate(ps):
                cell[(sl, inn, k)] = p
    inns = sorted({inn for (_, inn, _) in cell} | set(range(1, max(m['innings'], 9) + 1)))
    for inn in inns:
        ks = max([k for (_, i, k) in cell if i == inn] + [-1]) + 1
        for k in range(max(ks, 1)):
            cols.append((inn, k))
    rows = []
    for sl in sorted(slots):
        ents = slots[sl]
        rows.append({'slot': sl, 'ents': ents, 'cells': [cell.get((sl, inn, k)) for inn, k in cols],
                     'ab': sum(x['ab'] for x in ents), 'h': sum(x['h'] for x in ents), 'rbi': sum(x['rbi'] for x in ents),
                     'bb': sum(x['bb'] for x in ents), 'k': sum(x['k'] for x in ents)})
    return {'cols': cols, 'rows': rows, 'inns': inns}


# ------------------------------------------------- scorebook, paper-style layout
def pitch_letter(r):
    t = (pitchfx._label(r) or '').lower()
    if any(k in t for k in ('seam', 'fastball', 'sinker')):
        return 'F'
    if 'slider' in t or 'sweeper' in t:
        return 'S'
    if 'curve' in t or 'slurve' in t:
        return 'C'
    if 'cutter' in t:
        return 'O'
    if 'change' in t or 'split' in t:
        return 'X'
    return '?'


def pitch_kind(r):
    c = r.get('PitchCall') or ''
    if c in _BALLS:
        return 'ball'
    if c == 'HitByPitch':
        return 'hbp'
    if c == 'StrikeCalled':
        return 'called'
    if c == 'StrikeSwinging':
        return 'swing'
    if c.startswith('Foul'):
        return 'foul'
    if c == 'InPlay':
        return 'inplay'
    return 'ball'


def pa_strikes(pa):
    return sum(1 for r in pa['rows'] if pitch_kind(r) in ('called', 'swing', 'foul'))


def cell2(pa, new_pitcher='', end_inning=False, ink='#2a2118', gold='#b5763a', gray='#ddd3c2'):
    """One at-bat cell in the paper-scorebook layout: pitch sequence on top (B row / S row), field diagram, out circle, result box."""
    W, Hh = 148, 100
    o = [f'<svg viewBox="0 0 {W} {Hh}" width="{W}" height="{Hh}" xmlns="http://www.w3.org/2000/svg" style="display:block;font-family:Barlow,Arial,sans-serif">']
    # pitch grid
    gx, cw, rh = 16, 16.5, 13
    o.append(f'<text x="4" y="12" font-size="9" fill="#a79c8a" font-weight="700">B</text><text x="4" y="25" font-size="9" fill="#a79c8a" font-weight="700">S</text>')
    for r_ in range(2):
        for c_ in range(8):
            o.append(f'<rect x="{gx + c_ * cw:.1f}" y="{2 + r_ * rh}" width="{cw}" height="{rh}" fill="none" stroke="#d3c9b8" stroke-width=".8"/>')
    seq = [r for r in pa['rows'] if pitch_kind(r) != 'hbp'][-8:]
    for i, r in enumerate(seq):
        k = pitch_kind(r)
        L = pitch_letter(r)
        row = 0 if k == 'ball' else 1
        cx = gx + i * cw + cw / 2
        cy = 2 + row * rh + rh / 2
        if k in ('foul', 'inplay'):
            o.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="5.8" fill="none" stroke="{ink}" stroke-width="1.3"/>')
        elif k == 'swing':
            o.append(f'<rect x="{cx - 5.5:.1f}" y="{cy - 5.5:.1f}" width="11" height="11" fill="none" stroke="{ink}" stroke-width="1.3"/>')
        o.append(f'<text x="{cx:.1f}" y="{cy + 3.4:.1f}" text-anchor="middle" font-size="9.5" font-weight="800" fill="{ink}">{L}</text>')
    # field
    hx, hy, rad = 38, 90, 22
    P = {'h': (hx, hy), 'f': (hx + rad, hy - rad), 's': (hx, hy - 2 * rad), 't': (hx - rad, hy - rad)}
    o.append(f'<path d="M{P["h"][0]} {P["h"][1]} L{P["f"][0]} {P["f"][1]} L{P["s"][0]} {P["s"][1]} L{P["t"][0]} {P["t"][1]} Z" fill="none" stroke="#c9bfae" stroke-width="1.2"/>')
    for k_, (x, y) in P.items():
        o.append(f'<rect x="{x - 3.5}" y="{y - 3.5}" width="7" height="7" fill="#fdfbf6" stroke="#9c917f" stroke-width="1"/>')
    res = pa['result']
    nb = _BASES.get(res, 0)
    order_ = ['h', 'f', 's', 't', 'h']
    if nb == 4:
        o.append(f'<path d="M{P["h"][0]} {P["h"][1]} L{P["f"][0]} {P["f"][1]} L{P["s"][0]} {P["s"][1]} L{P["t"][0]} {P["t"][1]} Z" fill="{ink}"/>')
    elif nb:
        o.append('<path d="M' + ' L'.join(f'{P[k_][0]} {P[k_][1]}' for k_ in order_[:nb + 1]) + f'" fill="none" stroke="{ink}" stroke-width="4" stroke-linecap="square" stroke-linejoin="miter"/>')
    # batted ball path
    last = pa['rows'][-1]
    d_ = e._fnum(last.get('Direction'))
    dist = e._fnum(last.get('Distance'))
    ht = (last.get('TaggedHitType') or last.get('AutoHitType') or '').strip()
    if d_ is not None and last.get('PitchCall') == 'InPlay':
        import math
        Ln = min(58, 16 + (dist or 120) * 0.15)
        ang = math.radians(max(-60, min(60, d_)))
        ex, ey = hx + math.sin(ang) * Ln * 1.15, hy - 6 - math.cos(ang) * Ln
        ey = max(ey, 34)
        if ht == 'GroundBall':
            o.append(f'<path d="M{hx} {hy - 4} L{ex:.1f} {ey:.1f}" stroke="{ink}" stroke-width="1.5" stroke-dasharray="3 2.4" fill="none"/>')
        elif ht == 'LineDrive':
            o.append(f'<path d="M{hx} {hy - 4} L{ex:.1f} {ey:.1f}" stroke="{ink}" stroke-width="1.7" fill="none"/>')
        else:
            mx, my = (hx + ex) / 2, (hy + ey) / 2 - 14
            o.append(f'<path d="M{hx} {hy - 4} Q{mx:.1f} {my:.1f} {ex:.1f} {ey:.1f}" stroke="{ink}" stroke-width="1.7" fill="none"/>')
    # out circle
    o.append(f'<circle cx="96" cy="82" r="9" fill="none" stroke="{ink}" stroke-width="1.3"/>')
    if pa['outs_made']:
        n = min(3, pa['outs'] + pa['outs_made'])
        o.append(f'<text x="96" y="86" text-anchor="middle" font-size="11" font-weight="800" fill="{ink}">{n}</text>')
    # result box
    o.append(f'<rect x="108" y="44" width="38" height="54" fill="{gray}"/>')
    nt = notation(pa)
    if nt:
        fs = 21 if len(nt) <= 2 else 15 if len(nt) == 3 else 11.5
        if res == 'K looking':
            o.append(f'<text x="127" y="77" text-anchor="middle" font-size="22" font-weight="800" fill="{ink}" transform="translate(254 0) scale(-1 1)">K</text>')
        else:
            o.append(f'<text x="127" y="{76 if len(nt) <= 3 else 74}" text-anchor="middle" font-size="{fs}" font-weight="800" fill="{ink}">{html.escape(nt)}</text>')
    note = ''
    if new_pitcher:
        note = new_pitcher.split(',')[0][:9].upper()
    elif pa['runs'] and res not in ('K swinging', 'K looking', 'Out', None):
        note = f"{pa['runs']} RBI"
    if note:
        o.append(f'<text x="127" y="92" text-anchor="middle" font-size="7.5" font-weight="700" fill="#5b4a33">{html.escape(note)}</text>')
    if new_pitcher:
        o.append(f'<line x1="0" y1="33" x2="9" y2="26" stroke="{ink}" stroke-width="1.8"/>')
    if pa.get('grade'):
        gc = {'A': '#2f8a57', 'B': '#4a93a8', 'C': '#d9a028', 'D': '#d9702c', 'F': '#c0443c'}[pa['grade'][0]]
        o.append(f'<rect x="110" y="46" width="20" height="11" rx="3" fill="{gc}"/><text x="120" y="54.6" text-anchor="middle" font-size="8.5" font-weight="800" fill="#fff">{pa["grade"]}</text>')
    if end_inning:
        o.append(f'<line x1="0" y1="{Hh - .8}" x2="{W}" y2="{Hh - .8}" stroke="{ink}" stroke-width="3"/>')
    o.append('</svg>')
    return ''.join(o)


def split_box(top, bottom, w=34, h=26, ink='#2a2118'):
    return (f'<svg viewBox="0 0 {w} {h}" width="{w}" height="{h}" xmlns="http://www.w3.org/2000/svg" style="display:block;font-family:Barlow,Arial,sans-serif">'
            f'<rect x=".5" y=".5" width="{w - 1}" height="{h - 1}" fill="none" stroke="#c9bfae"/><line x1="{w - 1}" y1="1" x2="1" y2="{h - 1}" stroke="#c9bfae"/>'
            f'<text x="4" y="11" font-size="10" font-weight="700" fill="#5b4a33">{top}</text><text x="{w - 4}" y="{h - 4}" text-anchor="end" font-size="11" font-weight="800" fill="{ink}">{bottom}</text></svg>')


def staff_table(m, bat_side):
    """The opposing pitchers who faced this lineup, with the paper-sheet columns: IP H R ER BB K HBP HR, pitch types (strikes / total), B S TP."""
    opp = 'opp' if bat_side == 'us' else 'us'
    out, letters = [], []
    for p in m['pitchers'][opp]:
        by = {}
        for r in p['rows']:
            L = pitch_letter(r)
            d = by.setdefault(L, {'n': 0, 's': 0, 'v': []})
            d['n'] += 1
            d['s'] += 1 if pitch_kind(r) in ('called', 'swing', 'foul') else 0
            v = e._fnum(r.get('RelSpeed'))
            if v:
                d['v'].append(v)
        balls = sum(1 for r in p['rows'] if pitch_kind(r) in ('ball', 'hbp'))
        strikes = sum(1 for r in p['rows'] if pitch_kind(r) in ('called', 'swing', 'foul'))
        for L in by:
            if L not in letters:
                letters.append(L)
        pas = p['pas']
        out.append({'p': p, 'by': by, 'balls': balls, 'strikes': strikes, 'tp': len(p['rows']),
                    'hbp': sum(1 for x in pas if x['result'] == 'HBP'), 'bb': sum(1 for x in pas if x['result'] == 'Walk')})
    letters = [L for L in 'FSCOX?' if L in letters]
    for row in out:
        row['split'] = {L: (split_box(row['by'][L]['s'], row['by'][L]['n'], 40, 26) if L in row['by'] else '') for L in letters}
        row['ranges'] = ' · '.join(f"{L} {int(min(d['v']))}-{int(max(d['v']))}" for L, d in sorted(row['by'].items()) if d['v'])
    return out, letters
