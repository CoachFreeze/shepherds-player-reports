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


# --- Programs ---------------------------------------------------------------
PUBLIC_PROGRAMS = set()                  # nothing is public: every program is private to its own coaches (and admins)
ADMIN_ONLY_PROGRAMS = {'shepherds'}      # Shepherds reports: only admins can see or be assigned to them
_KNOWN_LABELS = {'shepherds': 'Shepherds', 'long_beach_state': 'Long Beach State'}


def program_slug(label):
    return re.sub(r'[^a-z0-9]+', '_', (label or '').lower()).strip('_')


def program_label(slug):
    for c in _load(COACHES_PATH, {}).values():
        if c.get('program') == slug and c.get('program_label'):
            return c['program_label']
    return _KNOWN_LABELS.get(slug) or (slug or '').replace('_', ' ').title()


def list_programs():
    """Private programs known to the app: [(slug, label)]."""
    slugs = {p.get('program') for p in list_players().values() if p.get('program')} | {c.get('program') for c in list_coaches().values() if c.get('program')}
    return sorted(((x, program_label(x)) for x in slugs if x and x not in ADMIN_ONLY_PROGRAMS), key=lambda t: t[1])


# --- Coaches ----------------------------------------------------------------

def list_coaches():
    return _load(COACHES_PATH, {})


def _push_coaches():
    try:
        with open(COACHES_PATH, 'rb') as f:
            github_sync.put_file('data/coaches.json', f.read())
    except Exception as exc:
        print(f'WARNING: could not push coaches.json: {exc}')


def add_coach(username, display_name, password, role='admin', program=None, push=False, program_label=None):
    """role: 'admin' (everything) or 'program' (only the players of one program, e.g. long_beach_state)."""
    coaches = list_coaches()
    coaches[username] = {
        'display_name': display_name,
        'password_hash': generate_password_hash(password),
        'role': role,
    }
    if program:
        coaches[username]['program'] = program
        if program_label:
            coaches[username]['program_label'] = program_label
    _save(COACHES_PATH, coaches)
    if push:
        _push_coaches()


def delete_coach(username):
    coaches = list_coaches()
    if username in coaches:
        del coaches[username]
        _save(COACHES_PATH, coaches)
        _push_coaches()


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


# --- Delete / rename (coach-only, from the dashboard) -------------------------

REPORT_SUFFIXES = ('_pitching.html', '_hitting.html', '_trackman_mini.html')


def _report_files(slug):
    d = os.path.join(DATA_DIR, 'reports')
    return [(s, os.path.join(d, slug + s)) for s in REPORT_SUFFIXES if os.path.exists(os.path.join(d, slug + s))]


def delete_player(slug):
    """Removes the player's record, bio override and report files (locally and, when
    GitHub sync is configured, in the repo). Returns False if the slug doesn't exist."""
    players = _load(PLAYERS_PATH, {})
    if slug not in players:
        return False
    del players[slug]
    _save(PLAYERS_PATH, players)
    ov = _load(OVERRIDES_PATH, {})
    if slug in ov:
        del ov[slug]
        _save(OVERRIDES_PATH, ov)
    for suffix, path in _report_files(slug):
        os.remove(path)
        github_sync.delete_file(f'data/reports/{slug}{suffix}')
    import outings, headshots
    outings.delete(slug)
    headshots.delete(slug)
    sync_to_github()
    return True


def rename_player(slug, new_name):
    """Fixes a misspelled name: re-keys the record under the new slug, renames the report
    files and swaps the old name for the new one inside them. Returns (new_slug, error)."""
    new_name = ' '.join(new_name.split())
    players = _load(PLAYERS_PATH, {})
    if slug not in players:
        return None, 'Player not found.'
    new_slug = slugify(new_name)
    if not new_slug:
        return None, 'Enter a name.'
    if new_slug != slug and new_slug in players:
        return None, f'A player named "{players[new_slug]["name"]}" already exists.'
    old_name = players[slug]['name']
    entry = players.pop(slug)
    entry['name'] = new_name
    players[new_slug] = entry
    _save(PLAYERS_PATH, players)
    ov = _load(OVERRIDES_PATH, {})
    if slug in ov and new_slug != slug:
        ov[new_slug] = ov.pop(slug)
        _save(OVERRIDES_PATH, ov)
    for suffix, path in _report_files(slug):
        with open(path, encoding='utf-8') as f:
            html = f.read()
        html = html.replace(old_name, new_name).replace(old_name.upper(), new_name.upper())
        new_path = os.path.join(DATA_DIR, 'reports', new_slug + suffix)
        with open(new_path, 'w', encoding='utf-8') as f:
            f.write(html)
        if new_slug != slug:
            os.remove(path)
            github_sync.delete_file(f'data/reports/{slug}{suffix}')
        github_sync.put_file(f'data/reports/{new_slug}{suffix}', html.encode('utf-8'))
    if new_slug != slug:
        import outings, headshots
        outings.move(slug, new_slug)
        headshots.move(slug, new_slug)
    sync_to_github()
    return new_slug, None


def update_profile(slug, name=None, school=None, grad_year=None, position=None, height_in=None, weight_lbs=None):
    """Edit Profile: overwrites the bio fields (blank clears height/weight/year), renames if the name changed.
    Returns (slug, error)."""
    players = _load(PLAYERS_PATH, {})
    if slug not in players:
        return None, 'Player not found.'
    e = players[slug]
    e['school'] = school or None
    e['grad_year'] = grad_year
    for k, v in (('height_in', height_in), ('weight_lbs', weight_lbs)):
        if v:
            e[k] = v
        else:
            e.pop(k, None)
    ov = _load(OVERRIDES_PATH, {})
    if slug in ov:                      # an override would otherwise refill a field the coach just cleared
        for k in ('height_in', 'weight_lbs'):
            ov[slug].pop(k, None)
        _save(OVERRIDES_PATH, ov)
    if position:
        e.setdefault('roles', {}).setdefault('pitch', {})['position'] = position
    _save(PLAYERS_PATH, players)
    new_slug = slug
    if name and ' '.join(name.split()) != e['name']:
        new_slug, err = rename_player(slug, name)
        if err:
            return slug, err
    else:
        sync_to_github()
    return new_slug, None


def set_stat_ids(slug, ids):
    """Saves which stats a player's overview shows (ordered list of stat ids). Empty list resets to the default."""
    players = _load(PLAYERS_PATH, {})
    if slug not in players:
        return False
    if ids:
        players[slug]['stat_ids'] = list(ids)
    else:
        players[slug].pop('stat_ids', None)
    _save(PLAYERS_PATH, players)
    sync_to_github()
    return True
