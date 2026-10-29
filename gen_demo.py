"""Regenerates the bundled Demo University outings (demo/outings/*.json) with realistic pitches and batted balls.

Run from the repo root:  python3 gen_demo.py   (deterministic: same seed, same files)
Pitchers have their own arsenals and command; hitters have their own approach, contact quality, launch-angle shape and spray.
Pitch sequences are simulated plate appearance by plate appearance, so counts, strikeouts, walks and batted balls all line up.
"""
import json
import math
import os
import random
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hitting  # noqa: E402  (for hit_prob, so tagged hits agree with the app's expected-batting-average model)
import field_art  # noqa: E402

SEED = 20261009
G = 32.174

# ------------------------------------------------------------------ pitchers (HB is written for a righty; lefties are mirrored)
# type: (usage, velo, velo_sd, spin, spin_sd, ivb, ivb_sd, hb, hb_sd)
PITCHERS = {
    'diego_salazar': dict(name='Salazar, Diego', pid='37487428', throws='Right', rel_h=6.12, rel_s=-1.25, ext=6.55, cmd=0.60, dates=['2026-10-09', '2026-10-06', '2026-10-02', '2026-09-29', '2026-09-25', '2026-09-22'],
        mix={'Fastball': (.52, 94.1, 1.1, 2380, 90, 17.4, 1.5, 8.6, 1.5), 'Slider': (.22, 86.6, 1.2, 2560, 100, 1.2, 1.6, -4.4, 1.6),
             'Cutter': (.13, 90.3, 1.1, 2450, 90, 9.0, 1.5, -2.6, 1.4), 'ChangeUp': (.13, 87.2, 1.3, 1860, 110, 6.4, 1.8, 14.2, 1.8)}),
    'ethan_whitfield': dict(name='Whitfield, Ethan', pid='51203871', throws='Right', rel_h=5.55, rel_s=-1.9, ext=6.05, cmd=0.56, dates=['2026-10-09', '2026-10-06', '2026-10-02', '2026-09-30', '2026-09-26', '2026-09-23'],
        mix={'Sinker': (.38, 88.9, 1.2, 2170, 90, 8.6, 1.4, 17.2, 1.6), 'Fastball': (.12, 91.0, 1.2, 2260, 90, 14.2, 1.5, 12.0, 1.5),
             'Slider': (.28, 80.9, 1.3, 2480, 110, 0.4, 1.6, -13.6, 1.9), 'ChangeUp': (.22, 82.4, 1.3, 1720, 100, 3.6, 1.7, 16.6, 1.8)}),
    'jackson_reyes': dict(name='Reyes, Jackson', pid='66918204', throws='Right', rel_h=5.85, rel_s=-1.55, ext=6.30, cmd=0.62, dates=['2026-10-09', '2026-10-05', '2026-10-02', '2026-09-28', '2026-09-24', '2026-09-21'],
        mix={'Fastball': (.46, 91.2, 1.2, 2290, 90, 15.4, 1.5, 10.6, 1.5), 'Slider': (.22, 83.4, 1.2, 2450, 100, 1.6, 1.5, -7.4, 1.7),
             'Curveball': (.14, 77.3, 1.3, 2650, 110, -9.6, 1.8, -11.4, 1.9), 'ChangeUp': (.18, 83.1, 1.3, 1770, 100, 8.0, 1.7, 14.6, 1.8)}),
    'marcus_hale': dict(name='Hale, Marcus', pid='23841775', throws='Right', rel_h=6.00, rel_s=-1.45, ext=6.40, cmd=0.57, dates=['2026-10-08', '2026-10-06', '2026-10-01', '2026-09-29', '2026-09-24', '2026-09-22'],
        mix={'Fastball': (.48, 92.6, 1.2, 2330, 90, 15.0, 1.5, 11.8, 1.5), 'ChangeUp': (.20, 84.5, 1.3, 1790, 100, 7.0, 1.7, 15.4, 1.8),
             'Curveball': (.12, 79.1, 1.4, 2700, 110, -10.1, 1.8, -10.2, 1.9), 'Slider': (.20, 86.0, 1.2, 2420, 100, 0.2, 1.5, -6.2, 1.7)}),
    'noah_kimura': dict(name='Kimura, Noah', pid='79285939', throws='Left', rel_h=5.80, rel_s=2.35, ext=6.15, cmd=0.55, dates=['2026-10-09', '2026-10-06', '2026-10-03', '2026-09-30', '2026-09-26', '2026-09-23'],
        mix={'Fastball': (.50, 91.3, 1.1, 2310, 90, 14.8, 1.5, 13.0, 1.5), 'Slider': (.24, 84.1, 1.2, 2490, 100, 0.6, 1.5, -5.4, 1.6),
             'ChangeUp': (.26, 81.9, 1.3, 1710, 100, 7.4, 1.7, 16.2, 1.8)}),
    'tyler_brandt': dict(name='Brandt, Tyler', pid='40662190', throws='Left', rel_h=5.65, rel_s=2.10, ext=5.95, cmd=0.50, dates=['2026-10-08', '2026-10-06', '2026-10-02', '2026-09-29', '2026-09-25', '2026-09-22'],
        mix={'Fastball': (.52, 89.5, 1.1, 2230, 90, 14.4, 1.4, 12.6, 1.5), 'ChangeUp': (.26, 79.9, 1.3, 1650, 100, 6.2, 1.6, 15.2, 1.8),
             'Curveball': (.22, 76.6, 1.3, 2610, 110, -8.6, 1.7, -11.6, 1.8)}),
}

