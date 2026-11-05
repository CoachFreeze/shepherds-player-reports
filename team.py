"""
Team Dashboard data: team-level stats, leaderboards, risers/decliners and goals, for the pitching and hitting halves.

Pitching comes from each pitcher's stored Trackman outings (stats.compute), hitting from every batter's pitches
(hitting.hitter_stats). Everything is computed on request from the stored rows, so a new upload shows up immediately.
Per-program choices (which stat tiles to show, the goals list) live in data/team/<program>.json and are committed to
GitHub like the rosters, so they survive Render's filesystem resets.
"""
import datetime
import json
import os
import re
import uuid

import cache
import github_sync
import hitting
import outings as outings_mod
import stats as stats_mod
import store

TEAM_DIR = os.path.join(store.DATA_DIR, 'team')

# ------------------------------------------------------------------ catalogs
# Hitting stats a program can put on its team dashboard: id -> (label, group, definition, kind). kind picks the formatting.
HIT_CATALOG = {
    'avg_ev': ('Avg Exit Velo', 'Contact quality', 'Average exit velocity on balls in play (mph).', 'mph'),
    'max_ev': ('Max Exit Velo', 'Contact quality', 'Hardest ball hit (mph).', 'mph'),
    'ev90': ('EV90', 'Contact quality', 'Exit velocity of the 90th-percentile batted ball (mph).', 'mph'),
    'hard_hit_pct': ('Hard-Hit %', 'Contact quality', 'Balls in play at 95+ mph.', 'pct'),
    'sweet_spot_pct': ('Sweet Spot %', 'Contact quality', 'Balls in play with a launch angle of 8-32 degrees.', 'pct'),
    'xba': ('xBA', 'Contact quality', 'Expected batting average from exit velocity and launch angle.', 'avg'),
    'avg_la': ('Avg Launch Angle', 'Contact quality', 'Average launch angle on balls in play (degrees).', 'deg'),
    'qab_pct': ('Quality AB %', 'Plate discipline', 'Quality at-bats / plate appearances. A quality at-bat is a hit, a walk or HBP, a ball hit 95+ mph, or a 6+ pitch plate appearance. Needs 5 finished plate appearances.', 'pct'),
    'score': ('Swing Decision Rating', 'Plate discipline', 'Overall swing-decision score, 0-100.', 'int'),
    'chase_pct': ('Chase %', 'Plate discipline', 'Swings at pitches outside the zone. Lower is better.', 'pct'),
    'zone_swing_pct': ('Zone Swing %', 'Plate discipline', 'Swings at pitches in the zone.', 'pct'),
    'swing_pct': ('Swing %', 'Plate discipline', 'Swings / pitches seen.', 'pct'),
    'whiff_pct': ('Whiff %', 'Plate discipline', 'Swings and misses / swings. Lower is better.', 'pct'),
    'zone_contact_pct': ('Zone Contact %', 'Plate discipline', 'Contact on swings at pitches in the zone.', 'pct'),
    'brl_pct': ('Barrel %', 'Contact quality', 'Balls in play that were barrels (98+ mph at the launch angles that have historically produced .500+ AVG and 1.500+ SLG).', 'pct'),
    'gb_pct': ('Ground Ball %', 'Batted-ball mix', 'Share of balls in play that are ground balls (launch angle under 10 degrees).', 'pct'),
    'ld_pct': ('Line Drive %', 'Batted-ball mix', 'Share of balls in play that are line drives (10-25 degrees).', 'pct'),
    'fb_pct': ('Fly Ball %', 'Batted-ball mix', 'Share of balls in play that are fly balls (25-50 degrees).', 'pct'),
    'pu_pct': ('Pop-Up %', 'Batted-ball mix', 'Share of balls in play that are pop-ups (over 50 degrees).', 'pct'),
    'pull_pct': ('Pull %', 'Batted-ball mix', 'Share of balls in play pulled.', 'pct'),
    'avg_bs': ('Avg Bat Speed', 'Swing tracking', 'Average bat speed on tracked swings (mph). Needs a bat-tracking system such as Full Swing.', 'mph'),
    'max_bs': ('Max Bat Speed', 'Swing tracking', 'Fastest tracked swing (mph).', 'mph'),
    'sq_pct': ('Squared-Up %', 'Swing tracking', 'Average squared-up rate on balls in play: how close the ball came to the exit velocity that swing could have produced.', 'pct'),
    'avg_smash': ('Avg Smash Factor', 'Swing tracking', 'Exit velocity divided by bat speed on balls in play. Higher means more of the swing went into the ball.', 'x2'),
    'ev_gap': ('EV Left On The Table', 'Swing tracking', 'Average gap between the exit velocity the swing could have produced and what the ball actually did (mph). Lower is better.', 'mph'),
    'pitches': ('Pitches Seen', 'Volume', 'Total pitches the team has seen.', 'int'),
    'bip': ('Balls In Play', 'Volume', 'Total balls put in play.', 'int'),
}
# The Basic view of the Hitters stat sheet, in this order: id -> (label, abbreviation, definition, kind). Values come from hitting.basic_stats (xBA from hitter_stats).
BASIC_HIT = [
    ('b_pa', 'Plate Appearances', 'PA', 'Finished plate appearances: a ball in play, walk, hit-by-pitch or strikeout. A ball in play with no result (no tag, and no Trackman PlayResult) is left out of every stat on this line, so these cover the at-bats whose result is known.', 'int'),
    ('b_ab', 'At Bats', 'AB', 'Plate appearances minus walks, hit-by-pitch and sacrifices.', 'int'),
    ('b_h', 'Hits', 'H', 'Hits, from the result of each ball in play (tag or Trackman PlayResult). A ball in play with no result is left out.', 'int'),
    ('b_bb', 'Walks', 'BB', 'Walks, from the count.', 'int'),
    ('b_hbp', 'Hit By Pitch', 'HBP', 'Times hit by a pitch.', 'int'),
    ('b_k', 'Strikeouts', 'K', 'Strikeouts, from the count.', 'int'),
    ('b_bb_pct', 'Walk %', 'BB%', 'Walks / plate appearances.', 'pct'),
    ('b_k_pct', 'Strikeout %', 'K%', 'Strikeouts / plate appearances.', 'pct'),
    ('b_avg', 'Batting Average', 'AVG', 'Hits / at bats. At-bats whose ball in play has no result are left out.', 'avg'),
    ('b_obp', 'On Base Percentage', 'OBP', '(Hits + walks + hit-by-pitch) / (at bats + walks + hit-by-pitch). At-bats whose ball in play has no result are left out.', 'avg'),
    ('b_slg', 'Slugging Percentage', 'SLG', 'Total bases / at bats. At-bats whose ball in play has no result are left out.', 'avg'),
    ('b_ops', 'On Base Plus Slugging', 'OPS', 'On-base percentage plus slugging percentage. At-bats whose ball in play has no result are left out.', 'avg'),
    ('xba', 'xBA', 'xBA', 'Expected batting average from exit velocity and launch angle.', 'avg'),
    ('b_2b', 'Doubles', '2B', 'Doubles. At-bats whose ball in play has no result are left out.', 'int'),
    ('b_3b', 'Triples', '3B', 'Triples. At-bats whose ball in play has no result are left out.', 'int'),
    ('b_hr', 'Home Runs', 'HR', 'Home runs. At-bats whose ball in play has no result are left out.', 'int'),
]
HIT_DEFAULT = ['avg_ev', 'hard_hit_pct', 'xba', 'score', 'chase_pct', 'whiff_pct']

