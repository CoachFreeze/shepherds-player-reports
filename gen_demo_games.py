"""Adds a full 56-game spring season to the bundled sample program (demo/): Demo University against eight invented schools.

Everything here is simulated with the same pitch model as gen_demo.py; no real players or real game data. Our side uses the sample
program's pitchers and hitters, plus four relievers so the bullpen can cover a season. Re-running replaces the games it made before
and leaves the fall live at-bats from gen_demo.py alone.

    python gen_demo_games.py          # writes demo/outings, demo/players.json, demo/schedules, demo/logos

gen_demo.py rewrites the pitchers' files from scratch, so run this again after it.
"""
import datetime
import json
import os
import random
import re
import uuid

import gen_demo as gd

DEMO = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'demo')
P = 'demo_university'; LABEL = 'Demo University'; CODE = 'DEM_UNI'
rng = random.Random(56)
OPP_PREFIX = 'opp-demo-'          # the sample program's opponent pitchers; real uploads never make this prefix

def name_flip(n):
    f, l = n.split(' ', 1); return f'{l}, {f}'

# ---------------------------------------------------------------- our staff: demo arsenals + four relievers
STAFF = {k: dict(v) for k, v in gd.PITCHERS.items()}
STAFF['owen_castillo'] = dict(name='Castillo, Owen', pid='51882043', throws='Right', rel_h=6.25, rel_s=-1.3, ext=6.6, cmd=0.58,
    mix={'Fastball': (.58, 95.0, 1.0, 2450, 90, 18.2, 1.4, 7.8, 1.4), 'Slider': (.32, 87.0, 1.1, 2620, 100, 2.0, 1.5, -5.0, 1.5), 'ChangeUp': (.10, 87.5, 1.2, 1800, 100, 6.0, 1.6, 13.5, 1.6)})
STAFF['luke_pendleton'] = dict(name='Pendleton, Luke', pid='51882044', throws='Left', rel_h=5.4, rel_s=2.6, ext=6.0, cmd=0.55,
    mix={'Sinker': (.50, 88.5, 1.1, 2150, 90, 8.0, 1.4, 16.0, 1.5), 'Slider': (.38, 79.5, 1.2, 2400, 100, -1.0, 1.6, -12.0, 1.7), 'ChangeUp': (.12, 81.0, 1.2, 1700, 100, 4.0, 1.6, 15.0, 1.7)})
STAFF['ryan_okafor'] = dict(name='Okafor, Ryan', pid='51882045', throws='Right', rel_h=6.4, rel_s=-1.1, ext=6.8, cmd=0.60,
    mix={'Fastball': (.55, 93.0, 1.1, 2350, 90, 16.0, 1.5, 9.0, 1.5), 'Curveball': (.30, 78.0, 1.2, 2750, 110, -12.0, 1.7, -9.0, 1.7), 'ChangeUp': (.15, 84.0, 1.2, 1750, 100, 7.0, 1.6, 14.0, 1.6)})
STAFF['sam_whitaker'] = dict(name='Whitaker, Sam', pid='51882046', throws='Right', rel_h=5.9, rel_s=-1.6, ext=6.2, cmd=0.52,
    mix={'Fastball': (.55, 90.5, 1.2, 2250, 90, 14.0, 1.5, 11.0, 1.5), 'Slider': (.25, 82.0, 1.3, 2400, 100, 1.0, 1.6, -6.0, 1.7), 'Cutter': (.20, 86.5, 1.2, 2350, 90, 8.0, 1.5, -2.0, 1.4)})
ROT = ['diego_salazar', 'jackson_reyes', 'marcus_hale']          # Fri / Sat / Sun
MID = ['noah_kimura', 'ethan_whitfield']                          # Tuesdays
PEN = ['owen_castillo', 'luke_pendleton', 'ryan_okafor', 'sam_whitaker', 'tyler_brandt', 'ethan_whitfield', 'noah_kimura']
BIO = {'diego_salazar': (76, 215, 2027), 'ethan_whitfield': (73, 195, 2028), 'jackson_reyes': (74, 200, 2027), 'marcus_hale': (75, 210, 2026),
       'noah_kimura': (72, 185, 2028), 'tyler_brandt': (73, 190, 2029), 'owen_castillo': (77, 225, 2027), 'luke_pendleton': (74, 205, 2028),
       'ryan_okafor': (76, 210, 2026), 'sam_whitaker': (72, 190, 2029)}

