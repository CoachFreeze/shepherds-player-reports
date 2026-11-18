"""Team Home: the coach's season-focused landing page, in two versions.

Development mode (fall and winter): are players getting better? Biggest gains this season, process stats by week, a development board,
arsenal changes, and a ready-for-spring checklist.
Game mode (spring into early summer): are we winning, and why? Record and season line, results by week, the latest game, hot and cold
over the last week, bullpen availability, next opponents, and tagging coverage.
Both: team goals with season pace, the season's activity calendar, and personal bests.

Which version shows: the coach's choice (team config 'home_mode': auto / dev / game). Auto = game mode from February 1 through June 30,
development mode the rest of the year.
"""
import datetime
import math

import cache
import extract as e
import hitting
import prs
import stats as stats_mod
import store
import team

MODES = ('auto', 'dev', 'game')
GAME_TYPES = ('Game', 'Scrimmage')
# Days of rest after an outing, by pitch count: a conservative default for the bullpen board, not a published standard.
REST_RULE = ((30, 0), (45, 1), (60, 2), (80, 3), (10 ** 6, 4))
TYPE_COLORS = {'Game': '#c84a3a', 'Intrasquad': '#e0904a', 'Live BP': '#5c97a8', 'Bullpen': '#9fc1cc', 'Batting practice': '#b9a6d6'}


def _num(v):
    return team._num(v)


def _d(s):
    try:
        return datetime.date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


def _fmt_date(s):
    d = _d(s)
    return (d.strftime('%b ') + str(d.day)) if d else (s or '')


# ------------------------------------------------------------------ mode
def stored_mode(program):
    m = team.load(program).get('home_mode') or 'auto'
    return m if m in MODES else 'auto'


def set_mode(program, mode):
    d = team.load(program)
    d['home_mode'] = mode if mode in MODES else 'auto'
    team.save(program, d)


GAME_START = (2, 1)       # Game mode from February 1 ...
GAME_END = (7, 1)         # ... until July 1 (exclusive); development the rest of the year


def auto_mode(program, today=None):
    """(mode, reason) by the calendar: game mode from February 1 through June 30, development mode the rest of the year."""
    today = today or datetime.date.today()
    if GAME_START <= (today.month, today.day) < GAME_END:
        return 'game', 'game mode runs February 1 through June 30'
    return 'dev', 'development mode runs July 1 through January 31; game mode starts February 1'


def mode_for(program, today=None):
    """{'mode': 'dev'|'game', 'choice': 'auto'|'dev'|'game', 'reason'}."""
    choice = stored_mode(program)
    if choice != 'auto':
        return {'mode': choice, 'choice': choice, 'reason': 'set by a coach'}
    m, why = auto_mode(program, today)
    return {'mode': m, 'choice': 'auto', 'reason': why}


# ------------------------------------------------------------------ helpers
def _session_type(o):
    """What kind of session an outing was, from its rows."""
    ts = {r.get('SessionType') for r in o['rows']}
    if ts & set(GAME_TYPES):
        return 'Game'
    if 'Intrasquad' in ts:
        return 'Intrasquad'
    if o.get('live_ab') or any(r.get('Batter') for r in o['rows'][:5]):
        return 'Live BP'
    return 'Bullpen'


def _week_start(d):
    return d - datetime.timedelta(days=d.weekday())


def _spark(vals, good_up=True, w=150, h=36):
    import groupview
    return groupview._spark(vals, good_up, w, h)


def _pct(det):
    import re
    m = re.match(r'\s*(\d+)\s*/\s*(\d+)', str(det or ''))
    return (int(m.group(1)), int(m.group(2))) if m else None


