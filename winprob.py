"""Win probability and Win Probability Added (WPA).

1. Win expectancy. A half-inning is played out as a chain of plate appearances (every out / runner state, 24 in all), using our league's
   own odds of a strikeout, walk, hit by pitch, single, double, triple, home run or ball-in-play out (measured from the tagged games in
   the app, all programs pooled, blended with a college prior). That gives the chance of scoring 0, 1, 2 ... more runs from any state.
   Chaining half-innings together gives the home team's chance of winning from any inning, half, outs, runners and score margin,
   with walk-offs, the home team skipping the last bottom half when ahead, and extra innings.
2. WPA. Each plate appearance moves the win chance from where it stood as the at-bat began to where it stood after the play.
   The batter is credited with the change for his team, the pitcher with the opposite. Runners are inferred (gamereport.advance_runners),
   since the tracking files carry no baserunners. Steals, wild pitches and pickoffs land on the at-bat they happened in.

Nothing here is borrowed from MLB tables: every number comes from the college run environment measured in the app.
"""
import functools

import cache

MAX_RUNS = 20               # runs in a half-inning beyond this are lumped into the last bucket
MAX_INN = 25                # extra innings are modelled up to here; a tie beyond counts as a coin flip
MAX_MARGIN = 30
PRIOR_PA = 2000             # the college prior counts as this many plate appearances
PRIOR = {'K': 0.200, 'BB': 0.105, 'HBP': 0.035, '1B': 0.150, '2B': 0.045, '3B': 0.006, 'HR': 0.024, 'ROE': 0.018}
# baserunning on plays the files don't describe (rough college rates)
P_1B_2ND_SCORES = 0.62      # runner on 2nd scores on a single
P_1B_1ST_TO_3RD = 0.28      # runner on 1st goes first to third on a single
P_2B_1ST_SCORES = 0.45      # runner on 1st scores on a double
P_OUT_3RD_SCORES = 0.33     # runner on 3rd scores on a ball-in-play out with fewer than two outs
P_OUT_2ND_TO_3RD = 0.35     # runner on 2nd moves up on a ball-in-play out with fewer than two outs
P_OUT_1ST_TO_2ND = 0.22
P_DP = 0.12                 # ground-ball double play with a runner on 1st and fewer than two outs


# ------------------------------------------------------------------ league event rates
@cache.memo
def rates():
    """{'K','BB','HBP','1B','2B','3B','HR','ROE','OUT'} chances per plate appearance."""
    import runenv
    n = {k: 0 for k in PRIOR}
    out = 0
    try:
        rows = runenv._rows()
    except Exception:
        rows = []
    for _d, r in rows:
        if r.get('SessionType') not in ('Game', 'Scrimmage'):
            continue
        kb, call, pr = r.get('KorBB') or '', r.get('PitchCall') or '', r.get('PlayResult') or ''
        if kb == 'Strikeout':
            n['K'] += 1
        elif kb == 'Walk':
            n['BB'] += 1
        elif call == 'HitByPitch':
            n['HBP'] += 1
        elif call == 'InPlay':
            k = {'Single': '1B', 'Double': '2B', 'Triple': '3B', 'HomeRun': 'HR', 'Error': 'ROE'}.get(pr)
            if k:
                n[k] += 1
            elif pr and pr != 'Undefined':
                out += 1
    tot = sum(n.values()) + out
    p = {k: (n[k] + PRIOR[k] * PRIOR_PA) / (tot + PRIOR_PA) for k in PRIOR}
    p['OUT'] = max(0.0, 1.0 - sum(p.values()))
    return p


