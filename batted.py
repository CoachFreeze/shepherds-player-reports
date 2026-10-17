"""Batted-ball classification shared by the hitting and pitching sides, so both use one set of cutoffs (the same ones Statcast uses).

Type from launch angle alone: ground ball < 10 deg, line drive 10-25, fly ball 25-50, pop-up > 50.
Barrel: MLB's published zone -- at least 98 mph, launch angle 26-30 at 98 mph, 25-31 at 99, 24-33 at 100, then roughly 1 degree wider
below and above per extra mph until 116 mph, where 8-50 degrees all count. MLB publishes the zone as a table; the points between its
quoted speeds are interpolated here, so a ball right on the edge can differ from Savant's own call. Barrel % = barrels / batted balls
that have both an exit velocity and a launch angle.
"""

_PTS = [(98.0, 26.0, 30.0), (99.0, 25.0, 31.0), (100.0, 24.0, 33.0), (116.0, 8.0, 50.0)]


def bucket(la):
    """'GB' | 'LD' | 'FB' | 'PU' from launch angle in degrees (None if unknown)."""
    if la is None:
        return None
    if la < 10:
        return 'GB'
    if la < 25:
        return 'LD'
    if la < 50:
        return 'FB'
    return 'PU'


def barrel_range(ev):
    """(low, high) launch angle that counts as a barrel at this exit velocity, or None below 98 mph."""
    if ev is None or ev < 98:
        return None
    if ev >= 116:
        return 8.0, 50.0
    for (e0, l0, h0), (e1, l1, h1) in zip(_PTS, _PTS[1:]):
        if e0 <= ev <= e1:
            f = (ev - e0) / (e1 - e0)
            return l0 + (l1 - l0) * f, h0 + (h1 - h0) * f
    return None


def is_barrel(ev, la):
    r = barrel_range(ev)
    return bool(r) and la is not None and r[0] <= la <= r[1]