# ------------------------------------------------------------------ shared blocks
def _calendar(ps, hs, start, today):
    """Season activity: one cell per day from the first session (or season start) to today, colored by the kind of session."""
    by = {}
    for _s, _b, outs in ps:
        for o in outs:
            d = _d(o['date'])
            if d:
                t = _session_type(o)
                rank = list(TYPE_COLORS).index(t)
                cur = by.get(d)
                if cur is None or rank < list(TYPE_COLORS).index(cur[0]):
                    by[d] = (t, (cur[1] if cur else 0) + len(o['rows']))
                else:
                    by[d] = (cur[0], cur[1] + len(o['rows']))
    for h in (hs or {}).values():
        for p in h['pitches']:
            d = _d(p.get('date'))
            if d and d not in by:
                by[d] = ('Batting practice', 0)
            if d:
                by[d] = (by[d][0], by[d][1] + 1)
    if not by:
        return None
    first = min(by)
    s = _d(start) if start else None
    begin = _week_start(max(s, first - datetime.timedelta(days=14)) if s else first)
    end = max(today, max(by))
    weeks, d = [], begin
    while d <= end:
        col = []
        for i in range(7):
            x = d + datetime.timedelta(days=i)
            t = by.get(x)
            col.append({'date': x.isoformat(), 'label': f"{x.strftime('%a %b')} {x.day}" + (f': {t[0]} ({t[1]} pitches)' if t else ''),
                        'type': t[0] if t else None, 'future': x > today})
        weeks.append({'month': d.strftime('%b') if d.day <= 7 else '', 'days': col})
        d += datetime.timedelta(days=7)
    counts = {}
    for t, _n in by.values():
        counts[t] = counts.get(t, 0) + 1
    return {'weeks': weeks, 'legend': [(t, c, counts.get(t, 0)) for t, c in TYPE_COLORS.items() if counts.get(t)], 'days': len(by)}


def _goals(program, P, H, today):
    out = []
    for side, D in (('pitching', P), ('hitting', H)):
        if D is None:
            continue
        for g in team.goal_rows(program, side, D['tiles']):
            pace = None
            c, du = _d(g.get('created')), _d(g.get('due'))
            if c and du and du > c and not g['met'] and g.get('pct') is not None:
                exp = max(0.0, min(100.0, 100 * (today - c).days / (du - c).days))
                pace = 'ahead' if g['pct'] >= exp + 5 else ('behind' if g['pct'] < exp - 10 else 'on')
                g = dict(g, expected=round(exp))
            out.append(dict(g, side=side, pace=pace))
    return out


def _weekly(by_week_rows, fn, ids, good_up_ids):
    """{metric id: {'vals', 'labels', 'spark', 'last', 'first'}} for team numbers week by week."""
    weeks = sorted(by_week_rows)
    res = {}
    for sid in ids:
        vals = [fn(by_week_rows[w], sid) for w in weeks]
        pts = [v for v in vals if v is not None]
        res[sid] = {'vals': vals, 'n': len(pts), 'spark': _spark(vals[-12:], sid in good_up_ids) if len(pts) >= 2 else '',
                    'first': pts[0] if pts else None, 'last': pts[-1] if pts else None}
    return res


