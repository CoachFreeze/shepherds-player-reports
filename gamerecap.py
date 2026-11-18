"""Game Recap: top performers and key plays for one game, from the built game model (gamereport.build).

Trackman has no baserunner data, so runners on base are inferred (gamereport.advance_runners) and key plays are picked by a simple impact
score rather than true win probability: runs that score, go-ahead and tying runs, late innings, and threats that end with runners stranded.
"""
import gamereport as gr

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
                    'score': score + (' (tied)' if lead else ''), 'good': bat == 'us' if pa['runs'] or tag == 'Extra-base hit' else bat != 'us'})
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
        rows.append({'name': gr._flip(ent['name']), 'raw': ent['name'], 'line': ', '.join(bits), 'score': round(score, 2),
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
        rows.append({'name': p['name'], 'raw': p['raw'], 'slug': p['slug'], 'line': line, 'score': gs, 'np': p['np'], 'top': p['top'],
                     'strike_pct': p['strike_pct'], 'kind': 'p'})
    return sorted(rows, key=lambda r: -r['score'])


def performers(m):
    """{'us': {'hitters', 'pitchers'}, 'opp': {...}} with every player's line, best first."""
    return {s: {'hitters': _hitter_lines(m, s), 'pitchers': _pitcher_lines(m, s)} for s in ('us', 'opp')}


def summary(m, names):
    P = performers(m)
    plays = key_plays(m, names)
    top = sorted(plays, key=lambda x: -x['impact'])[:5]
    top_ids = {id(x) for x in top}
    return {'perf': P, 'plays': plays, 'top_plays': [x for x in plays if id(x) in top_ids],
            'hits': {s: sum(1 for p in m['teams'][s]['pas'] if p['result'] in gr.HITS) for s in ('us', 'opp')},
            'errs': {s: sum(1 for p in m['teams']['opp' if s == 'us' else 'us']['pas'] if p['result'] == 'Error') for s in ('us', 'opp')}}
