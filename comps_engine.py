"""
Automatic MLB comps engine.

Replaces the old conversational process (ask Claude to pick comps by hand)
with a real similarity calculation:

  1. Our player's percentile rows (from build_hitter_percentiles /
     build_pitcher_percentiles_master) are already on a 0-100 "higher is
     always better" scale -- the same convention Baseball Savant itself uses
     for its own percentile rankings (e.g. a hitter's K% percentile is
     already inverted so a LOW strikeout rate shows as a HIGH percentile).
  2. data/mlb_reference.json holds hand-curated MLB player profiles on that
     same convention and the same categories, so the two are directly
     comparable -- not by raw numbers (our players are HS/college, not MLB),
     but by the *shape* of their percentile profile: who's relatively
     power-over-contact, patient-over-aggressive, etc.
  3. Candidates are filtered to the same role (hitter/pitcher) and a loosely
     matching position group first, then ranked by Euclidean distance on the
     percentile vector. Closest distances win.

Output is tagged 'auto' so the web app knows these were algorithm-generated,
as opposed to a coach's manual override (tagged 'locked' -- see app.py).
"""
import json
import math
import os

REFERENCE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'mlb_reference.json')

HITTER_KEYS = ['ev90', 'bat_speed', 'top50_dist', 'launch_quality', 'squared_up', 'whiff_pct', 'k_pct', 'bb_pct']
PITCHER_KEYS = ['fb_velo', 'avg_ev_allowed', 'strike_pct', 'fps_pct', 'k_pct', 'bb_pct', 'whiff_pct']

# Loose position groups so e.g. a 2B comps against middle infielders before
# we'd ever reach for a 1B/DH masher -- without being so strict that a
# position with few MLB reference examples comes up empty.
POSITION_GROUPS = {
    'C': {'C'},
    '1B': {'1B', 'OF/1B', '2B/1B'},
    '2B': {'2B', '2B/SS', '2B/OF', 'SS'},
    '3B': {'3B', 'SS'},
    'SS': {'SS', '2B/SS'},
    'OF': {'OF', 'OF/DH', 'OF/1B', 'OF/SS', '2B/OF'},
    'DH': {'OF/DH', '1B'},
    'INF': {'2B', '3B', 'SS', '1B', '2B/SS', '2B/1B'},
    'RHP': {'RHP'},
    'LHP': {'LHP'},
}


def _load_reference():
    with open(REFERENCE_PATH) as f:
        return json.load(f)


def _position_group_names(position):
    """Our players' positions are free text ('OF/1B', 'RHP/INF', etc.) --
    take the first slash-separated token and anything it loosely maps to."""
    if not position:
        return set()
    tokens = [t.strip().upper() for t in position.replace('/', ' ').split()]
    groups = set()
    for t in tokens:
        for group_name, members in POSITION_GROUPS.items():
            if t == group_name or t in members:
                groups.add(group_name)
    return groups


def _candidate_matches_position(candidate_position, wanted_groups):
    if not wanted_groups:
        return True  # no position info on our player -- don't filter anything out
    cand_groups = _position_group_names(candidate_position)
    return bool(cand_groups & wanted_groups)


def _vector_distance(a, b, keys):
    diffs = []
    for k in keys:
        av, bv = a.get(k), b.get(k)
        if av is None or bv is None:
            continue
        diffs.append((av - bv) ** 2)
    if not diffs:
        return float('inf')
    return math.sqrt(sum(diffs) / len(diffs))  # mean so missing keys don't skew it


def _percentile_rows_to_vector(pctl_rows, label_to_key):
    """pctl_rows is the output of build_hitter_percentiles/
    build_pitcher_percentiles_master: [{'label':..., 'value':..., 'pctl':...}]."""
    vec = {}
    for row in pctl_rows:
        key = label_to_key.get(row['label'])
        if key and row.get('pctl') is not None:
            vec[key] = row['pctl']
    return vec


# Qualitative phrasing per metric/tier, used to build each comp's "why this
# player" write-up. Each phrase is a full predicate meant to follow "both" --
# e.g. "both {phrase}" -- so every entry needs to be a self-contained verb
# phrase, not a bare noun fragment. 'high'/'low' describe a notably strong or
# weak trait; 'mid' traits are never mentioned since "about average" tells a
# coach nothing worth watching for.
HITTER_TRAITS = {
    'ev90':           {'high': 'hit the ball with well above-average raw power', 'low': 'profile with modest raw power right now'},
    'bat_speed':      {'high': 'swing with plus bat speed', 'low': 'show below-average bat speed'},
    'top50_dist':     {'high': 'carry the ball deep when they connect', 'low': "don't hit for much distance yet"},
    'launch_quality': {'high': 'show a consistently efficient launch angle', 'low': 'are still developing their launch-angle control'},
    'squared_up':     {'high': 'show excellent barrel control and contact quality', 'low': 'show below-average contact quality'},
    'whiff_pct':      {'high': 'rarely swing and miss', 'low': 'show some swing-and-miss in their game'},
    'k_pct':          {'high': 'keep the strikeouts down', 'low': 'carry an elevated strikeout rate'},
    'bb_pct':         {'high': 'show a patient approach that draws walks', 'low': 'play with an aggressive, early-count approach'},
}
PITCHER_TRAITS = {
    'fb_velo':        {'high': 'bring plus fastball velocity', 'low': 'pitch with below-average velocity, leaning more on command and shape'},
    'avg_ev_allowed': {'high': 'are excellent at limiting hard contact', 'low': 'allow more hard contact than most'},
    'strike_pct':     {'high': 'show well above-average strike-throwing', 'low': 'show below-average strike-throwing'},
    'fps_pct':        {'high': 'get ahead in counts early', 'low': 'fall behind in counts more than most'},
    'k_pct':          {'high': 'post a high strikeout rate', 'low': 'post a modest strikeout rate and work more off contact'},
    'bb_pct':         {'high': 'show excellent walk avoidance and control', 'low': 'walk more hitters than most'},
    'whiff_pct':      {'high': 'carry a swing-and-miss arsenal', 'low': 'work with a pitch mix hitters make contact against'},
}
HIGH_CUTOFF, LOW_CUTOFF = 72, 32


