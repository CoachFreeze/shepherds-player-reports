"""Personal bests (PRs) for pitchers and hitters.

A PR is the best value a player has ever posted for a tracked stat, across every session (games and practice together).
Each stat is checked session by session in date order; a session that strictly beats everything before it is a PR event
(the first session a player has only sets the baseline, it is not a broken record). Ties keep the earlier date.

build() returns the whole index and caches it until a stored outing file changes:
  {'p': {pitcher slug: entity}, 'h': {hitter key: entity}, 'uploads': {upload id: {'dates': set, 'slugs': set}}}
  entity = {'name', 'program', 'demo', 'last': latest session date, 'items': [current PR per stat], 'new': count set in the latest session,
            'events': [every record-breaking session]}
  item/event = {'id', 'group', 'label', 'value', 'disp', 'date', 'prev', 'prev_disp', 'new'}
"""
import datetime
import os

import extract as e
import cache
import hitting
import outings as outings_mod
import store

RECENT_DAYS = 14

_BREAKING = ('Slider', 'Sweeper', 'Curveball')
_FASTBALLS = ('Fastball', 'Sinker')


# ------------------------------------------------------------------ the stats (id, group, label, format)
def _f1(v):
    return f'{v:.1f}'


def _f0(v):
    return f'{v:,.0f}'


def _pct(v):
    return f'{v:.1f}%'


def _ft(v):
    return f'{v:,.0f} ft'


def _bbl(v):
    return f'{v:.1f} in'


def _pitch_session(rows):
    """{stat id: (group, label, value, disp)} for one pitcher on one day (a session is one date)."""
    out = {}
    by_t = {}
    swings = whiffs = pitches = strikes = 0
    for r in rows:
        t = hitting._PT_LABELS.get(r.get('TaggedPitchType') or '')
        o = e._outcome(r)
        if o != 'unk':
            pitches += 1
            if o not in ('ball', 'hbp'):
                strikes += 1
        if o in ('whiff', 'foul', 'inplay'):
            swings += 1
            whiffs += o == 'whiff'
        if t:
            by_t.setdefault(t, []).append(r)
    top = 0
    for t, rs in by_t.items():
        v = [x for x in (e._fnum(r.get('RelSpeed')) for r in rs) if x]
        s = [x for x in (e._fnum(r.get('SpinRate')) for r in rs) if x]
        if v:
            out[f'velo:{t}'] = ('Velocity', f'Max {t.lower()} velo', max(v), f'{max(v):.1f} mph')
            top = max(top, max(v))
        if s:
            out[f'spin:{t}'] = ('Spin', f'Max {t.lower()} spin', max(s), f'{max(s):,.0f} rpm')
    if top:
        out['velo:all'] = ('Velocity', 'Max velocity (any pitch)', top, f'{top:.1f} mph')
    fb = [r for t in _FASTBALLS for r in by_t.get(t, [])]
    fv = [x for x in (e._fnum(r.get('RelSpeed')) for r in fb) if x]
    if len(fv) >= 10:
        a = sum(fv) / len(fv)
        out['avgfb'] = ('Velocity', 'Best average fastball velo', a, f'{a:.1f} mph')
    ivb = [x for x in (e._fnum(r.get('InducedVertBreak')) for r in by_t.get('Fastball', [])) if x is not None]
    if ivb:
        out['ivb'] = ('Movement', 'Most fastball induced vertical break', max(ivb), f'{max(ivb):.1f} in')
    hb = [abs(x) for t in _BREAKING for x in (e._fnum(r.get('HorzBreak')) for r in by_t.get(t, [])) if x is not None]
    if hb:
        out['hb'] = ('Movement', 'Most horizontal break on a breaking ball', max(hb), f'{max(hb):.1f} in')
    if whiffs:
        out['whiffs'] = ('Results', 'Most whiffs in an outing', whiffs, f'{whiffs}')
    if swings >= 15:
        out['whiffpct'] = ('Results', 'Best whiff rate (15+ swings)', 100 * whiffs / swings, f'{100 * whiffs / swings:.1f}%')
    if pitches >= 30:
        out['strikepct'] = ('Results', 'Best strike % (30+ pitches)', 100 * strikes / pitches, f'{100 * strikes / pitches:.1f}%')
    if len(rows):
        out['pitches'] = ('Workload', 'Longest outing (pitches)', len(rows), f'{len(rows)}')
    return out


def _hit_session(ps):
    out = {}
    bbs = [p for p in ps if p['outcome'] == 'inplay' and p['ev'] is not None]
    evs = [p['ev'] for p in bbs]
    if evs:
        out['maxev'] = ('Power', 'Max exit velocity', max(evs), f'{max(evs):.1f} mph')
        dist = [p['distance'] for p in bbs if p.get('distance')]
        if dist:
            out['dist'] = ('Power', 'Longest batted ball', max(dist), f'{max(dist):,.0f} ft')
        hh = sum(1 for v in evs if v >= 95)
        if hh:
            out['hardhit'] = ('Power', 'Most hard-hit balls (95+ mph) in a session', hh, f'{hh}')
    s = hitting.hitter_stats(ps)
    if len(evs) >= 5:
        out['avgev'] = ('Power', 'Best average exit velocity (5+ balls)', s['avg_ev'], f"{s['avg_ev']:.1f} mph")
        if s['sweet_spot_pct'] is not None:
            out['sweet'] = ('Contact', 'Best sweet-spot rate (5+ balls)', s['sweet_spot_pct'], f"{s['sweet_spot_pct']:.1f}%")
    if s['mix_n'] >= 5 and s['brl_pct'] is not None:
        out['barrel'] = ('Power', 'Best barrel rate (5+ balls)', s['brl_pct'], f"{s['brl_pct']:.1f}%")
    if s['decisions'] >= 15 and s['score'] is not None:
        out['sdr'] = ('Decisions', 'Best Swing Decision Rating (15+ decisions)', s['score'], f"{s['score']}")
    return out


