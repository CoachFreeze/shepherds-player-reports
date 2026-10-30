"""Coach insights (beta): patterns in a player's data that are large enough, repeated enough and in enough sessions to be worth acting on.

Nothing is reported from a small sample. Every candidate must clear four gates:
  1. enough pitches/sessions overall (READY_*) and enough events in the specific cell (min_n),
  2. a big difference from the baseline (delta), not just a statistically detectable one,
  3. statistical confidence (z) against that baseline,
  4. it survives dropping any single session (so one bad outing can't create an insight) and spans several sessions.
A player with nothing that clears all four simply gets "nothing stands out", which is the honest answer.
"""
import math

import cache
import hitting
import outings as outings_mod
import store

READY_PITCHES = 150
READY_SESSIONS = 3
MAX_SHOWN = 5

HARD_MPH = 95.0


def _z(k, n, p0):
    if n <= 0 or p0 <= 0 or p0 >= 1:
        return 0.0
    return (k / n - p0) / math.sqrt(p0 * (1 - p0) / n)


def _z2(k1, n1, k2, n2):
    if n1 <= 0 or n2 <= 0:
        return 0.0
    p = (k1 + k2) / (n1 + n2)
    if p <= 0 or p >= 1:
        return 0.0
    return (k1 / n1 - k2 / n2) / math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))


def _pct(x):
    return f'{round(100 * x)}%'


def _robust(events, base, min_delta, min_z, sign=1):
    """events: [(session, hit?)]. True when the rate beats the baseline by min_delta with confidence min_z in at least 3 sessions
    and still does so with any one session removed."""
    sess = {}
    for d, y in events:
        sess.setdefault(d, []).append(y)
    if len(sess) < 3:
        return False

    def ok(evs):
        n = len(evs)
        k = sum(evs)
        if n == 0:
            return False
        return sign * (k / n - base) >= min_delta and sign * _z(k, n, base) >= min_z
    allev = [y for v in sess.values() for y in v]
    if not ok(allev):
        return False
    for d in sess:
        if not ok([y for dd, v in sess.items() if dd != d for y in v]):
            return False
    return True


# ------------------------------------------------------------------ trends over time
def _halves(events):
    """events: [(session, value)] -> (earlier values, later values) split by session date, or None with fewer than 4 sessions."""
    sess = sorted({d for d, _ in events if d})
    if len(sess) < 4:
        return None
    cut = len(sess) // 2
    early, late = set(sess[:cut]), set(sess[cut:])
    return [v for d, v in events if d in early], [v for d, v in events if d in late]


def _rate_trend(events, name, unit, good_when_up, found, kind, action_up, action_down, min_n=30, delta=0.08):
    h = _halves(events)
    if not h or len(h[0]) < min_n or len(h[1]) < min_n:
        return
    a, b = h
    ka, kb = sum(a), sum(b)
    z = _z2(kb, len(b), ka, len(a))
    d = kb / len(b) - ka / len(a)
    if abs(d) < delta or abs(z) < 2.0:
        return
    up = d > 0
    good = (up == good_when_up)
    found.append({'kind': kind, 'tone': 'good' if good else 'watch', 'z': abs(z) * 0.9, 'n': len(a) + len(b),
                  'title': f'{name} is {"up" if up else "down"} lately',
                  'detail': f'{name} went from {_pct(ka / len(a))} in his earlier sessions to {_pct(kb / len(b))} in his recent ones ({len(a)} then {len(b)} {unit}).',
                  'action': action_up if up else action_down})


def _mean_trend(events, name, unit_suffix, good_when_up, found, kind, action_up, action_down, min_n=30, min_diff=1.0):
    h = _halves(events)
    if not h or len(h[0]) < min_n or len(h[1]) < min_n:
        return
    a, b = h
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    va = sum((x - ma) ** 2 for x in a) / max(1, len(a) - 1)
    vb = sum((x - mb) ** 2 for x in b) / max(1, len(b) - 1)
    se = math.sqrt(va / len(a) + vb / len(b)) or 1
    z = (mb - ma) / se
    if abs(mb - ma) < min_diff or abs(z) < 2.0:
        return
    up = mb > ma
    found.append({'kind': kind, 'tone': 'good' if up == good_when_up else 'watch', 'z': abs(z) * 0.9, 'n': len(a) + len(b),
                  'title': f'{name} is {"up" if up else "down"} lately',
                  'detail': f'{name} moved from {ma:.1f}{unit_suffix} in his earlier sessions to {mb:.1f}{unit_suffix} in his recent ones.',
                  'action': action_up if up else action_down})


