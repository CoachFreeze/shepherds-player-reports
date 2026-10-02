"""Extracts per-player data from 2026_Shepherds_Live_AB_Data.xlsx for the report generator."""
import openpyxl
from collections import defaultdict
import benchmarks as bm

DATA_XLSX = '/mnt/user-data/uploads/2026_Shepherds_Live_AB_Data.xlsx'  # default/fallback for CLI use

PITCH_TYPE_MAP = {
    'FB': 'Fastball', 'FB 1': 'Fastball', 'FB 2': 'Fastball', 'FB S': 'Fastball',
    'SL': 'Slider', 'SL 2': 'Slider', 'Sl': 'Slider',
    'CH': 'Changeup', 'CH 1': 'Changeup',
    'CB': 'Curveball', 'CB 1': 'Curveball', 'CB 2': 'Curveball',
    'CT': 'Cutter', 'SP': 'Splitter',
}
PITCH_COLORS = {
    'Fastball': '#d6336c', 'Slider': '#e8c93a', 'Sinker': '#f2994a',
    'Changeup': '#4a9e6e', 'Curveball': '#4a7de8', 'Cutter': '#a24ae8', 'Splitter': '#888888',
}


def _num(v):
    return v if isinstance(v, (int, float)) else None


def load_totals(xlsx_path=None):
    wb = openpyxl.load_workbook(xlsx_path or DATA_XLSX, data_only=True)
    ws = wb['Totals']

    def read_block(header_row, start_row, end_row):
        hdr = list(ws.iter_rows(min_row=header_row, max_row=header_row, values_only=True))[0]
        rows = []
        for r in range(start_row, end_row + 1):
            name = ws.cell(row=r, column=3).value
            if not name:
                continue
            d = {}
            for i, h in enumerate(hdr, start=1):
                if h is not None:
                    d[h] = ws.cell(row=r, column=i).value
            rows.append(d)
        return rows

    pitching = read_block(3, 4, 10)
    hitting = read_block(16, 17, 25)
    return pitching, hitting


def load_master_rows(xlsx_path=None):
    wb = openpyxl.load_workbook(xlsx_path or DATA_XLSX, data_only=True)
    ws = wb['Master']
    hdr = [c.value for c in ws[1]]
    idx = {h: i for i, h in enumerate(hdr) if h}
    rows = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row[idx['Pitcher']] is None:
            continue
        rows.append({h: row[i] for h, i in idx.items()})
    return rows


def pitcher_tracking_table(totals_row):
    specs = [
        ('Fastball', 'TFB', 'FB USG', 'FB K%', 'FB S/M%'),
        ('Curveball', 'TCB', 'CB USG', 'CB K%', 'CB S/M%'),
        ('Changeup', 'TCH', 'CH USG', 'CH K%', 'CH S/M%'),
        ('Other', 'TO', 'O USG', 'O K%', 'O S/M%'),
    ]
    out = []
    for label, ncol, usgcol, kcol, smcol in specs:
        n = totals_row.get(ncol) or 0
        if not n:
            continue
        usg = _num(totals_row.get(usgcol)) or 0
        kpct = _num(totals_row.get(kcol)) or 0
        smpct = _num(totals_row.get(smcol)) or 0
        out.append({'type': label, 'n': int(n), 'pct': usg * 100, 'k_pct': kpct * 100, 'whiff_pct': smpct * 100})
    return out


# ---------------------------------------------------------------------------
# Master-tab-only pitcher stats -- no reliance on the Totals sheet's fixed
# Fastball/Curveball/Changeup/Other columns at all. Pitch-type labels come
# straight from each pitch's own "Pitch Type" cell (via PITCH_TYPE_MAP), so
# a pitcher who actually throws Slider/Cutter/Splitter instead of a true
# Curveball is represented correctly -- this is what fixed the Esteban/
# Samples Curveball-vs-Slider mislabeling.
#
# Plate-appearance (BF) boundaries aren't stored explicitly in Master, so
# they're inferred: consecutive rows with the same Pitcher+Batter belong to
# one PA, which ends the moment a pitch's outcome is one of the PA-ending
# values below (or the Pitcher/Batter changes without one, as a fallback
# for any incomplete/edge-case AB).
_PA_END_OUTCOMES = {'BB', 'K', 'bK', 'In Play', 'HBP'}
_SWING_OUTCOMES = {'Foul', 'In Play', 'Yes'}  # 'Yes' = swinging strike/whiff


