# ⚽ World Cup 2026 Pool

A dead-simple bracket pool for your friend group. Everyone picks **one winner per group** (12 groups, 12 picks). Scores sync automatically from a free open-source feed every 5 minutes, and a live leaderboard tracks who's winning.

No accounts, no passwords — players are identified by name and remembered in your browser. **The app URL is the invite link** — share it and friends just open it.

## Run locally

```bash
pip install flask requests
python app.py
```

Then open <http://localhost:5000>. The SQLite database (`pool.db`) is created automatically on first run, and scores sync on startup + every 5 minutes.

(Recommended: use a virtual environment — `python3 -m venv .venv && source .venv/bin/activate` before `pip install`.)

## Deploy (free)

**Railway** — push this project to a GitHub repo, go to [railway.app](https://railway.app), connect GitHub, and deploy. Railway auto-detects Python, installs `requirements.txt`, and runs `python app.py`. It sets `PORT` automatically. Generate a public domain under Settings → Networking — that URL is your invite link.

**Render** — same idea at [render.com](https://render.com); the included `render.yaml` configures the build and start commands.

> Note: SQLite lives on the instance's local disk. On free tiers it may reset on redeploy — add a persistent volume/disk mounted next to `app.py` if you want picks to survive restarts.

## Tabs

- **Dashboard** — games today + next 2 days (grouped by date, with live scores) and live group standings (top 2 highlighted as advancing).
- **My Picks** — tap a team to crown your group winner, progress bar, save. Invite link with copy button.
- **Leaderboard** — ranked by correct group winners; faded flags = that pick is currently 3rd/4th.
- **Results** — every group's 6 matches with auto-synced scores + a standings table, plus a "Sync now" button.

## How scoring works

- Standings use standard football points (W=3, D=1, L=0), tie-broken by goal difference, then goals for.
- Your score = number of groups where your pick is **currently top** of the table.
- A group only counts once at least one of its matches has been played.

## Notes

- Tournament runs **June 11 – July 19, 2026** — 48 teams, 12 groups of 4.
- All times shown are **Eastern (ET)**.
- Scores come from [openfootball/worldcup.json](https://github.com/openfootball/worldcup.json) — free, open-source, no API key. A few team spellings are mapped automatically (`Czech Republic→Czechia`, `Bosnia & Herzegovina→Bosnia & Herz.`, `Turkey→Türkiye`).
