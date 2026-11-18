"""Content and structure for the public website (/welcome). Everything a visitor reads lives here or in templates/site_*.html, so wording,
prices and the name can be changed without touching the app. Branding: BRAND and TAGLINE here, logo files in static/site/brand/, colors at the top of templates/site_base.html.

Visibility: only admins can open the site until it is switched on for everyone with the environment variable SHEPSAVANT_SITE_PUBLIC=on.
Nothing else in the app changes when it is on or off, except that a signed-out visitor to the home address lands on the site instead of the login."""
import os

import plans

BRAND = 'Dugout Tracer'
TAGLINE = 'Every pitch. Every game. Everywhere.'
TRIAL_DAYS = 7

# Monthly or yearly prices shown on the plan cards. None shows "Pricing coming soon". Example: {'price': '$49', 'per': 'per month'}
PRICES = {
    'free':    None,
    'team':    None,
    'program': None,
}

TAGLINES = {
    'free':    'For one coach getting started with a handful of arms.',
    'team':    'For a coaching staff developing pitchers and hitters in one place.',
    'program': 'For a whole program: development, game recaps, scouting and the full staff.',
}
LABELS = {'free': 'Starter', 'team': 'Team', 'program': 'Program'}


def is_public():
    return (os.environ.get('SHEPSAVANT_SITE_PUBLIC') or '').lower() in ('on', '1', 'true', 'yes')


# The two jobs the product does for a staff, shown side by side near the top of the home page.
PILLARS = [
    ('Player development', 'See who is getting better, and why.', [
        'Live profiles for every pitcher and hitter that update with each session',
        'Biggest gains, week-by-week trends and personal bests, so progress is easy to show a player',
        'Pitch grades, swing decisions and hot zones that point to the next thing to work on',
    ]),
    ('Data management', 'Every pitch filed, found and shared in one place.', [
        'Upload the CSV your tracking system already makes; players are matched for you',
        'Rosters, schedules and seasons kept in order, with nothing deleted and every season one click away',
        'One login per coach, with you deciding who can upload, edit or see what',
    ]),
]

BENEFITS = [
    ('Hours back every week', 'Upload a session once. Every pitcher and hitter in the file gets an up-to-date profile, with no spreadsheets and no copy-paste.'),
    ('Progress you can show a player', 'Trends, biggest gains and personal bests turn a pile of numbers into a conversation about what is improving.'),
    ('A season that runs itself', 'Team Home follows the calendar: development in the fall, results and bullpen availability once the games start.'),
    ('Your whole staff on the same page', 'Assistants get their own logins and see the same numbers. You decide who can upload or change things.'),
]

STEPS = [
    ('Upload your session', 'Drop in the CSV from Trackman or Full Swing. Pitchers and hitters are matched to your roster, and opponents are kept apart.'),
    ('Review in a minute', 'Anything new or unusual is flagged, from a first-time player to a pitch that looks mislabeled. Fix it once and it stays fixed.'),
    ('Coach with it', 'Open profiles, Team Home, game recaps and scouting pages, and send a clean report to any player.'),
]

# The two halves of the year, shown as a pair on the home page.
SEASONS = [
    ('Fall', 'Development', 'From July through early January, Team Home asks one question: are players getting better? Biggest gains, process stats week by week, arsenal changes and a ready-for-spring checklist.', 'team_fall.jpg'),
    ('Spring', 'Game mode', 'From January 10, it switches to winning: record and season line, the latest game, who is hot and cold, and which arms are rested and available. Look back at the fall any time.', 'team_home.jpg'),
]

