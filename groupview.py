"""The overview at the top of the Pitchers and Hitters pages: key metrics with their session-by-session trend, standout recent outings,
a quadrant chart of the group, workload (pitchers) or hot and cold bats (hitters), the staff arsenal, and recent personal bests.

Built only from data the app already has (team.py session data, stats.py / hitting.py numbers, prs.py personal bests)."""
import datetime
import math
from html import escape

import cache
import extract as e
import hitting
import prs
import stats as stats_mod
import store
import team

RECENT_DAYS = 21          # an outing counts as recent within this many days of the team's newest session
MIN_OUTING = 15           # pitches in an outing before it can be a standout
MIN_GAME_PITCHES = 8      # pitches a hitter saw in a session before it can be a standout
MIN_SESSION_TEAM = 30     # pitches in a team session before it is a point on a trend line
MIN_QUAD_P = 40           # pitches before a pitcher appears on the quadrant chart
MIN_QUAD_H = 30           # pitches seen before a hitter appears on the quadrant chart
FAMILY_ORDER = ['4-Seam', 'Sinker', 'Cutter', 'Slider', 'Sweeper', 'Curve', 'Slurve', 'Change', 'Split', 'Knuckle', 'Other']


def _num(v):
    return team._num(v)


def _fmt_date(d):
    try:
        x = datetime.date.fromisoformat(d)
        return x.strftime('%b ') + str(x.day)
    except (TypeError, ValueError):
        return d or ''


def _initials(name):
    p = [w for w in (name or '').replace(',', ' ').split() if w[:1].isalpha()]
    return ((p[0][0] + p[-1][0]) if len(p) > 1 else (p[0][:2] if p else '?')).upper()


def _spark(vals, good_up=True, w=150, h=40):
    """A filled trend line for a KPI card (None points are skipped)."""
    pts = [(i, v) for i, v in enumerate(vals) if v is not None]
    if len(pts) < 2:
        return ''
    lo, hi = min(v for _, v in pts), max(v for _, v in pts)
    rng = (hi - lo) or 1.0
    n = len(vals) - 1 or 1
    xy = [(4 + (w - 8) * i / n, h - 5 - (h - 12) * (v - lo) / rng) for i, v in pts]
    line = ' '.join(f'{x:.1f},{y:.1f}' for x, y in xy)
    area = f'{xy[0][0]:.1f},{h} ' + line + f' {xy[-1][0]:.1f},{h}'
    up = pts[-1][1] >= pts[-2][1]
    col = 'var(--good)' if up == good_up else 'var(--bad)'
    return (f'<svg viewBox="0 0 {w} {h}" preserveAspectRatio="none" class="kspark" aria-hidden="true">'
            f'<polygon points="{area}" fill="currentColor" opacity=".10"/>'
            f'<polyline points="{line}" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round"/>'
            f'<circle cx="{xy[-1][0]:.1f}" cy="{xy[-1][1]:.1f}" r="3.6" fill="{col}" stroke="#fff" stroke-width="1.5"/></svg>')


def _delta_txt(d, unit):
    if d is None:
        return None
    if unit == '%':
        return f'{d:+.1f} pts'
    if unit == 'avg':
        return f'{d:+.3f}'.replace('0.', '.', 1)
    if unit == 'int':
        return f'{d:+.0f}'
    return f'{d:+.1f}{unit}'


def _fmt_val(v, unit):
    if v is None:
        return None
    if unit == '%':
        return f'{v:.1f}%'
    if unit == 'avg':
        return f'{v:.3f}'.lstrip('0')
    if unit == 'int':
        return f'{v:.0f}'
    return f'{v:.1f}'


def _unit_of(value_str, sid):
    s = str(value_str or '')
    if s.endswith('%'):
        return '%'
    if sid in ('xba', 'avg', 'obp', 'slg', 'xslg', 'xwoba'):
        return 'avg'
    if sid in ('score', 'avg_spin', 'max_spin', 'fb_spin', 'pitches', 'ks', 'brl'):
        return 'int'
    if 'velo' in sid or sid in ('avg_ev', 'max_ev', 'ev90', 'avg_bs', 'max_bs'):
        return ' mph'
    return ''


