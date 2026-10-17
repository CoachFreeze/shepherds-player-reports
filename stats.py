"""
Stat catalog for the player overview. compute(rows) returns every stat we can derive from a pitcher's
Trackman rows; the coach picks which ones to show (stored per player as bio['stat_ids']).

Each stat: id, label, group, definition. Values are display strings; detail is a small caption.
Per-pitch-type stats get ids like 'pt:Fastball:velo' and exist only for pitch types the player throws.
"""
import extract as e
import batted

DEFAULT_IDS = ['strike_pct', 'whiff_pct', 'zone_pct', 'chase_pct']
HARD_HIT = 95.0
FB_TYPES = {'Fastball', 'FourSeamFastBall', 'Four-Seam', 'Four-Seam Fastball'}

# id: (label, group, definition)
BASE = {
    # Volume
    'pitches': ('Pitches', 'Volume', 'Total pitches thrown.'),
    'bf': ('Batters Faced', 'Volume', 'Pitches thrown at a 0-0 count (estimate).'),
    'ip': ('Innings Pitched', 'Volume', 'Outs recorded (tagged outs + strikeouts) / 3. Estimate.'),
    'hits': ('Hits', 'Volume', 'Pitches tagged single, double, triple or home run.'),
    'walks': ('Walks', 'Volume', 'Balls thrown with 3 balls already in the count (estimate).'),
    'hbp': ('Hit By Pitch', 'Volume', 'Pitches that hit the batter.'),
    'ks': ('Strikeouts', 'Volume', 'Swinging or called strike three (estimate).'),
    # Command
    'strike_pct': ('Strike %', 'Command', 'Strikes / pitches (called, swinging, foul, in play).'),
    'ball_pct': ('Ball %', 'Command', 'Balls / pitches.'),
    'fps_pct': ('First-Pitch Strike %', 'Command', 'Strikes on 0-0 pitches.'),
    'zone_pct': ('In Zone %', 'Command', 'Pitches in the strike zone / pitches with location.'),
    'edge_pct': ('Out of Zone %', 'Command', 'Pitches outside the strike zone.'),
    'ahead_pct': ('Ahead in Count %', 'Command', 'Pitches thrown with more strikes than balls.'),
    'twostrike_pct': ('Putaway %', 'Command', 'Strikeouts / pitches thrown with two strikes.'),
    # Swing & miss
    'whiff_pct': ('Whiff %', 'Swing & Miss', 'Swinging strikes / swings.'),
    'chase_pct': ('Chase %', 'Swing & Miss', 'Swings at pitches outside the zone / pitches outside the zone.'),
    'csw_pct': ('CSW %', 'Swing & Miss', 'Called strikes + whiffs / pitches.'),
    'swing_pct': ('Swing %', 'Swing & Miss', 'Swings / pitches.'),
    'zswing_pct': ('Zone Swing %', 'Swing & Miss', 'Swings at pitches in the zone.'),
    'zcontact_pct': ('Zone Contact %', 'Swing & Miss', 'Contact on swings at pitches in the zone.'),
    'ocontact_pct': ('Chase Contact %', 'Swing & Miss', 'Contact on swings at pitches outside the zone.'),
    'contact_pct': ('Contact %', 'Swing & Miss', 'Fouls + balls in play / swings.'),
    'cs_pct': ('Called Strike %', 'Swing & Miss', 'Called strikes / takes (pitches not swung at).'),
    'foul_pct': ('Foul %', 'Swing & Miss', 'Fouls / swings.'),
    # Contact quality
    'bip': ('Balls In Play', 'Contact Allowed', 'Pitches put in play.'),
    'avg_ev': ('Avg Exit Velo', 'Contact Allowed', 'Average exit velocity on balls in play (mph).'),
    'max_ev': ('Max Exit Velo', 'Contact Allowed', 'Hardest ball hit (mph).'),
    'avg_la': ('Avg Launch Angle', 'Contact Allowed', 'Average launch angle on balls in play (degrees).'),
    'hh_pct': ('Hard-Hit %', 'Contact Allowed', f'Balls in play at {HARD_HIT:.0f}+ mph.'),
    'gb_pct': ('Ground Ball %', 'Contact Allowed', 'Launch angle under 10 degrees.'),
    'ld_pct': ('Line Drive %', 'Contact Allowed', 'Launch angle 10-25 degrees.'),
    'fb_pct': ('Fly Ball %', 'Contact Allowed', 'Launch angle 25-50 degrees.'),
    'pu_pct': ('Pop-Up %', 'Contact Allowed', 'Launch angle over 50 degrees.'),
    'brl_pct': ('Barrel % Allowed', 'Contact Allowed', 'Balls in play that were barrels (the ideal mix of exit velocity and launch angle: 98+ mph at about 26-30 degrees, widening as the ball is hit harder) / balls in play.'),
    # Stuff (all pitches)
    'top_velo': ('Top Velocity', 'Stuff', 'Fastest pitch (mph).'),
    'fb_velo': ('Avg Fastball Velo', 'Stuff', 'Average velocity of fastballs (mph).'),
    'fb_top': ('Top Fastball Velo', 'Stuff', 'Fastest fastball (mph).'),
    'fb_spin': ('Avg Fastball Spin', 'Stuff', 'Average fastball spin rate (rpm).'),
    'fb_ivb': ('Fastball Induced Vert Break', 'Stuff', 'Average fastball induced vertical break (in).'),
    'fb_hb': ('Fastball Horizontal Break', 'Stuff', 'Average fastball horizontal break (in).'),
    'fb_vaa': ('Fastball Vertical Approach Angle', 'Stuff', 'Average fastball VAA (degrees).'),
    'avg_spin': ('Avg Spin Rate', 'Stuff', 'Average spin rate, all pitches (rpm).'),
    'max_spin': ('Max Spin Rate', 'Stuff', 'Highest spin rate (rpm).'),
    'velo_gap': ('Velo Separation', 'Stuff', 'Fastball velocity minus avg changeup/splitter velocity (mph).'),
    # Mechanics
    'ext': ('Extension', 'Delivery', 'Average release extension (ft).'),
    'rel_h': ('Release Height', 'Delivery', 'Average release height (ft).'),
    'rel_s': ('Release Side', 'Delivery', 'Average release side (ft).'),
    'rel_h_sd': ('Release Height Consistency', 'Delivery', 'Standard deviation of release height (in). Lower = more repeatable.'),
    'rel_s_sd': ('Release Side Consistency', 'Delivery', 'Standard deviation of release side (in). Lower = more repeatable.'),
    'arsenal': ('Pitch Types Thrown', 'Delivery', 'Number of different pitch types used.'),
}
PT_STATS = [  # suffix, label, definition
    ('usage', 'Usage', 'Share of all pitches.'),
    ('velo', 'Avg Velo', 'Average velocity (mph).'),
    ('top', 'Top Velo', 'Fastest pitch (mph).'),
    ('spin', 'Avg Spin', 'Average spin rate (rpm).'),
    ('ivb', 'Induced Vert Break', 'Average induced vertical break (in).'),
    ('hb', 'Horizontal Break', 'Average horizontal break (in).'),
    ('strike', 'Strike %', 'Strikes / pitches.'),
    ('zone', 'In Zone %', 'Pitches in the zone.'),
    ('whiff', 'Whiff %', 'Swinging strikes / swings.'),
    ('chase', 'Chase %', 'Chases / pitches outside the zone.'),
    ('csw', 'CSW %', 'Called strikes + whiffs / pitches.'),
]
GROUP_ORDER = ['Command', 'Swing & Miss', 'Volume', 'Contact Allowed', 'Stuff', 'Delivery']


