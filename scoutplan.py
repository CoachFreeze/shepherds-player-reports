"""Scouting reports for opposing players: what a hitter does and how to pitch / defend him, what a pitcher does and how to attack him.
Everything is derived from the tracked pitches we have, so every statement carries its sample size and small samples say so."""
import hitting as H
import pitchfx

SW = H.SWING
_THIRD = (H.ZT - H.ZB) / 3.0
COLS = ('away_out', 'away', 'mid', 'in', 'in_out')


def _ix(p):
    """Horizontal location from the hitter's side: positive = inside (toward him). None if his side is unknown."""
    x, s = p.get('x'), p.get('side')
    if x is None or s not in ('L', 'R'):
        return None
    return -x if s == 'R' else x


def _col(v):
    return 0 if v < -H.ZX else 1 if v < -0.28 else 2 if v <= 0.28 else 3 if v <= H.ZX else 4


def _row(z):
    return 0 if z > H.ZT else 1 if z > H.ZT - _THIRD else 2 if z > H.ZB + _THIRD else 3 if z >= H.ZB else 4


def _cell(p):
    v, z = _ix(p), p.get('z')
    if v is None or z is None:
        return None
    return _row(z), _col(v)


def _coarse(rc):
    r, c = rc
    return (0 if r <= 1 else 1 if r == 2 else 2), (0 if c <= 1 else 1 if c == 2 else 2)


_WORDS = {(0, 0): 'up and away', (0, 1): 'up', (0, 2): 'up and in', (1, 0): 'away', (1, 1): 'the middle', (1, 2): 'in',
          (2, 0): 'down and away', (2, 1): 'down', (2, 2): 'down and in'}


def words(cr):
    return _WORDS[cr]


def _pct(a, b):
    return 100.0 * a / b if b else None


def _f1(v):
    return f'{v:.0f}%' if v is not None else '—'


def _summ(ps):
    """Counts for any set of normalized pitches."""
    sw = [p for p in ps if p['outcome'] in SW]
    wh = [p for p in sw if p['outcome'] == 'whiff']
    bip = [p for p in ps if p['outcome'] == 'inplay' and p.get('ev') is not None]
    evs = [p['ev'] for p in bip]
    j = [(p, H.judge(p)) for p in ps]
    j = [(p, x) for p, x in j if x]
    out = [(p, x) for p, x in j if x[0] in ('chase', 'waste')]
    return {'n': len(ps), 'sw': len(sw), 'wh': len(wh), 'bip': len(bip), 'ev': (sum(evs) / len(evs)) if evs else None,
            'swing': _pct(len(sw), len(ps)), 'whiff': _pct(len(wh), len(sw)),
            'chase': _pct(sum(1 for _, x in out if x[1]), len(out)), 'n_out': len(out),
            'hard': _pct(sum(1 for v in evs if v >= 95), len(evs)), 'xba': H.xba(ps)}


# ------------------------------------------------------------------ hitters
def zone_cells(ps):
    """5 x 5 grid (rows high-off ... low-off, columns away-off ... in-off, from the hitter's side), each with the counts for that spot."""
    grid = [[[] for _ in range(5)] for _ in range(5)]
    for p in ps:
        rc = _cell(p)
        if rc:
            grid[rc[0]][rc[1]].append(p)
    return [[dict(_summ(c), r=r, c=cc) for cc, c in enumerate(row)] for r, row in enumerate(grid)]


def _coarse_stats(ps, only_out=False):
    g = {}
    for p in ps:
        rc = _cell(p)
        if not rc:
            continue
        if only_out and H.region(p['x'], p['z']) not in ('chase', 'waste'):
            continue
        g.setdefault(_coarse(rc), []).append(p)
    return {k: _summ(v) for k, v in g.items()}


def type_table(ps):
    groups = {}
    for p in ps:
        groups.setdefault(p.get('label') or p.get('pitch_type') or 'Unknown', []).append(p)
    rows = []
    for t, g in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        s = _summ(g)
        rows.append({'type': t, **s, 'xba_v': s['xba']['xba'] if s['xba']['ab'] >= 3 else None})
    return rows


