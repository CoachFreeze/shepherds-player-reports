"""Opponent scouting: the hitters our pitchers faced and the pitchers our hitters faced, grouped by the opponent
entered when a Game / Scrimmage CSV was uploaded. Private to the program that uploaded it."""
import cleanup
import extract as e
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
            s['pitchers'].append({'slug': slug, 'name': name, 'n': len(rows), 'top': max(velos) if velos else None,
                                  'throws': (rows[0].get('PitcherThrows') or '')[:1].upper()})
            s['dates'] |= {(r.get('Date') or '')[:10] for r in rows if r.get('Date')}
    for s in out.values():
        s['hitters'].sort(key=lambda x: x['name'].split()[-1].lower())
        s['pitchers'].sort(key=lambda x: x['name'].split()[-1].lower())
        s['dates'] = sorted(s['dates'])
    return out