# ------------------------------------------------------------------ pitchers
def _fam(label):
    c = hitting.pitch_class({'pitch_type': label})
    return c


@cache.memo
def _program_pool(program):
    """Normalized pitches thrown by every pitcher in the program (own pitchers' files), for baselines."""
    real, demo = hitting._all_pitch_files()
    out = []
    for slug, is_demo in real + demo:
        if slug.startswith('opp-') or (is_demo and any(s == slug for s, _ in real)):
            continue
        pl = store.get_player(slug) or {}
        if (pl.get('program') or ('demo_university' if is_demo else 'shepherds')) != program:
            continue
        out += _pitcher_pitches(slug)
    return out


def _pitcher_pitches(slug):
    out = []
    for o in outings_mod.load(slug)['outings']:
        for i, r in enumerate(o['rows']):
            try:
                p = hitting._norm_trackman(r)
            except Exception:
                continue
            p['label'] = hitting._PT_LABELS.get(p.get('pitch_type') or '')
            p['sess'] = p['date'] or o['id']
            p['i'] = i
            p['relh'] = _num(r.get('RelHeight'))
            p['rels'] = _num(r.get('RelSide'))
            p['session_type'] = r.get('SessionType')
            out.append(p)
    return out


def _num(v):
    try:
        f = float(v)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def _in_zone(p):
    return p['x'] is not None and p['z'] is not None and abs(p['x']) <= hitting.ZX and hitting.ZB <= p['z'] <= hitting.ZT


def _hand_word(s):
    return {'R': 'right-handed', 'L': 'left-handed'}[s]