def _kpis(ids, tiles, series_fn, dates, low_better, goals):
    """[{label, value, def, spark, last, prev, delta, better, goal}] for the team's chosen key metrics."""
    out = []
    gmap = {g['metric']: g for g in goals if g.get('metric')}
    for sid in ids:
        t = tiles.get(sid)
        if not t:
            continue
        vals = [series_fn(d, sid) for d in dates]
        good_up = sid not in low_better
        pts = [v for v in vals if v is not None]
        last = pts[-1] if pts else None
        season_v = t.get('num')
        delta = (last - season_v) if (last is not None and season_v is not None and len(pts) > 1) else None   # latest session against the season
        unit = _unit_of(t['value'], sid)
        better = None if delta is None or abs(delta) < 1e-9 else ((delta > 0) == good_up)
        g = gmap.get(sid)
        out.append({'id': sid, 'label': t['label'], 'value': t['value'], 'def': t.get('definition') or '', 'spark': _spark(vals[-10:], good_up),
                    'n_sessions': len(pts), 'delta': _delta_txt(delta, unit), 'better': better,
                    'last': _fmt_val(last, unit), 'last_date': _fmt_date([d for d, v in zip(dates, vals) if v is not None][-1]) if pts else None,
                    'goal': ({'target': g['target_disp'], 'pct': g['pct'], 'met': g['met'], 'ge': g['cmp'] == 'ge'} if g else None)})
    return out


def _recent_cut(dates):
    if not dates:
        return ''
    try:
        return (datetime.date.fromisoformat(max(dates)) - datetime.timedelta(days=RECENT_DAYS)).isoformat()
    except ValueError:
        return ''


def _pb_index(program, kind):
    """{(player key, date): [personal-best labels]} for badges on standout cards."""
    idx = {}
    for ev in prs.program_recent(program, days=60, limit=500):
        if ev['kind'] == kind:
            idx.setdefault((ev['key'], ev['date']), []).append(ev.get('label') or '')
    return idx


def _quad_svg(points, xl, yl, xmid, ymid, labels, fmt_x, fmt_y, invert_x=False):
    """Scatter of players on two axes with the team average as crosshairs. points: [(x, y, name, url, size)].
    labels: (top-right, top-left, bottom-right, bottom-left) quadrant names, oriented so top-right is always the good corner."""
    W, H, L, R, T, B = 640, 420, 58, 18, 22, 52
    if len(points) < 2:
        return ''
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    def pad(lo, hi, mid):
        lo, hi = min(lo, mid), max(hi, mid)
        r = (hi - lo) or 1.0
        return lo - r * 0.12, hi + r * 0.12
    x0, x1 = pad(min(xs), max(xs), xmid)
    y0, y1 = pad(min(ys), max(ys), ymid)
    def X(v):
        f = (v - x0) / (x1 - x0)
        return L + (W - L - R) * ((1 - f) if invert_x else f)
    def Y(v):
        return T + (H - T - B) * (1 - (v - y0) / (y1 - y0))
    mx, my = X(xmid), Y(ymid)
    o = [f'<svg viewBox="0 0 {W} {H}" class="quad" role="img" aria-label="{escape(yl)} against {escape(xl)}">']
    o.append(f'<rect x="{mx:.1f}" y="{T}" width="{W - R - mx:.1f}" height="{my - T:.1f}" fill="var(--good)" opacity=".07"/>')
    o.append(f'<rect x="{L}" y="{my:.1f}" width="{mx - L:.1f}" height="{H - B - my:.1f}" fill="var(--bad)" opacity=".06"/>')
    o.append(f'<line x1="{mx:.1f}" y1="{T}" x2="{mx:.1f}" y2="{H - B}" stroke="#9aa7ae" stroke-dasharray="4 4"/>')
    o.append(f'<line x1="{L}" y1="{my:.1f}" x2="{W - R}" y2="{my:.1f}" stroke="#9aa7ae" stroke-dasharray="4 4"/>')
    o.append(f'<rect x="{L}" y="{T}" width="{W - L - R}" height="{H - T - B}" fill="none" stroke="#dde3e6"/>')
    o.append(f'<text x="{(L + W - R) / 2:.0f}" y="{H - 12}" text-anchor="middle" class="qa">{escape(xl)} (better →)</text>')
    o.append(f'<text x="16" y="{(T + H - B) / 2:.0f}" text-anchor="middle" class="qa" transform="rotate(-90 16 {(T + H - B) / 2:.0f})">{escape(yl)} (better ↑)</text>')
    for v, anchor in ((x0 + (x1 - x0) * 0.06, None), (xmid, 'avg'), (x1 - (x1 - x0) * 0.06, None)):
        o.append(f'<text x="{X(v):.1f}" y="{H - B + 16}" text-anchor="middle" class="qt">{escape(fmt_x(v))}{" team" if anchor else ""}</text>')
    for v, anchor in ((y0 + (y1 - y0) * 0.06, None), (ymid, 'avg'), (y1 - (y1 - y0) * 0.06, None)):
        o.append(f'<text x="{L - 6}" y="{Y(v) + 4:.1f}" text-anchor="end" class="qt">{escape(fmt_y(v))}</text>')
    placed = []
    for x, y, name, url, size in sorted(points, key=lambda p: -p[4]):
        cx, cy = X(x), Y(y)
        r = 5 + min(7, math.sqrt(max(size, 1)) / 3)
        good = ((cx > mx) + (cy < my))
        col = 'var(--good)' if good == 2 else ('var(--bad)' if good == 0 else 'var(--accent,#5c97a8)')
        last = name.split()[-1] if name else ''
        ly = cy - r - 4
        for (px, py) in placed:
            if abs(px - cx) < 46 and abs(py - ly) < 12:
                ly = cy + r + 12
                break
        placed.append((cx, ly))
        tip = escape(f'{name}: {fmt_x(x)} / {fmt_y(y)}')
        o.append(f'<a href="{escape(url)}"><g class="qd"><title>{tip}</title><circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" fill="{col}" fill-opacity=".85" stroke="#fff" stroke-width="1.5"/>'
                 f'<text x="{cx:.1f}" y="{ly:.1f}" text-anchor="middle" class="qn">{escape(last)}</text></g></a>')
    o.append('</svg>')
    return ''.join(o)


