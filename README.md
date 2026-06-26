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

## How it works

This is a **knockout bracket pool**. There's no group-stage picking — players predict the winner of every knockout match, round by round, and earn more points the deeper the round.

The entire bracket (matchups, kickoff times, scores, winners) is pulled **automatically from the openfootball feed** every 5 minutes. Round-of-32 teams appear once the group stage decides them; later rounds fill in as winners advance.

## Tabs

- **Dashboard** — the full match schedule (every upcoming game in date order, group + knockout, with live scores), plus your personal bracket score and your decided picks at the top.
- **Bracket** — tap a team to pick the winner of each knockout match. Picks save instantly and **lock the moment that match kicks off**. Decided matches show the result and whether you got it right.
- **Leaderboard** — ranked by total points.

## Scoring

| Correct winner pick | Points |
| --- | --- |
| Round of 32 | 1 |
| Round of 16 | 2 |
| Quarterfinals | 3 |
| Semifinals | 4 |
| Final | 5 |

A pick only scores once that match has a winner. Picks lock at kickoff, so you can't change them after a game starts.

## Notes

- Tournament runs **June 11 – July 19, 2026** — 48 teams, 12 groups of 4.
- All times shown are **Eastern (ET)**.
- Scores come from [openfootball/worldcup.json](https://github.com/openfootball/worldcup.json) — free, open-source, no API key. A few team spellings are mapped automatically (`Czech Republic→Czechia`, `Bosnia & Herzegovina→Bosnia & Herz.`, `Turkey→Türkiye`).