# ------------------------------------------------------------------ one half-inning
def _branches(ev, outs, b):
    """[(chance, new bases, runs, outs added)] for event `ev` from `outs` outs and bases bitmask b (1 = 1st, 2 = 2nd, 4 = 3rd)."""
    on1, on2, on3 = bool(b & 1), bool(b & 2), bool(b & 4)
    if ev == 'K':
        return [(1.0, b, 0, 1)]
    if ev in ('BB', 'HBP'):
        if not on1:
            return [(1.0, b | 1, 0, 0)]
        if not on2:
            return [(1.0, b | 3, 0, 0)]
        if not on3:
            return [(1.0, 7, 0, 0)]
        return [(1.0, 7, 1, 0)]
    if ev == 'HR':
        return [(1.0, 0, 1 + on1 + on2 + on3, 0)]
    if ev == '3B':
        return [(1.0, 4, on1 + on2 + on3, 0)]
    if ev == '2B':
        base = on2 + on3
        if on1:
            return [(P_2B_1ST_SCORES, 2, base + 1, 0), (1 - P_2B_1ST_SCORES, 6, base, 0)]
        return [(1.0, 2, base, 0)]
    if ev in ('1B', 'ROE'):
        out = []
        p2 = P_1B_2ND_SCORES if ev == '1B' else 0.5
        for s2, q2 in (((True, p2), (False, 1 - p2)) if on2 else ((False, 1.0),)):
            third_open = not on2 or s2               # runner from 2nd either scored or now holds 3rd
            for go3, q1 in (((True, P_1B_1ST_TO_3RD), (False, 1 - P_1B_1ST_TO_3RD)) if (on1 and third_open) else ((False, 1.0),)):
                runs = on3 + (1 if on2 and s2 else 0)
                nb = 1
                if on2 and not s2:
                    nb |= 4
                if on1:
                    nb |= 4 if go3 else 2
                out.append((q2 * q1, nb, runs, 0))
        return out
    # ball-in-play out
    if outs == 2:
        return [(1.0, b, 0, 1)]
    out = []
    if on1:
        out.append((P_DP, b & ~1, 0, 2))
        rest = 1 - P_DP
    else:
        rest = 1.0
    for s3, q3 in (((True, P_OUT_3RD_SCORES), (False, 1 - P_OUT_3RD_SCORES)) if on3 else ((False, 1.0),)):
        for m2, q2 in (((True, P_OUT_2ND_TO_3RD), (False, 1 - P_OUT_2ND_TO_3RD)) if on2 else ((False, 1.0),)):
            for m1, q1 in (((True, P_OUT_1ST_TO_2ND), (False, 1 - P_OUT_1ST_TO_2ND)) if on1 else ((False, 1.0),)):
                nb, runs = 0, 0
                if on3:
                    if s3:
                        runs += 1
                    else:
                        nb |= 4
                if on2:
                    nb |= 4 if (m2 and not nb & 4) else 2
                if on1:
                    nb |= 2 if (m1 and not nb & 2) else 1
                out.append((rest * q3 * q2 * q1, nb, runs, 1))
    return out


def _rt(p):
    """A rates dict as a hashable, ordered tuple (the key the tables below are cached under)."""
    return tuple(sorted((k, round(v, 6)) for k, v in (p or rates()).items()))


def run_dist(p=None):
    """{(outs, bases): [chance of scoring exactly k more runs this half-inning]} for the event rates `p` (default: rates())."""
    return _run_dist(_rt(p))


@functools.lru_cache(maxsize=16)
def _run_dist(pt):
    p = dict(pt)
    trans = {}
    for outs in range(3):
        for b in range(8):
            t = []
            for ev, pe in p.items():
                if pe <= 0:
                    continue
                for q, nb, r, o in _branches(ev, outs, b):
                    t.append((pe * q, nb, r, outs + o))
            trans[(outs, b)] = t
    done = [1.0] + [0.0] * MAX_RUNS
    g = {}
    for outs in (2, 1, 0):
        for b in range(8):
            g[(outs, b)] = [0.0] * (MAX_RUNS + 1)
        for _ in range(60):                      # same-out moves only add runners, so this settles fast
            for b in range(8):
                v = [0.0] * (MAX_RUNS + 1)
                for pr, nb, r, no in trans[(outs, b)]:
                    src = done if no >= 3 else g[(no, nb)]
                    for k, x in enumerate(src):
                        if x:
                            v[min(k + r, MAX_RUNS)] += pr * x
                g[(outs, b)] = v
    return g