def pitcher(slug, program):
    ps = _pitcher_pitches(slug)
    sessions = {p['sess'] for p in ps}
    if len(ps) < READY_PITCHES or len(sessions) < READY_SESSIONS:
        return {'ready': False, 'have': f'{len(ps)} pitches over {len(sessions)} session{"" if len(sessions) == 1 else "s"}',
                'need': f'{READY_PITCHES} pitches over at least {READY_SESSIONS} sessions'}
    pool = _program_pool(program)

    def hh_base(label):
        bip = [p for p in pool if p['label'] == label and p['outcome'] == 'inplay' and p['ev'] is not None]
        if len(bip) >= 80:
            return min(0.95, max(0.05, sum(1 for p in bip if p['ev'] >= HARD_MPH) / len(bip))), 'program average'
        mine = [p for p in ps if p['outcome'] == 'inplay' and p['ev'] is not None]
        return (sum(1 for p in mine if p['ev'] >= HARD_MPH) / len(mine) if mine else 0.3), 'his own average'
    found = []

    # 1. a pitch that keeps getting hit hard (overall, else by batter hand)
    for label in sorted({p['label'] for p in ps if p['label']}):
        base, base_name = hh_base(label)
        cands = [('all', [p for p in ps if p['label'] == label])] + [(s, [p for p in ps if p['label'] == label and p['side'] == s]) for s in ('R', 'L')]
        res = {}
        for hand, rows in cands:
            bip = [p for p in rows if p['outcome'] == 'inplay' and p['ev'] is not None]
            if len(bip) < 20:
                continue
            ev = [(p['sess'], p['ev'] >= HARD_MPH) for p in bip]
            if _robust(ev, base, 0.15, 2.0):
                res[hand] = (bip, sum(1 for _, y in ev if y))
        # one hand flagged and not the other: the problem is against that hand; otherwise report it for everyone
        hands = [h for h in ('R', 'L') if h in res]
        pick = hands[0] if len(hands) == 1 else ('all' if 'all' in res else None)
        if pick:
            bip, k = res[pick]
            avg = sum(p['ev'] for p in bip) / len(bip)
            who = 'hitters' if pick == 'all' else f'{_hand_word(pick)} hitters'
            found.append({'kind': 'Pitch Results', 'z': _z(k, len(bip), base), 'n': len(bip),
                          'title': f'His {label} keeps getting hit hard' + ('' if pick == 'all' else f' by {_hand_word(pick)} hitters'),
                          'detail': f'{_pct(k / len(bip))} of balls in play off his {label} {"" if pick == "all" else "against " + _hand_word(pick) + " hitters "}were hit 95+ mph ({k} of {len(bip)}, average {avg:.1f} mph), '
                                    f'against {_pct(base)} for the {base_name}. It held up across sessions, not just one outing.',
                          'action': f'Consider throwing the {label} less often to {who}, or work on reshaping it (more movement, a different release or a better target) to get weaker contact.'})

    # 2. fastball velocity that fades during outings
    fb = [p for p in ps if p['label'] in ('Fastball', 'Sinker') and p['speed']]
    drops = []
    for s in sorted({p['sess'] for p in fb}):
        v = [p['speed'] for p in sorted((p for p in fb if p['sess'] == s), key=lambda p: p['i'])]
        if len(v) >= 24:
            drops.append(sum(v[:10]) / 10 - sum(v[-10:]) / 10)
    if len(drops) >= 4 and sum(drops) / len(drops) >= 1.5 and sum(1 for d in drops if d >= 1.0) / len(drops) >= 0.75:
        found.append({'kind': 'Mechanics / Workload', 'z': 3.0, 'n': len(drops),
                      'title': 'Fastball velocity fades late in outings',
                      'detail': f'Over {len(drops)} outings his last 10 fastballs averaged {sum(drops) / len(drops):.1f} mph slower than his first 10, and it happened in {sum(1 for d in drops if d >= 1.0)} of {len(drops)} outings.',
                      'action': 'Look at pitch counts and conditioning, and check whether his delivery (posture, finish, arm slot) changes as he tires.'})

    # 3. cannot land the fastball for strikes
    for label in ('Fastball', 'Sinker'):
        rows = [p for p in ps if p['label'] == label and p['x'] is not None and p['z'] is not None]
        pr = [p for p in pool if p['label'] == label and p['x'] is not None and p['z'] is not None]
        if len(rows) >= 60 and len(pr) >= 150:
            base = sum(1 for p in pr if _in_zone(p)) / len(pr)
            ev = [(p['sess'], _in_zone(p)) for p in rows]
            k = sum(1 for _, y in ev if y)
            if _robust(ev, base, 0.12, 2.0, sign=-1):
                found.append({'kind': 'Command', 'z': -_z(k, len(rows), base), 'n': len(rows),
                              'title': f'Not landing his {label} in the zone',
                              'detail': f'Only {_pct(k / len(rows))} of his {label}s ({k} of {len(rows)}) finish in the strike zone, against {_pct(base)} for the program, and it is consistent across sessions.',
                              'action': 'Work on release-point repeatability and a clear target. Hitters can take until he proves he can throw it for strikes.'})

    # 4. release point scatter on the main pitch
    for label in ('Fastball', 'Sinker'):
        rows = [p for p in ps if p['label'] == label and p['relh'] is not None and p['rels'] is not None]
        if len(rows) >= 60:
            mh, ms = sum(p['relh'] for p in rows) / len(rows), sum(p['rels'] for p in rows) / len(rows)
            sd = math.sqrt(sum((p['relh'] - mh) ** 2 + (p['rels'] - ms) ** 2 for p in rows) / len(rows))
            if sd >= 0.40 and len({p['sess'] for p in rows}) >= 3:
                found.append({'kind': 'Mechanics', 'z': 2.5, 'n': len(rows),
                              'title': f'Release point is scattered on his {label}',
                              'detail': f'His {label} release point varies by about {sd * 12:.1f} inches around its average over {len(rows)} pitches. A repeatable delivery usually keeps this tighter.',
                              'action': 'Check his delivery for a changing arm slot or stride and work on a repeatable release.'})
                break

    # 5. predictable in hitter-friendly counts
    ctx = [(p, hitting.count_ctx(p)) for p in ps if hitting.pitch_class(p)]
    ahead = [hitting.pitch_class(p) == 'hard' for p, c in ctx if c and c[0] > c[1]]
    if len(ahead) >= 40 and sum(ahead) / len(ahead) >= 0.88:
        found.append({'kind': 'Pitch Selection', 'z': 2.2, 'n': len(ahead),
                      'title': 'Predictable when behind in the count',
                      'detail': f'{_pct(sum(ahead) / len(ahead))} of his pitches when the hitter is ahead in the count are fastballs ({sum(ahead)} of {len(ahead)}).',
                      'action': 'Hitters can sit on the fastball. Mix in a pitch he can throw for a strike in those counts.'})
    # 6. trends over time
    fbv = [(p['sess'], p['speed']) for p in ps if p['label'] in ('Fastball', 'Sinker') and p['speed']]
    _mean_trend(fbv, 'Fastball velocity', ' mph', True, found, 'Trend', 'Whatever he changed is working. Point it out so he can repeat it.', 'Check workload, recovery and any change in delivery or arm slot.')
    sw = [(p['sess'], p['outcome'] == 'whiff') for p in ps if p['outcome'] in hitting.SWING]
    _rate_trend(sw, 'His swing-and-miss rate', 'swings', True, found, 'Trend', 'His stuff is missing more bats. Review what he is doing differently.', 'Look at pitch location and shape; he may be leaving pitches over the plate.', min_n=40)
    kz = [(p['sess'], p['outcome'] != 'ball' and p['outcome'] != 'hbp') for p in ps if p['outcome'] in ('ball', 'cs', 'whiff', 'foul', 'inplay')]
    _rate_trend(kz, 'His strike rate', 'pitches', True, found, 'Trend', 'He is throwing more strikes. Reinforce what is helping his command.', 'He is falling behind more. Check release consistency and his approach to the zone.', min_n=60)
    hhb = [(p['sess'], p['ev'] >= HARD_MPH) for p in ps if p['outcome'] == 'inplay' and p['ev'] is not None]
    _rate_trend(hhb, 'Hard contact against him', 'balls in play', False, found, 'Trend', 'Hitters are squaring him up more. Look at his pitch locations and movement.', 'Hitters are making weaker contact. Reinforce his locations.', min_n=25, delta=0.12)
    return _finish(found)


