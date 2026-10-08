"""
All persisted app state, kept as plain JSON files under data/ -- consistent
with how this project has always stored config (bio_config.json,
comps_cache.json) and plenty for a tool used by a handful of coaches and a
few dozen players. Swap for a real database later if the roster/coach count
ever grows enough to need it; nothing calling into this module would need to
change.
"""
import json
import os
import re
from werkzeug.security import generate_password_hash, check_password_hash

import github_sync

BUILD_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BUILD_DIR, 'data')
COACHES_PATH = os.path.join(DATA_DIR, 'coaches.json')
PLAYERS_PATH = os.path.join(DATA_DIR, 'players.json')


def slugify(name):
    return re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_')


def _load(path, default):
    if not os.path.exists(path):
        return default
    with open(path) as f:
        return json.load(f)


def _save(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        json.dump(data, f, indent=2, sort_keys=True)


# --- Coaches ----------------------------------------------------------------

def list_coaches():
    return _load(COACHES_PATH, {})


def add_coach(username, display_name, password):
    coaches = list_coaches()
    coaches[username] = {
        'display_name': display_name,
        'password_hash': generate_password_hash(password),
    }
    _save(COACHES_PATH, coaches)


def verify_coach(username, password):
    coaches = list_coaches()
    entry = coaches.get(username)
    if not entry:
        return False
    return check_password_hash(entry['password_hash'], password)


def coach_display_name(username):
    return list_coaches().get(username, {}).get('display_name', username)


# --- Players ------------------------------------------------------------
# players.json shape:
# {
#   "jackson_orr": {
#     "name": "Jackson Orr", "school": "La Mirada HS", "grad_year": 2032,
#     "roles": {"pitch": {"position": "LHP"}, "hit": {"position": "OF"}},
#     "comps": {
#       "pitch": [{"name": "...", "position": "...", "source": "auto|locked"}],
#       "hit":   [{"name": "...", "position": "...", "source": "auto|locked"}]
#     }
#   }
# }

OVERRIDES_PATH = os.path.join(DATA_DIR, 'bio_overrides.json')


def list_players():
    """players.json plus data/bio_overrides.json -- a small hand-editable file of extra bio
    fields (height_in, weight_lbs, ...) per player slug. Overrides only fill fields the
    player's own record doesn't already have, so an intake-form value always wins."""
    players = _load(PLAYERS_PATH, {})
    for slug, extra in _load(OVERRIDES_PATH, {}).items():
        if slug in players and isinstance(extra, dict):
            for k, v in extra.items():
                players[slug].setdefault(k, v)
    return players


def sync_to_github():
    """Best-effort: pushes the current data/players.json straight to GitHub
    (see github_sync.py). Called once at the end of each coach-facing
    action (a new upload, a comp override, a 60-time edit) rather than
    after every individual setter, so one action produces one commit
    instead of several. A no-op if GITHUB_TOKEN/GITHUB_REPO aren't set."""
    github_sync.sync_players_json(list_players())


def get_player(slug):
    return list_players().get(slug)


def upsert_player_bio(name, school, grad_year, position_pitch=None, position_hit=None, height_in=None, weight_lbs=None):
    players = list_players()
    slug = slugify(name)
    entry = players.get(slug, {'comps': {}})
    entry['name'] = name
    entry['school'] = school
    entry['grad_year'] = grad_year
    if height_in:                       # total inches; only overwritten when a new value is given
        entry['height_in'] = height_in
    if weight_lbs:
        entry['weight_lbs'] = weight_lbs
    roles = entry.setdefault('roles', {})
    if position_pitch:
        roles['pitch'] = {'position': position_pitch}
    if position_hit:
        roles['hit'] = {'position': position_hit}
    players[slug] = entry
    _save(PLAYERS_PATH, players)
    return slug


def set_last_xlsx(slug, xlsx_path):
    players = list_players()
    entry = players.setdefault(slug, {'comps': {}})
    entry['last_xlsx_path'] = xlsx_path
    players[slug] = entry
    _save(PLAYERS_PATH, players)


def set_program(slug, program):
    """Which roster group this player shows under on the dashboard --
    'shepherds' (Full Swing-based, Shepherds Baseball's own training
    program) or 'long_beach_state' (Trackman-only, no Full Swing data).
    A player without this set (every player added before this field existed)
    is treated as 'shepherds' by whatever reads it, since all of them are
    Full Swing-based."""
    players = list_players()
    entry = players.setdefault(slug, {'comps': {}})
    entry['program'] = program
    players[slug] = entry
    _save(PLAYERS_PATH, players)


def set_last_trackman(slug, csv_path):
    """Path to this player's most recently uploaded Trackman CSV (pitching
    only -- optional, alongside the Full Swing workbook). Same pattern as
    set_last_xlsx(): render_pitcher() reads real break/spin data from this
    file when present, and falls back to sample values when it's absent."""
    players = list_players()
    entry = players.setdefault(slug, {'comps': {}})
    entry['last_trackman_path'] = csv_path
    players[slug] = entry
    _save(PLAYERS_PATH, players)


def set_sixty_yd_time(slug, seconds):
    """60-yard dash time in seconds (hitters only). Stored on the player so
    it survives re-uploads/regenerations without needing to be re-entered
    every time -- pipeline.render_hitter() derives Sprint Speed (ft/s) and
    both percentiles from this on every render."""
    players = list_players()
    entry = players.setdefault(slug, {'comps': {}})
    entry['sixty_yd_time'] = seconds
    players[slug] = entry
    _save(PLAYERS_PATH, players)


def set_auto_comps(slug, role, auto_comps, n_slots):
    """Writes the engine's suggestions into every slot that isn't locked by a
    coach. Locked slots are left completely untouched."""
    players = list_players()
    entry = players.setdefault(slug, {'comps': {}})
    comps_for_role = entry.setdefault('comps', {}).setdefault(role, [])

    locked = [c for c in comps_for_role if c.get('source') == 'locked']
    locked_names = {c['name'] for c in locked}

    fresh_auto = [c for c in auto_comps if c['name'] not in locked_names][:max(0, n_slots - len(locked))]
    for c in fresh_auto:
        c['source'] = 'auto'

    # Keep locked slots in their original position where possible; fill the
    # rest with fresh auto picks.
    merged = locked + fresh_auto
    comps_for_role[:] = merged[:n_slots]

    players[slug] = entry
    _save(PLAYERS_PATH, players)
    return comps_for_role


def override_comp(slug, role, index, name, position=None):
    """A coach replaces (or adds) the comp at `index` with their own pick,
    locking that slot so future auto-runs leave it alone."""
    players = list_players()
    entry = players.setdefault(slug, {'comps': {}})
    comps_for_role = entry.setdefault('comps', {}).setdefault(role, [])
    while len(comps_for_role) <= index:
        comps_for_role.append({'name': None, 'position': None, 'source': 'auto'})
    comps_for_role[index] = {'name': name, 'position': position, 'source': 'locked'}
    players[slug] = entry
    _save(PLAYERS_PATH, players)


def unlock_comp(slug, role, index):
    """Coach reverts a slot back to algorithm control. It'll show the old
    pick until the next regeneration recomputes it."""
    players = list_players()
    entry = players.get(slug)
    if not entry:
        return
    comps_for_role = entry.get('comps', {}).get(role, [])
    if index < len(comps_for_role):
        comps_for_role[index]['source'] = 'auto'
    _save(PLAYERS_PATH, players)
