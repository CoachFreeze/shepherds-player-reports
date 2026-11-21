"""Game Recap: top performers and key plays for one game, from the built game model (gamereport.build).

Trackman has no baserunner data, so runners on base are inferred (gamereport.advance_runners). Every plate appearance carries its Win
Probability Added (winprob.game); key plays are the scoring plays, stranded threats and double plays plus any at-bat that swung the win
chance by WPA_KEY or more, and the top plays are the biggest swings.
"""
import gamereport as gr
import winprob

WPA_KEY = 0.10            # an at-bat that moves the win chance this much is a key play even without a run

HARD_HIT = 95.0
_VERB = {'Single': 'singled', 'Double': 'doubled', 'Triple': 'tripled', 'Walk': 'walked', 'HBP': 'was hit by a pitch',
         'Sacrifice': 'hit a sacrifice', 'Error': 'reached on an error', 'FieldersChoice': "reached on a fielder's choice",
         'K swinging': 'struck out swinging', 'K looking': 'struck out looking', 'In play': 'put the ball in play'}
_OUT = {'GroundBall': 'grounded out', 'FlyBall': 'flied out', 'LineDrive': 'lined out', 'Popup': 'popped out', 'Bunt': 'bunted out'}
_ORD = {1: '1st', 2: '2nd', 3: '3rd'}


def _ordinal(n):
    return _ORD.get(n, f'{n}th')


def _half(pa):
    return f"{'Top' if pa['tb'] == 0 else 'Bot'} {_ordinal(pa['inn'])}"


def _ip_outs(ip):
    w, _, f = str(ip).partition('.')
    return int(w or 0) * 3 + int(f or 0)


def _describe(pa):
    """'Jane Doe doubled (101 mph), 2 runs scored' style text for one plate appearance."""
    res = pa['result']
    who = gr._flip(pa['batter'])
    if res == 'HomeRun':
        n = pa['runs']
        verb = 'hit a grand slam' if n == 4 else ('hit a solo homer' if n <= 1 else f'hit a {n}-run homer')
    elif res == 'Out':
        verb = _OUT.get(pa.get('hit_type') or '', 'made an out')
        if pa['outs_made'] >= 2:
            verb = 'grounded into a double play' if pa.get('hit_type') == 'GroundBall' else 'hit into a double play'
    else:
        verb = _VERB.get(res, (res or '').lower())
    t = f'{who} {verb}'
    if pa.get('ev') and res not in ('Walk', 'HBP', 'K swinging', 'K looking'):
        t += f" ({pa['ev']:.0f} mph)"
    if pa['runs'] and res != 'HomeRun':
        t += f", {pa['runs']} run{'s' if pa['runs'] > 1 else ''} scored"
    return t


def _bases_text(on):
    on = on or (False, False, False)
    if all(on):
        return 'bases loaded'
    names = [b for b, x in zip(('1st', '2nd', '3rd'), on) if x]
    if not names:
        return 'bases empty'
    return 'runner on ' + names[0] if len(names) == 1 else 'runners on ' + ' and '.join(names)


def key_plays(m, names):
    """Every play worth a line, oldest first: [{'half','text','tag','score','impact','bat','pitcher','ctx'}]."""
    last = m['innings'] or 9
    late = max(7, last - 2)
    out = []
    run = {'us': 0, 'opp': 0}
    for pa in m['pas']:
        if pa['result'] is None:
            continue
        bat = pa['bat']
        oth = 'opp' if bat == 'us' else 'us'
        before = pa['margin']
        run[bat] += pa['runs']
        after = run[bat] - run[oth]
        on = pa.get('on_before') or (False, False, False)
        risp = on[1] or on[2]
        ended = pa['outs'] + pa['outs_made'] >= 3
        tag, imp = None, 0.0
        if pa['runs']:
            imp = 2.0 * pa['runs']
            if before <= 0 < after:
                tag, imp = 'Go-ahead', imp + 3
            elif before < 0 == after:
                tag, imp = 'Tying', imp + 2.5
            elif pa['result'] == 'HomeRun':
                tag = 'Home run'
            else:
                tag = 'Scoring play'
            if pa['result'] == 'HomeRun':
                imp += 1
        elif risp and pa['result'] in ('Out', 'K swinging', 'K looking') and (ended or pa['outs_made'] >= 2) and abs(before) <= 3:
            tag = 'Double play' if pa['outs_made'] >= 2 else 'Stranded'
            imp = 2.0 + (1 if all(on) else 0) + (0.5 if pa['result'].startswith('K') else 0)
        elif pa['outs_made'] >= 2 and any(on) and abs(before) <= 3:
            tag, imp = 'Double play', 2.0
        elif pa['result'] in ('Double', 'Triple') and (pa.get('ev') or 0) >= 100:
            tag, imp = 'Extra-base hit', 1.0
        w = pa.get('wpa')
        if not tag and w is not None and abs(w) >= WPA_KEY:
            tag, imp = 'Big swing', 1.0
        if not tag:
            continue
        if pa['inn'] >= late:
            imp += 1.5
        if abs(before) >= 6:
            imp *= 0.5
        lead = 'tied' if run['us'] == run['opp'] else None
        score = f"{names['us']} {run['us']}, {names['opp']} {run['opp']}"
        out.append({'half': _half(pa), 'inn': pa['inn'], 'tb': pa['tb'], 'text': _describe(pa), 'tag': tag, 'impact': round(imp, 1), 'bat': bat,
                    'pitcher': gr._flip(pa['pitcher']), 'ctx': f"{_bases_text(on)}, {pa['outs']} out{'' if pa['outs'] == 1 else 's'}",
                    'score': score + (' (tied)' if lead else ''), 'wpa': w, 'swing_no': pa.get('swing_no'),
                    'good': ((w > 0) == (bat == 'us')) if w is not None else (bat == 'us' if pa['runs'] or tag == 'Extra-base hit' else bat != 'us')})
    return out


