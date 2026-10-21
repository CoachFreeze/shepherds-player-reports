"""Proposed defensive alignments for an opposing hitter, from where his tracked balls in play went.

Infielders (3B, SS, 2B, 1B) are spread so each covers an equal share of his ground balls; outfielders (LF, CF, RF) the same for his
balls hit to the outfield. Depth follows how hard he hits it and how far his outfield balls travel. Every move is blended with a
standard alignment by how many balls we have seen, so a thin sample stays close to standard instead of overreacting.
Positions are in feet from home plate (x toward right field, y toward center field), the same frame the spray charts use.
"""
import math

import field_art

# (label, standard direction in degrees, standard distance from home in feet); 0 = center field, + = right-field side
INF_STD = {'3B': (-34.6, 102), '6': (-14.0, 115), '4': (14.0, 115), '1B': (39.0, 98)}
INF_ORDER = ['3B', '6', '4', '1B']                      # left side to right side
OF_STD = {'7': (-22.0, 270), '8': (0.0, 290), '9': (22.0, 270)}
OF_ORDER = ['7', '8', '9']
LABEL = {'3B': '5', '6': '6', '4': '4', '1B': '3', '7': '7', '8': '8', '9': '9'}
NAME = {'5': 'Third', '6': 'Short', '4': 'Second', '3': 'First', '7': 'Left', '8': 'Center', '9': 'Right'}
MIN_BIP = 5


def _q(vals, q):
    s = sorted(vals)
    k = (len(s) - 1) * q
    lo, hi = int(math.floor(k)), int(math.ceil(k))
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def _xy(deg, dist):
    a = math.radians(deg)
    return dist * math.sin(a), dist * math.cos(a)


def _spread(angles, lo, hi, gap):
    """Keeps fielders in order, at least `gap` degrees apart, inside [lo, hi]; the group moves together when it has to."""
    a = [max(lo, min(hi, x)) for x in angles]
    for _ in range(6):
        for i in range(1, len(a)):
            if a[i] - a[i - 1] < gap:
                mid = (a[i] + a[i - 1]) / 2
                a[i - 1], a[i] = mid - gap / 2, mid + gap / 2
        a = [max(lo, min(hi, x)) for x in a]
    return a


def _type(p):
    """Batted-ball type: the tracked type, else worked out from launch angle."""
    t = p.get('hit_type')
    if t:
        return t
    la = p.get('la')
    return None if la is None else 'GB' if la < 10 else 'LD' if la < 25 else 'FB' if la < 50 else 'PU'


def _align(balls):
    """balls: normalized in-play pitches from one hitter, all from the same batting side."""
    real = [p for p in balls if p.get('direction') is not None and _type(p) != 'BUNT']
    bunts = sum(1 for p in balls if _type(p) == 'BUNT')
    gb = [p for p in real if _type(p) == 'GB']
    of = [p for p in real if _type(p) not in ('GB', None) and (p.get('distance') or 0) >= 150]
    w_in, w_of = min(1.0, len(gb) / 12), min(1.0, len(of) / 10)
    ang, dep = {}, {}
    # infield: equal share of his ground balls for each of the four infielders
    if len(gb) >= 3:
        dirs = [p['direction'] for p in gb]
        tgt = [_q(dirs, qq) for qq in (0.125, 0.375, 0.625, 0.875)]
    else:
        tgt = [INF_STD[k][0] for k in INF_ORDER]
    cur = [INF_STD[k][0] + w_in * (t - INF_STD[k][0]) for k, t in zip(INF_ORDER, tgt)]
    cur = _spread(cur, -41, 41, 9)
    cur[3] = max(28, min(41, cur[3]))                 # first base holds the bag
    for i in (2, 1, 0):
        cur[i] = min(cur[i], cur[i + 1] - 9)
    evs = [p['ev'] for p in gb if p.get('ev') is not None]
    avg_ev = sum(evs) / len(evs) if len(evs) >= 3 else None
    adj = 5 if (avg_ev is not None and avg_ev >= 88) else -5 if (avg_ev is not None and avg_ev < 75) else 0
    for k, a in zip(INF_ORDER, cur):
        d = INF_STD[k][1] + adj
        if bunts >= 2 and k in ('3B', '1B'):
            d -= 14
        ang[k], dep[k] = a, d
    # outfield: thirds of the balls he hits to the outfield; depth from how far they travel
    if len(of) >= 3:
        dirs = [p['direction'] for p in of]
        tgt = [_q(dirs, qq) for qq in (1 / 6, 0.5, 5 / 6)]
        far = _q([p['distance'] for p in of], 0.75)
    else:
        tgt, far = [OF_STD[k][0] for k in OF_ORDER], 370
    cur = [OF_STD[k][0] + w_of * (t - OF_STD[k][0]) for k, t in zip(OF_ORDER, tgt)]
    cur = _spread(cur, -38, 38, 14)
    cf = 290 + w_of * (max(255, min(325, 0.93 * far)) - 290)
    for k, a in zip(OF_ORDER, cur):
        ang[k], dep[k] = a, cf - (0 if k == '8' else 18)
    return ang, dep, {'gb': len(gb), 'of': len(of), 'bip': len(balls), 'bunts': bunts, 'avg_ev': avg_ev, 'cf': cf, 'w_in': w_in, 'w_of': w_of}


