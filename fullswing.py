"""Full Swing (Live at Bat) CSV -> Trackman-shaped rows.

The app stores one shape of per-pitch row (Trackman's), so a Full Swing session is translated into that shape on upload and then
flows through the same intake, outings, pitcher and hitter code. What the Full Swing "Live at Bat" export contains:

  pitch      PitchNo, Date, Time, Pitcher, Batter, RelSpeed (mph), SpinRate (rpm), PitchDistance, Mode, LM FSID
  contact    ExitSpeed, Angle, Direction, Distance, HitSpinRate, SmashFactor, PotSmashFactor, PotExitSpeed, SquaredUp
  swing      BatSpeed (logged on every swing, with or without contact)

and what it does NOT contain: pitch location, pitch type, break/movement, count, handedness or a pitch call. So:
  * a row with BatSpeed and ExitSpeed          -> ball in play   (tag PC_InPlay)
  * a row with BatSpeed and no ExitSpeed       -> swing and miss (tag PC_StSw)
  * a row with neither                         -> unknown (take or no result); never counted as a ball or strike
Unnamed 'Guest' pitchers / batters are dropped. Strike %, chase, in-zone and swing-decision stats stay empty for Full Swing files.
"""
import csv
import datetime
import re

FS_KEYS = ('LM FSID', 'SmashFactor', 'PotSmashFactor')
KEEP = ('BatSpeed', 'SmashFactor', 'PotSmashFactor', 'PotExitSpeed', 'SquaredUp', 'HitSpinRate')
OUT_COLS = ['PitchNo', 'PitchUID', 'Date', 'Time', 'Pitcher', 'PitcherThrows', 'Batter', 'BatterSide', 'PitchCall', 'CustomTags',
            'TaggedPitchType', 'PitchSession', 'RelSpeed', 'SpinRate', 'ExitSpeed', 'Angle', 'Direction', 'Distance',
            'Balls', 'Strikes', 'Source'] + list(KEEP[:-1]) + ['HitSpinRate']
OUT_COLS = list(dict.fromkeys(OUT_COLS))


def _read(path):
    with open(path, newline='', encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


def is_fullswing(path):
    """True for a raw Full Swing export (not one we already converted)."""
    try:
        with open(path, newline='', encoding='utf-8-sig') as f:
            hdr = next(csv.reader(f), [])
    except Exception:
        return False
    return 'Source' not in hdr and 'PitchUID' not in hdr and any(k in hdr for k in FS_KEYS) and 'Pitcher' in hdr and 'Batter' in hdr


def is_converted(path):
    try:
        with open(path, newline='', encoding='utf-8-sig') as f:
            hdr = next(csv.reader(f), [])
        return 'Source' in hdr
    except Exception:
        return False


def _v(x):
    x = (x or '').strip()
    return '' if x.lower() in ('null', 'none', 'nan') else x


def _name(n):
    """'First Last' -> 'Last, First' (what the rest of the app expects). '' for guests / blanks."""
    n = re.sub(r'\s+', ' ', (n or '').strip())
    if not n or n.lower().startswith('guest') or ',' in n and not n.split(',')[1].strip():
        return ''
    if ',' in n:
        return n
    parts = n.split(' ')
    return f'{parts[-1]}, {" ".join(parts[:-1])}' if len(parts) > 1 else n


def _date(d):
    d = _v(d)
    for fmt in ('%m/%d/%y', '%m/%d/%Y', '%Y-%m-%d'):
        try:
            return datetime.datetime.strptime(d, fmt).strftime('%Y-%m-%d')
        except ValueError:
            pass
    return d


def _time(t):
    t = _v(t)
    for fmt in ('%I:%M:%S %p', '%H:%M:%S'):
        try:
            return datetime.datetime.strptime(t, fmt).strftime('%H:%M:%S')
        except ValueError:
            pass
    return t


def _num(x, nd=3):
    x = _v(x)
    try:
        return str(round(float(x), nd))
    except ValueError:
        return ''


def convert_rows(rows):
    """-> (trackman-shaped rows, summary dict)."""
    out, dropped_pitcher, dropped_batter, dropped_both = [], 0, 0, 0
    for r in rows:
        p, b = _name(r.get('Pitcher')), _name(r.get('Batter'))
        if not p:                                   # nobody to hang a pitcher profile on: the row can't be stored
            dropped_pitcher += 1
            continue
        if not b:
            dropped_batter += 1                     # keep the pitch for the pitcher (velo/spin); there is just no hitter
        d = _date(r.get('Date'))
        ev, bs = _num(r.get('ExitSpeed')), _num(r.get('BatSpeed'))
        if ev:
            call, tag = 'InPlay', 'PC_InPlay'
        elif bs:
            call, tag = 'StrikeSwinging', 'PC_StSw'
        else:
            call, tag = '', ''
        o = {c: '' for c in OUT_COLS}
        o.update({'PitchNo': _v(r.get('PitchNo')), 'PitchUID': f"fs-{_v(r.get('LM FSID'))}-{d}-{_v(r.get('PitchNo'))}",
                  'Date': d, 'Time': _time(r.get('Time')), 'Pitcher': p, 'Batter': b, 'PitchCall': call, 'CustomTags': tag, 'TaggedPitchType': 'Untagged',
                  'PitchSession': 'Live', 'Source': 'fullswing',
                  'RelSpeed': _num(r.get('RelSpeed'), 2), 'SpinRate': _num(r.get('SpinRate'), 0),
                  'ExitSpeed': ev, 'Angle': _num(r.get('Angle'), 2), 'Direction': _num(r.get('Direction'), 2),
                  'Distance': _num(r.get('Distance'), 0)})
        for k in KEEP:
            o[k] = _num(r.get(k), 4 if k in ('SmashFactor', 'PotSmashFactor', 'SquaredUp') else 2)
        out.append(o)
    summary = {'rows_in': len(rows), 'rows_out': len(out), 'dropped_guest_pitcher': dropped_pitcher,
               'no_batter': dropped_batter,
               'pitchers': sorted({o['Pitcher'] for o in out}), 'batters': sorted({o['Batter'] for o in out if o['Batter']}),
               'batted_balls': sum(1 for o in out if o['ExitSpeed']), 'misses': sum(1 for o in out if o['CustomTags'] == 'PC_StSw')}
    return out, summary


def convert_file(path):
    """Rewrites a Full Swing export in place as a Trackman-shaped CSV the existing intake understands. Returns the summary."""
    rows, summary = convert_rows(_read(path))
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=OUT_COLS)
        w.writeheader()
        w.writerows(rows)
    return summary