PITCH_IDS = ['avg_velo', 'avg_spin', 'max_spin', 'fb_velo', 'fb_top', 'top_velo', 'fb_spin', 'strike_pct', 'fps_pct', 'zone_pct', 'ahead_pct', 'whiff_pct', 'csw_pct',
             'chase_pct', 'avg_ev', 'hh_pct', 'brl_pct', 'gb_pct', 'ld_pct', 'fb_pct', 'pu_pct', 'pitches', 'ks']
# Full Swing programs (see store.is_fullswing): no location, pitch type or counts, so the dashboard leans on what Full Swing measures.
# Live At Bat outcomes are predicted from the batted ball, not actual results.
HIT_DEFAULT_FS = ['avg_bs', 'avg_ev', 'hard_hit_pct', 'sq_pct', 'xba', 'whiff_pct']
PITCH_DEFAULT_FS = ['avg_velo', 'top_velo', 'avg_spin', 'whiff_pct', 'avg_ev', 'hh_pct']
HIT_TREND_FS = {'avg_ev': ('Avg exit velo', ' mph', 1.5), 'avg_bs': ('Avg bat speed', ' mph', 1.5), 'sq_pct': ('Squared-up %', '%', 5.0)}
PITCH_TREND_FS = {'avg_velo': ('Avg velo', ' mph', 0.8), 'avg_spin': ('Avg spin', ' rpm', 60.0), 'whiff_pct': ('Whiff %', '%', 5.0)}
PITCH_DEFAULT = ['fb_velo', 'strike_pct', 'fps_pct', 'whiff_pct', 'csw_pct', 'chase_pct']