def _notes(ang, dep, info, side):
    out = []
    if info['bip'] < MIN_BIP:
        return [f"Only {info['bip']} tracked ball{'s' if info['bip'] != 1 else ''} in play, so this stays at the standard alignment."]
    inf = [ang[k] for k in ('3B', '6', '4')]
    left, right = sum(1 for a in inf if a < -2), sum(1 for a in inf if a > 2)
    centre = sum(ang[k] for k in INF_ORDER) / 4 - sum(INF_STD[k][0] for k in INF_ORDER) / 4
    if left == 3 or right == 3:
        out.append(f"Full infield shift toward {'left' if left == 3 else 'right'} field: all three middle infielders to that side of second base.")
    elif abs(centre) >= 6:
        out.append(f"Shade the infield toward {'left' if centre < 0 else 'right'} field ({abs(centre):.0f} degrees).")
    elif info['gb'] >= 6:
        out.append('Infield stays near standard: he sprays his ground balls.')
    if info['bunts'] >= 2:
        out.append(f"Corners in: {info['bunts']} bunts tracked.")
    if info['avg_ev'] is not None and info['avg_ev'] >= 88:
        out.append(f"Infield plays a few feet deeper: his ground balls average {info['avg_ev']:.0f} mph.")
    elif info['avg_ev'] is not None and info['avg_ev'] < 75:
        out.append(f"Infield can play in a few feet: his ground balls average {info['avg_ev']:.0f} mph.")
    if info['of'] >= 4:
        o = (ang['7'] + ang['8'] + ang['9']) / 3
        if abs(o) >= 5:
            out.append(f"Outfield shades toward {'left' if o < 0 else 'right'} field.")
        if info['cf'] >= 305:
            out.append('Outfield plays deep: he hits it a long way.')
        elif info['cf'] <= 272:
            out.append('Outfield can come in: his outfield balls are short.')
    if info['w_in'] < 1 or info['w_of'] < 1:
        out.append(f"Light sample ({info['gb']} ground balls, {info['of']} outfield balls): the moves are partial.")
    return out or ['Standard alignment.']


def alignment(pitches):
    """[{'side', 'svg', 'notes', 'bip', 'fielders'}] for one hitter: one entry, or two for a switch-hitter with enough balls from each side."""
    by = {}
    for p in pitches:
        if p.get('outcome') == 'inplay':
            by.setdefault(p.get('side') or '?', []).append(p)
    sides = sorted(by, key=lambda s: -len(by[s]))
    keep = [sides[0]] if sides else ['?']
    if len(sides) > 1 and len(by[sides[1]]) >= 6 and len(by[sides[0]]) >= 6:
        keep = sides[:2]
    out = []
    for s in keep:
        balls = by.get(s, [])
        ang, dep, info = _align(balls) if len(balls) >= MIN_BIP else _align([])
        info['bip'] = len(balls)
        fl = []
        for k in INF_ORDER + OF_ORDER:
            x, y = _xy(ang[k], dep[k])
            hx, hy = _xy(*(INF_STD.get(k) or OF_STD[k]))
            fl.append({'label': LABEL[k], 'x': x, 'y': y, 'home_x': hx, 'home_y': hy})
        pts = [{'direction': p['direction'], 'distance': p['distance']} for p in balls if p.get('direction') is not None and p.get('distance') is not None]
        out.append({'side': s, 'bip': len(balls), 'notes': _notes(ang, dep, info, s),
                    'svg': field_art.make_svg(pts, width=340, fielders=fl)})
    return out