def count_table(ps):
    def bucket(p):
        cc = H.count_ctx(p)
        if cc is None:
            return None
        b, s = cc
        return ('First pitch (0-0)' if (b, s) == (0, 0) else 'Two strikes' if s == 2 else "Hitter's counts" if b > s else 'Even counts')
    groups = {}
    for p in ps:
        k = bucket(p)
        if k:
            groups.setdefault(k, []).append(p)
    order = ['First pitch (0-0)', "Hitter's counts", 'Even counts', 'Two strikes']
    return [{'label': k, **_summ(groups[k])} for k in order if k in groups]


def spray_summary(ps):
    z = [H.spray_zone(p) for p in ps if p['outcome'] == 'inplay' and p.get('direction') is not None]
    z = [x for x in z if x]
    ht = [p['hit_type'] for p in ps if p['outcome'] == 'inplay' and p.get('hit_type') and p['hit_type'] != 'BUNT']
    n = len(z)
    return {'n': n, 'pull': _pct(z.count('pull'), n), 'center': _pct(z.count('center'), n), 'oppo': _pct(z.count('oppo'), n),
            'n_type': len(ht), 'gb': _pct(ht.count('GB'), len(ht)), 'ld': _pct(ht.count('LD'), len(ht)),
            'fb': _pct(ht.count('FB') + ht.count('PU'), len(ht))}


