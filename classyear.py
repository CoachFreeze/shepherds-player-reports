"""Class years for a team's own players. A roster records Fr / So / Jr / Sr / Gr as of the school year it was uploaded (the year turns over
on Aug 1). Each new school year the class moves up one; a Sr or Gr becomes graduated. A fresh roster upload that still lists him resets it,
so a returning fifth-year just shows as Gr again. A typed-in graduation year ("Class of 2027") counts as graduated once that spring is over."""
import os

import roster as roster_mod
import scoutbio

_UPD = {}


def _snaps(program):
    """{'ys': school year of the current roster, 'by_year': {school year: {name key: class}}} for the current roster and every kept earlier one."""
    path = roster_mod._path(program)
    try:
        m = os.path.getmtime(path)
    except OSError:
        return {'ys': None, 'by_year': {}}
    hit = _UPD.get(program)
    if hit and hit[0] == m:
        return hit[1]
    r = roster_mod.load(program) or {}
    by_year = {}
    for snap in list(r.get('history') or []) + [r]:                     # oldest first, so a later upload in the same school year wins
        if snap.get('updated') and snap.get('players'):
            y = scoutbio.school_year(snap['updated'])
            by_year[y] = {roster_mod.name_key(p['name']): scoutbio.norm_year(p.get('class_year')) for p in snap['players'] if p.get('name')}
    out = {'ys': scoutbio.school_year(r['updated']) if r.get('updated') else None, 'by_year': by_year}
    _UPD[program] = (m, out)
    return out


def roster_year(program):
    """The school year the program's current roster was uploaded in (None when it has none)."""
    return _snaps(program)['ys']


def view_year(program):
    """The school year of the season being looked at: today's for the current season, otherwise the one the picked season belongs to."""
    import datetime
    import season
    today = scoutbio.school_year()
    try:
        ss, sel = season.seasons(program), season.selected(program)
        if not ss or sel['key'] == ss[-1]['key']:
            return today
        d = sel['start'] or ((datetime.date.fromisoformat(sel['end']) - datetime.timedelta(days=1)).isoformat() if sel.get('end') else None)
        return scoutbio.school_year(d) if d else today
    except Exception:
        return today


def current(raw_class, ys, grad_year=None, now=None):
    """{'label': class in school year `now` or None, 'graduated': bool, 'note': 'was Jr in 2025-26' or ''}. `now` earlier than the recorded
    year works backward (a Sr recorded in 2026-27 was a Jr in 2025-26), and is blank before he could have been on the team."""
    now = now or scoutbio.school_year()
    out = {'label': None, 'graduated': False, 'note': ''}
    try:
        gy = int(grad_year) if grad_year else None
    except (TypeError, ValueError):
        gy = None
    y = scoutbio.norm_year(raw_class)
    if y and ys:
        steps = now - ys
        idx = scoutbio.YEARS.index(y) + steps
        tag = f'{ys - 1}-{str(ys)[2:]}'
        if steps > 0 and (y in ('Sr', 'Gr') or idx >= 4):
            out['graduated'], out['note'] = True, f'was {y} in {tag}'
        elif idx < 0:
            out['note'] = f'not yet on the team ({y} in {tag})'
        else:
            out['label'] = scoutbio.YEARS[idx]
            if steps:
                out['note'] = f'{y} in {tag}'
    elif raw_class:
        out['label'] = raw_class
    if gy and gy < now:
        out['graduated'] = True
    return out


def player_state(program, name, raw_class, ys, grad_year=None):
    """The class state for the season being viewed. A kept roster from that school year that lists him gives his class exactly;
    otherwise it is worked out from the class recorded on his profile."""
    program = program or 'shepherds'
    now = view_year(program)
    snap = _snaps(program)['by_year'].get(now)
    if snap is not None and name:
        y = snap.get(roster_mod.name_key(name))
        if y:
            return {'label': y, 'graduated': False, 'note': ''}
    return current(raw_class, ys or roster_year(program), grad_year, now)