# ------------------------------------------------------------------ the whole game
@functools.lru_cache(maxsize=16)
def _start_table(reg, pt):
    """H[(inning, half, margin)] = home team's win chance at the start of that half (half 0 = top, 1 = bottom, margin = home - away)."""
    g = _run_dist(pt)
    r0 = g[(0, 0)]
    H = {}
    M = range(-MAX_MARGIN, MAX_MARGIN + 1)

    def clamp(m):
        return max(-MAX_MARGIN, min(MAX_MARGIN, m))
    for m in M:
        H[(MAX_INN + 1, 0, m)] = 0.5 if m == 0 else (1.0 if m > 0 else 0.0)
    for inn in range(MAX_INN, 0, -1):
        for m in M:
            H[(inn, 1, m)] = _half_value(r0, inn, 1, m, reg, H, clamp)
        for m in M:
            H[(inn, 0, m)] = _half_value(r0, inn, 0, m, reg, H, clamp)
    return H


def _after_half(inn, half, m, reg, H, clamp):
    """Home win chance the moment half (inn, half) ends with margin m."""
    if half == 0:
        if inn >= reg and m > 0:
            return 1.0                           # home team ahead after the top: the bottom isn't played
        return H[(inn, 1, clamp(m))]
    if inn >= reg and m != 0:
        return 1.0 if m > 0 else 0.0
    return H[(inn + 1, 0, clamp(m))]


def _half_value(dist, inn, half, m, reg, H, clamp):
    if half == 1 and inn >= reg and m > 0:
        return 1.0
    v = 0.0
    for k, x in enumerate(dist):
        if not x:
            continue
        if half == 0:
            v += x * _after_half(inn, 0, m - k, reg, H, clamp)
        elif inn >= reg and m + k > 0:
            v += x                               # walk-off
        else:
            v += x * _after_half(inn, 1, m + k, reg, H, clamp)
    return v


def home_we(inn, half, outs, bases, margin, reg=9, p=None):
    """Home team's win chance with the half (inn, half) in progress: `outs` outs, runners `bases` (bitmask) and margin = home - away.
    `p`: event rates for the level (default: the rates measured from the tracked games)."""
    pt = _rt(p)
    H = _start_table(reg, pt)
    inn = max(1, min(int(inn), MAX_INN))
    margin = max(-MAX_MARGIN, min(MAX_MARGIN, margin))
    if outs >= 3:
        return _after_half(inn, half, margin, reg, H, lambda m: max(-MAX_MARGIN, min(MAX_MARGIN, m)))
    dist = _run_dist(pt)[(max(0, outs), bases)]
    return _half_value(dist, inn, half, margin, reg, H, lambda m: max(-MAX_MARGIN, min(MAX_MARGIN, m)))


def _bits(on):
    on = on or (False, False, False)
    return (1 if on[0] else 0) | (2 if on[1] else 0) | (4 if on[2] else 0)


# ------------------------------------------------------------------ one game
def game(m):
    """Adds pa['wpa'] (change in the batting team's win chance, or None when it can't be measured) and pa['we_us'] (our win chance
    as the at-bat began) to every plate appearance of a built game (gamereport.build), and returns
    {'points': [(we_us, pa or None)], 'reg': innings, 'ok': bool}. The last point is the final."""
    pas = [pa for pa in m['pas'] if pa['result'] is not None]
    if not pas:
        return {'points': [], 'reg': 9, 'ok': False}
    reg = 7 if (m.get('innings') or 9) <= 7 else 9
    home = 'us' if m['us_home'] else 'opp'

    def hm(pa, bat_margin):
        return bat_margin if pa['bat'] == home else -bat_margin

    def state(pa):
        return home_we(pa['inn'], pa['tb'], min(pa['outs'], 2), _bits(pa.get('on_before')), hm(pa, pa['margin']), reg)

    fs = m['score']
    final = 1.0 if fs[home] > fs['opp' if home == 'us' else 'us'] else (0.0 if fs[home] < fs['opp' if home == 'us' else 'us'] else 0.5)
    pts = []
    ok = True
    for i, pa in enumerate(pas):
        before = state(pa)
        nxt = pas[i + 1] if i + 1 < len(pas) else None
        ended = pa['outs'] + pa['outs_made'] >= 3
        after_margin = hm(pa, pa['margin'] + pa['runs'])
        if nxt is None:
            after = final
        elif (nxt['inn'], nxt['tb']) == (pa['inn'], pa['tb']) and not ended:
            after = state(nxt)
        elif ended:
            after = home_we(pa['inn'], pa['tb'], 3, 0, after_margin, reg)
        else:
            after = None                         # pitches are missing between here and the next at-bat
            ok = False
        sign = 1 if pa['bat'] == home else -1
        pa['wpa'] = None if after is None else sign * (after - before)
        pa['we_us'] = before if home == 'us' else 1 - before
        pts.append((pa['we_us'], pa))
    pts.append((final if home == 'us' else 1 - final, None))
    return {'points': pts, 'reg': reg, 'ok': ok}