# Metrics tracked session-to-session for risers/decliners: id -> (label, unit, "meaningful change", minimum sample key)
HIT_TREND = {'avg_ev': ('Avg exit velo', ' mph', 1.5), 'xba': ('xBA', '', 0.030), 'score': ('Swing decision rating', '', 6.0)}
PITCH_TREND = {'fb_velo': ('Fastball velo', ' mph', 0.8), 'strike_pct': ('Strike %', '%', 4.0), 'whiff_pct': ('Whiff %', '%', 5.0)}


def _num(s):
    try:
        return float(re.sub(r'[^0-9.\-]', '', str(s)))
    except Exception:
        return None


def _fmt_hit(kind, v):
    if v is None:
        return '—'
    if kind == 'avg':
        return f'{v:.3f}'.lstrip('0')
    if kind == 'mph':
        return f'{v:.1f}'
    if kind == 'x2':
        return f'{v:.2f}'
    if kind == 'deg':
        return f'{v:.1f}°'
    if kind == 'pct':
        return f'{v:.1f}%'
    return f'{v:.0f}'


# ------------------------------------------------------------------ storage
def _path(program):
    return os.path.join(TEAM_DIR, f'{program}.json')


def load(program):
    p = _path(program)
    data = {}
    if os.path.exists(p):
        try:
            with open(p, encoding='utf-8') as f:
                data = json.load(f)
        except Exception:
            data = {}
    fs = store.is_fullswing(program)
    data.setdefault('hitting_stats', list(HIT_DEFAULT_FS if fs else HIT_DEFAULT))
    data.setdefault('pitching_stats', list(PITCH_DEFAULT_FS if fs else PITCH_DEFAULT))
    data.setdefault('goals', [])
    return data


def save(program, data):
    os.makedirs(TEAM_DIR, exist_ok=True)
    text = json.dumps(data, separators=(',', ':'), ensure_ascii=False)
    with open(_path(program), 'w', encoding='utf-8') as f:
        f.write(text)
    github_sync.put_file(f'data/team/{program}.json', text.encode('utf-8'))


def set_stats(program, side, ids):
    d = load(program)
    valid = HIT_CATALOG if side == 'hitting' else None
    if side == 'hitting':
        ids = [i for i in ids if i in HIT_CATALOG]
        d['hitting_stats'] = ids or list(HIT_DEFAULT)
    else:
        ids = [i for i in ids if i in PITCH_IDS]
        d['pitching_stats'] = ids or list(PITCH_DEFAULT)
    save(program, d)


def add_goal(program, f):
    d = load(program)
    side = 'hitting' if f.get('side') == 'hitting' else 'pitching'
    try:
        target = float(f.get('target'))
    except Exception:
        return None
    title = (f.get('title') or '').strip()
    metric = (f.get('metric') or '').strip() or None
    cat = HIT_CATALOG if side == 'hitting' else None
    if metric and not ((side == 'hitting' and metric in HIT_CATALOG) or (side == 'pitching' and metric in PITCH_IDS)):
        metric = None
    if not title:
        title = (HIT_CATALOG[metric][0] if side == 'hitting' else stats_mod.label_for(metric)[0]) if metric else 'Team goal'
    g = {'id': uuid.uuid4().hex[:8], 'side': side, 'kind': 'process' if f.get('kind') == 'process' else 'result', 'title': title[:90],
         'metric': metric, 'cmp': 'le' if f.get('cmp') == 'le' else 'ge', 'target': target, 'due': (f.get('due') or '')[:10] or None,
         'current': None, 'done': False, 'created': datetime.date.today().isoformat(), 'baseline': None}
    if metric:
        cur = (team_values(program, side) or {}).get(metric)
        g['baseline'] = cur['num'] if cur else None
    d['goals'].append(g)
    save(program, d)
    return g