HIT = dict(gd.HITTERS)
LINEUP = ['Cole, Aiden', 'Lowe, Eli', 'Nguyen, Caleb', 'Monroe, Gavin', 'Tate, Hudson', 'Vega, Felix', 'Pratt, Dylan', 'Ortiz, Beau', 'Sims, Jake']
BENCH = ['Boyd, Kyle']
HBIO = {'Lowe, Eli': ('INF', 'L', 71, 190, 2027, 5), 'Monroe, Gavin': ('OF', 'R', 74, 210, 2026, 24), 'Sims, Jake': ('C', 'R', 72, 205, 2028, 12),
        'Cole, Aiden': ('OF', 'L', 70, 175, 2028, 1), 'Tate, Hudson': ('INF', 'R', 75, 220, 2027, 33), 'Ortiz, Beau': ('INF', 'R', 71, 180, 2029, 7),
        'Pratt, Dylan': ('OF', 'R', 73, 195, 2027, 18), 'Nguyen, Caleb': ('INF', 'L', 72, 195, 2026, 9), 'Boyd, Kyle': ('C', 'R', 72, 210, 2029, 27),
        'Vega, Felix': ('INF', 'R', 74, 215, 2028, 44)}

# ---------------------------------------------------------------- opponents (all invented)
FIRST = ['Mason', 'Logan', 'Carter', 'Wyatt', 'Owen', 'Jace', 'Brody', 'Colton', 'Easton', 'Nolan', 'Reid', 'Tanner', 'Cade', 'Rhett', 'Grady', 'Beckett',
         'Hayden', 'Kai', 'Miles', 'Jonah', 'Silas', 'Rowan', 'Theo', 'Dawson', 'Bryce', 'Chase', 'Garrett', 'Landon', 'Parker', 'Quinn']
LAST = ['Archer', 'Bishop', 'Crane', 'Dalton', 'Ellis', 'Foster', 'Gaines', 'Holt', 'Ingram', 'Jarvis', 'Keller', 'Lyle', 'Mercer', 'Nash', 'Oakes',
        'Porter', 'Quill', 'Rowe', 'Sutton', 'Tolliver', 'Underwood', 'Vance', 'Wade', 'Yates', 'Zeller', 'Barlowe', 'Corbin', 'Drake', 'Emery', 'Fenwick',
        'Garner', 'Harlan', 'Irving', 'Jensen', 'Kerr', 'Lomax', 'Marsh', 'Noble', 'Orr', 'Pryor', 'Radley', 'Shaw', 'Thorne', 'Upton', 'Voss', 'Wilder']
OPPS = [('Lakeshore Tech', 'LAK_TEC', '#1f4e8c', '#f2b632'), ('Pinecrest College', 'PIN_COL', '#1d5c3a', '#e8e1c8'), ('Redwood Valley', 'RED_VAL', '#7a1f1f', '#d9b56c'),
        ('Mesa Grande', 'MES_GRA', '#b35a1f', '#2b2b2b'), ('Silver Creek', 'SIL_CRE', '#3d4a5c', '#c0c7cf'), ('Cedar Point', 'CED_POI', '#0f6b6b', '#f4f1e8'),
        ('Ironwood University', 'IRO_UNI', '#2e2e2e', '#d64545'), ('Bayline State', 'BAY_STA', '#14395e', '#7fb3d5')]
used = set()
def newname():
    while True:
        n = f'{rng.choice(LAST)}, {rng.choice(FIRST)}'
        if n not in used and n not in HIT:
            used.add(n); return n