def _group_plate_appearances(master_rows, pitcher_name):
    pas, cur, cur_key = [], [], None
    for r in master_rows:
        if r.get('Pitcher') != pitcher_name:
            continue
        key = (r.get('Pitcher'), r.get('Batter'))
        if cur_key is not None and key != cur_key and cur:
            pas.append(cur)
            cur = []
        cur_key = key
        cur.append(r)
        if r.get('Sw/Miss/Outcome') in _PA_END_OUTCOMES:
            pas.append(cur)
            cur, cur_key = [], None
    if cur:
        pas.append(cur)
    return pas


def pitcher_master_stats(master_rows, pitcher_name):
    """Everything the report needs about a pitcher, computed straight from
    Master rows: overall rate stats (for the percentile bars) plus a
    per-pitch-type tracking table (usage/K%/whiff%/velo/spin/EV/SO),
    keyed off real per-pitch Pitch Type labels rather than Totals columns.

    NOTE: G / IP / H / WHIP still aren't derivable from Master alone --
    there's no outs-recorded or hit-vs-out-on-balls-in-play data here, so
    those keep coming from the Totals sheet (or the per-player sheets)
    until that data is captured at the point of entry.
    """
    prows = [r for r in master_rows if r.get('Pitcher') == pitcher_name]
    pas = _group_plate_appearances(master_rows, pitcher_name)
    bf = len(pas)

    k = bb = hbp = fps = 0
    strikes = pitches_with_bs = swings = whiffs = 0
    for pa in pas:
        last = pa[-1].get('Sw/Miss/Outcome')
        if last in ('K', 'bK'):
            k += 1
        elif last == 'BB':
            bb += 1
        elif last == 'HBP':
            hbp += 1
        if pa[0].get('Ball/Strike') == 1:
            fps += 1
        for p in pa:
            bs = p.get('Ball/Strike')
            if bs is not None:
                pitches_with_bs += 1
                if bs == 1:
                    strikes += 1
            oc = p.get('Sw/Miss/Outcome')
            if oc in _SWING_OUTCOMES:
                swings += 1
                if oc == 'Yes':
                    whiffs += 1

    overall = {
        'bf': bf, 'k': k, 'bb': bb, 'hbp': hbp,
        'strike_pct': round(100 * strikes / pitches_with_bs, 1) if pitches_with_bs else None,
        'fps_pct': round(100 * fps / bf, 1) if bf else None,
        'k_pct': round(100 * k / bf, 1) if bf else None,
        'bb_pct': round(100 * bb / bf, 1) if bf else None,
        'whiff_pct': round(100 * whiffs / swings, 1) if swings else None,
    }

    by_type = defaultdict(lambda: {'n': 0, 'k': 0, 'swings': 0, 'whiffs': 0,
                                    'velos': [], 'spins': [], 'evs': [], 'so': 0,
                                    'strikes': 0, 'pitches_with_bs': 0})
    total_pitches = len(prows)
    for r in prows:
        label = PITCH_TYPE_MAP.get(r.get('Pitch Type'))
        if not label:
            continue
        d = by_type[label]
        d['n'] += 1
        oc = r.get('Sw/Miss/Outcome')
        if oc in ('K', 'bK'):
            d['k'] += 1
            d['so'] += 1
        if oc in _SWING_OUTCOMES:
            d['swings'] += 1
            if oc == 'Yes':
                d['whiffs'] += 1
        if _num(r.get('Velocity')) is not None:
            d['velos'].append(r['Velocity'])
        if _num(r.get('SpinRate')) is not None:
            d['spins'].append(r['SpinRate'])
        if _num(r.get('ExitSpeed')) is not None:
            d['evs'].append(r['ExitSpeed'])
        # Ball/Strike: 1 = strike, 0 = ball -- per-pitch-type Strike%,
        # same convention as the overall Strike% above.
        bs = r.get('Ball/Strike')
        if bs is not None:
            d['pitches_with_bs'] += 1
            if bs == 1:
                d['strikes'] += 1

    tracking = []
    for label, d in sorted(by_type.items(), key=lambda kv: -kv[1]['n']):
        tracking.append({
            'type': label,
            'n': d['n'],
            'pct': 100 * d['n'] / total_pitches if total_pitches else 0,
            'k_pct': 100 * d['k'] / d['n'] if d['n'] else 0,
            'whiff_pct': 100 * d['whiffs'] / d['swings'] if d['swings'] else 0,
            'strike_pct': round(100 * d['strikes'] / d['pitches_with_bs'], 1) if d['pitches_with_bs'] else None,
            'velo': round(sum(d['velos']) / len(d['velos']), 1) if d['velos'] else None,
            'top_velo': round(max(d['velos']), 1) if d['velos'] else None,
            'spin': round(sum(d['spins']) / len(d['spins'])) if d['spins'] else None,
            'ev': round(sum(d['evs']) / len(d['evs']), 1) if d['evs'] else None,
            'so': d['so'],
        })
    return overall, tracking