# slug, title, one-line pitch, bullets, screenshot file (None = placeholder frame), plan note
FEATURES = [
    {'slug': 'home', 'title': 'Team Home', 'pitch': 'The first screen your staff opens, and it changes with the season.',
     'bullets': ['Fall: biggest gains, process trends, a development board and a ready-for-spring checklist',
                 'Spring: record, season line, latest game, hot and cold hitters and pitchers, bullpen availability',
                 'Team goals with a pace line, so you know if you are on track before the deadline',
                 'Needs Attention lists what is holding your numbers back, like untagged games or missing heights'], 'img': 'team_home.jpg', 'plan': 'All plans'},
    {'slug': 'pitching', 'title': 'Pitcher profiles', 'pitch': 'A live profile for every arm, built from every outing.',
     'bullets': ['Pitch movement, location heat maps against lefties and righties, and velocity trends by pitch',
                 'Pitch grades for stuff and location, so you can see which pitch to lean on and which to fix',
                 'Arm angle, release and extension, plus personal bests flagged the day they happen',
                 'Every outing in order, with a one-page report you can send'], 'img': 'pitcher.jpg', 'plan': 'All plans'},
    {'slug': 'hitting', 'title': 'Hitter profiles and swing decisions', 'pitch': 'See how a hitter decides, not just how he hits.',
     'bullets': ['A swing-decision rating built from chase discipline, hittable pitches and damage on contact',
                 'Hot and cold zones from his own results, which the swing-decision rating takes into account',
                 'Exit velocity, hard-hit and barrel rates, launch angle, and expected average and slugging',
                 'Spray chart and pitch map, plus a team-wide swing-decision chart from the catcher\'s view'], 'img': 'hitter.jpg', 'plan': 'Team and Program'},
    {'slug': 'group', 'title': 'Pitchers and Hitters pages', 'pitch': 'The whole staff or lineup at a glance, three ways.',
     'bullets': ['Overview: key metrics with trends, standout outings, leaderboards and a chart of the group',
                 'Stat Sheet: every player and every stat, sortable, with the columns you choose',
                 'Player Cards: a card for each player, ready to tap into a full profile'], 'img': 'group.jpg', 'plan': 'All plans'},
    {'slug': 'games', 'title': 'Schedule and game recaps', 'pitch': 'Every game on the calendar, and a full recap once it is played.',
     'bullets': ['Upload your schedule as a PDF from your athletics site and every game fills in',
                 'Game Recap with line score, top performers on both sides and the key plays',
                 'A scorecard built from the pitch data, with pitch counts, substitutions and runners',
                 'An umpire recap for your staff that grades every called ball and strike'], 'img': 'recap.jpg', 'plan': 'Team and Program'},
    {'slug': 'scouting', 'title': 'Opponent scouting', 'pitch': 'A scouting page for every team you face.',
     'bullets': ['A dashboard per opponent, with their pitchers and hitters side by side',
                 'Built from the games and scrimmages you already tracked, so there is nothing extra to enter',
                 'Upload their roster PDF to fill in class years and handedness',
                 'A printable scouting book and private notes that carry into the next series'], 'img': 'scouting.jpg', 'plan': 'Program'},
    {'slug': 'data', 'title': 'Your data, organized', 'pitch': 'The data management a staff never has time for, done for you.',
     'bullets': ['Trackman and Full Swing CSV files, matched to the right player automatically',
                 'Roster import from a PDF, Excel or CSV, with height, weight, class year and handedness',
                 'Seasons archive themselves; last fall and every season before it stay one click away',
                 'An upload log of who added what, and pitch retagging when a pitch type is wrong'], 'img': 'schedule.jpg', 'plan': 'All plans'},
    {'slug': 'reports', 'title': 'Outing reports', 'pitch': 'A one-page report for every session, ready to send.',
     'bullets': ['Outing summary with pitches, strike %, whiff % and exit velocity', 'Pitch tracking table and a full pitch log',
                 'Download a single file to text or email, or print to PDF', 'Each copy is marked with who it was prepared for'], 'img': 'report.jpg', 'plan': 'Download is on Team and Program'},
    {'slug': 'staff', 'title': 'Staff and player access', 'pitch': 'Give the right people the right access.',
     'bullets': ['Assistant coaches with their own logins, and you control uploading', 'Players can see only their own profile and reports (in beta)',
                 'Your school colors and logo on every page', 'Your data is private to your program'], 'img': None, 'plan': 'Assistants: 1 on Team, up to 5 on Program'},
]