# ------------------------------------------------------------------ hitters
# zsw: swing rate in the zone, chs: chase rate, zc / cc: contact rate on swings in / out of the zone,
# ev / evsd: exit velocity on contact, la / lasd: launch angle, pull: average degrees pulled (+ = pull side), dsd: spread
HITTERS = {
    'Lowe, Eli':     dict(side='L', zsw=.66, chs=.20, zc=.89, cc=.68, ev=88.0, evsd=10.0, la=11, lasd=17, pull=8,  dsd=25),
    'Monroe, Gavin': dict(side='R', zsw=.70, chs=.31, zc=.80, cc=.58, ev=91.5, evsd=11.5, la=17, lasd=20, pull=19, dsd=24),
    'Sims, Jake':    dict(side='R', zsw=.64, chs=.26, zc=.84, cc=.62, ev=85.0, evsd=10.5, la=6,  lasd=17, pull=9,  dsd=26),
    'Cole, Aiden':   dict(side='L', zsw=.60, chs=.19, zc=.90, cc=.72, ev=83.5, evsd=9.5,  la=6,  lasd=16, pull=-2, dsd=27),
    'Tate, Hudson':  dict(side='R', zsw=.72, chs=.30, zc=.82, cc=.60, ev=89.5, evsd=11.5, la=20, lasd=21, pull=23, dsd=23),
    'Ortiz, Beau':   dict(side='R', zsw=.63, chs=.23, zc=.86, cc=.66, ev=86.0, evsd=10.0, la=9,  lasd=16, pull=5,  dsd=26),
    'Pratt, Dylan':  dict(side='R', zsw=.67, chs=.25, zc=.85, cc=.63, ev=87.0, evsd=10.5, la=13, lasd=18, pull=7,  dsd=25),
    'Nguyen, Caleb': dict(side='L', zsw=.69, chs=.28, zc=.83, cc=.60, ev=90.0, evsd=11.0, la=15, lasd=19, pull=17, dsd=23),
    'Boyd, Kyle':    dict(side='R', zsw=.68, chs=.34, zc=.79, cc=.54, ev=87.0, evsd=12.0, la=10, lasd=22, pull=11, dsd=27),
    'Vega, Felix':   dict(side='R', zsw=.71, chs=.33, zc=.78, cc=.54, ev=91.0, evsd=13.0, la=14, lasd=22, pull=12, dsd=26),
}

ZONE_X, ZONE_LO, ZONE_HI = 0.83, 1.5, 3.5


def clip(v, lo, hi):
    return max(lo, min(hi, v))


def region(x, z):
    """heart / shadow / chase / waste, same idea as the app's decision chart."""
    dx = max(0.0, abs(x) - ZONE_X)
    dz = max(0.0, ZONE_LO - z, z - ZONE_HI)
    out = math.hypot(dx, dz)
    if out == 0:
        return 'heart' if abs(x) < 0.55 and 1.9 < z < 3.1 else 'zone'
    return 'shadow' if out < 0.25 else 'chase' if out < 0.75 else 'waste'


