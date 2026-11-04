"""Home plate umpire reports (staff only). Grades every taken pitch (a called ball or called strike) against the rule-book zone using Trackman's plate
location, keeps the umpire's name on the game's pitches, and rolls the games up per umpire so a coach can see if he is historically pitcher or hitter friendly.

The zone is fixed (no batter height in the data): 17 in. plate, 1.5 to 3.5 ft high, widened by the ball's radius so a pitch that touches it is a strike.
Calls within an inch of the edge are never counted as misses. Trackman location is good to about an inch, so those are coin flips."""
import re

import gamereport as gr
import outings as outings_mod

HALF = 17 / 24 + 0.121          # ft from the middle of the plate to the edge a ball can touch
BOT, TOP = 1.5 - 0.121, 3.5 + 0.121
MARGIN = 1 / 12                 # ft; calls this close to the edge are not counted as misses
MIN_GAMES, MIN_CALLS, LEAN = 2, 150, 1.5     # needed before a lean is stated; net extra strikes per 100 calls that counts as a lean


def clean(name):
    return re.sub(r'\s+', ' ', (name or '').strip())[:60]


def key(name):
    return re.sub(r'[^a-z0-9]+', ' ', clean(name).lower()).strip()


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def grade(items):
    """items = game rows ([{'r','pit'}]). Returns counts and the plotted calls. Verdicts: ok, border (too close to call, counted correct), ms = strike called that
    was a ball, mb = ball called that was a strike."""
    calls, c = [], {'calls': 0, 'cs': 0, 'ms': 0, 'mb': 0, 'us_for': 0, 'us_against': 0}
    for it in items:
        r = it['r']
        pc = (r.get('PitchCall') or '').strip()
        if pc not in ('StrikeCalled', 'BallCalled'):
            continue
        if (r.get('PitchLocationConfidence') or 'High').strip().lower() == 'low':
            continue
        x, z = _f(r.get('PlateLocSide')), _f(r.get('PlateLocHeight'))
        if x is None or z is None:
            continue
        d = max(abs(x) - HALF, BOT - z, z - TOP)        # > 0 outside the zone, < 0 inside
        strike = pc == 'StrikeCalled'
        v = 'ok'
        if strike and d > MARGIN:
            v = 'ms'
        elif not strike and d < -MARGIN:
            v = 'mb'
        elif abs(d) <= MARGIN:
            v = 'border'
        c['calls'] += 1
        c['cs'] += strike
        if v in ('ms', 'mb'):
            c[v] += 1
            pitching = it.get('pit') == 'us'             # a missed ball hurts the pitching team, a missed strike the batting team
            hurts_us = (v == 'mb') == pitching
            c['us_against' if hurts_us else 'us_for'] += 1
        calls.append({'x': -x, 'z': z, 'strike': strike, 'v': v, 'pitcher': r.get('Pitcher') or '', 'batter': r.get('Batter') or '',
                      'count': f"{r.get('Balls') or 0}-{r.get('Strikes') or 0}", 'inn': r.get('Inning') or ''})
    c['miss'] = c['ms'] + c['mb']
    c['acc'] = (c['calls'] - c['miss']) / c['calls'] * 100 if c['calls'] else None
    c['net100'] = (c['ms'] - c['mb']) / c['calls'] * 100 if c['calls'] else None      # > 0: more extra strikes than extra balls
    return c, calls


def lean(games, calls, net100):
    if games < MIN_GAMES or calls < MIN_CALLS or net100 is None:
        return 'Not enough games yet', 'early'
    if net100 >= LEAN:
        return 'Leans pitcher friendly', 'pit'
    if net100 <= -LEAN:
        return 'Leans hitter friendly', 'hit'
    return 'Calls it evenly', 'even'


def game_umpire(items):
    for it in items:
        n = clean(it['r'].get('Umpire'))
        if n:
            return n
    return ''


def set_umpire(program, gid, name):
    """Stamps (or clears, with an empty name) the umpire on every stored pitch of one game. Returns the number of pitches changed, or None for an unknown game."""
    gm = gr.collect(program).get(gid)
    if not gm:
        return None
    name = clean(name)
    date = gm['date']
    uids = {(x['slug'], x['r'].get('PitchUID') or '', x['r'].get('PitchNo')) for x in gm['rows']}
    n = 0
    for slug, _side, data in gr._our_files(program):
        hit = 0
        for o in data.get('outings', []):
            if o['date'][:10] != date:
                continue
            for r in o['rows']:
                if (slug, r.get('PitchUID') or '', r.get('PitchNo')) in uids:
                    if name:
                        r['Umpire'] = name
                    else:
                        r.pop('Umpire', None)
                    hit += 1
        if hit:
            outings_mod._save(slug, data)
            n += hit
    return n