# ------------------------------------------------------------------ needs attention
def _attention(program, P, ps, H, hs, mode, today):
    import advanced
    import grades
    items = []
    # untagged games: results-based stats wait on them
    gm = {}
    for _s, _b, outs in ps:
        for o in outs:
            for r in o['rows']:
                if r.get('SessionType') in GAME_TYPES and e._outcome(r) == 'inplay':
                    g = gm.setdefault(o['date'], [0, 0])
                    g[0] += 1
                    g[1] += bool(hitting._play_result(r))
    untagged = sorted(d for d, (n, t) in gm.items() if n and t / n < 0.8)
    if untagged:
        items.append({'level': 'high' if mode == 'game' else 'mid', 'title': f"{len(untagged)} of {len(gm)} game{'s' if len(gm) != 1 else ''} not fully tagged",
                      'text': 'Balls in play without a result hold back BAA, wOBA, wRC+, FIP and LOB%. Latest: ' + ', '.join(_fmt_date(d) for d in untagged[-3:]) + '.',
                      'link': ('team_games', {'program': program}), 'cta': 'Open game reports'})
    # heights: arm angle for pitchers, each hitter's own strike zone
    bios = hitting._load_json(hitting.HITTER_BIOS_PATH)
    no_ht_p = [b.get('name', s) for s, b, _ in ps if not b.get('height_in')]
    no_ht_h = [h['name'] for k, h in (hs or {}).items() if not ((bios.get(k) or {}).get('height_in') or (h.get('roster') or {}).get('height_in'))]
    if no_ht_p or no_ht_h:
        parts = []
        if no_ht_p:
            parts.append(f"{len(no_ht_p)} pitcher{'s' if len(no_ht_p) != 1 else ''} (arm angle)")
        if no_ht_h:
            parts.append(f"{len(no_ht_h)} hitter{'s' if len(no_ht_h) != 1 else ''} (strike zone)")
        items.append({'level': 'mid', 'title': 'Missing heights: ' + ' and '.join(parts),
                      'text': 'A height sizes each hitter\'s strike zone and anchors each pitcher\'s arm angle. Upload or update the roster to fill them in.',
                      'link': ('roster_page', {'program': program}), 'cta': 'Update roster'})
    # close to unlocking Location+
    try:
        tbl = advanced.table(program)['p']
        near = sorted(((v.get('loc_n') or 0, s) for s, v in tbl.items() if v.get('loc') is None and (v.get('loc_n') or 0) >= 0.6 * grades.MIN_LOC_PITCHES), reverse=True)
        if near:
            names = {s: b.get('name', s) for s, b, _ in ps}
            items.append({'level': 'low', 'title': f"{len(near)} pitcher{'s' if len(near) != 1 else ''} close to a Location+ grade",
                          'text': ', '.join(f"{names.get(s, s)} {n}/{grades.MIN_LOC_PITCHES}" for n, s in near[:4]) + ' located pitches.', 'link': None, 'cta': None})
    except Exception:
        pass
    # opponents without a roster
    try:
        import scouting
        import scoutroster
        opps = scouting.opponents(program)
        have = scoutroster.all_for(program)
        missing = [o['label'] for k, o in opps.items() if k not in have and k != 'unlabeled']
        if missing:
            items.append({'level': 'mid' if mode == 'game' else 'low', 'title': f"{len(missing)} scouted opponent{'s' if len(missing) != 1 else ''} without a roster",
                          'text': 'A roster fills in class years, heights and handedness on scouting pages: ' + ', '.join(missing[:4]) + ('…' if len(missing) > 4 else '') + '.',
                          'link': ('team_scouting', {'program': program}), 'cta': 'Open scouting'})
    except Exception:
        pass
    # heavy recent workload
    heavy = []
    for s, b, outs in ps:
        wk = sum(len(o['rows']) for o in outs if (today - (_d(o['date']) or today)).days <= 6)
        if wk >= 90:
            heavy.append((wk, b.get('name', s)))
    if heavy:
        heavy.sort(reverse=True)
        items.append({'level': 'high', 'title': f"Heavy week for {len(heavy)} pitcher{'s' if len(heavy) != 1 else ''}",
                      'text': ', '.join(f'{n} ({w} pitches in 7 days)' for w, n in heavy[:4]) + '.', 'link': None, 'cta': None})
    order = {'high': 0, 'mid': 1, 'low': 2}
    items.sort(key=lambda x: order[x['level']])
    return items


# ------------------------------------------------------------------ development mode
DEV_P = {'fb_velo': ('Fastball velo', ' mph', 0.8, True), 'strike_pct': ('Strike %', '%', 4.0, True), 'whiff_pct': ('Whiff %', '%', 5.0, True)}
DEV_H = {'avg_ev': ('Avg exit velo', ' mph', 1.5, True), 'score': ('Swing decisions', '', 6.0, True), 'avg_bs': ('Bat speed', ' mph', 1.5, True), 'xba': ('xBA', '', 0.030, True)}