def update_goal(program, gid, f):
    d = load(program)
    for g in d['goals']:
        if g['id'] != gid:
            continue
        act = f.get('action')
        if act == 'toggle':
            g['done'] = not g.get('done')
        elif act == 'progress':
            try:
                g['current'] = float(f.get('current'))
            except Exception:
                pass
        save(program, d)
        return True
    return False


def delete_goal(program, gid):
    d = load(program)
    n = len(d['goals'])
    d['goals'] = [g for g in d['goals'] if g['id'] != gid]
    if len(d['goals']) != n:
        save(program, d)
        return True
    return False


# ------------------------------------------------------------------ pitching
def _pitchers(program):
    """[(slug, bio, [outings newest first])] for a program's pitchers that have stored data."""
    out = []
    for slug, bio in store.list_players_view().items():
        if (bio.get('program') or 'shepherds') != program:
            continue
        outs = outings_mod.outings(slug)
        if outs:
            out.append((slug, bio, outs))
    return out


def _pitch_session_series(outs, trend=None):
    """Oldest-first list of {'date', 'fb_velo', 'strike_pct', 'whiff_pct', 'n'} per outing (None when the sample is too thin)."""
    res = []
    for o in sorted(outs, key=lambda x: x['date']):
        v = stats_mod.compute(o['rows'])
        n = len(o['rows'])
        row = {'date': o['date'], 'n': n}
        for k in (trend or PITCH_TREND):
            row[k] = _num(v[k][0]) if (k in v and n >= 15) else None
        res.append(row)
    return res


@cache.memo
def pitching_data(program):
    return pitching_from(_pitchers(program), fs=store.is_fullswing(program))