OPP = {}
for lab, code, c1, c2 in OPPS:
    hitters = {}
    for i in range(10):
        hitters[newname()] = dict(side=rng.choice('RRRL'), zsw=rng.uniform(.6, .72), chs=rng.uniform(.22, .34), zc=rng.uniform(.78, .88), cc=rng.uniform(.52, .66),
                                  ev=rng.uniform(83, 89), evsd=rng.uniform(10, 12), la=rng.uniform(6, 16), lasd=rng.uniform(16, 21), pull=rng.uniform(0, 18), dsd=rng.uniform(23, 27))
    pitchers = {}
    for i in range(5):
        nm = newname(); lh = rng.random() < .3; v = rng.uniform(86, 92)
        mix = {'Fastball': (.55, v, 1.2, rng.uniform(2150, 2350), 90, rng.uniform(13, 17), 1.6, rng.uniform(8, 13), 1.6),
               'Slider': (.25, v - 7.5, 1.3, rng.uniform(2300, 2550), 100, rng.uniform(-1, 3), 1.7, rng.uniform(-9, -3), 1.8),
               'ChangeUp': (.20, v - 7, 1.3, rng.uniform(1650, 1850), 100, rng.uniform(4, 8), 1.7, rng.uniform(12, 16), 1.8)}
        pitchers[nm] = dict(name=nm, pid=str(rng.randint(10**7, 10**8)), throws='Left' if lh else 'Right', rel_h=rng.uniform(5.5, 6.3),
                                  rel_s=(rng.uniform(1.8, 2.6) if lh else -rng.uniform(1.2, 2.0)), ext=rng.uniform(5.9, 6.5), cmd=rng.uniform(.6, .7), mix=mix)
    OPP[lab] = dict(code=code, hitters=hitters, pitchers=pitchers, colors=(c1, c2))

# ---------------------------------------------------------------- one plate appearance, pitch by pitch (Trackman-style fields)
def sim_pa(Pd, H, pcount):
    balls = strikes = 0; last = None; pitches = []
    while True:
        pcount += 1
        fatigue = max(0.0, (pcount - 60) * 0.05)
        t = gd.pick_pitch(rng, Pd, balls, strikes, last); last = t
        pit = gd.make_pitch(rng, Pd, t, balls, strikes, H['side'], fatigue)
        reg = gd.region(pit['_x'], pit['_z'])
        row = {k: v for k, v in pit.items() if not k.startswith('_')}
        row.update({'Balls': str(balls), 'Strikes': str(strikes), 'KorBB': 'Undefined', 'PlayResult': 'Undefined', 'RunsScored': '0', 'OutsOnPlay': '0'})
        call = None
        if rng.random() < gd.swing_prob(H, reg, balls, strikes, pit['_x'], pit['_z']):
            if rng.random() < gd.contact_prob(H, reg, t, pit['_v']):
                p_foul = (.47 if strikes < 2 else .55) + (.12 if reg in ('chase', 'waste') else 0) - (.08 if reg == 'heart' else 0)
                call = 'FoulBall' if rng.random() < p_foul else 'InPlay'
            else:
                call = 'StrikeSwinging'
        else:
            call = 'StrikeCalled' if rng.random() < gd.called_strike_prob(reg) else 'BallCalled'
        row['PitchCall'] = call
        pitches.append(row)
        if call == 'InPlay':
            bb = gd.batted_ball(rng, H, pit, reg)
            res = gd.result_for(rng, bb)[3:]
            row.update({'ExitSpeed': f'{bb["ev"]:.1f}', 'Angle': f'{bb["la"]:.1f}', 'Direction': f'{bb["dir"]:.1f}', 'Distance': f'{bb["dist"]:.0f}',
                        'HangTime': f'{bb["hang"]:.2f}', 'TaggedHitType': gd.hit_type_of(bb['la']), 'AutoHitType': gd.hit_type_of(bb['la'])})
            return pitches, ('InPlay', res, bb), pcount
        if call == 'BallCalled':
            balls += 1
            if balls == 4:
                row['KorBB'] = 'Walk'; return pitches, ('Walk', None, None), pcount
        elif call in ('StrikeSwinging', 'StrikeCalled'):
            strikes += 1
            if strikes == 3:
                row['KorBB'] = 'Strikeout'; return pitches, ('K', None, None), pcount
        elif call == 'FoulBall' and strikes < 2:
            strikes += 1