def _days_ago(d, today):
    try:
        return (today - datetime.date.fromisoformat(d)).days
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------------ pitchers
def _war_board(program, side, D):
    """A WAR leaderboard (spring games only) to lead the board list, or [] before any spring game is in."""
    import store
    import war
    if store.is_fullswing(program):
        return []
    try:
        T = war.for_program(program)
    except Exception:
        return []
    names = {p['key']: p['name'] for p in D['players']}
    got = sorted(((k, v) for k, v in T[side].items() if v.get('war') is not None and k in names), key=lambda kv: -kv[1]['war'])[:5]
    if not got:
        return []
    return [{'title': 'WAR', 'sub': f"Spring {T['year']} games only", 'unit': 'WAR',
             'rows': [{'key': k, 'name': names[k], 'value': f"{v['war']:.1f}", 'extra': war.label(v, side)} for k, v in got]}]


def pitching(program, ids, low_better, url_for_player, today=None):
    import season
    win = season.window(program)
    return _pitching(program, tuple(ids), frozenset(low_better), win, (today or datetime.date.today()).isoformat(), url_for_player)


@cache.memo
def _pitching(program, ids, low_better, win, today_s, url_for_player):
    fs = store.is_fullswing(program)
    today = datetime.date.fromisoformat(today_s)
    ps = team._pitchers(program, win)
    D = team.pitching_data(program)
    dates = D['sessions']
    by_date = {}
    for _s, _b, outs in ps:
        for o in outs:
            by_date.setdefault(o['date'], []).extend(o['rows'])
    comp = {}

    def series(d, sid):
        rows = by_date.get(d) or []
        if len(rows) < MIN_SESSION_TEAM:
            return None
        if d not in comp:
            comp[d] = stats_mod.compute(rows)
        v = comp[d].get(sid)
        return _num(v[0]) if v else None
    goals = team.goal_rows(program, 'pitching', D['tiles'])
    kpis = _kpis(list(ids), D['tiles'], series, dates, low_better, goals)

    # standout outings: the best recent outings by strikes, swing-and-miss and K-BB, plus a bump for velocity above his norm
    cut = _recent_cut(dates)
    pbs = _pb_index(program, 'p')
    season_v = {p['key']: p['v'] for p in D['players']}
    cands = []
    for slug, bio, outs in ps:
        sv = season_v.get(slug) or {}
        base_fb = _num((sv.get('fb_velo') or sv.get('avg_velo') or ('', ''))[0])
        for o in outs:
            if o['date'] < cut or len(o['rows']) < MIN_OUTING:
                continue
            v = stats_mod.compute(o['rows'])
            g = lambda k: _num((v.get(k) or ('', ''))[0])
            ks, bb, bf = g('ks') or 0, g('walks') or 0, g('bf') or 0
            csw, strike, whiff = g('csw_pct'), g('strike_pct'), g('whiff_pct')
            fb = g('fb_velo') or g('avg_velo')
            # rates count fully only over a real outing (40+ pitches), so a sharp 15-pitch inning can't beat a strong start
            vol = min(1.0, len(o['rows']) / 40)
            sc = 0.0
            sc += (csw - 27) * 0.8 if csw is not None else 0
            sc += (strike - 60) * 0.5 if strike is not None else 0
            sc += (whiff - 25) * 0.3 if whiff is not None else 0
            sc = sc * vol
            sc += 2.5 * (ks - bb)
            sc += 2.5 * (fb - base_fb) if (fb is not None and base_fb is not None) else 0
            sc += 0.08 * len(o['rows'])
            chips = []
            if not fs:
                for lab, k in (('Pitches', 'pitches'), ('K', 'ks'), ('BB', 'walks')):
                    if k in v:
                        chips.append((lab, v[k][0]))
                for lab, k in (('Strike%', 'strike_pct'), ('CSW%', 'csw_pct'), ('Whiff%', 'whiff_pct')):
                    if k in v:
                        chips.append((lab, v[k][0]))
                if 'fb_top' in v:
                    chips.append(('FB top', v['fb_top'][0]))
            else:
                chips = [('Pitches', str(len(o['rows'])))] + [(lab, v[k][0]) for lab, k in (('Avg velo', 'avg_velo'), ('Top velo', 'top_velo'), ('Spin', 'avg_spin'), ('Whiff%', 'whiff_pct')) if k in v]
            badges = list(pbs.get((slug, o['date'])) or [])
            if fb is not None and base_fb is not None and fb - base_fb >= 1.0:
                badges.append(f'Fastball +{fb - base_fb:.1f} mph over his average')
            cands.append({'key': slug, 'name': bio.get('name', slug), 'date': o['date'], 'date_s': _fmt_date(o['date']), 'score': sc,
                          'chips': chips[:7], 'badges': badges[:3], 'url': url_for_player('p', slug), 'initials': _initials(bio.get('name', slug)),
                          'label': o.get('label') or o.get('session_type') or ''})
    cands.sort(key=lambda c: -c['score'])
    standouts, seen = [], set()
    for c in cands:
        if c['key'] in seen:
            continue
        seen.add(c['key'])
        standouts.append(c)
        if len(standouts) == 4:
            break

    # quadrant: command against swing-and-miss (Full Swing: velocity against swing-and-miss)
    pts = []
    xk, yk = ('avg_velo', 'whiff_pct') if fs else ('strike_pct', 'whiff_pct')
    for p in D['players']:
        x, y = _num((p['v'].get(xk) or ('', ''))[0]), _num((p['v'].get(yk) or ('', ''))[0])
        if x is not None and y is not None and p['n'] >= MIN_QUAD_P:
            pts.append((x, y, p['name'], url_for_player('p', p['key']), p['n']))
    tx, ty = _num((D['tiles'].get(xk) or {}).get('value')), _num((D['tiles'].get(yk) or {}).get('value'))
    quad = ''
    qlab = ('Overpowering', 'Misses bats, wild' if not fs else 'Misses bats', 'Pounds the zone' if not fs else 'Throws hard', 'Needs work')
    if len(pts) >= 3 and tx is not None and ty is not None:
        quad = _quad_svg(pts, 'Average velocity' if fs else 'Strike %', 'Whiff %', tx, ty, qlab, (lambda v: f'{v:.1f}') if fs else (lambda v: f'{v:.0f}%'), lambda v: f'{v:.0f}%')

    # workload: who has thrown lately, and how much
    work = []
    for slug, bio, outs in ps:
        last = max(outs, key=lambda o: o['date'])
        ago = _days_ago(last['date'], today)
        wk = sum(len(o['rows']) for o in outs if (_days_ago(o['date'], today) or 99) <= 6)
        last3 = [len(o['rows']) for o in sorted(outs, key=lambda o: o['date'])[-3:]]
        work.append({'key': slug, 'name': bio.get('name', slug), 'url': url_for_player('p', slug), 'last': _fmt_date(last['date']), 'ago': ago,
                     'last_n': len(last['rows']), 'week': wk, 'last3': last3, 'outings': len(outs)})
    work.sort(key=lambda w: (w['ago'] if w['ago'] is not None else 9999, -w['last_n']))
    wmax = max([w['last_n'] for w in work] + [1])

    # staff arsenal: how the staff's pitches split by type, with average velocity
    import pitchfx
    mix = {}
    for _s, _b, outs in ps:
        for o in outs:
            for r in o['rows']:
                t = pitchfx._label(r) or 'Other'
                m = mix.setdefault(t, [0, 0.0, 0])
                m[0] += 1
                sp = e._fnum(r.get('RelSpeed'))
                if sp:
                    m[1] += sp
                    m[2] += 1
    tot = sum(m[0] for m in mix.values()) or 1
    colors = {}
    arsenal = []
    for t in sorted(mix, key=lambda t: (FAMILY_ORDER.index(t) if t in FAMILY_ORDER else 99, -mix[t][0])):
        n, sv_, sn = mix[t]
        if n / tot < 0.01:
            continue
        arsenal.append({'type': t, 'pct': 100 * n / tot, 'velo': (sv_ / sn) if sn else None, 'n': n, 'color': _pitch_color(t, colors)})

    pbs_recent = [dict(ev, url=url_for_player('p', ev['key']), date_s=_fmt_date(ev['date'])) for ev in prs.program_recent(program, days=30, limit=200) if ev['kind'] == 'p'][:8]
    return {'boards': _war_board(program, 'p', D) + D['boards'], 'side': 'pitching', 'fs': fs, 'kpis': kpis, 'standouts': standouts, 'quad': quad, 'qlab': qlab, 'work': work, 'wmax': wmax, 'arsenal': arsenal,
            'pbs': pbs_recent, 'n_players': D['n_players'], 'n_pitches': D['n_pitches'], 'n_sessions': len(dates),
            'last_session': _fmt_date(dates[-1]) if dates else None, 'recent_days': RECENT_DAYS,
            'trend': D['trend']}