def pitching_from(ps, fs=False):
    """Team pitching numbers for [(key, bio {'name'}, [outings newest first])]: used for a program's own pitchers and for scouting an opponent."""
    all_rows = [r for _, _, outs in ps for o in outs for r in o['rows']]
    vals = stats_mod.compute(all_rows) if all_rows else {}
    tiles_all = {}
    for sid in PITCH_IDS:
        if sid in vals:
            lab, d = stats_mod.label_for(sid)
            tiles_all[sid] = {'id': sid, 'label': lab, 'value': vals[sid][0], 'detail': vals[sid][1], 'definition': d, 'num': _num(vals[sid][0])}
    players = []
    for slug, bio, outs in ps:
        rows = [r for o in outs for r in o['rows']]
        v = stats_mod.compute(rows)
        players.append({'key': slug, 'name': bio.get('name', slug), 'v': v, 'n': len(rows), 'series': _pitch_session_series(outs, PITCH_TREND_FS if fs else None),
                        'sessions': len(outs)})
    boards = []
    if fs:
        def _num_board(sid, title, sub, unit, fmt, min_n=15, reverse=True):
            got = [(p, _num(p['v'][sid][0])) for p in players if sid in p['v'] and p['n'] >= min_n and _num(p['v'][sid][0]) is not None]
            boards.append({'title': title, 'sub': sub, 'unit': unit,
                           'rows': [{'key': p['key'], 'name': p['name'], 'value': fmt(v), 'extra': f"{p['n']} pitches"} for p, v in sorted(got, key=lambda x: -x[1] if reverse else x[1])[:5]]})
        _num_board('avg_velo', 'Average Velocity', 'All pitches, min. 15 pitches', 'mph', lambda v: f'{v:.1f}')
        _num_board('top_velo', 'Top Velocity', 'Fastest pitch, min. 15 pitches', 'mph', lambda v: f'{v:.1f}')
        _num_board('avg_spin', 'Average Spin Rate', 'All pitches, min. 15 pitches', 'rpm', lambda v: f'{v:.0f}')
        _num_board('whiff_pct', 'Whiff %', 'Swings and misses / swings, min. 15 pitches', '%', lambda v: f'{v:.1f}%')
        return {'players': players, 'tiles': tiles_all, 'boards': boards, 'n_players': len(players), 'n_pitches': len(all_rows),
                'sessions': sorted({o['date'] for _, _, outs in ps for o in outs}), 'trend': _trends(players, PITCH_TREND_FS, 'pitch')}
    fb = [(p, _num(p['v']['fb_velo'][0]), _num(p['v'].get('fb_top', ('', ''))[0])) for p in players if 'fb_velo' in p['v'] and p['n'] >= 15 and _num(p['v']['fb_velo'][0]) is not None]
    boards.append({'title': 'Fastball velocity', 'sub': 'Average, min. 15 pitches', 'unit': 'mph',
                   'rows': [{'key': p['key'], 'name': p['name'], 'value': f'{a:.1f}', 'extra': f'top {t:.1f}' if t else ''}
                            for p, a, t in sorted(fb, key=lambda x: -x[1])[:5]]})
    def _rate_board(sid, title, sub, min_den):
        got = []
        for p in players:
            if sid not in p['v']:
                continue
            val, det = p['v'][sid]
            m = re.match(r'\s*(\d+)\s*/\s*(\d+)', str(det or ''))
            if _num(val) is None or not m or int(m.group(2)) < min_den:
                continue
            got.append((p, _num(val), det))
        boards.append({'title': title, 'sub': sub, 'unit': '%',
                       'rows': [{'key': p['key'], 'name': p['name'], 'value': f'{v:.1f}%', 'extra': det}
                                for p, v, det in sorted(got, key=lambda x: -x[1])[:5]]})
    _rate_board('strike_pct', 'Strike %', 'Strikes / pitches, min. 15 pitches', 15)
    _rate_board('fps_pct', 'First-pitch strike %', 'Strikes on 0-0, min. 5 first pitches', 5)
    _rate_board('whiff_pct', 'Whiff %', 'Swinging strikes / swings, min. 10 swings', 10)
    return {'players': players, 'tiles': tiles_all, 'boards': boards, 'n_players': len(players), 'n_pitches': len(all_rows),
            'sessions': sorted({o['date'] for _, _, outs in ps for o in outs}), 'trend': _trends(players, PITCH_TREND, 'pitch')}


# ------------------------------------------------------------------ hitting
def _hitters(program, include_demo):
    return {k: h for k, h in hitting._collect(include_demo).items() if h['program'] == program}


def _hit_session_series(pitches):
    by = {}
    for p in pitches:
        if p['date']:
            by.setdefault(p['date'], []).append(p)
    res = []
    for d in sorted(by):
        s = hitting.hitter_stats(by[d])
        res.append({'date': d, 'n': len(by[d]),
                    'avg_ev': s['avg_ev'] if s['bip'] >= 3 else None,
                    'xba': s['xba'] if (s['ab'] or 0) >= 5 else None,
                    'score': s['score'] if s['decisions'] >= 10 else None,
                    'avg_bs': s.get('avg_bs') if (s.get('bs_n') or 0) >= 5 else None,
                    'sq_pct': s.get('sq_pct') if (s.get('bs_n') or 0) >= 5 else None})
    return res


@cache.memo
def hitting_data(program, include_demo):
    return hitting_from(_hitters(program, include_demo), fs=store.is_fullswing(program))