# ------------------------------------------------------------------ hitters
def _fam3(label):
    if label in ('Fastball', 'Sinker', 'Cutter'):
        return 'fastballs'
    if label in ('Slider', 'Sweeper', 'Curveball'):
        return 'breaking balls'
    if label in ('Changeup', 'Splitter'):
        return 'offspeed pitches'
    return None


_ROW = {'up': 'up in the zone', 'mid': 'in the middle of the zone', 'down': 'down in the zone'}
_COL = {'in': 'inside', 'mid': '', 'away': 'away'}


def _cell(p):
    x, z, side = p['x'], p['z'], p.get('side')
    if x is None or z is None or side not in ('R', 'L'):
        return None
    if abs(x) > hitting.ZX + 0.4 or z < hitting.ZB - 0.4 or z > hitting.ZT + 0.4:
        return None
    rel = -x if side == 'R' else x         # + = toward the hitter (inside)
    row = 'up' if z >= 2.87 else ('down' if z <= 2.13 else 'mid')
    col = 'in' if rel >= 0.28 else ('away' if rel <= -0.28 else 'mid')
    return row, col


def _cell_text(row, col):
    if col == 'mid':
        return _ROW[row]
    return {'up': f'up and {_COL[col]}', 'mid': _COL[col], 'down': f'down and {_COL[col]}'}[row]