def _gain_rows(players, metrics, kind, url):
    """Early season (first two sessions) against recent (last two), per player and metric."""
    rows = []
    for p in players:
        best, cells = None, {}
        for mid, (lab, unit, thr, up) in metrics.items():
            vals = [r[mid] for r in p['series'] if r.get(mid) is not None]
            if len(vals) < 4:
                continue
            a, b = sum(vals[:2]) / 2, sum(vals[-2:]) / 2
            d = b - a
            cells[mid] = {'from': a, 'to': b, 'delta': d, 'score': (d if up else -d) / thr, 'spark': _spark(vals[-8:], up, 90, 26)}
            if best is None or cells[mid]['score'] > best[1]['score']:
                best = (mid, cells[mid])
        if cells:
            rows.append({'key': p['key'], 'name': p['name'], 'kind': kind, 'url': url(kind, p['key']), 'cells': cells, 'best': best,
                         'sessions': p.get('sessions') or len(p['series'])})
    return rows


def _fmt_metric(mid, v, unit):
    if v is None:
        return '–'
    if mid == 'xba':
        return f'{v:.3f}'.lstrip('0')
    if mid == 'score':
        return f'{v:.0f}'
    return f'{v:.1f}{unit}'


def _fmt_delta(mid, d, unit):
    if mid == 'xba':
        return f'{d:+.3f}'.replace('0.', '.', 1)
    if mid == 'score':
        return f'{d:+.0f}'
    return f'{d:+.1f}' + (' pts' if unit == '%' else unit)


def _arsenal_changes(ps, url):
    """Per pitcher: new pitches and clear shape / velocity changes, first half of his season against the second half."""
    import pitchfx
    out = []
    for slug, bio, outs in ps:
        o = sorted(outs, key=lambda x: x['date'])
        if len(o) < 4:
            continue
        half = len(o) // 2
        def agg(group):
            d, tot = {}, 0
            for x in group:
                for r in x['rows']:
                    t = pitchfx._label(r)
                    if not t:
                        continue
                    tot += 1
                    a = d.setdefault(t, {'n': 0, 'v': [], 'ivb': [], 'hb': []})
                    a['n'] += 1
                    for k, col in (('v', 'RelSpeed'), ('ivb', 'InducedVertBreak'), ('hb', 'HorzBreak')):
                        val = e._fnum(r.get(col))
                        if val is not None:
                            a[k].append(val)
            return d, tot
        A, ta = agg(o[:half])
        B, tb = agg(o[half:])
        if not ta or not tb:
            continue
        notes = []
        m = lambda l: sum(l) / len(l) if len(l) >= 5 else None
        for t, b in B.items():
            a = A.get(t)
            share_b = b['n'] / tb
            if (not a or a['n'] / ta < 0.02) and share_b >= 0.08 and b['n'] >= 8:
                notes.append({'kind': 'new', 'text': f'Added a {t.lower()} ({share_b * 100:.0f}% of recent pitches)'})
                continue
            if not a:
                continue
            va, vb = m(a['v']), m(b['v'])
            if va is not None and vb is not None and abs(vb - va) >= 1.5:
                notes.append({'kind': 'up' if vb > va else 'down', 'text': f'{t} velo {va:.1f} → {vb:.1f} mph'})
            ia, ib = m(a['ivb']), m(b['ivb'])
            if ia is not None and ib is not None and abs(ib - ia) >= 2.5:
                notes.append({'kind': 'shape', 'text': f'{t} vertical break {ia:+.1f} → {ib:+.1f} in'})
            ha, hb = m(a['hb']), m(b['hb'])
            if ha is not None and hb is not None and abs(abs(hb) - abs(ha)) >= 2.5:
                notes.append({'kind': 'shape', 'text': f'{t} horizontal break {abs(ha):.1f} → {abs(hb):.1f} in'})
        for t, a in A.items():
            if a['n'] / ta >= 0.08 and (t not in B or B[t]['n'] / tb < 0.02):
                notes.append({'kind': 'down', 'text': f'Stopped throwing his {t.lower()}'})
        if notes:
            out.append({'key': slug, 'name': bio.get('name', slug), 'url': url('p', slug), 'notes': notes[:4], 'span': f'{_fmt_date(o[0]["date"])} – {_fmt_date(o[-1]["date"])}'})
    out.sort(key=lambda x: (-sum(n['kind'] == 'new' for n in x['notes']), -len(x['notes'])))
    return out