def hitting_from(hs, fs=False):
    """Team hitting numbers for {key: {'name', 'pitches': [...]}}: a program's own hitters, or the hitters of an opponent being scouted."""
    all_p = [p for h in hs.values() for p in h['pitches']]
    s_all = hitting.hitter_stats(all_p) if all_p else None
    tiles_all = {}
    if s_all:
        for sid, (lab, grp, d, kind) in HIT_CATALOG.items():
            v = s_all.get(sid)
            if v is not None:
                tiles_all[sid] = {'id': sid, 'label': lab, 'value': _fmt_hit(kind, v), 'detail': '', 'definition': d, 'num': v}
    players = []
    for key, h in hs.items():
        s = hitting.hitter_stats(h['pitches'])
        players.append({'key': key, 'name': hitting.display_name(h['name']), 's': s, 'n': len(h['pitches']),
                        'series': _hit_session_series(h['pitches']), 'sessions': len({p['date'] for p in h['pitches'] if p['date']})})
    boards = []
    if fs:
        def _hboard(key, title, sub, unit, fmt, ok, extra):
            got = [p for p in players if p['s'].get(key) is not None and ok(p)]
            boards.append({'title': title, 'sub': sub, 'unit': unit,
                           'rows': [{'key': p['key'], 'name': p['name'], 'value': fmt(p['s'][key]), 'extra': extra(p)} for p in sorted(got, key=lambda p: -p['s'][key])[:5]]})
        _hboard('avg_bs', 'Average Bat Speed', 'Tracked swings, min. 10 swings', 'mph', lambda v: f'{v:.1f}', lambda p: (p['s'].get('bs_n') or 0) >= 10,
                lambda p: f"max {p['s']['max_bs']:.1f}" if p['s'].get('max_bs') else '')
        _hboard('avg_ev', 'Average Exit Velocity', f'Balls in play, min. {hitting.RANK_MIN_BIP} balls in play', 'mph', lambda v: f'{v:.1f}',
                lambda p: (p['s']['bip'] or 0) >= hitting.RANK_MIN_BIP, lambda p: f"max {p['s']['max_ev']:.1f}" if p['s'].get('max_ev') else '')
        _hboard('sq_pct', 'Squared-Up %', 'Tracked swings, min. 10 swings', '%', lambda v: f'{v:.1f}%', lambda p: (p['s'].get('bs_n') or 0) >= 10, lambda p: '')
        _hboard('xba', 'Predicted xBA', 'Predicted from the batted ball, min. 5 at-bats', '', lambda v: f'{v:.3f}'.lstrip('0'), lambda p: (p['s']['ab'] or 0) >= 5, lambda p: f"{p['s']['ab']} AB")
        return {'players': players, 'tiles': tiles_all, 'boards': boards, 'n_players': len(players), 'n_pitches': len(all_p),
                'sessions': sorted({p['date'] for h in hs.values() for p in h['pitches'] if p['date']}),
                'trend': _trends(players, HIT_TREND_FS, 'hit')}
    ev = [p for p in players if p['s']['avg_ev'] is not None and (p['s']['bip'] or 0) >= hitting.RANK_MIN_BIP]
    boards.append({'title': 'Average Exit Velocity', 'sub': f'Average on balls in play, min. {hitting.RANK_MIN_BIP} balls in play', 'unit': 'mph',
                   'rows': [{'key': p['key'], 'name': p['name'], 'value': f"{p['s']['avg_ev']:.1f}",
                             'extra': f"max {p['s']['max_ev']:.1f}" if p['s']['max_ev'] is not None else ''} for p in sorted(ev, key=lambda p: -p['s']['avg_ev'])[:5]]})
    xb = [p for p in players if p['s']['xba'] is not None and (p['s']['ab'] or 0) >= 5]
    boards.append({'title': 'xBA', 'sub': 'Expected batting average, min. 5 at-bats', 'unit': '',
                   'rows': [{'key': p['key'], 'name': p['name'], 'value': f"{p['s']['xba']:.3f}".lstrip('0'),
                             'extra': f"{p['s']['ab']} AB"} for p in sorted(xb, key=lambda p: -p['s']['xba'])[:5]]})
    sd = [p for p in players if p['s']['score'] is not None and p['s']['decisions'] >= 15]
    boards.append({'title': 'Swing Decision Rating', 'sub': '0-100, min. 15 decisions', 'unit': '',
                   'rows': [{'key': p['key'], 'name': p['name'], 'value': f"{p['s']['score']:.0f}",
                             'extra': p['s']['grade'] or ''} for p in sorted(sd, key=lambda p: -p['s']['score'])[:5]]})
    br = [p for p in players if (p['s'].get('mix_n') or 0) > 0]
    boards.append({'title': 'Total barrels', 'sub': 'Barrels on balls in play', 'unit': '',
                   'rows': [{'key': p['key'], 'name': p['name'], 'value': str(p['s']['brl']),
                             'extra': f"{p['s']['brl_pct']:.1f}%" if isinstance(p['s'].get('brl_pct'), (int, float)) else str(p['s'].get('brl_pct') or '')}
                            for p in sorted(br, key=lambda p: (-p['s']['brl'], -(p['s']['mix_n'])))[:5] if p['s']['brl']]})
    return {'players': players, 'tiles': tiles_all, 'boards': boards, 'n_players': len(players), 'n_pitches': len(all_p),
            'sessions': sorted({p['date'] for h in hs.values() for p in h['pitches'] if p['date']}),
            'trend': _trends(players, HIT_TREND, 'hit')}


