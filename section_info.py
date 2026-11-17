"""The little circled "i" next to each section title: what the section measures, how it is calculated and why a coach should care.

info('key') returns a button plus a hidden panel; the page script (templates/_info_ui.html) moves the panel under the title and toggles it.
Keep each entry to a sentence or two per line: these are read on a phone between innings.
"""
from markupsafe import Markup, escape

INFO = {
    # ---- pitcher profile
    'pitching_profile': (
        'The headline results of his pitches over the outings shown: strike %, whiff %, in-zone % and chase % by default (you can customize the tiles).',
        'Strike % is strikes divided by pitches. Whiff % is swings and misses divided by swings. In Zone % is pitches in the strike zone divided by pitches. Chase % is swings at pitches outside the zone divided by pitches outside the zone. Every tracked pitch counts.',
        'These are the fastest read on whether he is throwing strikes, missing bats and getting hitters to expand the zone.'),
    'pitch_movement': (
        'How each pitch moves: horizontal break against induced vertical break (the movement beyond what gravity alone would do), with one dot per pitch.',
        'Dots come from the tracked movement of each pitch, grouped and colored by pitch type. Large samples are thinned to a representative set of dots; the averages in the table use every pitch. The arm-angle badge is his release slope, estimated from his release height and side and his listed height. Measured against Baseball Savant\'s pose-tracked angles, this runs within about 6 degrees of it, and steep slots tend to read a few degrees low. Short samples are less reliable.',
        'Pitches with a distinct shape are harder to sit on. Overlapping clusters mean two pitches look alike to a hitter, and stray dots can point to a mis-tagged pitch.'),
    'pitch_grades': (
        'Two grades for every pitch he throws: Stuff+ for the pitch itself and Location+ for where he puts it. Both are in beta: still being tuned, so treat them as estimates.',
        'Stuff+ uses only the shape of the pitch: velocity, movement, how it plays off his fastball, and how the movement differs from what hitters expect out of his arm slot. It is measured against MLB pitches of the same type, so 100 is an average MLB pitch and most college pitches land below that. Breaking balls, changeups and splitters use weights fitted to MLB whiffs and run value; fastballs use weights set by hand, which tested better for them. Location+ values every pitch by where it ended up, how high, the count and the kind of pitch, using run values measured from MLB pitches, so a fastball up and a breaking ball down both get credit. Those values shift toward what the tracked pitches in ShepSavant show as more data comes in, and his average is compared with the other pitchers here. Pitches on the inside edge of the zone are worth the most; pitches just off the edge count for much less. Stuff+ needs 8 tracked pitches of a type; Location+ needs 150 located pitches (50 for one pitch type). Zone rate and walk rate sit beside it, so a good location grade with a lot of walks stands out. Run value per 100 appears once a pitch has 100 pitches thrown to hitters.',
        'Stuff+ tells you what a pitch could be, even from bullpens. Location+ tells you whether he commands it. A pitch with good stuff and poor location needs command work; the reverse needs a better shape. Both are estimates. In a test on 22 MLB pitchers, Stuff+ tracked strikeout rate closely and Location+ tracked walk rate; neither is a full measure of run prevention on its own.'),
    'pitch_effectiveness': (
        'How each of his pitch types performs, split by whether the batter is left- or right-handed.',
        'Every pitch of a type is counted for usage, strike, whiff and contact-quality results. Rows with fewer than 10 pitches are greyed out because the sample is too small to trust.',
        'It shows which pitches actually work against lefties versus righties, which is the basis for deciding what to throw and when.'),
    'pitch_location': (
        'Where each pitch type finishes in and around the strike zone, seen from the catcher\'s view, against left- and right-handed batters.',
        'Every pitch is placed by its location as it crossed the plate and shaded into a heat map by pitch type.',
        'It shows whether he commands the edges, lives in one spot, or leaves pitches in the middle, and how that changes by batter side.'),
    'exit_velo_location': (
        'How hard each of his pitches gets hit, and how often hitters swing and miss, in each of the nine pockets of the strike zone.',
        'Pitches in the zone are sorted into a 3 by 3 grid. Each pocket shows the average exit velocity of balls in play and the swing-and-miss rate (misses divided by swings), by pitch type. Switch batter side or pitch with the buttons.',
        'It turns "pitch to the corners" into specifics: which pockets cost him damage and which ones earn misses.'),
    'velo_trend': (
        'His average velocity for each pitch type from outing to outing.',
        'Each point is the average mph of that pitch type on that date, with an arrow noting the recent change.',
        'A dip can mean fatigue, a lingering issue or a change in approach, and a steady climb shows a build-up working.'),
    'spin_trend': (
        'His average spin rate (rpm) for each pitch type from outing to outing.',
        'Each point is the average spin rate of that pitch type on that date, with an arrow noting the recent change.',
        'Spin shapes movement. Falling spin can signal grip or fatigue problems, and rising spin often comes with sharper pitches.'),
    'arsenal_ideas': (
        'Pitches that could add the most to his arsenal, based on what similar MLB pitchers throw.',
        'Ranked by how common the pitch is among MLB pitchers with a similar fastball shape and arm slot, how differently it would move from his current arsenal, how well his spin suits it, and whether he is missing a breaking ball or offspeed pitch. Target shapes are the MLB averages for that group; the speed gap off his fastball is scaled to his own fastball, and the clips show the shape to copy, not the velocity. Video clips are real 2026 MLB pitches of this type from Baseball Savant, picked for the closest shape and a swing-and-miss or strikeout result.',
        'A new pitch with a different shape from his current ones is the quickest way to give hitters another look.'),
    'arsenal_comps': (
        'The MLB pitchers whose arsenals look most like his.',
        'Matched on pitch shape: induced vertical break and horizontal break, with spin counting less, against 2026 MLB pitch-arsenal data and weighted by how often each pitch is thrown. Velocity is not part of the match, so a comp can throw harder and still be the right model for the movement. HB: A = arm-side, G = glove-side, so lefties and righties compare directly. Built from all of his tracked pitches across the outings shown.',
        'A good comp is a model to study: how that pitcher sequences, locates and uses the same shapes.'),
    # ---- hitter profile
    'batted_ball': (
        'The quality of contact on every tracked ball he put in play: expected batting average (xBA), average and max exit velocity, EV90, hard-hit % and barrel %.',
        'Each ball in play with an exit velocity and launch angle counts. xBA is the batting average typically produced by a ball hit at that speed and angle. EV90 is the exit velocity of his 90th-percentile ball, a measure of his hard-hit ceiling. Hard-hit % is balls at 95 mph or more. Barrel % is the share of balls hit with the speed and angle that most often become extra-base hits.',
        'Contact quality is steadier than results over small samples, so it shows who is hitting the ball well before the box score catches up.'),
    'by_pitch_type': (
        'How he hits each type of pitch he has seen.',
        'His tracked balls in play are grouped by the pitch type that was thrown, then summarized with exit velocity, hard-hit %, barrel %, launch angle and ground ball, line drive and fly ball shares. Rows with fewer than 5 balls in play are greyed out.',
        'It shows which pitches he handles and which ones he does not, so a scouting plan or a lineup decision has something to hold on to.'),
    'ev_heatmap': (
        'The average exit velocity of the balls he put in play, by where the pitch was in and around the strike zone.',
        'The zone and the area up to a foot outside it are divided into small areas. Each shows the average exit velocity of his tracked balls in play from pitches there, from blue (soft) to red (hard).',
        'Red areas are where he does damage and blue areas are where he is beaten, which is a ready-made hitting plan and scouting report.'),
    'spray': (
        'Where his balls in play go: direction and distance for every tracked ball.',
        'Each dot is one ball in play, placed by its hit direction and distance, and colored by exit velocity.',
        'It shows pull, middle and opposite-field tendencies and where he hits the ball hard, which drives both his approach and defensive positioning against him.'),
    'hot_zones': (
        'Where in the zone he does damage and where he struggles, split into nine boxes from his point of view (up, middle, down by in, middle, away).',
        'Each box scores his swings by the chance of a hit off exit velocity and launch angle (a whiff counts zero). With only a few swings in a box he is assumed to be like his team there, and his own results take over as they add up. A box turns hot or cold once he has at least 3 swings there and does clearly better or worse than in his other boxes. A coach can set any box by hand (marked with a pencil), and that always wins.',
        'Swing decisions use these zones before two strikes: a take in a cold zone costs half, and attacking an edge pitch in a hot zone is a small plus. That rewards a hitter for sticking to his approach instead of swinging at everything to avoid a penalty.'),
    'swing_decisions': (
        'How well he decides which pitches to swing at and which to take.',
        'Every pitch is judged by its location (against his own strike zone, sized from his height when known) and the count: an early-count take of a middle pitch costs little, a two-strike take a lot. Swinging at hittable pitches and taking balls are good decisions, chasing or taking hittable strikes are bad ones, and pitches on the edge are borderline. Before two strikes his hot and cold zones count too: a take in a cold zone costs half, and attacking an edge pitch in a hot zone is a small plus. The Swing Decision Rating (SDR) blends chase discipline (40%), hittable pitches (20%) and damage on contact (40%), and scores them on a scale where 90+ is Elite, 82+ Above Average, 74+ Average, 66+ Below Average and anything lower Concerning.',
        'Good decisions lead to walks, hitter\'s counts and better contact, and they are one of the quickest things to coach.'),
    'pitch_map': (
        'Every pitch he saw, from the catcher\'s view, with what he did on each one.',
        'Each dot is a pitch placed by its location. Filled dots are swings and hollow dots are takes, colored good, bad or borderline by the same rules as the Swing Decision Rating. Hover or tap a dot for the count and the reason.',
        'It puts the rating on the field: you can see exactly where he chases and which strikes he lets by.'),
    'player_insights': (
        'Plain-language observations written from his data.',
        'The page checks his numbers against set thresholds (and needs a minimum sample) and writes a note when something stands out as a strength or a concern.',
        'It points a coach to the few things worth talking about first without reading every table.'),
    'swing_tracking': (
        'How his swing performs: bat speed, how squared up the contact is, and how much of the swing goes into the ball.',
        'Bat speed is logged on every swing, contact or not. Squared-up % compares the exit velocity of a ball in play to the most that swing could have produced. Smash factor is exit velocity divided by bat speed. EV left on the table is the gap between the exit velocity the swing could have produced and what the ball actually did.',
        'Bat speed shows his raw tool. The other numbers show how much of it he is actually converting into hard contact.'),
    # ---- catcher
    'c_receiving': (
        'How many extra strikes he gets his pitchers on borderline pitches.',
        'Looks at pitches the hitter took, near the edge of the zone. Each is compared with how often pitches that same distance from the edge are called strikes across the whole program. The difference, per 100 takes, is Extra strikes. Under 25 borderline takes it is only a rough picture.',
        'A strike on a borderline pitch changes the count and the at-bat, so catchers who win those calls are worth real runs to a staff.'),
    'c_pitch_calling': (
        'What gets thrown while he is catching, by count, next to the program average.',
        'Pitches are grouped into fastballs (including cutters and sinkers), breaking balls and offspeed pitches, and shown as a share in each count group. The grey numbers are the program-wide mix.',
        'It shows his tendencies: whether he is predictable in certain counts or leans on one family. The pitcher can shake off or call his own game, so it reflects the whole battery.'),
    'c_results': (
        'The results of the pitches thrown while he was catching.',
        'Counted across every pitch to him: strike %, zone %, first-pitch strike %, whiff %, chase %, CSW % (called strikes plus whiffs), hard-hit % allowed and average exit velocity allowed.',
        'It is the overall picture of how his games went. Pitcher quality has a large effect, so read it next to the by-pitcher table.'),
    'c_by_pitcher': (
        'How each pitcher did with him behind the plate.',
        'His pitches are split by the pitcher who threw them and summarized as strike %, whiff % and CSW %.',
        'It shows which pairings work best and where a catcher and a pitcher might not be on the same page.'),
}


def info(key):
    t = INFO.get(key)
    if not t:
        return Markup('')
    labs = ('What it measures', 'How it is calculated', 'Why it matters')
    body = ''.join(f'<span class="ip"><b>{l}</b>{escape(x)}</span>' for l, x in zip(labs, t))
    return Markup(f'<button type="button" class="ib" aria-label="About this section" aria-expanded="false">i</button><span class="info-hold" hidden><span class="info-src">{body}</span></span>')