def _n(r, k):
    return e._fnum(r.get(k))


def _avg(rows, k):
    v = [x for x in (_n(r, k) for r in rows) if x is not None]
    return sum(v) / len(v) if v else None


def _pct(a, b):
    return (f'{100 * a / b:.1f}%', f'{a}/{b}') if b else ('-', '')


def _f(v, d=1, suf=''):
    return (f'{v:.{d}f}{suf}', '') if v is not None else ('-', '')


def _sd(rows, k):
    v = [x for x in (_n(r, k) for r in rows) if x is not None]
    if len(v) < 3:
        return None
    m = sum(v) / len(v)
    return (sum((x - m) ** 2 for x in v) / (len(v) - 1)) ** 0.5


def _core(rows):
    """Counts shared by the overall and per-pitch-type calculations."""
    o = [e._outcome(r) for r in rows]
    c = {'n': len(rows), 'o': o}
    c['swings'] = sum(1 for x in o if x in ('whiff', 'foul', 'inplay'))
    c['whiffs'] = o.count('whiff')
    c['fouls'] = o.count('foul')
    c['bip'] = o.count('inplay')
    c['cs'] = o.count('cs')
    c['known'] = sum(1 for x in o if x != 'unk')
    c['strikes'] = sum(1 for x in o if x not in ('ball', 'hbp', 'unk'))
    c['balls'] = o.count('ball')
    if rows and all((r.get('Source') or '') == 'fullswing' for r in rows):     # Full Swing logs swings only, so there is no called-strike / ball data
        c['known'] = c['strikes'] = c['balls'] = 0
    zin = zout = zsw = ocon = zcon = osw = loc = 0
    for r, x in zip(rows, o):
        a, b = _n(r, 'PlateLocSide'), _n(r, 'PlateLocHeight')
        if a is None or b is None:
            continue
        loc += 1
        sw = x in ('whiff', 'foul', 'inplay')
        con = x in ('foul', 'inplay')
        if abs(a) <= 0.83 and 1.4 <= b <= 3.6:
            zin += 1
            zsw += sw
            zcon += con
        else:
            zout += 1
            osw += sw
            ocon += con
    c.update(loc=loc, zin=zin, zout=zout, zsw=zsw, zcon=zcon, osw=osw, ocon=ocon)
    return c