def pick_pitch(rng, P, balls, strikes, last_type):
    w = {}
    for t, (use, *_r) in P['mix'].items():
        u = use
        if t in ('Slider', 'Curveball', 'ChangeUp', 'Cutter'):
            u *= 1.45 if strikes == 2 else (0.80 if balls > strikes else 1.0)
        if t in ('Fastball', 'Sinker'):
            u *= 1.35 if balls > strikes else (0.85 if strikes == 2 else 1.0)
        if t == last_type:
            u *= 0.88
        w[t] = u
    r, tot = rng.random() * sum(w.values()), 0
    for t, u in w.items():
        tot += u
        if r <= tot:
            return t
    return t


def make_pitch(rng, P, t, balls, strikes, bside, fatigue):
    use, v, vsd, sp, ssd, ivb, ivsd, hb, hsd = P['mix'][t]
    lh = P['throws'] == 'Left'
    velo = rng.gauss(v - fatigue, vsd)
    ivb_ = rng.gauss(ivb, ivsd) + (velo - v) * 0.25
    hb_ = rng.gauss(hb, hsd) * (-1 if lh else 1)
    spin = rng.gauss(sp, ssd)
    # where is he trying to throw it?
    ahead = strikes >= 2 or (strikes > balls and rng.random() < .45)
    away = 1 if bside == 'R' else -1          # +x is away from a right-handed hitter in this data set
    cmd = P['cmd']
    fb = t in ('Fastball', 'Sinker')
    if ahead and rng.random() < (.62 if strikes == 2 else .38):
        if fb:
            tx, tz = rng.choice([(-away * .5, 3.85), (away * .35, 3.9), (-away * .9, 2.5)])
        else:
            tx, tz = away * rng.uniform(.55, 1.15), rng.uniform(.75, 1.5)
            if t == 'Curveball':
                tx, tz = away * rng.uniform(.0, .8), rng.uniform(.6, 1.3)
    else:
        if balls > strikes + 0:
            tx, tz = rng.gauss(0, .38), rng.gauss(2.5, .4)
        else:
            tx, tz = rng.gauss(away * .12, .5), rng.gauss(2.4 if not fb else 2.6, .5)
    sc = .78 if (balls == 3 and strikes < 2) else 1.0          # throwing strikes when he has to
    x = rng.gauss(tx, cmd * 1.32 * sc * (1.0 if fb else 1.1))
    z = rng.gauss(tz, cmd * 1.15 * sc * (1.0 if fb else 1.12))
    z = clip(z, 0.35, 4.6)
    x = clip(x, -2.0, 2.0)
    tfl = 54.0 / (velo * 1.467 * 0.93)                     # flight time release->plate
    vb = ivb_ - 0.5 * G * tfl * tfl * 12
    axis = (180 + math.degrees(math.atan2(hb_ * (-1 if lh else 1), ivb_)) + rng.gauss(0, 7)) % 360
    if lh:
        axis = (360 - axis) % 360
    tilt_h = ((axis + 180) % 360) / 30.0
    th = int(tilt_h) or 12
    tm = int(round((tilt_h - int(tilt_h)) * 60))
    if tm == 60:
        tm, th = 0, (th % 12) + 1
    rel_h = rng.gauss(P['rel_h'], .08)
    rel_s = rng.gauss(P['rel_s'], .06)
    va = clip(-9.5 + 0.105 * ivb_ + 0.029 * (velo - 80) + 0.2 * (z - 2.5) + rng.gauss(0, .3), -11, -2.5)
    return {
        'TaggedPitchType': t, 'RelSpeed': f'{velo:.2f}', 'SpinRate': f'{spin:.0f}', 'RelHeight': f'{rel_h:.3f}', 'RelSide': f'{rel_s:.3f}',
        'PlateLocHeight': f'{z:.3f}', 'PlateLocSide': f'{-x:.3f}', 'VertApprAngle': f'{va:.2f}', 'HorzApprAngle': f'{clip(rng.gauss(0, .2) - hb_ * .03 + rel_s * .1, -3, 3):.2f}',
        'InducedVertBreak': f'{ivb_:.1f}', 'HorzBreak': f'{hb_:.1f}', 'VertBreak': f'{vb:.1f}', 'Extension': f'{rng.gauss(P["ext"], .12):.2f}',
        'pfxx': f'{-0.65 * hb_:.1f}', 'pfxz': f'{ivb_:.1f}', 'ZoneSpeed': f'{velo * 0.915:.1f}', 'SpinAxis': f'{axis:.0f}', 'Tilt': f'{th}:{tm:02d}',
        '_x': x, '_z': z, '_v': velo, '_t': t,
    }


