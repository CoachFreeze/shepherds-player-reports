"""Finds a real, playable Baseball Savant video for "this pitcher's <pitch type> in <season>", on demand.

The old links pointed at Savant's search page, which often loaded empty. Instead the app now asks Savant's data feed for that pitcher's
pitches of that type, picks the best clip (a swinging strike, ideally a strikeout, else a called strike), looks up its play id, and sends
the coach straight to the video. Answers are remembered in data/pitch_clips_cache.json, so each combination is looked up once.
If Savant can't be reached the caller falls back to the search page link."""
import csv
import io
import json
import os
import threading

import requests

import store

CACHE_PATH = os.path.join(store.DATA_DIR, 'pitch_clips_cache.json')
UA = {'User-Agent': 'Mozilla/5.0 (ShepSavant clip finder)'}
CODES = {'ff', 'si', 'fc', 'sl', 'st', 'sv', 'cu', 'ch', 'fs'}
_lock = threading.Lock()
_mem = None


def _load():
    global _mem
    if _mem is None:
        try:
            with open(CACHE_PATH, encoding='utf-8') as f:
                _mem = json.load(f)
        except (OSError, ValueError):
            _mem = {}
    return _mem


def _remember(key, value):
    with _lock:
        m = _load()
        m[key] = value
        try:
            os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
            with open(CACHE_PATH, 'w', encoding='utf-8') as f:
                json.dump(m, f)
        except OSError:
            pass


def search_url(pid, code, year):
    return ('https://baseballsavant.mlb.com/statcast_search?hfPT=' + code.upper() + '%7C&hfGT=R%7C&hfSea=' + str(year) +
            '%7C&player_type=pitcher&pitchers_lookup%5B%5D=' + str(pid) + '&type=details&sort_col=pitch_number_thisgame&sort_order=desc')


def video_url(play_id):
    return 'https://baseballsavant.mlb.com/sporty-videos?playId=' + play_id


def _pick(rows):
    """Best clip first: a strikeout on a swinging strike, then any swinging strike, then a called strike, then anything."""
    def score(r):
        d, e = r.get('description', ''), r.get('events', '')
        s = 0
        if d in ('swinging_strike', 'swinging_strike_blocked'):
            s = 3
            if e == 'strikeout':
                s = 4
        elif d == 'called_strike':
            s = 2
        try:
            v = float(r.get('release_speed') or 0)
        except ValueError:
            v = 0
        return (s, v)
    return sorted(rows, key=score, reverse=True)[:6]


def find_play_id(pid, code, year):
    """The play id of a good clip, '' if none, or None when Savant couldn't be reached (so it is retried next time)."""
    if code not in CODES:
        return ''
    key = f'{pid}|{code}|{year}'
    hit = _load().get(key)
    if hit is not None:
        return hit
    try:
        r = requests.get('https://baseballsavant.mlb.com/statcast_search/csv', headers=UA, timeout=14,
                         params={'all': 'true', 'hfPT': code.upper() + '|', 'hfSea': f'{year}|', 'hfGT': 'R|', 'player_type': 'pitcher',
                                 'pitchers_lookup[]': str(pid), 'type': 'details'})
        r.raise_for_status()
        rows = list(csv.DictReader(io.StringIO(r.content.decode('utf-8-sig'))))
        if not rows:
            _remember(key, '')
            return ''
        games = {}
        for c in _pick(rows):
            gp = c.get('game_pk')
            if not gp:
                continue
            if gp not in games:
                g = requests.get(f'https://baseballsavant.mlb.com/gf?game_pk={gp}', headers=UA, timeout=14)
                g.raise_for_status()
                j = g.json()
                games[gp] = (j.get('team_home') or []) + (j.get('team_away') or [])
            for p in games[gp]:
                if str(p.get('ab_number')) == str(c.get('at_bat_number')) and str(p.get('pitch_number')) == str(c.get('pitch_number')) and p.get('play_id'):
                    _remember(key, p['play_id'])
                    return p['play_id']
        _remember(key, '')
        return ''
    except Exception as exc:
        print(f'WARNING: could not look up a clip for {key}: {exc}')
        return None


def resolve(pid, code, year):
    """URL to send the coach to: the video itself when found, otherwise the Savant search page."""
    pl = find_play_id(pid, code, year)
    return video_url(pl) if pl else search_url(pid, code, year)