def _readiness(program, ps, hs):
    import advanced
    import roster as roster_mod
    import scouting
    import scoutroster
    checks = []
    try:
        ro = roster_mod.load(program) or {}
        n_ro = len(ro.get('players') or [])
    except Exception:
        n_ro = 0
    checks.append({'ok': n_ro > 0, 'title': 'Team roster uploaded', 'detail': f'{n_ro} players' if n_ro else 'No roster yet', 'link': ('roster_page', {'program': program})})
    bios = hitting._load_json(hitting.HITTER_BIOS_PATH)
    tot = len(ps) + len(hs or {})
    with_ht = sum(1 for _s, b, _o in ps if b.get('height_in')) + sum(1 for k, h in (hs or {}).items() if (bios.get(k) or {}).get('height_in') or (h.get('roster') or {}).get('height_in'))
    checks.append({'ok': tot and with_ht >= tot, 'title': 'Heights for every player', 'detail': f'{with_ht} of {tot}', 'link': ('roster_page', {'program': program}), 'frac': (with_ht / tot) if tot else 0})
    try:
        tbl = advanced.table(program)['p']
        st_n = sum(1 for v in tbl.values() if v.get('stuff') is not None)
        lo_n = sum(1 for v in tbl.values() if v.get('loc') is not None)
    except Exception:
        st_n = lo_n = 0
    np_ = len(ps)
    checks.append({'ok': np_ and st_n >= np_, 'title': 'Stuff+ for every pitcher', 'detail': f'{st_n} of {np_}', 'link': None, 'frac': (st_n / np_) if np_ else 0})
    checks.append({'ok': np_ and lo_n >= np_, 'title': 'Location+ for every pitcher', 'detail': f'{lo_n} of {np_} (needs 150 located pitches each)', 'link': None, 'frac': (lo_n / np_) if np_ else 0})
    try:
        opps = {k: v for k, v in scouting.opponents(program).items() if k != 'unlabeled'}
        have = scoutroster.all_for(program)
        n_have = sum(1 for k in opps if k in have)
        if opps:
            checks.append({'ok': n_have >= len(opps), 'title': 'Rosters for scouted opponents', 'detail': f'{n_have} of {len(opps)}', 'link': ('team_scouting', {'program': program}), 'frac': n_have / len(opps)})
    except Exception:
        pass
    return checks


# ------------------------------------------------------------------ game mode
def _rest_days(n):
    for cap, days in REST_RULE:
        if n <= cap:
            return days
    return REST_RULE[-1][1]


def _bullpen(ps, today, url):
    out = []
    for slug, bio, outs in ps:
        last = max(outs, key=lambda o: o['date'])
        d = _d(last['date'])
        if not d:
            continue
        n = len(last['rows'])
        rest = _rest_days(n)
        ready = d + datetime.timedelta(days=rest + 1) if rest else d + datetime.timedelta(days=1)
        ago = (today - d).days
        wk = sum(len(o['rows']) for o in outs if 0 <= (today - (_d(o['date']) or today)).days <= 6)
        avail = today >= ready
        out.append({'key': slug, 'name': bio.get('name', slug), 'url': url('p', slug), 'last': _fmt_date(last['date']), 'ago': ago, 'n': n, 'rest': rest,
                    'avail': avail, 'ready': _fmt_date(ready.isoformat()), 'week': wk, 'type': _session_type(last)})
    out.sort(key=lambda x: (not x['avail'], x['ago']))
    return out