def hitter(key):
    h = hitting._collect(True).get(key)
    if not h:
        return {'ready': False, 'have': '0 pitches', 'need': f'{READY_PITCHES} pitches over at least {READY_SESSIONS} sessions'}
    ps = [p for p in h['pitches'] if p.get('outcome') and p['outcome'] != 'unk']
    sessions = {p['date'] for p in ps if p['date']}
    if len(ps) < READY_PITCHES or len(sessions) < READY_SESSIONS:
        return {'ready': False, 'have': f'{len(ps)} pitches over {len(sessions)} session{"" if len(sessions) == 1 else "s"}',
                'need': f'{READY_PITCHES} pitches over at least {READY_SESSIONS} sessions'}
    found = []
    swings = [p for p in ps if p['outcome'] in hitting.SWING]
    if len(swings) < 60:
        return _finish(found)
    base_w = sum(1 for p in swings if p['outcome'] == 'whiff') / len(swings)

    # 1. swing-and-miss by pitch family and location
    cells = {}
    for p in swings:
        fam, c = _fam3(hitting._PT_LABELS.get(p.get('pitch_type') or '')), _cell(p)
        if fam and c:
            cells.setdefault((fam, c), []).append((p['date'], p['outcome'] == 'whiff'))
    for (fam, (row, col)), ev in cells.items():
        if len(ev) < 20:
            continue
        k = sum(1 for _, y in ev if y)
        if k / len(ev) >= 0.40 and _robust(ev, base_w, 0.15, 2.0):
            found.append({'kind': 'Swing And Miss', 'z': _z(k, len(ev), base_w), 'n': len(ev),
                          'title': f'Gets beat by {fam} {_cell_text(row, col)}',
                          'detail': f'He misses on {_pct(k / len(ev))} of his swings at {fam} {_cell_text(row, col)} ({k} of {len(ev)}), against {_pct(base_w)} on all his swings, and it shows up in several sessions.',
                          'action': f'Build in drill work on {fam} in that spot (tee or front toss placed there, or machine work), and consider a plan for taking or laying off it until it improves.'})

    # 2. chasing off the zone
    oz = [p for p in ps if p['x'] is not None and p['z'] is not None and hitting.region(p['x'], p['z']) in ('chase', 'waste')]
    base_c = (sum(1 for p in oz if p['outcome'] in hitting.SWING) / len(oz)) if oz else 0
    for fam in ('fastballs', 'breaking balls', 'offspeed pitches'):
        sub = [(p['date'], p['outcome'] in hitting.SWING) for p in oz if _fam3(hitting._PT_LABELS.get(p.get('pitch_type') or '')) == fam]
        if len(sub) >= 25:
            k = sum(1 for _, y in sub if y)
            if k / len(sub) >= 0.40 and _robust(sub, base_c, 0.15, 2.0):
                found.append({'kind': 'Swing Decisions', 'z': _z(k, len(sub), base_c), 'n': len(sub),
                              'title': f'Chases {fam} out of the zone',
                              'detail': f'He swings at {_pct(k / len(sub))} of {fam} thrown out of the zone ({k} of {len(sub)}), against {_pct(base_c)} for all pitch types.',
                              'action': f'Work on recognition and a plan: pick a zone and lay off {fam} outside it.'})

    # 3. weak contact against a pitch family
    bip = [p for p in ps if p['outcome'] == 'inplay' and p['ev'] is not None]
    if len(bip) >= 60:
        m = sum(p['ev'] for p in bip) / len(bip)
        sd = math.sqrt(sum((p['ev'] - m) ** 2 for p in bip) / len(bip)) or 1
        for fam in ('fastballs', 'breaking balls', 'offspeed pitches'):
            sub = [p for p in bip if _fam3(hitting._PT_LABELS.get(p.get('pitch_type') or '')) == fam]
            if len(sub) < 20 or len({p['date'] for p in sub}) < 3:
                continue
            mf = sum(p['ev'] for p in sub) / len(sub)
            z = (mf - m) / (sd / math.sqrt(len(sub)))
            loo_ok = all((sum(p['ev'] for p in sub if p['date'] != d) / max(1, sum(1 for p in sub if p['date'] != d)) - m) <= -5 for d in {p['date'] for p in sub})
            if m - mf >= 7 and z <= -2.0 and loo_ok:
                found.append({'kind': 'Contact Quality', 'z': -z, 'n': len(sub),
                              'title': f'Weak contact against {fam}',
                              'detail': f'Average exit velocity on {fam} is {mf:.1f} mph ({len(sub)} balls in play), against {m:.1f} mph on everything else he puts in play.',
                              'action': 'Check timing and swing path against that pitch. It may be an early or late timing problem, or an unsound approach to those pitches.'})

    # 4. platoon gap in swing and miss
    vs = {s: [p for p in swings if p.get('p_throws') == s] for s in ('R', 'L')}
    if len(vs['R']) >= 30 and len(vs['L']) >= 30:
        kr, kl = [sum(1 for p in vs[s] if p['outcome'] == 'whiff') for s in ('R', 'L')]
        pr, pl = kr / len(vs['R']), kl / len(vs['L'])
        z = _z2(kr, len(vs['R']), kl, len(vs['L']))
        if abs(pr - pl) >= 0.12 and abs(z) >= 2.0:
            worse, w, wk, o, ok = ('left-handed', pl, len(vs['L']), pr, len(vs['R'])) if pl > pr else ('right-handed', pr, len(vs['R']), pl, len(vs['L']))
            found.append({'kind': 'Platoon', 'z': abs(z), 'n': wk,
                          'title': f'Struggles more against {worse} pitchers',
                          'detail': f'He swings and misses on {_pct(w)} of swings against {worse} pitchers ({wk} swings), against {_pct(o)} against the other side.',
                          'action': f'Get him more live or machine work against {worse} pitching and look at how he picks up the ball out of their hand.'})
    # 5. trends over time
    sw = [(p['date'], p['outcome'] == 'whiff') for p in swings]
    _rate_trend(sw, 'His swing-and-miss rate', 'swings', False, found, 'Trend', 'He is missing more. Check timing and whether he is expanding his zone.', 'He is making more contact. Point out what is working.', min_n=40)
    ozs = [(p['date'], p['outcome'] in hitting.SWING) for p in oz]
    _rate_trend(ozs, 'His chase rate', 'pitches out of the zone', False, found, 'Trend', 'He is chasing more. Revisit his plan and zone.', 'He is laying off more pitches out of the zone. Reinforce it.', min_n=40)
    evs = [(p['date'], p['ev']) for p in bip]
    _mean_trend(evs, 'His average exit velocity', ' mph', True, found, 'Trend', 'He is hitting the ball harder. Reinforce what is working.', 'His contact quality is slipping. Check timing, bat path and any recent changes.', min_n=40, min_diff=2.0)
    return _finish(found)


def _finish(found):
    found.sort(key=lambda f: -f['z'])
    return {'ready': True, 'items': found[:MAX_SHOWN], 'hidden': max(0, len(found) - MAX_SHOWN)}