def swing_prob(H, reg, balls, strikes, x, z):
    base = {'heart': H['zsw'] + .14, 'zone': H['zsw'], 'shadow': (H['zsw'] + H['chs']) / 2 + .02, 'chase': H['chs'], 'waste': H['chs'] * .35}[reg]
    if strikes == 2:
        base += {'heart': .12, 'zone': .17, 'shadow': .22, 'chase': .17, 'waste': .09}[reg]
    if balls == 3 and strikes < 2:
        base = base * .45 if reg in ('zone', 'shadow', 'chase', 'waste') else base * .8
    elif balls == 0 and strikes == 0:
        base *= .78
    elif balls > strikes:
        base += .04
    return clip(base, .02, .97)


def contact_prob(H, reg, t, velo):
    base = H['zc'] if reg in ('heart', 'zone') else (H['zc'] + H['cc']) / 2 if reg == 'shadow' else H['cc'] if reg == 'chase' else H['cc'] - .22
    base += .045 if reg == 'heart' else 0
    base -= (velo - 88) * .007
    if t in ('Slider', 'Curveball'):
        base -= .08
    elif t == 'ChangeUp':
        base -= .05
    return clip(base, .08, .97)


def called_strike_prob(reg):
    return {'heart': .985, 'zone': .93, 'shadow': .52, 'chase': .10, 'waste': .02}[reg]


def hit_type_of(la):
    return 'GroundBall' if la < 10 else 'LineDrive' if la < 25 else 'FlyBall' if la < 50 else 'Popup'


def batted_ball(rng, H, pitch, reg):
    la = rng.gauss(H['la'], H['lasd'])
    if reg in ('chase', 'waste'):
        la += rng.choice([-1, 1]) * rng.uniform(0, 7)
    la = clip(la, -42, 82)
    ev = rng.gauss(H['ev'], H['evsd'])
    ev += 0.12 * (pitch['_v'] - 86) - (1.6 if pitch['_t'] in ('Slider', 'Curveball', 'ChangeUp') else 0)
    ev -= 0.11 * max(0, abs(la - 14) - 9)                    # weak contact on the extremes
    if reg in ('chase', 'waste'):
        ev -= 3.0
    if ev > 102:                                              # a soft ceiling, so the hardest hitters still separate (a hard clip piled every top ball at one value)
        ev = 102 + (ev - 102) * 0.55
    ev = clip(ev, 38, 116)
    pull = rng.gauss(H['pull'], H['dsd']) + 0.18 * (la - 12) * (1 if H['pull'] > 5 else .4)
    pull = clip(pull, -52, 52)
    direction = -pull if H['side'] == 'R' else pull         # RHH pull = negative (left field)
    # distance
    v = ev * 1.467
    if la >= 6:
        r = math.radians(la)
        vx, vy = v * math.cos(r), v * math.sin(r)
        t = (vy + math.sqrt(vy * vy + 2 * G * 3.0)) / G
        dist = vx * t * (1 - 0.067 * t)
        hang = t * 0.93
    else:
        dist = clip(28 + 1.25 * (ev - 62) + rng.gauss(0, 22) + 3 * la, 8, 230)
        hang = 0.4 + max(0, la) * .05
    dist = max(4.0, dist * rng.gauss(1.0, .035))
    return dict(ev=ev, la=la, dir=clip(direction, -62, 62), dist=dist, hang=hang)


def result_for(rng, bb):
    ev, la, d, dist = bb['ev'], bb['la'], bb['dir'], bb['dist']
    fence = field_art.fence_r(clip(d, -45, 45))
    if la >= 14 and la <= 50 and dist >= fence + rng.uniform(2, 14) and abs(d) <= 47:
        return 'PR_HomeRun'
    p = (hitting.hit_prob(ev, la) or 0) * 0.8
    if la < 10:
        p = p * (0.93 if dist < 150 else 1.0)
    if rng.random() >= p:
        return 'PR_Out'
    if la < 10:
        if ev >= 97 and abs(d) > 32 and rng.random() < .22:
            return 'PR_Double'
        return 'PR_Single'
    if la < 25:
        if dist >= 300 and rng.random() < .62:
            return 'PR_Double' if rng.random() > .08 else 'PR_Triple'
        if dist >= 230 and rng.random() < .32:
            return 'PR_Double'
        return 'PR_Single'
    if dist >= 290:
        return 'PR_Double' if rng.random() < .94 else 'PR_Triple'
    return 'PR_Single' if dist < 230 else 'PR_Double'