def compute(rows):
    """Returns {stat_id: (value, detail)} for every stat computable from these rows, including per-pitch-type."""
    if not rows:
        return {}
    c = _core(rows)
    o, n = c['o'], c['n']
    out = {}
    base = e.outing_summary(rows) or {}
    for k in ('pitches', 'bf', 'ip', 'hits', 'walks', 'hbp'):
        out[k] = (str(base.get(k, '-')), '')
    ks = sum(1 for r, x in zip(rows, o) if r.get('Strikes') == '2' and x in ('whiff', 'cs'))
    out['ks'] = (str(ks), '')
    out['strike_pct'] = _pct(c['strikes'], c['known'])
    out['ball_pct'] = _pct(c['balls'] + o.count('hbp'), c['known'])
    out['fps_pct'] = (base.get('fps_pct', '-'), (base.get('detail') or {}).get('fps', ''))
    out['zone_pct'] = _pct(c['zin'], c['loc'])
    out['edge_pct'] = _pct(c['zout'], c['loc'])
    ahead = sum(1 for r in rows if (_n(r, 'Strikes') or 0) > (_n(r, 'Balls') or 0))
    out['ahead_pct'] = _pct(ahead, n)
    two = sum(1 for r in rows if r.get('Strikes') == '2')
    out['twostrike_pct'] = _pct(ks, two)
    out['whiff_pct'] = _pct(c['whiffs'], c['swings'])
    out['chase_pct'] = _pct(c['osw'], c['zout'])
    out['csw_pct'] = _pct(c['cs'] + c['whiffs'], n)
    out['swing_pct'] = _pct(c['swings'], n)
    out['zswing_pct'] = _pct(c['zsw'], c['zin'])
    out['zcontact_pct'] = _pct(c['zcon'], c['zsw'])
    out['ocontact_pct'] = _pct(c['ocon'], c['osw'])
    out['contact_pct'] = _pct(c['fouls'] + c['bip'], c['swings'])
    out['cs_pct'] = _pct(c['cs'], n - c['swings'])
    out['foul_pct'] = _pct(c['fouls'], c['swings'])
    # contact allowed
    bip = [r for r, x in zip(rows, o) if x == 'inplay']
    ev = [v for v in (_n(r, 'ExitSpeed') for r in bip) if v]
    la = [v for r in bip for v in [_n(r, 'Angle')] if v is not None and _n(r, 'ExitSpeed')]
    out['bip'] = (str(c['bip']), '')
    out['avg_ev'] = _f(sum(ev) / len(ev) if ev else None)
    out['max_ev'] = _f(max(ev) if ev else None)
    out['avg_la'] = _f(sum(la) / len(la) if la else None, 0, '°')
    out['hh_pct'] = _pct(sum(1 for v in ev if v >= HARD_HIT), len(ev))
    pairs = [(_n(r, 'ExitSpeed'), _n(r, 'Angle')) for r in bip]
    pairs = [(v, a) for v, a in pairs if v and a is not None]
    out['gb_pct'] = _pct(sum(1 for v in la if batted.bucket(v) == 'GB'), len(la))
    out['ld_pct'] = _pct(sum(1 for v in la if batted.bucket(v) == 'LD'), len(la))
    out['fb_pct'] = _pct(sum(1 for v in la if batted.bucket(v) == 'FB'), len(la))
    out['pu_pct'] = _pct(sum(1 for v in la if batted.bucket(v) == 'PU'), len(la))
    out['brl_pct'] = _pct(sum(1 for v, a in pairs if batted.is_barrel(v, a)), len(pairs))
    # stuff
    spd = [v for v in (_n(r, 'RelSpeed') for r in rows) if v]
    out['top_velo'] = _f(max(spd) if spd else None)
    fb = [r for r in rows if r.get('TaggedPitchType') in FB_TYPES] or [r for r in rows if r.get('TaggedPitchType') == 'Sinker']
    fbs = [v for v in (_n(r, 'RelSpeed') for r in fb) if v]
    out['fb_velo'] = _f(sum(fbs) / len(fbs) if fbs else None)
    out['fb_top'] = _f(max(fbs) if fbs else None)
    out['fb_spin'] = _f(_avg(fb, 'SpinRate'), 0)
    out['fb_ivb'] = _f(_avg(fb, 'InducedVertBreak'), 1, '"')
    out['fb_hb'] = _f(_avg(fb, 'HorzBreak'), 1, '"')
    out['fb_vaa'] = _f(_avg(fb, 'VertApprAngle'), 1, '°')
    out['avg_spin'] = _f(_avg(rows, 'SpinRate'), 0)
    sp = [v for v in (_n(r, 'SpinRate') for r in rows) if v]
    out['max_spin'] = _f(max(sp) if sp else None, 0)
    off = [r for r in rows if r.get('TaggedPitchType') in ('ChangeUp', 'Splitter')]
    ov, fv = _avg(off, 'RelSpeed'), (sum(fbs) / len(fbs) if fbs else None)
    out['velo_gap'] = _f(fv - ov if (ov and fv) else None)
    out['ext'] = _f(_avg(rows, 'Extension'), 2, ' ft')
    out['rel_h'] = _f(_avg(rows, 'RelHeight'), 2, ' ft')
    out['rel_s'] = _f(_avg(rows, 'RelSide'), 2, ' ft')
    for k, col in (('rel_h_sd', 'RelHeight'), ('rel_s_sd', 'RelSide')):
        s = _sd(rows, col)
        out[k] = _f(s * 12 if s is not None else None, 1, '"')
    types = {}
    for r in rows:
        t = r.get('TaggedPitchType')
        if t:
            types.setdefault(t, []).append(r)
    if all((r.get('Source') or '') == 'fullswing' for r in rows):
        for k in ('strike_pct', 'ball_pct', 'ahead_pct', 'twostrike_pct', 'csw_pct', 'cs_pct', 'ks', 'fps_pct', 'zone_pct', 'edge_pct', 'chase_pct'):
            out[k] = ('-', '')
    out['arsenal'] = (str(len(types)), ', '.join(types))
    # per pitch type
    for t, rs in types.items():
        pc = _core(rs)
        s = [v for v in (_n(r, 'RelSpeed') for r in rs) if v]
        p = f'pt:{t}:'
        out[p + 'usage'] = _pct(len(rs), n)
        out[p + 'velo'] = _f(sum(s) / len(s) if s else None)
        out[p + 'top'] = _f(max(s) if s else None)
        out[p + 'spin'] = _f(_avg(rs, 'SpinRate'), 0)
        out[p + 'ivb'] = _f(_avg(rs, 'InducedVertBreak'), 1, '"')
        out[p + 'hb'] = _f(_avg(rs, 'HorzBreak'), 1, '"')
        out[p + 'strike'] = _pct(pc['strikes'], pc['known'])
        out[p + 'zone'] = _pct(pc['zin'], pc['loc'])
        out[p + 'whiff'] = _pct(pc['whiffs'], pc['swings'])
        out[p + 'chase'] = _pct(pc['osw'], pc['zout'])
        out[p + 'csw'] = _pct(pc['cs'] + pc['whiffs'], len(rs))
    return out


