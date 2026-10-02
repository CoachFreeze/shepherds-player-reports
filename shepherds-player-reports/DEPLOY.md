# Deploying the Shepherds Player Reports app (Render, free tier)

## 1. Push this folder to a GitHub repo

Render deploys from a git repo, so this `app/` folder needs to be its own
repo (or a repo with this folder at the root).

```
cd webapp/app
git init
git add .
git commit -m "Initial deploy"
git branch -M main
git remote add origin <your empty GitHub repo URL>
git push -u origin main
```

## 2. Create the Render service

Easiest path: in the Render dashboard, **New → Blueprint**, point it at your
repo, and it will read `render.yaml` in this folder and set everything up
(build command, start command, a generated `SECRET_KEY`) automatically.

If you'd rather click through it manually instead: **New → Web Service**,
point at the repo, and set:
- **Build command:** `pip install -r requirements.txt`
- **Start command:** `gunicorn app:app --workers 2 --timeout 120`
- **Plan:** Free
- **Environment variable:** `SECRET_KEY` = any long random string (Render
  can generate one for you)

Either way, the free plan means the app may take 30-60 seconds to "wake up"
the first time it's opened after a period of no traffic — normal for a free
host, not a bug.

## 3. Add coaches

The one coach account already set up (`CoachFreeze`) is in `data/coaches.json`,
which is committed to the repo, so it comes with the deploy automatically.

To add another coach later, run this on your own computer and push the
updated file:

```
python3 manage.py add-coach <username> "<Display Name>" <password>
git add data/coaches.json
git commit -m "Add coach account"
git push
```

## 4. Data persistence — the one real tradeoff of a free host

This app stores players, comps, and uploaded workbooks as plain files under
`data/` rather than in a database (intentional — see the project scope doc
for why). On Render's **free** tier, the filesystem is **not persistent
across redeploys**: every time you push new code, the service rebuilds from
a clean copy of the repo, which wipes `data/players.json`, uploaded `.xlsx`
files, and generated reports (anything listed in `.gitignore`).

What this means in practice:
- **Day-to-day use is unaffected.** The app doesn't redeploy itself — data
  added by coaches (uploads, overrides) stays put through spin-downs,
  restarts, and normal traffic. It's only wiped when *you* push a code
  change.
- **Before you push a change** (a bug fix, a new feature), export or note
  down anything in `data/players.json` you'd be upset to lose, or re-run
  the intake form for each player again afterward.
- **If this becomes a real pain point**, Render's cheapest paid tier
  (currently ~$7/mo, "Starter") supports attaching a persistent disk, which
  removes this limitation entirely with no code changes — just mount a disk
  at `data/` in the Render dashboard. Fly.io's free tier (the scope doc's
  backup option) behaves similarly if Render doesn't work out.

## 5. Custom domain / Squarespace link

Once deployed you'll have a URL like `https://shepherds-player-reports.onrender.com`.
Link to it from the Squarespace site (a button or link on the Training
Program page pointing at that URL) — this app runs alongside the Squarespace
site, not inside it, per the original scope.
