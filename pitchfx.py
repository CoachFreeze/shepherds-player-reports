"""Pitch Effectiveness (per pitch type, split by the batter's side) for the pitcher player dashboard, plus the hand filter
used by the Pitch Movement Profile toggle."""
import extract as e
import stats as stats_mod

SIDES = (('R', 'vs Righties'), ('L', 'vs Lefties'))


def side_of(r):
    """'R' | 'L' | None from the batter side on a pitch row (Trackman 'Right'/'Left', or R/L)."""
    v = str(r.get('BatterSide') or r.get('Batter Side') or '').strip().upper()[:1]
    return v if v in ('R', 'L') else None


def by_side(rows, side):
    return [r for r in rows if side_of(r) == side]


def _label(r):
    return e._normalize_pitch_type(e._tm_get(r, e._TM_TYPE_COLS), fine=True)


def _xba(rs, outcomes):
    import hitting
    scored, ks = [], 0
    for r, o in zip(rs, outcomes):
        if o == 'inplay' and (r.get('HitType') or '') != 'Bunt':
            p = hitting.hit_prob(e._fnum(r.get('ExitSpeed')), e._fnum(r.get('Angle')))
            if p is not None:
                scored.append(p)
        elif o in ('whiff', 'cs') and str(r.get('Strikes')) == '2':
            ks += 1
    ab = len(scored) + ks
    return (sum(scored) / ab) if ab >= 3 else None


def _row(rs, total):
    c = stats_mod._core(rs)
    fs = bool(rs) and all((r.get('Source') or '') == 'fullswing' for r in rs)
    velos = [v for v in (e._fnum(r.get('RelSpeed')) for r in rs) if v]
    evs = [v for r, o in zip(rs, c['o']) if o == 'inplay' for v in [e._fnum(r.get('ExitSpeed'))] if v]
    return {'n': len(rs), 'usage': 100.0 * len(rs) / total if total else None,
            'velo': sum(velos) / len(velos) if velos else None,
            'zone': None if fs or not c['loc'] else 100.0 * c['zin'] / c['loc'],
            'whiff': 100.0 * c['whiffs'] / c['swings'] if c['swings'] else None,
            'chase': None if fs or not c['zout'] else 100.0 * c['osw'] / c['zout'],
            'ev': sum(evs) / len(evs) if evs else None,
            'xba': _xba(rs, c['o'])}


def effectiveness(rows, order, colors):
    """-> [{'side','title','n','rows':[{'type','color',+metrics}]}] for Righties then Lefties, one row per pitch type in `order`."""
    out = []
    for side, title in SIDES:
        sr = by_side(rows, side)
        groups = {}
        for r in sr:
            t = _label(r)
            if t:
                groups.setdefault(t, []).append(r)
        total = sum(len(g) for g in groups.values())
        out.append({'side': side, 'title': title, 'n': len(sr),
                    'rows': [dict(_row(groups.get(t, []), total), type=t, color=colors.get(t, '#555')) for t in order]})
    return out