def hitter_report(ps, bats=None):
    """ps: normalized pitches this hitter saw. Returns everything the hitter scouting page shows."""
    n = len(ps)
    all_ = _summ(ps)
    s = H.hitter_stats(ps)
    types = type_table(ps)
    counts = count_table(ps)
    spray = spray_summary(ps)
    cells = zone_cells(ps)
    coarse = _coarse_stats(ps)
    coarse_out = _coarse_stats(ps, only_out=True)
    go, stop, info = [], [], []

    # swing and miss: pitch type
    cand = [t for t in types if t['sw'] >= 4 and t['whiff'] is not None]
    if cand:
        best = max(cand, key=lambda t: t['whiff'])
        if best['whiff'] >= 25:
            go.append(('Swing-and-miss pitch', f"{best['type']}: he misses {_f1(best['whiff'])} of his swings ({best['wh']} of {best['sw']})."))
    # chase
    chase_spots = [(k, v) for k, v in coarse_out.items() if v['n'] >= 4 and v['swing'] is not None and v['swing'] >= 40]
    if chase_spots:
        k, v = max(chase_spots, key=lambda kv: kv[1]['swing'])
        go.append(('Where he expands', f"He swings at {_f1(v['swing'])} of the pitches he sees {words(k)} off the zone ({v['n']} seen). Finish him there."))
    elif s.get('chase_pct') is not None and s['chases'] >= 2 and s['chase_pct'] <= 18:
        info.append(('Disciplined', f"Only {s['chase_pct']}% chase outside the zone. Don't expect him to expand, so you have to win in the zone."))
    ctype = [t for t in types if t['n_out'] >= 6 and t['chase'] is not None]
    if ctype:
        t = max(ctype, key=lambda t: t['chase'])
        if t['chase'] >= 35:
            go.append(('Chases', f"{t['type']} off the plate: he goes after {_f1(t['chase'])} of them ({t['n_out']} seen)."))
    # weak contact
    weak = [(k, v) for k, v in coarse.items() if v['bip'] >= 2 and v['ev'] is not None]
    if weak:
        k, v = min(weak, key=lambda kv: kv[1]['ev'])
        if v['ev'] < 85:
            go.append(('Weak contact', f"Balls he hits {words(k)} average just {v['ev']:.0f} mph ({v['bip']} in play)."))
        k, v = max(weak, key=lambda kv: kv[1]['ev'])
        if v['ev'] >= 90:
            stop.append(('Danger zone', f"{words(k).capitalize()}: he's hitting those {v['ev']:.0f} mph ({v['bip']} in play). Keep it out of there."))
    tweak = [t for t in types if t['bip'] >= 3 and t['ev'] is not None]
    if tweak:
        t = max(tweak, key=lambda t: t['ev'])
        if t['ev'] >= 88:
            stop.append(('Hits hard', f"{t['type']}: {t['ev']:.0f} mph average exit velocity ({t['bip']} in play)" + (f", {t['hard']:.0f}% hit 95+." if t['hard'] is not None else '.')))
        t = min(tweak, key=lambda t: t['ev'])
        if t['ev'] <= 82 and t is not max(tweak, key=lambda t: t['ev']):
            go.append(('Soft contact', f"{t['type']}: only {t['ev']:.0f} mph when he puts it in play ({t['bip']} in play)."))
    # zone damage on swings in heart
    if s.get('zone_contact_pct') is not None and s['zone_contact_pct'] < 75 and s.get('decisions', 0) >= 15:
        go.append(('Beatable in the zone', f"Only {s['zone_contact_pct']}% contact on swings at strikes. Attack the zone with your best stuff."))
    # counts
    ct = {c['label']: c for c in counts}
    fp = ct.get('First pitch (0-0)')
    if fp and fp['n'] >= 6 and fp['swing'] is not None:
        if fp['swing'] >= 45:
            go.append(('First pitch', f"Swings at {_f1(fp['swing'])} of first pitches ({fp['n']} seen). Start him off-speed or just off the plate."))
        elif fp['swing'] <= 15:
            go.append(('First pitch', f"Takes {100 - fp['swing']:.0f}% of first pitches ({fp['n']} seen). Steal a strike."))
    ts = ct.get('Two strikes')
    if ts and ts['n'] >= 6:
        bits = []
        if ts['whiff'] is not None and ts['sw'] >= 3 and ts['whiff'] >= 20:
            bits.append(f"misses {_f1(ts['whiff'])} of his swings")
        if ts['chase'] is not None and ts['n_out'] >= 4 and ts['chase'] >= 25:
            bits.append(f"chases {_f1(ts['chase'])} out of the zone")
        if bits:
            go.append(('Two strikes', 'With two strikes he ' + ' and '.join(bits) + f" ({ts['n']} pitches)."))
    # velocity / breaking
    spl = {x['label']: x for x in s['splits']}
    sf, sb = spl.get('Vs fastballs'), spl.get('Vs breaking / off-speed')
    hard = [p for p in ps if H.pitch_class(p) == 'hard']
    soft = [p for p in ps if H.pitch_class(p) == 'soft']
    sh, so = _summ(hard), _summ(soft)
    if so['sw'] >= 5 and sh['sw'] >= 5 and so['whiff'] is not None and sh['whiff'] is not None:
        if so['whiff'] - sh['whiff'] >= 12:
            go.append(('Breaking balls', f"Misses {_f1(so['whiff'])} against breaking / off-speed vs {_f1(sh['whiff'])} against fastballs."))
        elif sh['whiff'] - so['whiff'] >= 12:
            go.append(('Velocity', f"Misses {_f1(sh['whiff'])} against fastballs vs {_f1(so['whiff'])} against breaking / off-speed. He's late on velocity; challenge him up."))
    # platoon
    lh = [p for p in ps if p.get('p_throws') == 'L']
    rh = [p for p in ps if p.get('p_throws') == 'R']
    if len(lh) >= 12 and len(rh) >= 12:
        a, b = _summ(lh), _summ(rh)
        if a['whiff'] is not None and b['whiff'] is not None and abs(a['whiff'] - b['whiff']) >= 12:
            w, l_ = ('lefties', 'righties') if a['whiff'] > b['whiff'] else ('righties', 'lefties')
            info.append(('Platoon', f"Swings and misses more against {w} ({_f1(max(a['whiff'], b['whiff']))}) than {l_} ({_f1(min(a['whiff'], b['whiff']))})."))
    # defense
    defend = []
    if spray['n'] >= 6:
        side_word = {'R': 'left', 'L': 'right'}.get(bats, 'pull')
        if spray['pull'] is not None and spray['pull'] >= 50:
            defend.append(('Pull-heavy', f"{_f1(spray['pull'])} of his tracked balls in play go to the pull side ({spray['n']}). Shade the infield and outfield toward {side_word if bats in ('R', 'L') else 'the pull side'}."))
        elif spray['oppo'] is not None and spray['oppo'] >= 35:
            defend.append(('Uses the whole field', f"{_f1(spray['oppo'])} go the other way ({spray['n']}). Don't overshift."))
        elif spray['pull'] is not None:
            defend.append(('Spray', f"{_f1(spray['pull'])} pull, {_f1(spray['center'])} center, {_f1(spray['oppo'])} oppo ({spray['n']} tracked)."))
    if spray['n_type'] >= 6:
        if spray['gb'] is not None and spray['gb'] >= 50:
            defend.append(('Ground-ball hitter', f"{_f1(spray['gb'])} of his balls in play are on the ground. Infield in the right spots, turn two."))
        elif spray['fb'] is not None and spray['fb'] >= 40:
            defend.append(('Fly-ball hitter', f"{_f1(spray['fb'])} of his balls in play are in the air. Outfield plays a step deeper."))
    if s.get('hard_hit_pct') is not None and s['bip'] >= 5 and s['hard_hit_pct'] >= 35:
        defend.append(('Hits it hard', f"{s['hard_hit_pct']}% of balls in play are 95+ mph (max {s['max_ev']}). Keep the infield honest."))
    return {'n': n, 'stats': s, 'all': all_, 'types': types, 'counts': counts, 'spray': spray, 'cells': cells,
            'go': go, 'stop': stop, 'info': info, 'defend': defend, 'small': n < 40}