def _pt_label(t):
    import re
    return re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', t)


def catalog(values):
    """Groups available for the picker: [(group, [{id,label,definition,value}])]. Only stats that have a value
    (or are a base stat) are listed; pitch-type groups appear for pitch types the player throws."""
    groups = {g: [] for g in GROUP_ORDER}
    for sid, (lab, g, d) in BASE.items():
        if sid in values:
            groups[g].append({'id': sid, 'label': lab, 'definition': d, 'value': values[sid][0]})
    for sid in values:
        if sid.startswith('pt:'):
            pass
    types = []
    for sid in values:
        if sid.startswith('pt:'):
            t = sid.split(':')[1]
            if t not in types:
                types.append(t)
    out = [(g, groups[g]) for g in GROUP_ORDER if groups[g]]
    for t in types:
        items = []
        for suf, lab, d in PT_STATS:
            sid = f'pt:{t}:{suf}'
            if sid in values:
                items.append({'id': sid, 'label': f'{_pt_label(t)} {lab}', 'definition': d, 'value': values[sid][0]})
        out.append((_pt_label(t), items))
    return out


def label_for(sid):
    if sid in BASE:
        return BASE[sid][0], BASE[sid][2]
    if sid.startswith('pt:'):
        _, t, suf = sid.split(':')
        for s, lab, d in PT_STATS:
            if s == suf:
                return f'{_pt_label(t)} {lab}', d
    return sid, ''


def tiles(values, ids):
    """Selected stats in the chosen order, as tile dicts."""
    res = []
    for sid in ids or DEFAULT_IDS:
        if sid in values:
            lab, d = label_for(sid)
            res.append({'id': sid, 'label': lab, 'value': values[sid][0], 'detail': values[sid][1], 'definition': d})
    return res