# ------------------------------------------------------------------ trends
def _trends(players, metrics, side):
    """Per player, per metric: recent sessions vs. the ones before. Risers = biggest improvements, decliners = biggest drops,
    each only if the move is at least one 'meaningful change' for that metric. Up to 3 of each."""
    found = []
    for p in players:
        best = []
        for mid, (label, unit, thr) in metrics.items():
            pts = [(r['date'], r[mid]) for r in p['series'] if r.get(mid) is not None]
            if len(pts) < 2:
                continue
            vals = [v for _, v in pts]
            if len(vals) >= 4:
                recent, base = sum(vals[-2:]) / 2, sum(vals[-6:-2]) / len(vals[-6:-2])
                span = 'last 2 sessions vs. the 4 before' if len(vals[-6:-2]) == 4 else f'last 2 sessions vs. the {len(vals[-6:-2])} before'
            else:
                recent, base = vals[-1], sum(vals[:-1]) / len(vals[:-1])
                span = 'latest session vs. earlier' if len(vals) > 2 else 'latest session vs. the one before'
            delta = recent - base
            best.append({'key': p['key'], 'name': p['name'], 'metric': mid, 'label': label, 'unit': unit, 'from': base, 'to': recent,
                         'delta': delta, 'score': delta / thr, 'span': span, 'spark': vals[-6:], 'sessions': len(vals)})
        found.extend(best)
    # one card per player: his single biggest move, in whichever direction it went
    top = {}
    for f in found:
        if abs(f['score']) >= 1 and abs(f['score']) > abs(top.get(f['key'], {}).get('score', 0)):
            top[f['key']] = f
    ups = {k: f for k, f in top.items() if f['score'] > 0}
    downs = {k: f for k, f in top.items() if f['score'] < 0}
    risers = sorted(ups.values(), key=lambda f: -f['score'])[:3]
    decl = sorted(downs.values(), key=lambda f: f['score'])[:3]
    for f in risers + decl:
        f['fmt'] = _fmt_trend(f, side)
        f['spark_svg'] = _spark(f['spark'], f['score'] > 0)
    return {'risers': risers, 'decliners': decl, 'have_history': any(len(p['series']) >= 2 for p in players)}


def _spark(vals, up):
    w, h, pad = 84, 26, 3
    lo, hi = min(vals), max(vals)
    rng = (hi - lo) or 1
    pts = [(pad + (w - 2 * pad) * i / max(1, len(vals) - 1), h - pad - (h - 2 * pad) * (v - lo) / rng) for i, v in enumerate(vals)]
    col = '#2f9e6b' if up else '#d0503f'
    line = ' '.join(f'{x:.1f},{y:.1f}' for x, y in pts)
    return (f'<svg viewBox="0 0 {w} {h}" width="{w}" height="{h}" aria-hidden="true"><polyline fill="none" stroke="{col}" stroke-width="2" '
            f'stroke-linejoin="round" stroke-linecap="round" points="{line}"/><circle cx="{pts[-1][0]:.1f}" cy="{pts[-1][1]:.1f}" r="3" fill="{col}"/></svg>')