def apply_play(outcome, bases, outs):
    """-> (runs, outs_on_play, play_result, new_bases)"""
    kind, res, bb = outcome
    b = list(bases)
    if kind == 'K':
        return 0, 1, None, b
    if kind == 'Walk':
        runs = 0
        if b[0]:
            if b[1]:
                if b[2]: runs = 1
                b[2] = True
            b[1] = True
        b[0] = True
        return runs, 0, None, b
    if res == 'HomeRun':
        return 1 + sum(b), 0, 'HomeRun', [False] * 3
    if res == 'Triple':
        return sum(b), 0, 'Triple', [False, False, True]
    if res == 'Double':
        runs = int(b[2]) + int(b[1]) + (1 if b[0] and rng.random() < .45 else 0)
        third = b[0] and runs < int(b[2]) + int(b[1]) + 1
        return runs, 0, 'Double', [False, True, bool(third)]
    if res == 'Single':
        runs = int(b[2]) + (1 if b[1] and rng.random() < .6 else 0)
        nb = [True, b[0], b[1] and runs < int(b[2]) + 1]
        return runs, 0, 'Single', nb
    # an out on a ball in play
    ht = bb and gd.hit_type_of(bb['la'])
    if rng.random() < .035:
        return int(b[2]), 0, 'Error', [True, b[0], b[1]]
    if ht == 'GroundBall' and b[0] and outs < 2 and rng.random() < .45:
        runs = int(b[2]) if outs == 0 else 0
        return runs, 2, 'Out', [False, False, b[1] or (b[2] and outs == 1)]
    if ht in ('FlyBall', 'LineDrive') and b[2] and outs < 2 and (bb['dist'] > 230) and rng.random() < .7:
        return 1, 1, 'Sacrifice', [b[0], b[1], False]
    if ht == 'GroundBall' and outs < 2:
        runs = 1 if (b[2] and rng.random() < .4) else 0
        return runs, 1, 'Out', [False, b[0] or b[1], (b[1] and rng.random() < .6) or (b[2] and not runs)]
    return 0, 1, 'Out', b


class Staff:
    def __init__(self, pool, starter, cap):
        self.pool = pool; self.cur = starter; self.n = {starter: 0}; self.cap = cap; self.used = [starter]; self.runs = 0
    def maybe_change(self, inning, runs_inn):
        n = self.n[self.cur]
        lim = self.cap if self.cur == self.used[0] else rng.randint(22, 38)
        if n >= lim or (runs_inn >= 4 and n > 30):
            left = [p for p in self.pool if p not in self.used]
            if left:
                self.cur = rng.choice(left[:3]); self.used.append(self.cur); self.n[self.cur] = 0


def sim_game(date, opp, home, starter_us, starter_opp, game_no, t0):
    O = OPP[opp]
    us = Staff(PEN, starter_us, rng.randint(80, 98))
    oppp = list(O['pitchers'])
    th = Staff([p for p in oppp if p != starter_opp], starter_opp, rng.randint(75, 95))
    lineup_us = LINEUP[:] if rng.random() < .8 else LINEUP[:7] + BENCH + LINEUP[8:]
    lineup_opp = list(O['hitters'])[:9]
    idx = {'us': 0, 'opp': 0}; score = {'us': 0, 'opp': 0}
    rows_us, rows_opp = [], []          # our pitchers' rows / their pitchers' rows
    guid = str(uuid.UUID(int=rng.getrandbits(128), version=4)); sec = t0; pno = 0
    home_code, away_code = (CODE, O['code']) if home else (O['code'], CODE)
    inn = 0
    while True:
        inn += 1
        for half in ('Top', 'Bottom'):
            bat = ('opp' if home else 'us') if half == 'Top' else ('us' if home else 'opp')
            if half == 'Bottom' and inn >= 9 and score[bat] > score['opp' if bat == 'us' else 'us']:
                break
            outs = 0; bases = [False] * 3; pa_i = 0; runs_inn = 0
            staff = us if bat == 'opp' else th
            pdict = STAFF if bat == 'opp' else O['pitchers']
            lineup = lineup_opp if bat == 'opp' else lineup_us
            hdict = O['hitters'] if bat == 'opp' else HIT
            while outs < 3:
                staff.maybe_change(inn, runs_inn)
                pk = staff.cur; Pd = pdict[pk]
                bname = lineup[idx[bat] % 9]; idx[bat] += 1; pa_i += 1
                H = hdict[bname]
                pitches, outcome, staff.n[pk] = sim_pa(Pd, H, staff.n[pk])
                runs, oop, pres, nb = apply_play(outcome, bases, outs)
                if outs + oop >= 3:
                    runs = 0 if pres not in ('HomeRun',) else runs
                    if pres not in ('HomeRun',):
                        runs = 0
                for k, r in enumerate(pitches):
                    pno += 1; sec += rng.randint(16, 26)
                    r.update({'PitchNo': str(pno), 'Date': date, 'Time': f'{13 + sec // 3600:02d}:{(sec // 60) % 60:02d}:{sec % 60:02d}.00',
                              'Pitcher': Pd['name'], 'PitcherId': Pd['pid'], 'PitcherThrows': Pd['throws'], 'PitcherTeam': CODE if bat == 'opp' else O['code'],
                              'PitcherSet': 'Stretch' if any(bases) else 'Windup', 'Batter': bname, 'BatterSide': 'Right' if H['side'] == 'R' else 'Left',
                              'BatterTeam': O['code'] if bat == 'opp' else CODE, 'Inning': str(inn), 'Top/Bottom': half, 'Outs': str(outs),
                              'PAofInning': str(pa_i), 'PitchofPA': str(k + 1), 'SessionType': 'Game', 'Opponent': opp, 'GameUID': guid,
                              'HomeTeam': home_code, 'AwayTeam': away_code, 'Level': 'D2', 'League': 'Demo', 'Stadium': 'Demo Field' if home else opp + ' Field',
                              })
                last = pitches[-1]
                if pres:
                    last['PlayResult'] = pres
                last['RunsScored'] = str(runs); last['OutsOnPlay'] = str(oop if pres or outcome[0] != 'K' else 0)
                (rows_us if bat == 'opp' else rows_opp).append((pk, pitches))
                outs += oop; bases = nb if outs < 3 else [False] * 3
                score[bat] += runs; runs_inn += runs
                if half == 'Bottom' and inn >= 9 and score[bat] > score['opp' if bat == 'us' else 'us']:
                    break
            sec += 120
        if inn >= 9 and score['us'] != score['opp']:
            break
        if inn >= 15:
            break
    return rows_us, rows_opp, score, sec