def _season_line(ps, hs):
    """Team pitching and hitting lines for the season, results-based numbers only where the games are tagged."""
    import advanced
    rows = [r for _s, _b, outs in ps for o in outs for r in o['rows']]
    pit = advanced._calc([advanced._from_row(r) for r in rows], True) if rows else {}
    hp = [p for h in (hs or {}).values() for p in h['pitches']]
    hit = advanced._calc([advanced._from_pitch(p) for p in hp], False) if hp else {}
    ok_p = pit.get('tag_cov', 0) >= advanced.MIN_TAG_COVERAGE
    ok_h = hit.get('tag_cov', 0) >= advanced.MIN_TAG_COVERAGE

    def f3(v):
        return f'{v:.3f}'.lstrip('0') if v is not None and 0 <= v < 1 else (f'{v:.3f}' if v is not None else None)
    P = []
    if pit:
        ip = pit.get('ip') or 0
        has_runs = any(r.get('RunsScored') not in (None, '') for r in rows)
        ra9 = (9 * pit.get('runs', 0) / ip) if (ip and has_runs) else None
        P = [('Runs / 9', f'{ra9:.2f}' if (ra9 is not None and ok_p) else None, 'Runs allowed per nine innings (runs, not earned runs), from tagged games.'),
             ('FIP', f"{pit['fip']:.2f}" if (pit.get('fip') is not None and ok_p) else None, 'Fielding independent pitching, scaled to the league in the app.'),
             ('xERA', f"{pit['xera']:.2f}" if pit.get('xera') is not None else None, 'Expected ERA from contact quality, strikeouts and walks.'),
             ('xwOBA', f3(pit.get('xwoba')), 'Expected weighted on-base average allowed.'),
             ('K%', f"{100 * pit['k'] / pit['pa']:.1f}%" if pit.get('pa') else None, 'Strikeouts per batter faced.'),
             ('BB%', f"{100 * pit['bb'] / pit['pa']:.1f}%" if pit.get('pa') else None, 'Walks per batter faced.')]
    H = []
    if hit:
        H = [('AVG', f3(hit.get('avg')) if ok_h else None, 'Batting average from tagged results.'),
             ('wOBA', f3(hit.get('woba')) if ok_h else None, 'Weighted on-base average from tagged results.'),
             ('wRC+', f"{hit['wrc_plus']:.0f}" if (hit.get('wrc_plus') is not None and ok_h) else None, '100 = league average in the app.'),
             ('xwOBA', f3(hit.get('xwoba')), 'Expected weighted on-base average from contact quality, strikeouts and walks.'),
             ('K%', f"{100 * hit['k'] / hit['pa']:.1f}%" if hit.get('pa') else None, 'Strikeouts per plate appearance.'),
             ('BB%', f"{100 * hit['bb'] / hit['pa']:.1f}%" if hit.get('pa') else None, 'Walks per plate appearance.')]
    return {'pit': P, 'hit': H, 'cov_p': pit.get('tag_cov'), 'cov_h': hit.get('tag_cov'), 'ok_p': ok_p, 'ok_h': ok_h}


def _games(program, win, today):
    import gamereport as gr
    import schedule as sched
    import season
    played = []
    for gid, gm in gr.collect(program).items():
        if not season.in_window(gm['date'], win):
            continue
        try:
            m = gr.build(gm['rows'])
        except Exception:
            continue
        partial = not (m['pitchers']['us'] and m['pitchers']['opp'])
        played.append({'gid': gid, 'date': gm['date'], 'date_s': _fmt_date(gm['date']), 'opp': gm['opp'], 'us': m['score']['us'], 'them': m['score']['opp'],
                       'partial': partial})
    played.sort(key=lambda x: x['date'])
    w = sum(1 for g in played if g['us'] > g['them'])
    l_ = sum(1 for g in played if g['us'] < g['them'])
    t = len(played) - w - l_
    form = ['W' if g['us'] > g['them'] else ('L' if g['us'] < g['them'] else 'T') for g in played[-10:]]
    _m, rest = sched.split(program, played)
    upcoming = [dict(s, date_s=_fmt_date(s['date'])) for s in rest if s['date'] >= today.isoformat()][:5]
    return {'played': played[::-1], 'w': w, 'l': l_, 't': t, 'form': form, 'last': played[-1] if played else None, 'upcoming': upcoming}


# ------------------------------------------------------------------ page
def build(program, mode_info, url, hitting_ok=True, today=None):
    import season
    today = today or datetime.date.today()
    win = season.window(program)
    return _build(program, mode_info['mode'], url, hitting_ok, win, today.isoformat())