def _tier(val):
    if val is None:
        return None
    if val >= HIGH_CUTOFF:
        return 'high'
    if val <= LOW_CUTOFF:
        return 'low'
    return 'mid'


def _build_blurb(our_vec, cand, keys, traits, our_name, role_noun):
    """Finds the shared high/low traits our player and this comp have in
    common and turns them into a short, specific sentence -- not just a
    name and a photo."""
    cand_vec = cand['pctl']
    shared = []
    for k in keys:
        ot, ct = _tier(our_vec.get(k)), _tier(cand_vec.get(k))
        if ot and ct and ot == ct and ot != 'mid' and k in traits:
            # rank by how extreme the shared trait is (further from 50 = more defining)
            extremity = abs(our_vec[k] - 50) + abs(cand_vec[k] - 50)
            shared.append((extremity, traits[k][ot]))
    shared.sort(key=lambda t: t[0], reverse=True)
    phrases = [p for _, p in shared[:2]]

    if not phrases:
        return (f"{cand['name']} is the closest statistical match in this reference set for "
                f"{our_name} right now — worth studying his overall approach as a {role_noun}.")
    if len(phrases) == 1:
        trait_text = phrases[0]
    else:
        trait_text = f'{phrases[0]} and {phrases[1]}'
    return f"{cand['name']} is a close statistical match for {our_name} — both {trait_text}. Watch for that same pattern on film."


HITTER_LABEL_TO_KEY = {
    'EV90': 'ev90', 'Bat Speed 90': 'bat_speed', 'Top 50% Dist': 'top50_dist',
    'Avg Launch °': 'launch_quality', 'Squared Up %': 'squared_up',
    'Whiff %': 'whiff_pct', 'K%': 'k_pct', 'BB%': 'bb_pct',
}
PITCHER_LABEL_TO_KEY = {
    'FB Velo': 'fb_velo', 'Avg EV Allowed': 'avg_ev_allowed', 'Strike%': 'strike_pct',
    'FPS%': 'fps_pct', 'K%': 'k_pct', 'BB%': 'bb_pct', 'Whiff%': 'whiff_pct',
}


def find_comps(pctl_rows, role, our_name='this player', position=None, n=3, exclude_names=None, locked_names=None):
    """role: 'hitter' or 'pitcher'. position: our player's position string
    (e.g. 'OF/1B'). exclude_names: comp names already assigned elsewhere on
    this report (avoid duplicates across slots). locked_names: coach-chosen
    names that should never be displaced by this call (still returned, just
    not recomputed) -- callers typically filter locked slots out before
    calling this at all; this param exists for convenience when calling it
    on the full slot list.

    Returns up to n dicts: {'name', 'position', 'distance', 'source': 'auto'}.
    """
    exclude_names = set(exclude_names or [])
    locked_names = set(locked_names or [])
    ref = _load_reference()

    if role == 'hitter':
        keys, label_map, pool, traits = HITTER_KEYS, HITTER_LABEL_TO_KEY, ref['hitters'], HITTER_TRAITS
    else:
        keys, label_map, pool, traits = PITCHER_KEYS, PITCHER_LABEL_TO_KEY, ref['pitchers'], PITCHER_TRAITS

    our_vec = _percentile_rows_to_vector(pctl_rows, label_map)
    wanted_groups = _position_group_names(position)

    scored = []
    for cand in pool:
        if cand['name'] in exclude_names or cand['name'] in locked_names:
            continue
        if not _candidate_matches_position(cand['position'], wanted_groups):
            continue
        dist = _vector_distance(our_vec, cand['pctl'], keys)
        scored.append((dist, cand))

    # If the position filter was too strict to find enough candidates (small
    # reference set), fall back to the whole pool rather than returning short.
    if len(scored) < n:
        scored = []
        for cand in pool:
            if cand['name'] in exclude_names or cand['name'] in locked_names:
                continue
            dist = _vector_distance(our_vec, cand['pctl'], keys)
            scored.append((dist, cand))

    scored.sort(key=lambda t: t[0])
    role_noun = 'hitter' if role == 'hitter' else 'pitcher'
    out = []
    for dist, cand in scored[:n]:
        out.append({
            'name': cand['name'],
            'position': cand['position'],
            'distance': round(dist, 2),
            'source': 'auto',
            'blurb': _build_blurb(our_vec, cand, keys, traits, our_name, role_noun),
        })
    return out