def zone_map_svg(cells, bats=None, uid='zm'):
    """Catcher's-view 5x5 map (inner 3x3 = the strike zone). Three metrics, switched in the page: swing %, miss %, exit velocity."""
    flip = bats == 'R'          # a right-handed hitter stands on the catcher's left, so 'inside' is drawn on the left
    cs = 64
    L, T = 18, 8
    W, Hh = L + 5 * cs + 8, T + 5 * cs + 34
    mx = max((c['n'] for row in cells for c in row), default=1) or 1

    def col_for(v, metric):
        if v is None:
            return '#f4f6f6'
        if metric == 'seen':
            t = min(1.0, v / mx)
            return f'rgb({round(244 - 110 * t)},{round(247 - 70 * t)},{round(249 - 40 * t)})'
        if metric == 'swing':
            t = max(0.0, min(1.0, v / 100))
            return f'rgb({round(244 - 120 * t)},{round(247 - 80 * t)},{round(249 - 20 * t)})'
        if metric == 'miss':      # more misses = better for the pitcher = green
            t = max(0.0, min(1.0, v / 60))
            return f'rgb({round(244 - 150 * t)},{round(247 - 40 * t)},{round(249 - 120 * t)})'
        t = max(0.0, min(1.0, (v - 70) / 30))      # exit velocity: soft = green, hard = red
        return f'rgb({round(150 + 80 * t)},{round(215 - 130 * t)},{round(160 - 90 * t)})'

    o = [f'<svg id="{uid}" viewBox="0 0 {W} {Hh}" xmlns="http://www.w3.org/2000/svg" style="width:100%;max-width:420px;height:auto;display:block;margin:0 auto;" font-family="Barlow,Arial,sans-serif">']
    for metric in ('seen', 'swing', 'miss', 'ev'):
        o.append(f'<g class="{uid}-l" data-m="{metric}"' + ('' if metric == 'swing' else ' style="display:none"') + '>')
        for r in range(5):
            for c in range(5):
                cell = cells[r][c]
                dc = 4 - c if flip else c
                x, y = L + dc * cs, T + r * cs
                if metric == 'seen':
                    v, txt = (cell['n'] if cell['n'] else None), (str(cell['n']) if cell['n'] else '')
                elif metric == 'swing':
                    ok = cell['n'] >= 3
                    v, txt = (cell['swing'] if ok else None), (f"{cell['swing']:.0f}%" if ok else '')
                elif metric == 'miss':
                    ok = cell['sw'] >= 3
                    v, txt = (cell['whiff'] if ok else None), (f"{cell['whiff']:.0f}%" if ok else '')
                else:
                    ok = cell['bip'] >= 2 and cell['ev'] is not None
                    v, txt = (cell['ev'] if ok else None), (f"{cell['ev']:.0f}" if ok else '')
                o.append(f'<rect x="{x}" y="{y}" width="{cs}" height="{cs}" fill="{col_for(v, metric)}" stroke="#fff" stroke-width="2"/>')
                if txt:
                    o.append(f'<text x="{x + cs / 2}" y="{y + cs / 2 + 5}" text-anchor="middle" font-size="15" font-weight="700" fill="#22303a">{txt}</text>')
        o.append('</g>')
    o.append(f'<rect x="{L + cs}" y="{T + cs}" width="{3 * cs}" height="{3 * cs}" fill="none" stroke="#22303a" stroke-width="2.5"/>')
    inside_x, away_x = (L + 2, L + 5 * cs - 2) if flip else (L + 5 * cs - 2, L + 2)
    ly = T + 5 * cs + 20
    o.append(f'<text x="{away_x}" y="{ly}" text-anchor="{"end" if flip else "start"}" font-size="12" fill="#6b7680">Away</text>')
    o.append(f'<text x="{inside_x}" y="{ly}" text-anchor="{"start" if flip else "end"}" font-size="12" fill="#6b7680">Inside</text>')
    o.append('</svg>')
    return ''.join(o)