def pitcher_spin_ev_so(master_rows, pitcher_name):
    buckets = defaultdict(lambda: {'spins': [], 'evs': [], 'so': 0, 'velos': []})
    for row in master_rows:
        if row.get('Pitcher') != pitcher_name:
            continue
        label = PITCH_TYPE_MAP.get(row.get('Pitch Type'))
        if not label:
            continue
        if _num(row.get('SpinRate')) is not None:
            buckets[label]['spins'].append(row['SpinRate'])
        if _num(row.get('ExitSpeed')) is not None:
            buckets[label]['evs'].append(row['ExitSpeed'])
        if _num(row.get('Velocity')) is not None:
            buckets[label]['velos'].append(row['Velocity'])
        outcome = row.get('Sw/Miss/Outcome') or row.get('Outcome')
        if outcome in ('K', 'bK'):
            buckets[label]['so'] += 1
    result = {}
    for label, d in buckets.items():
        result[label] = {
            'spin': round(sum(d['spins']) / len(d['spins'])) if d['spins'] else None,
            'ev': round(sum(d['evs']) / len(d['evs']), 1) if d['evs'] else None,
            'so': d['so'],
            'velo': round(sum(d['velos']) / len(d['velos']), 1) if d['velos'] else None,
            'top_velo': round(max(d['velos']), 1) if d['velos'] else None,
            'n': len(d['velos']),
        }
    return result


def hitter_spray_points(master_rows, hitter_name):
    pts = []
    for row in master_rows:
        if row.get('Batter') != hitter_name:
            continue
        if _num(row.get('Direction')) is not None and _num(row.get('Distance')) is not None:
            pts.append({
                'direction': row['Direction'], 'distance': row['Distance'],
                'ev': _num(row.get('ExitSpeed')), 'la': _num(row.get('Angle')),
            })
    return pts