def gd_slug(n):
    last, first = n.split(', ')
    return f'{first}_{last}'.lower().replace(' ', '_')


DROP = ('PitchUID', 'Tilt', 'ZoneSpeed', 'pfxx', 'pfxz', 'PracticeType', 'PitchSession', 'CustomTags', 'Catcher', 'HomeTeam', 'AwayTeam',
        'Level', 'League', 'Stadium')
TOWNS = {'Lakeshore Tech': 'Lakeshore, CA', 'Pinecrest College': 'Pinecrest, CA', 'Redwood Valley': 'Redwood Valley, CA', 'Mesa Grande': 'Mesa Grande, AZ',
         'Silver Creek': 'Silver Creek, NV', 'Cedar Point': 'Cedar Point, OR', 'Ironwood University': 'Ironwood, AZ', 'Bayline State': 'Bayline, CA'}


def _slugify(s):
    return re.sub(r'[^a-z0-9]+', '_', (s or '').lower()).strip('_')


def _lean(rows):
    return [{k: v for k, v in r.items() if k not in DROP and v != ''} for r in rows]


def schedule():
    """56 games: fourteen Friday-Sunday series plus fourteen Tuesday games, February 13 through May 17, 2026."""
    games, opps = [], [o for o, *_ in OPPS]
    fri = datetime.date(2026, 2, 13)
    for w in range(14):
        opp = opps[w % len(opps)]
        home = w % 2 == 0
        for i, (dt, tm) in enumerate(((0, '6:00 PM'), (1, '1:00 PM'), (2, '12:00 PM'))):
            games.append({'day': fri + datetime.timedelta(days=7 * w + dt), 'time': tm, 'opp': opp, 'home': home, 'st': ROT[i]})
        tue = fri + datetime.timedelta(days=7 * w - 3)
        games.append({'day': tue, 'time': '3:00 PM', 'opp': opps[(w * 3 + 1) % len(opps)], 'home': w % 3 != 2, 'st': MID[w % 2]})
    return sorted(games, key=lambda g: g['day'])


def logo(path, text, c1, c2):
    from PIL import Image, ImageDraw, ImageFont
    S = 240
    im = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.ellipse((4, 4, S - 4, S - 4), fill=c1)
    d.ellipse((17, 17, S - 17, S - 17), outline=c2, width=7)
    try:
        f = ImageFont.truetype('DejaVuSansCondensed-Bold.ttf', 100)
    except OSError:
        f = ImageFont.load_default()
    b = d.textbbox((0, 0), text, font=f)
    d.text(((S - (b[2] - b[0])) / 2 - b[0], (S - (b[3] - b[1])) / 2 - b[1]), text, font=f, fill=c2)
    im.save(path, optimize=True)