def simulate_outing(rng, key, P, date, order, target_pitches):
    rows, no = [], 0
    sec = 25 + rng.randint(0, 40)
    bi = rng.randrange(len(order))
    while no < target_pitches:
        bname = order[bi % len(order)]
        bi += 1
        H = HITTERS[bname]
        balls = strikes = 0
        last = None
        bside = H['side']
        while True:
            no += 1
            fatigue = max(0.0, (no - 45) * 0.045)
            t = pick_pitch(rng, P, balls, strikes, last)
            last = t
            pit = make_pitch(rng, P, t, balls, strikes, bside, fatigue)
            reg = region(pit['_x'], pit['_z'])
            call, tags, ev_row = None, None, {}
            if rng.random() < swing_prob(H, reg, balls, strikes, pit['_x'], pit['_z']):
                if rng.random() < contact_prob(H, reg, t, pit['_v']):
                    p_foul = (.47 if strikes < 2 else .55) + (.12 if reg in ('chase', 'waste') else 0) - (.08 if reg == 'heart' else 0)
                    if rng.random() < p_foul:
                        call, tags = 'FoulBall', 'PC_STRIKE|HC_FOUL'
                    else:
                        call = 'InPlay'
                else:
                    call, tags = 'StrikeSwinging', 'PC_StSw|HC_WHIFF'
            else:
                if rng.random() < called_strike_prob(reg):
                    call, tags = 'StrikeCalled', 'PC_STRIKE'
                else:
                    call, tags = 'BallCalled', 'PC_BALL'
            if call == 'InPlay':
                bb = batted_ball(rng, H, pit, reg)
                res = result_for(rng, bb)
                tags = f'PC_InPlay|HC_IN_PLAY|{res}'
                ev_row = {'ExitSpeed': f'{bb["ev"]:.1f}', 'Angle': f'{bb["la"]:.1f}', 'Direction': f'{bb["dir"]:.1f}', 'Distance': f'{bb["dist"]:.0f}',
                          'HitType': hit_type_of(bb['la']), 'HangTime': f'{bb["hang"]:.2f}'}
            else:
                ev_row = {'ExitSpeed': '', 'Angle': ''}
            sec += rng.randint(14, 24)
            hh, mm, ss = 15 + sec // 3600, (sec // 60) % 60, sec % 60
            row = {'PitchNo': str(no), 'Date': date, 'Time': f'{hh:02d}:{mm:02d}:{ss:02d}.00', 'Pitcher': P['name'], 'PitcherId': P['pid'],
                   'PitcherThrows': P['throws'], 'PitcherTeam': 'DEMO', 'PitcherSet': 'Windup' if rng.random() < .85 else 'Stretch', 'PitchCall': call,
                   'Balls': str(balls), 'Strikes': str(strikes)}
            row.update({k: v for k, v in pit.items() if not k.startswith('_')})
            row.update({'PitchSession': 'Live', 'PracticeType': 'LiveBpPitching', 'BatterSide': 'Right' if bside == 'R' else 'Left', 'Batter': bname,
                        'PitchUID': str(uuid.UUID(int=rng.getrandbits(128), version=4)), 'CustomTags': tags})
            row.update(ev_row)
            rows.append(row)
            if call == 'InPlay':
                break
            if call in ('BallCalled',):
                balls += 1
                if balls == 4:
                    break
            elif call == 'StrikeSwinging' or call == 'StrikeCalled':
                strikes += 1
                if strikes == 3:
                    break
            elif call == 'FoulBall' and strikes < 2:
                strikes += 1
        sec += rng.randint(12, 30)
    return rows


def main(out_dir):
    rng = random.Random(SEED)
    names = list(HITTERS)
    for slug, P in PITCHERS.items():
        outings = []
        for i, date in enumerate(P['dates']):
            order = names[:]
            rng.shuffle(order)
            rows = simulate_outing(rng, slug, P, date, order, rng.randint(58, 76))
            outings.append({'id': date, 'date': date, 'live_ab': True, 'rows': rows})
        with open(os.path.join(out_dir, f'{slug}.json'), 'w', encoding='utf-8') as f:
            json.dump({'outings': outings}, f, separators=(',', ':'), ensure_ascii=False)
        print(slug, sum(len(o['rows']) for o in outings))


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'demo/outings')