def players(m):
    """{'us': {'hitters': {name: wpa}, 'pitchers': {(slug or name): wpa}}, 'opp': {...}} for one game, after game(m)."""
    out = {s: {'hitters': {}, 'pitchers': {}} for s in ('us', 'opp')}
    for pa in m['pas']:
        w = pa.get('wpa')
        if w is None:
            continue
        bat, pit = pa['bat'], pa['pit_side']
        out[bat]['hitters'][pa['batter']] = out[bat]['hitters'].get(pa['batter'], 0.0) + w
        pk = pa.get('slug') if pit == 'us' else pa['pitcher']
        out[pit]['pitchers'][pk] = out[pit]['pitchers'].get(pk, 0.0) - w
    return out


CHART_CSS = ('<style>.wpk{position:relative;height:240px;margin:0 12px 0 38px;} .wpk svg{position:absolute;inset:0;width:100%;height:100%;display:block;overflow:visible;}'
             '.wpk .lb{position:absolute;font:600 11px Barlow,sans-serif;color:#8a959c;white-space:nowrap;pointer-events:none;line-height:1;}'
             '.wpk .lb.y{transform:translate(calc(-100% - 8px),-50%);} .wpk .lb.x{transform:translate(3px,0);}'
             '.wpk .lb.t{font:700 11px Barlow,sans-serif;letter-spacing:.08em;text-transform:uppercase;}'
             '.wpk .mk{position:absolute;width:20px;height:20px;margin:-10px 0 0 -10px;border-radius:50%;border:2px solid #fff;color:#fff;'
             'font:700 11px/16px Barlow,sans-serif;text-align:center;box-shadow:0 1px 3px rgba(0,0,0,.2);pointer-events:none;}</style>')