def _fmt_trend(f, side):
    def v(x):
        if f['metric'] == 'xba':
            return f'{x:.3f}'.lstrip('0')
        if f['metric'] == 'score':
            return f'{x:.0f}'
        return f'{x:.1f}'
    d = f['delta']
    ds = (f'{d:+.3f}'.replace('0.', '.', 1) if f['metric'] == 'xba' else (f'{d:+.0f}' if f['metric'] == 'score' else f'{d:+.1f}'))
    return {'from': v(f['from']) + f['unit'], 'to': v(f['to']) + f['unit'], 'delta': ds + (f['unit'] if f['unit'] != '%' else ' pts')}


# ------------------------------------------------------------------ goals
def team_values(program, side, include_demo=True):
    """{metric id: {'num': float, 'value': display}} for the whole team's current numbers (used to track goals)."""
    d = pitching_data(program) if side == 'pitching' else hitting_data(program, include_demo)
    return d['tiles']


def goal_rows(program, side, tiles):
    out = []
    for g in load(program)['goals']:
        if g['side'] != side:
            continue
        cur, disp = None, None
        if g.get('metric'):
            t = tiles.get(g['metric'])
            if t:
                cur, disp = t['num'], t['value']
        else:
            cur = g.get('current')
            disp = None if cur is None else f'{cur:g}'
        tgt, ge = g['target'], g['cmp'] == 'ge'
        met = bool(g.get('done')) or (cur is not None and ((cur >= tgt) if ge else (cur <= tgt)))
        pct = None
        if met:
            pct = 100
        elif cur is not None:
            base = g.get('baseline')
            if base is None or base == tgt:
                base = 0 if ge else None
            if ge:
                pct = max(0, min(100, (cur - base) / (tgt - base) * 100)) if tgt != base else 0
            elif base is not None:
                pct = max(0, min(100, (base - cur) / (base - tgt) * 100)) if base != tgt else 0
            else:
                pct = max(0, min(100, tgt / cur * 100)) if cur else 100
        due = g.get('due')
        overdue = False
        if due and not met:
            try:
                overdue = datetime.date.fromisoformat(due) < datetime.date.today()
            except Exception:
                pass
        out.append({**g, 'cur': cur, 'disp': disp, 'met': met, 'pct': pct, 'overdue': overdue,
                    'target_disp': f'{tgt:g}', 'metric_label': (HIT_CATALOG[g['metric']][0] if side == 'hitting' else stats_mod.label_for(g['metric'])[0]) if g.get('metric') else None})
    out.sort(key=lambda g: (g['met'], g['due'] or '9999'))
    return out


def stat_picker(side, selected):
    """Groups for the 'customize' panel: [(group, [{id,label,definition,on}])]."""
    groups = {}
    if side == 'hitting':
        for sid, (lab, g, d, _) in HIT_CATALOG.items():
            groups.setdefault(g, []).append({'id': sid, 'label': lab, 'definition': d, 'on': sid in selected})
    else:
        for sid in PITCH_IDS:
            lab, d = stats_mod.label_for(sid)
            g = stats_mod.BASE[sid][1] if sid in stats_mod.BASE else 'Other'
            groups.setdefault(g, []).append({'id': sid, 'label': lab, 'definition': d, 'on': sid in selected})
    return list(groups.items())


def goal_metric_options(side):
    if side == 'hitting':
        return [(sid, v[0]) for sid, v in HIT_CATALOG.items()]
    return [(sid, stats_mod.label_for(sid)[0]) for sid in PITCH_IDS]


def swing_decision_page_data(program):
    """Every judged pitch the team's hitters saw, for the big plate view."""
    hs = _hitters(program, True)
    items, players = [], []
    for key, h in hs.items():
        nm = hitting.display_name(h['name'])
        players.append(nm)
        items += [(nm, p) for p in h['pitches']]
    items.sort(key=lambda x: x[0])
    svg, n = hitting.team_decision_chart_svg(items)
    s = hitting.hitter_stats([p for _, p in items]) if items else None
    return {'svg': svg, 'n': n, 'players': sorted(set(players), key=lambda x: x.split()[-1].lower()),
            'score': s['score'] if s else None, 'grade': s['grade'] if s else None}
