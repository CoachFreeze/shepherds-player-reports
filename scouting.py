"""Opponent scouting: the hitters our pitchers faced and the pitchers our hitters faced, grouped by the opponent
entered when a Game / Scrimmage CSV was uploaded. Private to the program that uploaded it."""
import cleanup
import hitting
import outings
import store


def _flip(n):
    last, _, first = (n or '').partition(', ')
    return f'{first} {last}'.strip() if first else (n or '')


def _opp_pitcher_files(program):
    import os
    d = outings.OUTINGS_DIR
    if not os.path.isdir(d):
        return []
    return [f[:-5] for f in sorted(os.listdir(d)) if f.startswith(cleanup.OPP_PREFIX) and f.endswith('.json')]


def opponents(program):
    """{opp_slug: {'label', 'hitters': [...], 'pitchers': [...], 'dates': [...]}} for one program."""
    out = {}

    def slot(label):
        k = store.slugify(label) or 'unlabeled'
        return out.setdefault(k, {'slug': k, 'label': label, 'hitters': [], 'pitchers': [], 'dates': set()})

    for key, h in hitting.collect_scouting(program).items():
        s = slot(h['opponent'])
        s['hitters'].append({'key': key, 'name': hitting.display_name(h['name']), 'n': len(h['pitches'])})
        s['dates'] |= {p['date'] for p in h['pitches'] if p.get('date')}
    for slug in _opp_pitcher_files(program):
        data = outings.load(slug, real_only=True)
        if data.get('program') != program:
            continue
        by = {}
        for o in data['outings']:
            for r in o['rows']:
                by.setdefault(r.get('Opponent') or 'Unlabeled opponent', []).append(r)
                s_ = None
        for opp, rows in by.items():
            s = slot(opp)
            name = _flip(rows[0].get('Pitcher'))
            velos = [float(r['RelSpeed']) for r in rows if str(r.get('RelSpeed') or '').replace('.', '', 1).isdigit()]
            s['pitchers'].append({'slug': slug, 'opp': s['slug'], 'name': name, 'n': len(rows), 'top': max(velos) if velos else None,
                                  'throws': (rows[0].get('PitcherThrows') or '')[:1].upper()})
            s['dates'] |= {(r.get('Date') or '')[:10] for r in rows if r.get('Date')}
    for s in out.values():
        s['hitters'].sort(key=lambda x: x['name'].split()[-1].lower())
        s['pitchers'].sort(key=lambda x: x['name'].split()[-1].lower())
        s['dates'] = sorted(s['dates'])
    return out


def team_data(program, opp_slug):
    """Team-dashboard numbers for one opponent: {'pitching': ..., 'hitting': ...} in the same shape as team.pitching_data / hitting_data.
    Pitching = the opposing pitchers we tracked; hitting = the opposing hitters our pitchers faced."""
    import team
    ps = []
    for slug in _opp_pitcher_files(program):
        data = outings.load(slug, real_only=True)
        if data.get('program') != program:
            continue
        outs = []
        for o in data['outings']:
            rows = [r for r in o['rows'] if (store.slugify(r.get('Opponent') or '') or 'unlabeled') == opp_slug]
            if rows:
                outs.append({'date': o['date'], 'rows': rows})
        if outs:
            outs.sort(key=lambda x: x['date'], reverse=True)
            ps.append((slug, {'name': _flip(outs[0]['rows'][0].get('Pitcher')) or slug}, outs))
    hs = {k: h for k, h in hitting.collect_scouting(program).items() if h['opp_slug'] == opp_slug}
    return {'pitching': team.pitching_from(ps), 'hitting': team.hitting_from(hs), 'cfg': team.load(program)}


def defense_data(program, opp_slug):
    """Defensive Positioning cards for one opponent's hitters, most plate appearances first: [{'key', 'name', 'pa', 'bip', 'bats', 'aligns': [...]}]."""
    import defense
    out = []
    for key, h in hitting.collect_scouting(program).items():
        if h['opp_slug'] != opp_slug:
            continue
        st = hitting.hitter_stats(h['pitches'])
        sides = {p['side'] for p in h['pitches'] if p.get('side')}
        out.append({'key': key, 'name': hitting.display_name(h['name']), 'pa': st['pa'] or 0, 'pitches': len(h['pitches']),
                    'bip': sum(1 for p in h['pitches'] if p.get('outcome') == 'inplay'),
                    'bats': 'S' if len(sides) > 1 else (next(iter(sides)) if sides else ''), 'aligns': defense.alignment(h['pitches'])})
    out.sort(key=lambda x: (-x['pa'], -x['bip'], x['name'].split()[-1].lower()))
    return out