def _pitch_color(t, colors):
    return colors.get(t) or e.MINI_PITCH_COLORS.get(t) or '#8a959c'


# ------------------------------------------------------------------ hitters
def hitting_view(program, ids, low_better, url_for_player, include_demo=True):
    import season
    return _hitting(program, tuple(ids), frozenset(low_better), season.window(program), include_demo, url_for_player)


@cache.memo
def _hitting(program, ids, low_better, win, include_demo, url_for_player):
    fs = store.is_fullswing(program)
    hs = team._hitters(program, include_demo, win)
    D = team.hitting_data(program, include_demo)
    dates = D['sessions']
    by_date = {}
    for h in hs.values():
        for p in h['pitches']:
            if p.get('date'):
                by_date.setdefault(p['date'], []).append(p)
    comp = {}

    def series(d, sid):
        ps_ = by_date.get(d) or []
        if len(ps_) < MIN_SESSION_TEAM:
            return None
        if d not in comp:
            comp[d] = hitting.hitter_stats(ps_)
        v = comp[d].get(sid)
        return v if isinstance(v, (int, float)) else None
    goals = team.goal_rows(program, 'hitting', D['tiles'])
    kpis = _kpis(list(ids), D['tiles'], series, dates, low_better, goals)

    # standout games: damage first (expected hits, hard contact, barrels), then swing decisions
    cut = _recent_cut(dates)
    pbs = _pb_index(program, 'h')
    cands = []
    for key, h in hs.items():
        by = {}
        for p in h['pitches']:
            if p.get('date') and p['date'] >= cut:
                by.setdefault(p['date'], []).append(p)
        for d, ps_ in by.items():
            if len(ps_) < MIN_GAME_PITCHES:
                continue
            s = hitting.hitter_stats(ps_)
            bip = [p for p in ps_ if p['outcome'] == 'inplay' and p.get('ev') is not None]
            hard = sum(1 for p in bip if p['ev'] >= 95)
            xh = sum(hitting.hit_prob(p['ev'], p['la']) or 0 for p in bip if p.get('la') is not None)
            mx = max((p['ev'] for p in bip), default=None)
            sc = 2.2 * xh + 0.9 * hard + 1.5 * (s.get('brl') or 0) + (0.05 * (mx - 90) if mx else 0)
            if s.get('score') is not None and (s.get('decisions') or 0) >= 6:
                sc += (s['score'] - 75) / 12
            if fs and s.get('avg_bs'):
                sc += 0.1 * (s['avg_bs'] - 65)
            chips = [('Pitches', str(len(ps_)))]
            if mx:
                chips.append(('Max EV', f'{mx:.1f}'))
            chips.append(('Hard-hit', str(hard)))
            if s.get('brl'):
                chips.append(('Barrels', str(s['brl'])))
            if s.get('xba') is not None and (s.get('ab') or 0) >= 2:
                chips.append(('xBA', f"{s['xba']:.3f}".lstrip('0')))
            if s.get('score') is not None and (s.get('decisions') or 0) >= 6:
                chips.append(('SDR', f"{s['score']:.0f}"))
            if fs and s.get('avg_bs'):
                chips.append(('Bat speed', f"{s['avg_bs']:.1f}"))
            cands.append({'key': key, 'name': hitting.display_name(h['name']), 'date': d, 'date_s': _fmt_date(d), 'score': sc, 'chips': chips[:7],
                          'badges': list(pbs.get((key, d)) or [])[:3], 'url': url_for_player('h', key), 'initials': _initials(h['name']), 'label': ''})
    cands.sort(key=lambda c: -c['score'])
    standouts, seen = [], set()
    for c in cands:
        if c['key'] in seen:
            continue
        seen.add(c['key'])
        standouts.append(c)
        if len(standouts) == 4:
            break

    # quadrant: discipline (chase rate, lower is better) against damage (exit velocity). Full Swing: bat speed against exit velocity.
    pts = []
    for p in D['players']:
        s = p['s']
        x = s.get('avg_bs') if fs else s.get('chase_pct')
        y = s.get('avg_ev')
        if x is not None and y is not None and p['n'] >= MIN_QUAD_H and (s.get('bip') or 0) >= 3:
            pts.append((x, y, p['name'], url_for_player('h', p['key']), p['n']))
    tx = (D['tiles'].get('avg_bs') if fs else D['tiles'].get('chase_pct')) or {}
    ty = D['tiles'].get('avg_ev') or {}
    quad = ''
    qlab = ('Fast and loud', 'Efficient', 'Fast, not squared up', 'Building') if fs else ('Disciplined damage', 'Damage, chases', 'Disciplined, light contact', 'Needs work')
    if len(pts) >= 3 and tx.get('num') is not None and ty.get('num') is not None:
        if fs:
            quad = _quad_svg(pts, 'Bat speed (mph)', 'Exit velocity (mph)', tx['num'], ty['num'], qlab,
                             lambda v: f'{v:.1f}', lambda v: f'{v:.1f}')
        else:
            quad = _quad_svg(pts, 'Chase %, low to high', 'Exit velocity (mph)', tx['num'], ty['num'],
                             qlab,
                             lambda v: f'{v:.0f}%', lambda v: f'{v:.1f}', invert_x=True)

    # hot and cold: last two sessions against the season, on exit velocity (and xBA when there is enough)
    hc = []
    for p in D['players']:
        ser = [r for r in p['series'] if r.get('avg_ev') is not None]
        if len(ser) < 3:
            continue
        rec = ser[-2:]
        base = ser[:-2]
        r_ev = sum(r['avg_ev'] for r in rec) / len(rec)
        b_ev = sum(r['avg_ev'] for r in base) / len(base)
        hc.append({'key': p['key'], 'name': p['name'], 'url': url_for_player('h', p['key']), 'recent': r_ev, 'base': b_ev, 'delta': r_ev - b_ev,
                   'spark': team._spark([r['avg_ev'] for r in ser[-6:]], r_ev >= b_ev)})
    hot = sorted([x for x in hc if x['delta'] >= 1.5], key=lambda x: -x['delta'])[:4]
    cold = sorted([x for x in hc if x['delta'] <= -1.5], key=lambda x: x['delta'])[:4]

    # lineup approach: how the group splits by swing-decision grade
    grades = {}
    for p in D['players']:
        g = p['s'].get('grade')
        if g and (p['s'].get('decisions') or 0) >= 15:
            grades.setdefault(g, []).append(p['name'])
    order = ['Elite', 'Above Average', 'Average', 'Below Average', 'Concerning']
    sdr_split = [{'grade': g, 'n': len(grades.get(g, [])), 'names': grades.get(g, [])} for g in order]

    pbs_recent = [dict(ev, url=url_for_player('h', ev['key']), date_s=_fmt_date(ev['date'])) for ev in prs.program_recent(program, days=30, limit=200) if ev['kind'] == 'h'][:8]
    return {'boards': _war_board(program, 'h', D) + D['boards'], 'side': 'hitting', 'fs': fs, 'kpis': kpis, 'standouts': standouts, 'quad': quad, 'qlab': qlab, 'hot': hot, 'cold': cold, 'sdr_split': sdr_split,
            'sdr_total': sum(x['n'] for x in sdr_split), 'pbs': pbs_recent, 'n_players': D['n_players'], 'n_pitches': D['n_pitches'],
            'n_sessions': len(dates), 'last_session': _fmt_date(dates[-1]) if dates else None, 'recent_days': RECENT_DAYS, 'trend': D['trend']}