def main():
    od = os.path.join(DEMO, 'outings')
    for f in os.listdir(od):                                     # start clean: earlier generated opponents go
        if f.startswith(OPP_PREFIX):
            os.remove(os.path.join(od, f))
    ours = {k: {} for k in STAFF}
    theirs = {}
    played, sched = [], []
    for n, g in enumerate(schedule()):
        day, opp = g['day'].isoformat(), g['opp']
        sp = list(OPP[opp]['pitchers'])[n % 3]
        rows_us, rows_opp, score, _ = sim_game(day, opp, g['home'], g['st'], sp, n, rng.randint(0, 600))
        guid = f'demo-{day}-{n}'
        for pk, ps in rows_us:
            for r in ps:
                r['GameUID'] = guid
            ours[pk].setdefault(day, []).extend(ps)
        for pk, ps in rows_opp:
            for r in ps:
                r['GameUID'] = guid
            theirs.setdefault(pk, (opp, {}))[1].setdefault(day, []).extend(ps)
        played.append((day, opp, score['us'], score['opp']))
        sched.append({'date': day, 'time': g['time'], 'at': 'Home' if g['home'] else 'Away', 'opp': opp,
                      'loc': 'Demo City, CA / Demo Field' if g['home'] else f'{TOWNS[opp]} / {opp} Field', 'tournament': ''})
    # our pitchers: keep the fall live at-bats, replace any games made before
    players = json.load(open(os.path.join(DEMO, 'players.json')))
    for k, P_ in STAFF.items():
        path = os.path.join(od, k + '.json')
        old = json.load(open(path))['outings'] if os.path.exists(path) else []
        keep = [o for o in old if not o.get('demo_game')]
        new = [{'id': f'{d}-g', 'date': d, 'live_ab': True, 'demo_game': True, 'rows': _lean(rows)} for d, rows in ours[k].items()]
        outs = sorted(keep + new, key=lambda o: o['date'], reverse=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump({'outings': outs}, f, separators=(',', ':'), ensure_ascii=False)
        if k not in players:
            last, first = P_['name'].split(', ')
            h, w_, gy = BIO[k]
            players[k] = {'comps': {}, 'grad_year': gy, 'height_in': h, 'name': f'{first} {last}', 'program': P,
                          'roles': {'pitch': {'position': 'LHP' if P_['throws'] == 'Left' else 'RHP'}}, 'school': LABEL, 'weight_lbs': w_}
    with open(os.path.join(DEMO, 'players.json'), 'w', encoding='utf-8') as f:
        json.dump(players, f, indent=1, sort_keys=True)
    for nm, (opp, by) in theirs.items():
        outs = [{'id': d, 'date': d, 'live_ab': True, 'rows': _lean(rows)} for d, rows in sorted(by.items(), reverse=True)]
        with open(os.path.join(od, OPP_PREFIX + gd_slug(nm) + '.json'), 'w', encoding='utf-8') as f:
            json.dump({'program': P, 'outings': outs}, f, separators=(',', ':'), ensure_ascii=False)
    os.makedirs(os.path.join(DEMO, 'schedules'), exist_ok=True)
    with open(os.path.join(DEMO, 'schedules', P + '.json'), 'w', encoding='utf-8') as f:
        json.dump({'program': P, 'season': '2026', 'source': 'generated by gen_demo_games.py', 'games': sched}, f, indent=1)
    os.makedirs(os.path.join(DEMO, 'logos', 'opp'), exist_ok=True)
    for lab, code, c1, c2 in OPPS:
        ini = ''.join(w[0] for w in lab.split())[:2].upper()
        logo(os.path.join(DEMO, 'logos', 'opp', f'{P}--{_slugify(lab)}.png'), ini, c1, c2)
    w = sum(1 for p in played if p[2] > p[3])
    l_ = sum(1 for p in played if p[2] < p[3])
    print(f'{len(played)} games, {w}-{l_}' + (f'-{len(played) - w - l_}' if len(played) - w - l_ else ''), f'{len(theirs)} opponent pitchers')


if __name__ == '__main__':
    main()
