"""
D2 percentile benchmark curves — reconstructed from the D2 Pitcher/Hitter
Percentile Calculator workbooks (Benchmarks tabs), verified earlier against
Garcia's and Steck's actual PDF reports. Values -> percentile, interpolated
linearly between anchor points and clamped at the ends.
"""

def interpolate(value, table):
    if value is None:
        return None
    pts = sorted(table, key=lambda p: p[0])
    if value <= pts[0][0]:
        return round(pts[0][1])
    if value >= pts[-1][0]:
        return round(pts[-1][1])
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= value <= x1:
            frac = (value - x0) / (x1 - x0) if x1 != x0 else 0
            return round(y0 + frac * (y1 - y0))
    return round(pts[-1][1])

PITCHER = {
    'fb_velo':        [(80,3),(82,10),(84,25),(86,50),(88,70),(90,85),(92,95),(94,99),(96,99)],
    'avg_ev_allowed': [(75,99),(77,95),(79,88),(81,72),(84,50),(86,30),(88,15),(90,7),(92,2)],
    'strike_pct':     [(55,5),(58,15),(60,30),(62,45),(64,60),(66,75),(68,88),(70,95),(72,99)],
    'fps_pct':        [(45,5),(50,15),(54,30),(58.4,50),(62,70),(65,85),(68,95),(72,99),(75,99)],
    'k_pct':          [(12,5),(15,10),(17.5,25),(20.5,50),(23.5,65),(26.5,75),(30,90),(33,95),(36,98),(40,99)],
    'bb_pct':         [(4,99),(5.5,95),(6.5,90),(8,75),(9,65),(10.5,50),(12,35),(14,20),(16,10),(20,3)],
    'whiff_pct':      [(10,5),(14,15),(18,30),(22.5,50),(26,70),(30,85),(34,95),(38,99),(42,99)],
}

HITTER = {
    'bat_speed':      [(62,5),(64,10),(66,25),(68,50),(71,75),(74,90),(76,95),(78,99)],
    'ev90':           [(88,5),(90,15),(92,28),(94,45),(96,62),(98,78),(100,90),(102,96),(105,99)],
    'sixty_yd':       [(6.45,99),(6.55,97),(6.65,92),(6.7,85),(6.8,70),(6.9,55),(7,40),(7.15,25),(7.3,10),(7.5,3)],
    # Sprint Speed (ft/s) -- same curve as sixty_yd, just converted from
    # seconds to average feet-per-second over the 60-yard (180 ft) dash, so
    # the two stay perfectly consistent with each other.
    'sprint_speed':   [(24.0,3),(24.66,10),(25.17,25),(25.71,40),(26.09,55),(26.47,70),(26.87,85),(27.07,92),(27.48,97),(27.91,99)],
    'top50_dist':     [(220,10),(240,25),(255,40),(270,60),(277,70),(290,82),(305,92),(320,97),(335,99)],
    'launch_quality': [(0,85),(2,85),(4,80),(6,70),(9,55),(12,35),(20,15)],  # x = |angle-18|
    'smash_factor':   [(1.05,5),(1.15,20),(1.25,40),(1.32,60),(1.4,80),(1.45,90),(1.5,97),(1.55,99)],
    'squared_up':     [(45,5),(60,25),(70,45),(80,70),(88,92),(92,97),(96,99)],
    'k_pct':          [(10,95),(12,90),(14,80),(16,65),(18,50),(20,35),(23,20),(26,10),(30,3)],
    'bb_pct':         [(4,5),(6,15),(8,30),(10,50),(12,70),(14,85),(16,93),(18,97),(20,99)],
    'whiff_pct':      [(10,99),(12,97),(15.9,90),(20.5,75),(24.4,50),(28.5,25),(31.6,10),(35,5),(38,1)],
}