FAQ = [
    ('What data do I need?', 'A CSV export from your tracking system. Trackman and Full Swing files work today. Rosters can come from a PDF printed from your athletics site, or an Excel or CSV file.'),
    ('Is this for development or for games?', 'Both. Fall and winter are built around player development; from January 10 the home screen switches to game mode. Your data from every session feeds both.'),
    ('Who can see my players?', 'Only the coaches you add, and the site administrator. Players can be given a login that shows only their own page.'),
    ('What happens to last season?', 'Nothing is deleted. Each new season starts fresh on the team pages, and every earlier season stays one pick away. Player profiles keep every season together.'),
    ('What happens after the 7-day trial?', 'The trial gives you everything for 7 days. When it ends, your account pauses and your data stays put. Pick a plan to keep going.'),
    ('Do I need to install anything?', 'No. It works in any browser, on a phone or a computer.'),
]


def _limit_rows():
    """The plan comparison table, generated from the real plan limits so it can never drift from what the app enforces."""
    P = plans.PLANS

    def yes(v):
        return 'Included' if v else 'Not included'

    def num(v, unit):
        return 'Unlimited' if v is None else f'Up to {v} {unit}'
    keys = ('free', 'team', 'program')
    rows = [
        ('Players', [num(P[k]['max_players'], 'players') for k in keys]),
        ('Assistant coaches', ['None' if not P[k]['max_assistants'] else f"Up to {P[k]['max_assistants']}" for k in keys]),
        ('Outings in each profile', [f"Last {P[k]['history']}" for k in keys]),
        ('Download and print reports', [yes(P[k]['download']) for k in keys]),
        ('Pick your own stats', [yes(P[k]['custom_stats']) for k in keys]),
        ('Hitter profiles and team hitting', [yes(P[k]['hitting']) for k in keys]),
        ('Schedule and game recaps', [yes(P[k]['hitting']) for k in keys]),
        ('Team roster upload', [yes(P[k]['roster_upload']) for k in keys]),
        ('Opponent scouting', [yes(P[k]['scouting']) for k in keys]),
    ]
    return rows


def plan_cards():
    P = plans.PLANS
    out = []
    for k in ('free', 'team', 'program'):
        pr = PRICES.get(k)
        out.append({'key': k, 'name': LABELS[k], 'tagline': TAGLINES[k], 'price': (pr or {}).get('price'), 'per': (pr or {}).get('per', ''),
                    'featured': k == 'team'})
    return out


def comparison():
    return {'head': [LABELS[k] for k in ('free', 'team', 'program')], 'rows': _limit_rows()}


def plan_bullets():
    """Short bullet list per plan, taken from the real limits."""
    P = plans.PLANS
    out = {}
    for k in ('free', 'team', 'program'):
        p = P[k]
        b = [('Unlimited players' if p['max_players'] is None else f"Up to {p['max_players']} players"), f"Last {p['history']} outings in every profile"]
        b.append('Assistant coaches: ' + ('none' if not p['max_assistants'] else f"up to {p['max_assistants']}"))
        if p['download']:
            b.append('Download and print reports')
        if p['custom_stats']:
            b.append('Pick your own stats')
        if p['hitting']:
            b.append('Hitter profiles and swing decisions')
            b.append('Schedule and game recaps')
        if p['roster_upload']:
            b.append('Team roster upload')
        if p['scouting']:
            b.append('Opponent scouting and scouting books')
        out[k] = b
    return out


def context(page=''):
    import datetime
    return dict(brand=BRAND, trial_days=TRIAL_DAYS, pillars=PILLARS, seasons=SEASONS, benefits=BENEFITS, steps=STEPS, features=FEATURES, faq=FAQ, cards=plan_cards(), bullets=plan_bullets(),
                cmp=comparison(), year=datetime.date.today().year, page=page, public=is_public(), tagline=TAGLINE)