def chart_svg(m, res, names, colors=('#2f6f80', '#b23b2e'), W=1000, Hh=240):
    """Win probability line for our team across the game, with inning marks and the three biggest swings numbered.
    The lines are an SVG stretched to the box; every label and marker is HTML placed by percent, so text never stretches."""
    pts = res['points']
    if len(pts) < 2:
        return ''
    padl, padr, padt, padb = 0, 0, 16, 28                 # the side margins are CSS pixels on .wpk, so the axis labels fit on a phone
    iw, ih = W - padl - padr, Hh - padt - padb
    n = len(pts) - 1

    def X(i):
        return padl + iw * i / n

    def Y(v):
        return padt + ih * (1 - v)

    def at(x, y):
        return f"left:{100 * x / W:.3f}%;top:{100 * y / Hh:.3f}%"
    us_c, opp_c = colors
    esc = lambda t: str(t).replace('&', '&amp;').replace('<', '&lt;')
    line = ' '.join(f"{X(i):.1f},{Y(v):.1f}" for i, (v, _p) in enumerate(pts))
    o = [CHART_CSS, f'<div class="wpk"><svg viewBox="0 0 {W} {Hh}" class="wpc" role="img" aria-label="{esc(names["us"])} win probability through the game" preserveAspectRatio="none">',
         f'<defs><clipPath id="wpa-top"><rect x="0" y="0" width="{W}" height="{Y(0.5):.1f}"/></clipPath><clipPath id="wpa-bot"><rect x="0" y="{Y(0.5):.1f}" width="{W}" height="{Hh}"/></clipPath></defs>']
    lab = []
    for v in (0.25, 0.5, 0.75):
        dash = ' stroke-dasharray="4 4"' if v == 0.5 else ''
        col = '#9aa5ab' if v == 0.5 else '#e4e8ea'
        o.append(f'<line x1="{padl}" x2="{W - padr}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="{col}" stroke-width="1" vector-effect="non-scaling-stroke"{dash}/>')
    for v, t in ((1.0, '100%'), (0.5, '50%'), (0.0, '0%')):
        lab.append(f'<span class="lb y" style="{at(padl, Y(v))}">{t}</span>')
    lab.append(f'<span class="lb t" style="{at(padl + 6, padt + 2)};color:{us_c}">{esc(names["us"])}</span>')
    lab.append(f'<span class="lb t" style="{at(padl + 6, Hh - padb - 16)};color:{opp_c}">{esc(names["opp"])}</span>')
    seen = set()
    for i, (_v, pa) in enumerate(pts):
        if pa is None or pa['inn'] in seen:
            continue
        seen.add(pa['inn'])
        x = X(i)
        o.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{padt}" y2="{Hh - padb}" stroke="#eef1f2" stroke-width="1" vector-effect="non-scaling-stroke"/>')
        lab.append(f'<span class="lb x" style="{at(x, Hh - padb + 8)}">{pa["inn"]}</span>')
    area = f"{X(0):.1f},{Y(0.5):.1f} {line} {X(n):.1f},{Y(0.5):.1f}"
    o.append(f'<polygon points="{area}" fill="{us_c}" fill-opacity=".16" clip-path="url(#wpa-top)"/>')
    o.append(f'<polygon points="{area}" fill="{opp_c}" fill-opacity=".16" clip-path="url(#wpa-bot)"/>')
    o.append(f'<polyline points="{line}" fill="none" stroke="#22303a" stroke-width="2.2" stroke-linejoin="round" vector-effect="non-scaling-stroke"/>')
    big = sorted([i for i, (_v, pa) in enumerate(pts) if pa is not None and pa.get('wpa') is not None], key=lambda i: -abs(pts[i][1]['wpa']))[:3]
    for rank, i in enumerate(sorted(big)):
        pa = pts[i][1]
        x, y = X(i + 1), Y(pts[i + 1][0])
        pa['swing_no'] = rank + 1
        good = (pa['wpa'] > 0) == (pa['bat'] == 'us')
        lab.append(f'<span class="mk" style="{at(x, y)};background:{us_c if good else opp_c}">{rank + 1}</span>')
    o.append('</svg>')
    o.extend(lab)
    o.append('</div>')
    return ''.join(o)


# ------------------------------------------------------------------ a season
@cache.memo
def season_table(program, win):
    """{'p': {pitcher slug: {'wpa','g'}}, 'h': {hitter key: {'wpa','g','pa'}}, 'year'} over the spring games inside `win`,
    the same games WAR uses."""
    import gamereport as gr
    import hitting
    import store
    import war
    lo, hi, yr = war.spring_window(win)
    demo = program in store.DEMO_PROGRAMS
    keys = {}
    for k, h in hitting._collect(True).items():
        if h['program'] == program and h['demo'] == demo:
            keys.setdefault(h['name'], k)
    P, Hh = {}, {}
    n = 0
    for gid, gm in gr.collect(program).items():
        if not (lo <= gm['date'] < hi):
            continue
        m = gr.build(gm['rows'])
        game(m)
        n += 1
        for pa in m['pas']:
            w = pa.get('wpa')
            if w is None:
                continue
            if pa['bat'] == 'us':
                k = keys.get(pa['batter'])
                if k:
                    v = Hh.setdefault(k, {'wpa': 0.0, 'g': set(), 'pa': 0})
                    v['wpa'] += w
                    v['g'].add(gid)
                    v['pa'] += 1
            elif pa.get('slug'):
                v = P.setdefault(pa['slug'], {'wpa': 0.0, 'g': set(), 'bf': 0})
                v['wpa'] -= w
                v['g'].add(gid)
                v['bf'] += 1
    for D in (P, Hh):
        for v in D.values():
            v['g'] = len(v['g'])
    return {'p': P, 'h': Hh, 'year': yr, 'games': n}


def for_program(program):
    import season
    return season_table(program, tuple(season.window(program) or (None, None)))


def fmt(v):
    return f"{v:+.2f}" if v is not None else '–'