def hitter_derived_metrics(master_rows, hitter_name):
    balls = []
    for row in master_rows:
        if row.get('Batter') != hitter_name:
            continue
        ev = _num(row.get('ExitSpeed'))
        if ev is None:
            continue
        balls.append({'ev': ev, 'dist': _num(row.get('Distance')), 'angle': _num(row.get('Angle')), 'squp': _num(row.get('SquaredUp'))})
    if not balls:
        return {}
    top_half = sorted(balls, key=lambda b: b['ev'], reverse=True)[:max(1, len(balls) // 2)]
    dists = [b['dist'] for b in top_half if b['dist'] is not None]
    angles = [b['angle'] for b in balls if b['angle'] is not None]
    squps = [b['squp'] for b in balls if b['squp'] is not None]
    return {
        'top50_dist': round(sum(dists) / len(dists), 1) if dists else None,
        'avg_launch_angle': round(sum(angles) / len(angles), 1) if angles else None,
        'squared_up_pct': round(100 * sum(squps) / len(squps), 1) if squps else None,
    }


def pitcher_velo_ev_metrics(master_rows, pitcher_name):
    """Fastball Velo and Avg Exit Velo Allowed aren't on the Totals sheet at
    all — they only exist as raw per-pitch values on the Master tab — so
    they're computed here the same way pitcher_spin_ev_so derives its
    per-pitch-type numbers, just rolled up across all of this pitcher's
    pitches instead of split by type."""
    fb_velos, all_evs = [], []
    for row in master_rows:
        if row.get('Pitcher') != pitcher_name:
            continue
        label = PITCH_TYPE_MAP.get(row.get('Pitch Type'))
        if label == 'Fastball' and _num(row.get('Velocity')) is not None:
            fb_velos.append(row['Velocity'])
        if _num(row.get('ExitSpeed')) is not None:
            all_evs.append(row['ExitSpeed'])
    return {
        'fb_velo': round(sum(fb_velos) / len(fb_velos), 1) if fb_velos else None,
        'avg_ev_allowed': round(sum(all_evs) / len(all_evs), 1) if all_evs else None,
    }


def build_pitcher_percentiles(totals_row, velo_ev=None):
    def pct(key, val):
        return bm.interpolate(val, bm.PITCHER[key]) if val is not None else None

    velo_ev = velo_ev or {}
    fb_velo = _num(velo_ev.get('fb_velo'))
    avg_ev_allowed = _num(velo_ev.get('avg_ev_allowed'))

    strike_pct = _num(totals_row.get('S%'))
    strike_pct = strike_pct * 100 if strike_pct is not None else None
    fps_pct = _num(totals_row.get('FPS%'))
    fps_pct = fps_pct * 100 if fps_pct is not None else None
    k_pct = _num(totals_row.get('K%'))
    k_pct = k_pct * 100 if k_pct is not None else None
    bb_pct = _num(totals_row.get('BB%'))
    bb_pct = bb_pct * 100 if bb_pct is not None else None
    whiff_pct = _num(totals_row.get('SW/M%'))
    whiff_pct = whiff_pct * 100 if whiff_pct is not None else None

    rows = [
        {'label': 'FB Velo', 'value': fb_velo, 'pctl': pct('fb_velo', fb_velo), 'unit': ''},
        {'label': 'Avg EV Allowed', 'value': avg_ev_allowed, 'pctl': pct('avg_ev_allowed', avg_ev_allowed), 'unit': ''},
        {'label': 'Strike%', 'value': strike_pct, 'pctl': pct('strike_pct', strike_pct), 'unit': '%'},
        {'label': 'FPS%', 'value': fps_pct, 'pctl': pct('fps_pct', fps_pct), 'unit': '%'},
        {'label': 'K%', 'value': k_pct, 'pctl': pct('k_pct', k_pct), 'unit': '%'},
        {'label': 'BB%', 'value': bb_pct, 'pctl': pct('bb_pct', bb_pct), 'unit': '%'},
        {'label': 'Whiff%', 'value': whiff_pct, 'pctl': pct('whiff_pct', whiff_pct), 'unit': '%'},
    ]
    return [r for r in rows if r['value'] is not None]


def build_pitcher_percentiles_master(overall, velo_ev=None):
    """Same output shape as build_pitcher_percentiles(), but Strike%/FPS%/
    K%/BB%/Whiff% come from the Master-tab-derived `overall` dict (see
    pitcher_master_stats) instead of the Totals sheet's S%/FPS%/K%/BB%/
    SW-M% columns. FB Velo and Avg EV Allowed were already Master-derived
    either way."""
    def pct(key, val):
        return bm.interpolate(val, bm.PITCHER[key]) if val is not None else None

    velo_ev = velo_ev or {}
    fb_velo = _num(velo_ev.get('fb_velo'))
    avg_ev_allowed = _num(velo_ev.get('avg_ev_allowed'))
    overall = overall or {}

    rows = [
        {'label': 'FB Velo', 'value': fb_velo, 'pctl': pct('fb_velo', fb_velo), 'unit': ''},
        {'label': 'Avg EV Allowed', 'value': avg_ev_allowed, 'pctl': pct('avg_ev_allowed', avg_ev_allowed), 'unit': ''},
        {'label': 'Strike%', 'value': overall.get('strike_pct'), 'pctl': pct('strike_pct', overall.get('strike_pct')), 'unit': '%'},
        {'label': 'FPS%', 'value': overall.get('fps_pct'), 'pctl': pct('fps_pct', overall.get('fps_pct')), 'unit': '%'},
        {'label': 'K%', 'value': overall.get('k_pct'), 'pctl': pct('k_pct', overall.get('k_pct')), 'unit': '%'},
        {'label': 'BB%', 'value': overall.get('bb_pct'), 'pctl': pct('bb_pct', overall.get('bb_pct')), 'unit': '%'},
        {'label': 'Whiff%', 'value': overall.get('whiff_pct'), 'pctl': pct('whiff_pct', overall.get('whiff_pct')), 'unit': '%'},
    ]
    return [r for r in rows if r['value'] is not None]


def build_hitter_percentiles(totals_row, derived):
    def pct(key, val):
        return bm.interpolate(val, bm.HITTER[key]) if val is not None else None

    ev90 = _num(totals_row.get('EV90'))
    bs90 = _num(totals_row.get('BatSpeed90'))
    k_pct = _num(totals_row.get('K%'))
    k_pct = k_pct * 100 if k_pct is not None else None
    bb_pct = _num(totals_row.get('BB%'))
    bb_pct = bb_pct * 100 if bb_pct is not None else None
    whiff_pct = _num(totals_row.get('Whiff %'))
    whiff_pct = whiff_pct * 100 if whiff_pct is not None else None
    top50 = derived.get('top50_dist')
    angle = derived.get('avg_launch_angle')
    squp = derived.get('squared_up_pct')
    launch_q_pctl = pct('launch_quality', abs(angle - 18)) if angle is not None else None

    rows = [
        {'label': 'EV90', 'value': ev90, 'pctl': pct('ev90', ev90), 'unit': ''},
        {'label': 'Bat Speed 90', 'value': bs90, 'pctl': pct('bat_speed', bs90), 'unit': ''},
        {'label': 'Top 50% Dist', 'value': top50, 'pctl': pct('top50_dist', top50), 'unit': 'ft'},
        {'label': 'Avg Launch °', 'value': angle, 'pctl': launch_q_pctl, 'unit': '°'},
        {'label': 'Squared Up %', 'value': squp, 'pctl': pct('squared_up', squp), 'unit': '%'},
        {'label': 'Whiff %', 'value': whiff_pct, 'pctl': pct('whiff_pct', whiff_pct), 'unit': '%'},
        {'label': 'K%', 'value': k_pct, 'pctl': pct('k_pct', k_pct), 'unit': '%'},
        {'label': 'BB%', 'value': bb_pct, 'pctl': pct('bb_pct', bb_pct), 'unit': '%'},
    ]
    return [r for r in rows if r['value'] is not None]


def build_running_metrics(sixty_yd_time):
    """60 Yard Dash time (seconds, hand- or laser-timed) -> both the raw time
    and a derived Sprint Speed in ft/s (60 yards = 180 ft, so ft/s = 180 /
    time), each with its own percentile. Kept separate from
    build_hitter_percentiles() -- this never feeds the main percentile board
    or the MLB-comp matching, only the dedicated Running panel."""
    sixty_yd_time = _num(sixty_yd_time)
    if sixty_yd_time is None or sixty_yd_time <= 0:
        return []
    sprint_speed = round(180 / sixty_yd_time, 1)
    rows = [
        {'label': '60 Yard Dash', 'value': sixty_yd_time,
         'pctl': bm.interpolate(sixty_yd_time, bm.HITTER['sixty_yd']), 'unit': 's'},
        {'label': 'Sprint Speed', 'value': sprint_speed,
         'pctl': bm.interpolate(sprint_speed, bm.HITTER['sprint_speed']), 'unit': ' ft/s'},
    ]
    return rows
