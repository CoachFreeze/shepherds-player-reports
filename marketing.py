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
    'team':    'For a coaching staff that wants hitting and pitching in one place.',
    'program': 'For a whole program: every tool, scouting and the full staff.',
}
LABELS = {'free': 'Starter', 'team': 'Team', 'program': 'Program'}


def is_public():
    return (os.environ.get('SHEPSAVANT_SITE_PUBLIC') or '').lower() in ('on', '1', 'true', 'yes')


BENEFITS = [
    ('Hours back every week', 'Upload a session once. Every pitcher and hitter in the file gets an up-to-date profile and report with no spreadsheets and no copy-paste.'),
    ('Reports players actually read', 'Clean, easy-to-read pages in a familiar MLB-style look. Send a single file by text or email, or print it.'),
    ('Know the opponent before first pitch', 'Scouting pages for every opponent, built from the games and scrimmages you tracked: what their hitters do and what their pitchers throw.'),
    ('Your whole staff on the same page', 'Add assistant coaches with their own logins. Everyone sees the same numbers, and you decide who can upload or change things.'),
]

STEPS = [
    ('Upload your session', 'Drop in the CSV from your tracking system. Players are found automatically, and your team is told apart from opponents.'),
    ('Review in a minute', 'Fill in class year, height and weight once. Anything that looks off is flagged for you.'),
    ('Coach with it', 'Open live profiles, team dashboards and scouting pages, and send reports to your players.'),
]

# slug, title, one-line pitch, bullets, screenshot file (None = placeholder frame), plan note
FEATURES = [
    {'slug': 'pitching', 'title': 'Pitcher profiles', 'pitch': 'A live profile for every arm, built from their most recent outings.',
     'bullets': ['Pitch movement profile and pitch location heat maps against lefties and righties', 'Velocity trend by pitch type across recent outings',
                 'Strike %, whiff %, chase % and 80+ more stats you can pick from', 'Arm angle, release and delivery numbers'], 'img': 'pitcher.jpg', 'plan': 'All plans'},
    {'slug': 'reports', 'title': 'Outing reports', 'pitch': 'A one-page report for every session, ready to send.',
     'bullets': ['Outing summary with pitches, strike %, whiff % and exit velocity', 'Pitch tracking table and a full pitch log', 'Download a single file to text or email, or print to PDF',
                 'Each copy is marked with who it was prepared for'], 'img': 'report.jpg', 'plan': 'Download is on Team and Program'},
    {'slug': 'hitting', 'title': 'Hitter profiles', 'pitch': 'See how a hitter decides, not just how he hits.',
     'bullets': ['A swing-decision score built from chase discipline, hittable pitches and damage', 'Spray chart, exit velocity heat map and pitch map',
                 'Exit velocity, hard-hit %, barrel %, launch angle and expected batting average', 'Bat speed and squared-up % when your system tracks the swing'], 'img': 'hitter.jpg', 'plan': 'Team and Program'},
    {'slug': 'team', 'title': 'Team dashboard', 'pitch': 'The whole staff, one screen.',
     'bullets': ['Team stats and leaderboards for pitching and hitting', 'Pick the stats that matter to you', 'Search and sort every pitcher and hitter', 'Your school colors and logo throughout'], 'img': 'team.jpg', 'plan': 'All plans'},
    {'slug': 'scouting', 'title': 'Opponent scouting', 'pitch': 'A scouting page for every team you face.',
     'bullets': ['A dashboard per opponent, with their pitchers and hitters', 'Built from the games and scrimmages you already tracked', 'Notes you can add and keep for the next series'], 'img': None, 'plan': 'Program'},
    {'slug': 'games', 'title': 'Game reports', 'pitch': 'A scorebook for every game, made from the pitch data.',
     'bullets': ['Box by box results, pitch counts, pinch hitters and pitching changes', 'Runners and runs worked out for you', 'Add your own notes to any game'], 'img': None, 'plan': 'Program'},
    {'slug': 'staff', 'title': 'Staff and player access', 'pitch': 'Give the right people the right access.',
     'bullets': ['Assistant coaches with their own logins, and you control uploading', 'Players can see only their own profile and reports (in beta)',
                 'Activity is logged and every report is marked with who it was prepared for', 'Your data is private to your program'], 'img': None, 'plan': 'Assistants: 1 on Team, up to 5 on Program'},
]

FAQ = [
    ('What data do I need?', 'A CSV export from your tracking system. Trackman and Full Swing files work today.'),
    ('Who can see my players?', 'Only the coaches you add, and the site administrator. Players can be given a login that shows only their own page.'),
    ('What happens after the 7-day trial?', 'The trial gives you everything for 7 days. When it ends, your account pauses and your data stays put. Pick a plan to keep going.'),
    ('Do I need to install anything?', 'No. It works in any browser, on a phone or a computer.'),
    ('Can my assistants upload?', 'Yes, and you can turn that off for any assistant at any time.'),
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
            b.append('Hitter profiles and team hitting')
        if p['roster_upload']:
            b.append('Team roster upload')
        if p['scouting']:
            b.append('Opponent scouting and game reports')
        out[k] = b
    return out


def context(page=''):
    import datetime
    return dict(brand=BRAND, trial_days=TRIAL_DAYS, benefits=BENEFITS, steps=STEPS, features=FEATURES, faq=FAQ, cards=plan_cards(), bullets=plan_bullets(),
                cmp=comparison(), year=datetime.date.today().year, page=page, public=is_public(), tagline=TAGLINE)