def _hitter_lines(m, side):
    rows = []
    for ent in m['teams'][side]['slots']:
        ps = [p for p in ent['pas'] if p['result']]
        if not ps:
            continue
        cnt = {k: sum(1 for p in ps if p['result'] == k) for k in ('Double', 'Triple', 'HomeRun', 'Walk', 'HBP')}
        runs = sum(1 for p in ent['pas'] if p.get('scored'))
        evs = [p['ev'] for p in ps if p.get('ev')]
        hard = sum(1 for e in evs if e >= HARD_HIT)
        tb = ent['h'] + cnt['Double'] + 2 * cnt['Triple'] + 3 * cnt['HomeRun']
        score = tb + 0.8 * (cnt['Walk'] + cnt['HBP']) + ent['rbi'] + runs - 0.25 * ent['k'] + 0.5 * hard
        bits = [f"{ent['h']}-for-{ent['ab']}"]
        for k, lab in (('Double', '2B'), ('Triple', '3B'), ('HomeRun', 'HR')):
            if cnt[k]:
                bits.append(f"{cnt[k]} {lab}" if cnt[k] > 1 else lab)
        if ent['rbi']:
            bits.append(f"{ent['rbi']} RBI")
        if runs:
            bits.append(f"{runs} R" if runs > 1 else 'R')
        if cnt['Walk']:
            bits.append(f"{cnt['Walk']} BB" if cnt['Walk'] > 1 else 'BB')
        if cnt['HBP']:
            bits.append('HBP')
        ws = [p['wpa'] for p in ps if p.get('wpa') is not None]
        rows.append({'name': gr._flip(ent['name']), 'raw': ent['name'], 'line': ', '.join(bits), 'score': round(score, 2), 'wpa': sum(ws) if ws else None,
                     'max_ev': max(evs) if evs else None, 'hard': hard, 'kind': 'h'})
    return sorted(rows, key=lambda r: -r['score'])


def _pitcher_lines(m, side):
    rows = []
    for p in m['pitchers'][side]:
        if not p['bf']:
            continue
        outs = _ip_outs(p['ip'])
        gs = 40 + 2 * outs + p['k'] - 2 * p['bb'] - 2 * p['h'] - 3 * p['r'] - 6 * p['hr']      # game score, version 2
        line = f"{p['ip']} IP, {p['h']} H, {p['r']} R, {p['bb']} BB, {p['k']} K"
        ws = [-x['wpa'] for x in p['pas'] if x.get('wpa') is not None]
        rows.append({'name': p['name'], 'raw': p['raw'], 'slug': p['slug'], 'line': line, 'score': gs, 'np': p['np'], 'top': p['top'], 'wpa': sum(ws) if ws else None,
                     'strike_pct': p['strike_pct'], 'kind': 'p'})
    return sorted(rows, key=lambda r: -r['score'])


def performers(m):
    """{'us': {'hitters', 'pitchers'}, 'opp': {...}} with every player's line, best first."""
    return {s: {'hitters': _hitter_lines(m, s), 'pitchers': _pitcher_lines(m, s)} for s in ('us', 'opp')}


def summary(m, names, colors=None):
    wp = winprob.game(m)
    chart = winprob.chart_svg(m, wp, names, **({'colors': (colors['us'], colors['opp'])} if colors else {}))       # numbers the three biggest swings, so it runs before key_plays
    P = performers(m)
    plays = key_plays(m, names)
    top = sorted(plays, key=lambda x: -(abs(x['wpa']) if x['wpa'] is not None else x['impact'] / 100))[:5]
    top_ids = {id(x) for x in top}
    swings = sorted([pa for pa in m['pas'] if pa.get('swing_no')], key=lambda pa: pa['swing_no'])
    return {'perf': P, 'plays': plays, 'top_plays': [x for x in plays if id(x) in top_ids], 'chart': chart, 'wp_ok': wp['ok'],
            'swings': [{'no': pa['swing_no'], 'half': _half(pa), 'text': _describe(pa), 'wpa': pa['wpa'], 'bat': pa['bat'],
                        'good': (pa['wpa'] > 0) == (pa['bat'] == 'us')} for pa in swings],
            'wp_series': [{'v': round(v, 4), 'lab': (f"{_half(pa)}, {pa['outs']} out{'' if pa['outs'] == 1 else 's'}: {_describe(pa)}" if pa else 'Final'),
                           'w': (round(pa['wpa'] if pa['bat'] == 'us' else -pa['wpa'], 4) if pa and pa.get('wpa') is not None else None)}
                          for v, pa in wp['points']],
            'hits': {s: sum(1 for p in m['teams'][s]['pas'] if p['result'] in gr.HITS) for s in ('us', 'opp')},
            'errs': {s: sum(1 for p in m['teams']['opp' if s == 'us' else 'us']['pas'] if p['result'] == 'Error') for s in ('us', 'opp')}}