@cache.memo
def _build(program, mode, url, hitting_ok, win, today_s):
    import season
    today = datetime.date.fromisoformat(today_s)
    ps = team._pitchers(program, win)
    P = team.pitching_data(program)
    hs = team._hitters(program, True, win) if hitting_ok else {}
    H = team.hitting_data(program, True) if hitting_ok else None
    sel = season.selected(program)
    dates = sorted(set(P['sessions']) | set(H['sessions'] if H else []))
    out = {'mode': mode, 'season_label': sel.get('label') or '', 'n_pitchers': P['n_players'], 'n_hitters': H['n_players'] if H else 0,
           'n_pitches': P['n_pitches'], 'n_seen': H['n_pitches'] if H else 0, 'n_sessions': len(dates),
           'first': _fmt_date(dates[0]) if dates else None, 'last': _fmt_date(dates[-1]) if dates else None, 'hitting_ok': hitting_ok}
    out['calendar'] = _calendar(ps, hs, sel.get('start'), today)
    out['goals'] = _goals(program, P, H, today)
    out['attention'] = _attention(program, P, ps, H, hs, mode, today)
    out['pbs'] = [dict(ev, url=url(ev['kind'], ev['key']), date_s=_fmt_date(ev['date'])) for ev in prs.program_recent(program, days=120, limit=200)
                  if ev['kind'] == 'p' or hitting_ok][:8]

    # team numbers week by week (pooled)
    wk_p, wk_h = {}, {}
    for _s, _b, outs in ps:
        for o in outs:
            d = _d(o['date'])
            if d:
                wk_p.setdefault(_week_start(d), []).extend(o['rows'])
    for h in hs.values():
        for p in h['pitches']:
            d = _d(p.get('date'))
            if d:
                wk_h.setdefault(_week_start(d), []).append(p)
    cp, chh = {}, {}

    def pfn(rows, sid):
        if len(rows) < 30:
            return None
        k = id(rows)
        if k not in cp:
            cp[k] = stats_mod.compute(rows)
        v = cp[k].get(sid)
        return _num(v[0]) if v else None

    def hfn(ps_, sid):
        if len(ps_) < 30:
            return None
        k = id(ps_)
        if k not in chh:
            chh[k] = hitting.hitter_stats(ps_)
        v = chh[k].get(sid)
        return v if isinstance(v, (int, float)) else None

    def snap(D, ids, low, fn, wk):
        rows = []
        W = _weekly(wk, fn, ids, {i for i in ids if i not in low})
        for sid in ids:
            t = D['tiles'].get(sid) if D else None
            if not t:
                continue
            w = W[sid]
            rows.append({'label': t['label'], 'value': t['value'], 'def': t.get('definition') or '', 'spark': w['spark'], 'weeks': w['n']})
        return rows

    if mode == 'dev':
        out['snap_p'] = snap(P, ['strike_pct', 'csw_pct', 'fb_velo', 'whiff_pct'], set(), pfn, wk_p)
        out['snap_h'] = snap(H, ['chase_pct', 'hard_hit_pct', 'avg_ev', 'score'], {'chase_pct'}, hfn, wk_h) if H else []
        gp = _gain_rows(P['players'], DEV_P, 'p', url)
        gh = _gain_rows(H['players'], DEV_H, 'h', url) if H else []
        gains = []
        for r in gp + gh:
            if r['best'] and r['best'][1]['score'] >= 1:
                mid, c = r['best']
                lab, unit, _t, _u = (DEV_P if r['kind'] == 'p' else DEV_H)[mid]
                gains.append({'name': r['name'], 'url': r['url'], 'kind': r['kind'], 'label': lab, 'from': _fmt_metric(mid, c['from'], unit),
                              'to': _fmt_metric(mid, c['to'], unit), 'delta': _fmt_delta(mid, c['delta'], unit), 'score': c['score'], 'spark': c['spark']})
        gains.sort(key=lambda g: -g['score'])
        out['gains'] = gains[:6]

        def board(rows, metrics):
            res = []
            for r in rows:
                cells = []
                for mid, (lab, unit, thr, up) in metrics.items():
                    c = r['cells'].get(mid)
                    cells.append(None if not c else {'to': _fmt_metric(mid, c['to'], unit), 'delta': _fmt_delta(mid, c['delta'], unit),
                                                     'cls': 'up' if c['score'] >= 1 else ('dn' if c['score'] <= -1 else 'eq')})
                res.append({'name': r['name'], 'url': r['url'], 'cells': cells, 'sessions': r['sessions'],
                            'sort': max((c['score'] for c in r['cells'].values()), default=0)})
            res.sort(key=lambda x: -x['sort'])
            return {'cols': [m[0] for m in metrics.values()], 'rows': res}
        out['board_p'] = board(gp, DEV_P)
        out['board_h'] = board(gh, {k: v for k, v in DEV_H.items() if k != 'avg_bs' or any('avg_bs' in r['cells'] for r in gh)}) if H else None
        out['arsenal'] = _arsenal_changes(ps, url)[:6]
        out['ready'] = _readiness(program, ps, hs)
        out['ready_done'] = sum(1 for c in out['ready'] if c['ok'])
    else:
        out['games'] = _games(program, win, today)
        out['line'] = _season_line(ps, hs)
        out['snap_p'] = snap(P, ['csw_pct', 'strike_pct', 'whiff_pct'], set(), pfn, wk_p)
        out['snap_h'] = snap(H, ['xba', 'hard_hit_pct', 'chase_pct'], {'chase_pct'}, hfn, wk_h) if H else []
        out['bullpen'] = _bullpen(ps, today, url)
        out['rest_rule'] = REST_RULE
        # hot and cold over the last 7 days of data
        newest = max([_d(x) for x in dates if _d(x)] or [today])
        cut = newest - datetime.timedelta(days=6)
        hot = []
        for p in (H['players'] if H else []):
            rec = [r for r in p['series'] if _d(r['date']) and _d(r['date']) >= cut and r.get('avg_ev') is not None]
            base = [r for r in p['series'] if _d(r['date']) and _d(r['date']) < cut and r.get('avg_ev') is not None]
            if rec and len(base) >= 2:
                a, b = sum(r['avg_ev'] for r in base) / len(base), sum(r['avg_ev'] for r in rec) / len(rec)
                hot.append({'name': p['name'], 'url': url('h', p['key']), 'kind': 'Hitter', 'metric': 'Avg exit velo', 'from': f'{a:.1f}', 'to': f'{b:.1f}', 'd': b - a, 'unit': ' mph', 'thr': 1.5})
        for p in P['players']:
            rec = [r for r in p['series'] if _d(r['date']) and _d(r['date']) >= cut and r.get('strike_pct') is not None]
            base = [r for r in p['series'] if _d(r['date']) and _d(r['date']) < cut and r.get('strike_pct') is not None]
            if rec and len(base) >= 2:
                a, b = sum(r['strike_pct'] for r in base) / len(base), sum(r['strike_pct'] for r in rec) / len(rec)
                hot.append({'name': p['name'], 'url': url('p', p['key']), 'kind': 'Pitcher', 'metric': 'Strike %', 'from': f'{a:.1f}%', 'to': f'{b:.1f}%', 'd': b - a, 'unit': ' pts', 'thr': 4.0})
        out['hot'] = sorted([x for x in hot if x['d'] >= x['thr']], key=lambda x: -x['d'] / x['thr'])[:5]
        out['cold'] = sorted([x for x in hot if x['d'] <= -x['thr']], key=lambda x: x['d'] / x['thr'])[:5]
        out['week_label'] = f'{_fmt_date(cut.isoformat())} – {_fmt_date(newest.isoformat())}'
        # next opponents: the schedule first, then the opponents scouted most recently
        try:
            import scouting
            opps = scouting.opponents(program)
            sc = sorted(((max(o['dates']) if o['dates'] else '', k, o['label'], len(o['hitters']), len(o['pitchers'])) for k, o in opps.items() if k != 'unlabeled'), reverse=True)
            out['scout'] = [{'slug': k, 'label': lab, 'last': _fmt_date(d), 'nh': nh, 'np': np_} for d, k, lab, nh, np_ in sc[:5]]
        except Exception:
            out['scout'] = []
    return out