# ------------------------------------------------------------------ pitchers
def prep_pitcher(rows):
    """Rows -> normalized pitches with a pitch-type label (same names as the rest of the app)."""
    out = []
    for r in rows:
        ps = H.normalize([r])
        if not ps:
            continue
        p = ps[0]
        p['label'] = pitchfx._label(r) or p.get('pitch_type') or 'Unknown'
        out.append(p)
    return out


def _is_fb(t):
    return any(k in t.lower() for k in ('seam', 'sinker', 'cutter', 'fastball'))


def _mix(ps, order):
    n = len(ps)
    return {t: _pct(sum(1 for p in ps if p['label'] == t), n) for t in order}, n


def pitcher_report(ps):
    n = len(ps)
    types = type_table([dict(p) for p in ps])
    order = [t['type'] for t in types]
    for t in types:
        t['usage'] = _pct(t['n'], n)
        zone = [p for p in ps if p['label'] == t['type'] and p.get('x') is not None and p.get('z') is not None]
        t['zone'] = _pct(sum(1 for p in zone if H.region(p['x'], p['z']) in ('heart', 'shadow') and abs(p['x']) <= H.ZX and H.ZB <= p['z'] <= H.ZT), len(zone))
    # mix by count
    def cc(p):
        return H.count_ctx(p)
    states = [('First pitch (0-0)', lambda b, s: (b, s) == (0, 0)), ('Pitcher ahead', lambda b, s: s > b),
              ('Even counts', lambda b, s: b == s and (b, s) != (0, 0)), ("Hitter ahead", lambda b, s: b > s), ('Two strikes', lambda b, s: s == 2)]
    mixes = []
    for lab, f in states:
        sub = [p for p in ps if cc(p) and f(*cc(p))]
        if sub:
            m, k = _mix(sub, order)
            mixes.append({'label': lab, 'n': k, 'mix': m})
    by_side = {}
    for side in ('R', 'L'):
        sub = [p for p in ps if p.get('side') == side]
        if sub:
            by_side[side] = _mix(sub, order)
    # first pitch strike %
    fp = [p for p in ps if cc(p) == (0, 0)]
    fps = _pct(sum(1 for p in fp if p['outcome'] not in ('ball', 'hbp', 'unk')), len([p for p in fp if p['outcome'] != 'unk']))
    allz = [p for p in ps if p.get('x') is not None and p.get('z') is not None]
    zone_pct = _pct(sum(1 for p in allz if abs(p['x']) <= H.ZX and H.ZB <= p['z'] <= H.ZT), len(allz))
    tot = _summ(ps)
    go, stop, info = [], [], []
    mm = {m['label']: m for m in mixes}
    # first pitch
    m0 = mm.get('First pitch (0-0)')
    if m0 and m0['n'] >= 8:
        fbs = sum(v or 0 for t, v in m0['mix'].items() if _is_fb(t))
        top = max(m0['mix'], key=lambda t: m0['mix'][t] or 0)
        if fbs >= 70:
            go.append(('First pitch', f"Fastball on {fbs:.0f}% of first pitches ({m0['n']} seen). Be ready to hit it early."))
        elif not _is_fb(top) and (m0['mix'][top] or 0) >= 35:
            go.append(('First pitch', f"Opens with his {top} {m0['mix'][top]:.0f}% of the time ({m0['n']} seen), so don't sit fastball on 0-0."))
    if fps is not None and len(fp) >= 8:
        if fps < 55:
            go.append(('Falls behind', f"First-pitch strike only {fps:.0f}% ({len(fp)} seen). Be patient and make him throw a strike."))
        elif fps >= 68:
            stop.append(('Gets ahead', f"First-pitch strike {fps:.0f}%. Be ready to swing early or you'll be in an 0-1 hole."))
    mh = mm.get('Hitter ahead')
    if mh and mh['n'] >= 8:
        top = max(mh['mix'], key=lambda t: mh['mix'][t] or 0)
        if (mh['mix'][top] or 0) >= 65:
            go.append(("When he's behind", f"{top} {mh['mix'][top]:.0f}% of the time in hitter's counts ({mh['n']}). Hunt it in 2-0, 3-1 and 2-1."))
    m2 = mm.get('Two strikes')
    if m2 and m2['n'] >= 8:
        top = max(m2['mix'], key=lambda t: m2['mix'][t] or 0)
        g = [t for t in types if t['type'] == top][0]
        extra = f" and it gets a {_f1(g['whiff'])} miss rate" if g['whiff'] is not None and g['sw'] >= 4 and g['whiff'] >= 15 else ''
        go.append(('Put-away pitch', f"With two strikes he goes to the {top} {m2['mix'][top]:.0f}% of the time ({m2['n']}){extra}. Shorten up and look for it."))
    # location of the put-away pitch
    if m2:
        top = max(m2['mix'], key=lambda t: m2['mix'][t] or 0)
        locs = {}
        for p in ps:
            c_ = cc(p)
            if c_ and c_[1] == 2 and p['label'] == top:
                rc = _cell(p)
                if rc:
                    locs.setdefault(_coarse(rc), []).append(p)
        if locs:
            k = max(locs, key=lambda k: len(locs[k]))
            if len(locs[k]) >= 4:
                info.append(('Where it ends up', f"His two-strike {top} most often finishes {words(k)} (from the hitter's side)."))
    # lay off / hunt
    for t in types:
        if t['n_out'] >= 8 and t['chase'] is not None and t['chase'] >= 30 and t['whiff'] is not None and t['whiff'] >= 30 and t['sw'] >= 4:
            stop.append(('Lay off', f"His {t['type']}: hitters chase it {_f1(t['chase'])} and miss {_f1(t['whiff'])} of their swings. Recognize it early."))
    good = [t for t in types if t['bip'] >= 3 and t['ev'] is not None and (t['whiff'] is None or t['sw'] < 4 or t['whiff'] < 20)]
    if good:
        t = max(good, key=lambda t: t['ev'])
        if t['ev'] >= 85:
            go.append(('Hit this one', f"His {t['type']}: hitters average {t['ev']:.0f} mph when they put it in play ({t['bip']}) and miss only {_f1(t['whiff'])}."))
    if zone_pct is not None and len(allz) >= 30:
        if zone_pct >= 55:
            info.append(('Strike thrower', f"{zone_pct:.0f}% of his pitches are in the zone. Be aggressive early; he won't walk you."))
        elif zone_pct <= 42:
            info.append(('Struggles to find the zone', f"Only {zone_pct:.0f}% in the zone. Take pitches and make him prove he can throw strikes."))
    # platoon usage
    if 'R' in by_side and 'L' in by_side and by_side['R'][1] >= 15 and by_side['L'][1] >= 15:
        best = max(order, key=lambda t: abs((by_side['L'][0].get(t) or 0) - (by_side['R'][0].get(t) or 0)))
        a, b = by_side['L'][0].get(best) or 0, by_side['R'][0].get(best) or 0
        if abs(a - b) >= 12:
            info.append(('Against lefties vs righties', f"His {best} is {a:.0f}% of pitches to lefties but {b:.0f}% to righties."))
    # mistakes: where hitters hit it hardest
    coarse = _coarse_stats(ps)
    weak = [(k, v) for k, v in coarse.items() if v['bip'] >= 3 and v['ev'] is not None]
    if weak:
        k, v = max(weak, key=lambda kv: kv[1]['ev'])
        if v['ev'] >= 88:
            go.append(('Where he gets hurt', f"Balls hit {words(k)} average {v['ev']:.0f} mph ({v['bip']} in play). That's his mistake spot."))
    return {'n': n, 'types': types, 'mixes': mixes, 'order': order, 'fps': fps, 'zone_pct': zone_pct, 'go': go, 'stop': stop, 'info': info, 'small': n < 40,
            'whiff': tot['whiff'], 'chase': tot['chase']}