# ------------------------------------------------------------------ walking the sessions
def _walk(name, program, demo, sessions):
    """sessions = {date: {stat id: (group, label, value, disp)}} -> entity dict."""
    dates = sorted(sessions)
    if not dates:
        return None
    best = {}
    events = []
    for d in dates:
        for sid, (grp, label, val, disp) in sessions[d].items():
            if not val or val <= 0:           # a zero is not a personal best
                continue
            cur = best.get(sid)
            if cur is None:
                best[sid] = {'id': sid, 'group': grp, 'label': label, 'value': val, 'disp': disp, 'date': d, 'prev': None, 'prev_disp': None}
            elif val > cur['value'] + 1e-9:
                ev = {'id': sid, 'group': grp, 'label': label, 'value': val, 'disp': disp, 'date': d, 'prev': cur['value'], 'prev_disp': cur['disp']}
                events.append(ev)
                best[sid] = dict(ev)
    last = dates[-1]
    for it in best.values():
        it['new'] = it['date'] == last and it['prev'] is not None
    for ev in events:
        ev['new'] = ev['date'] == last
    order = ['Velocity', 'Spin', 'Movement', 'Results', 'Workload', 'Power', 'Contact', 'Decisions']
    items = sorted(best.values(), key=lambda i: (order.index(i['group']) if i['group'] in order else 99, i['label']))
    return {'name': name, 'program': program, 'demo': demo, 'last': last, 'items': items,
            'new': sum(1 for i in items if i['new']), 'events': events, 'sessions': len(dates)}


_CACHE = {'sig': None, 'data': None}


def _signature():
    return cache.data_version()


def _old_signature():
    sig = []
    d = outings_mod.OUTINGS_DIR
    if os.path.isdir(d):
        for f in sorted(os.listdir(d)):
            if f.endswith('.json'):
                st = os.stat(os.path.join(d, f))
                sig.append((f, st.st_mtime_ns, st.st_size))
    return tuple(sig)


def build():
    try:
        return _build()
    except Exception as exc:                 # personal bests must never be able to break a page
        print(f'WARNING: personal bests unavailable: {exc}')
        return {'p': {}, 'h': {}, 'uploads': {}}


def _build():
    sig = _signature()
    if _CACHE['sig'] == sig and _CACHE['data'] is not None:
        return _CACHE['data']
    data = {'p': {}, 'h': {}, 'uploads': {}}
    real, demo = hitting._all_pitch_files()
    real_slugs = {s for s, _ in real}
    for slug, is_demo in real + demo:
        if is_demo and slug in real_slugs:
            continue
        if slug.startswith('opp-'):
            continue
        pl = store.get_player(slug) or {}
        sessions = {}
        for o in outings_mod.load(slug)['outings']:
            if o.get('rows'):
                sessions[o['date']] = _pitch_session(o['rows'])
            for r in o['rows']:
                up = r.get('_upload')
                if up:
                    u = data['uploads'].setdefault(up, {'dates': set(), 'slugs': set()})
                    u['dates'].add(o['date'])
                    u['slugs'].add(slug)
        ent = _walk(pl.get('name') or slug, pl.get('program') or ('demo_university' if is_demo else None), is_demo, sessions)
        if ent:
            data['p'][slug] = ent
    for key, h in hitting._collect(True).items():
        by_d = {}
        for p in h['pitches']:
            if p.get('date'):
                by_d.setdefault(p['date'], []).append(p)
        ent = _walk(hitting.display_name(h['name']), h['program'], h['demo'], {d: _hit_session(ps) for d, ps in by_d.items()})
        if ent:
            data['h'][key] = ent
    _CACHE['sig'], _CACHE['data'] = sig, data
    return data


# ------------------------------------------------------------------ helpers the pages use
def for_pitcher(slug):
    return build()['p'].get(slug)


def for_hitter(key):
    return build()['h'].get(key)


def new_count(kind, key):
    ent = build()[kind].get(key)
    return ent['new'] if ent else 0


def program_recent(program, days=RECENT_DAYS, limit=12):
    """Record-breaking sessions for a team within `days` of that team's latest session, newest first."""
    d = build()
    ents = [(k, 'p', v) for k, v in d['p'].items() if v['program'] == program] + [(k, 'h', v) for k, v in d['h'].items() if v['program'] == program]
    if not ents:
        return []
    newest = max(v['last'] for _, _, v in ents)
    try:
        cut = (datetime.date.fromisoformat(newest) - datetime.timedelta(days=days)).isoformat()
    except ValueError:
        cut = ''
    out = []
    for k, kind, v in ents:
        for ev in v['events']:
            if ev['date'] >= cut:
                out.append({**ev, 'who': v['name'], 'kind': kind, 'key': k})
    out.sort(key=lambda x: (x['date'], x['who']), reverse=True)
    return out[:limit]


def upload_events(entry):
    """Record-breaking results set on the sessions an upload touched: [{who, label, disp, prev_disp, kind, key}]."""
    d = build()
    u = d['uploads'].get(entry.get('id') or '')
    if not u:
        return []
    out = []
    for slug in u['slugs']:
        v = d['p'].get(slug)
        if v:
            out += [{**ev, 'who': v['name'], 'kind': 'p', 'key': slug} for ev in v['events'] if ev['date'] in u['dates']]
    for k, v in d['h'].items():
        if v['program'] == entry.get('program') and not v['demo']:
            out += [{**ev, 'who': v['name'], 'kind': 'h', 'key': k} for ev in v['events'] if ev['date'] in u['dates']]
    return out