def ledger(program):
    """{'umps': [{'name','games':[...],'calls','miss','acc','ms','mb','net100','lean','tone'}], 'none': [games without a name]}. Newest games first."""
    by, none = {}, []
    for gid, gm in sorted(gr.collect(program).items(), key=lambda kv: kv[1]['date'], reverse=True):
        c, _calls = grade(gm['rows'])
        if not c['calls']:
            continue
        g = {'gid': gid, 'date': gm['date'], 'opp': gm['opp'], **c}
        nm = game_umpire(gm['rows'])
        if not nm:
            none.append(g)
            continue
        u = by.setdefault(key(nm), {'name': nm, 'games': []})
        u['games'].append(g)
    umps = []
    for u in by.values():
        gs = u['games']
        t = {k: sum(g[k] for g in gs) for k in ('calls', 'ms', 'mb')}
        t['miss'] = t['ms'] + t['mb']
        t['acc'] = (t['calls'] - t['miss']) / t['calls'] * 100
        t['net100'] = (t['ms'] - t['mb']) / t['calls'] * 100
        t['lean'], t['tone'] = lean(len(gs), t['calls'], t['net100'])
        umps.append({**u, **t})
    umps.sort(key=lambda u: (-len(u['games']), u['name'].lower()))
    return {'umps': umps, 'none': none}


def names(program):
    return sorted({clean(x['r'].get('Umpire')) for gm in gr.collect(program).values() for x in gm['rows'] if clean(x['r'].get('Umpire'))}, key=str.lower)


def zone_svg(calls, w=360):
    """Catcher's view of the plate: Trackman's PlateLocSide is positive toward the right-handed hitter, so x is flipped (checked against hit-by-pitches) and the RHH side draws on the left. Light dots are correct calls; red = strike called outside the zone, blue = ball called inside it."""
    X0, X1, Z0, Z1 = -1.75, 1.75, 0.0, 4.4
    h = round(w * (Z1 - Z0) / (X1 - X0))
    sx, sz = w / (X1 - X0), h / (Z1 - Z0)
    px = lambda x: (x - X0) * sx
    pz = lambda z: h - (z - Z0) * sz
    s = [f'<svg viewBox="0 0 {w} {h}" width="100%" style="max-width:{w}px;display:block;" role="img" aria-label="Called pitches against the strike zone">',
         f'<rect x="{px(-HALF):.1f}" y="{pz(TOP):.1f}" width="{(2 * HALF) * sx:.1f}" height="{(TOP - BOT) * sz:.1f}" fill="none" stroke="#9aa3aa" stroke-width="1" stroke-dasharray="4 3"/>',
         f'<rect x="{px(-17 / 24):.1f}" y="{pz(3.5):.1f}" width="{(17 / 12) * sx:.1f}" height="{2 * sz:.1f}" fill="#f7f6f2" fill-opacity=".6" stroke="#22303a" stroke-width="1.6"/>',
         f'<path d="M{px(-17 / 24):.1f} {pz(0.8):.1f}L{px(17 / 24):.1f} {pz(0.8):.1f}L{px(17 / 24):.1f} {pz(0.5):.1f}L{px(0):.1f} {pz(0.15):.1f}L{px(-17 / 24):.1f} {pz(0.5):.1f}Z" fill="#fff" stroke="#22303a" stroke-width="1.6" stroke-linejoin="round"/>']
    for order in ('ok', 'border', 'ms', 'mb'):
        for c in calls:
            if c['v'] != order:
                continue
            col, rad, op = {'ok': ('#aab4ba', 3, .55), 'border': ('#aab4ba', 3, .55), 'ms': ('#c0392b', 6, .95), 'mb': ('#2a6fb0', 6, .95)}[order]
            what = ('Strike called' if c['strike'] else 'Ball called') + {'ms': ', outside the zone', 'mb': ', inside the zone'}.get(order, '')
            who = ' &middot; '.join(x for x in (f"{c['pitcher']} to {c['batter']}" if c['pitcher'] or c['batter'] else '', f"{c['count']} count") if x)
            s.append(f'<circle cx="{px(c["x"]):.1f}" cy="{pz(c["z"]):.1f}" r="{rad}" fill="{col}" fill-opacity="{op}"><title>{what}. {who}</title></circle>')
    lab = 'font-size="11" fill="#6b7680" font-family="Barlow,sans-serif"'
    s.append(f'<text x="{w / 2:.0f}" y="14" text-anchor="middle" {lab} font-weight="700">CATCHER\'S VIEW</text>'
             f'<text x="6" y="14" {lab}>&#9664; 3B (RHH)</text><text x="{w - 6}" y="14" text-anchor="end" {lab}>1B (LHH) &#9654;</text>')
    s.append('</svg>')
    return ''.join(s)
