from flask import Flask, request, jsonify, send_from_directory
import sqlite3, requests, threading, time, os
from datetime import datetime, timedelta, timezone

app = Flask(__name__, static_folder='static')
# DB path is configurable so it can live on a persistent volume in production.
# Locally it defaults to ./pool.db; on Railway set DB_PATH=/data/pool.db (mounted volume).
DB = os.environ.get("DB_PATH", "pool.db")

OFB_URL = "https://raw.githubusercontent.com/openfootball/worldcup.json/master/2026/worldcup.json"

# ── DATABASE ──────────────────────────────────────────────────────────────────

def get_db():
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    return db

def init_db():
    parent = os.path.dirname(DB)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with get_db() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS players (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL
            );
            CREATE TABLE IF NOT EXISTS knockout_matches (
                match_key TEXT PRIMARY KEY,   -- the feed's match number, as text
                round TEXT NOT NULL,          -- 'R32','R16','QF','SF','F','3P'
                match_number INTEGER,
                home TEXT,
                away TEXT,
                home_score INTEGER,
                away_score INTEGER,
                winner TEXT,
                date TEXT,
                time_et TEXT,
                venue TEXT,
                kickoff INTEGER               -- epoch ms, for locking picks
            );
            CREATE TABLE IF NOT EXISTS knockout_picks (
                player_id INTEGER,
                match_key TEXT,
                team_name TEXT,
                PRIMARY KEY (player_id, match_key)
            );
        """)
        # Migration for DBs created before the kickoff column existed.
        try:
            db.execute("ALTER TABLE knockout_matches ADD COLUMN kickoff INTEGER")
        except sqlite3.OperationalError:
            pass

# ── STATIC DATA ─────────────────────────────────────────────────────────────

FLAGS = {
  "Mexico":"🇲🇽","South Africa":"🇿🇦","South Korea":"🇰🇷","Czechia":"🇨🇿",
  "Canada":"🇨🇦","Bosnia & Herz.":"🇧🇦","Qatar":"🇶🇦","Switzerland":"🇨🇭",
  "Brazil":"🇧🇷","Morocco":"🇲🇦","Haiti":"🇭🇹","Scotland":"🏴󠁧󠁢󠁳󠁣󠁴󠁿",
  "USA":"🇺🇸","Paraguay":"🇵🇾","Australia":"🇦🇺","Türkiye":"🇹🇷",
  "Germany":"🇩🇪","Curaçao":"🇨🇼","Ivory Coast":"🇨🇮","Ecuador":"🇪🇨",
  "Netherlands":"🇳🇱","Japan":"🇯🇵","Sweden":"🇸🇪","Tunisia":"🇹🇳",
  "Belgium":"🇧🇪","Egypt":"🇪🇬","Iran":"🇮🇷","New Zealand":"🇳🇿",
  "Spain":"🇪🇸","Cape Verde":"🇨🇻","Saudi Arabia":"🇸🇦","Uruguay":"🇺🇾",
  "France":"🇫🇷","Senegal":"🇸🇳","Iraq":"🇮🇶","Norway":"🇳🇴",
  "Argentina":"🇦🇷","Algeria":"🇩🇿","Austria":"🇦🇹","Jordan":"🇯🇴",
  "Portugal":"🇵🇹","DR Congo":"🇨🇩","Uzbekistan":"🇺🇿","Colombia":"🇨🇴",
  "England":"🏴󠁧󠁢󠁥󠁮󠁧󠁿","Croatia":"🇭🇷","Ghana":"🇬🇭","Panama":"🇵🇦",
}

# openfootball uses a few different spellings for some teams.
NAME_MAP = {
    "Czech Republic": "Czechia",
    "Bosnia & Herzegovina": "Bosnia & Herz.",
    "Turkey": "Türkiye",
}

# Feed round label -> our short code.
FEED_ROUND = {
    "Round of 32": "R32",
    "Round of 16": "R16",
    "Quarter-final": "QF",
    "Semi-final": "SF",
    "Match for third place": "3P",
    "Final": "F",
}
ROUND_LABELS = {"R32":"Round of 32","R16":"Round of 16","QF":"Quarterfinals",
                "SF":"Semifinals","F":"Final","3P":"Third Place"}
# Points per correct winner pick. Third place is shown but not scored/picked.
ROUND_POINTS = {"R32":1,"R16":2,"QF":3,"SF":4,"F":5}
# Rounds players actually pick, in bracket order.
PICK_ROUNDS = ["R32","R16","QF","SF","F"]

# ── TIME HELPERS ──────────────────────────────────────────────────────────────

ET = timezone(timedelta(hours=-4))  # EDT — the whole tournament runs in summer

def fmt_et(dt):
    h = dt.hour % 12 or 12
    ap = "am" if dt.hour < 12 else "pm"
    return f"{h}:{dt.minute:02d}{ap} ET"

def to_et(date_str, time_str):
    """Convert feed 'YYYY-MM-DD' + 'HH:MM UTC-X' to (et_label, epoch_ms, et_date)."""
    try:
        hm, off = time_str.split(" UTC")
        offset = int(off)
        H, M = map(int, hm.split(":"))
        Y, Mo, D = map(int, date_str.split("-"))
        src = datetime(Y, Mo, D, H, M, tzinfo=timezone(timedelta(hours=offset)))
        et = src.astimezone(ET)
        return fmt_et(et), int(src.timestamp() * 1000), et.date().isoformat()
    except Exception:
        return time_str, None, date_str

def now_ms():
    return int(datetime.now(timezone.utc).timestamp() * 1000)

def et_today():
    return datetime.now(ET).date().isoformat()

def flag(team):
    return FLAGS.get(team, "")

KNOCKOUT_ROUND_LABELS = set(FEED_ROUND.keys())

# ── FEED SYNC ─────────────────────────────────────────────────────────────────

# In-memory cache of the full normalized schedule (group + knockout).
FEED_MATCHES = []
LAST_SYNC = None

def _winner_of(team1, team2, ft):
    if not ft:
        return None
    if ft[0] > ft[1]:
        return team1
    if ft[1] > ft[0]:
        return team2
    return None  # tie on the feed's ft — undecided (penalties not modeled)

def normalize_feed(data):
    """Turn raw feed JSON into a list of normalized match dicts."""
    out = []
    for m in data.get("matches", []):
        t1 = NAME_MAP.get(m.get("team1"), m.get("team1"))
        t2 = NAME_MAP.get(m.get("team2"), m.get("team2"))
        ft = (m.get("score") or {}).get("ft")
        label, epoch, et_date = to_et(m.get("date", ""), m.get("time", ""))
        round_label = m.get("round", "")
        code = FEED_ROUND.get(round_label)  # None for group-stage matchdays
        out.append({
            "num": m.get("num"),
            "round_label": round_label,
            "round_code": code,
            "is_knockout": code is not None,
            "group": m.get("group"),
            "date": et_date,
            "time_et": label,
            "kickoff": epoch,
            "home": t1, "away": t2,
            "flag_home": flag(t1), "flag_away": flag(t2),
            "score": ({"h": ft[0], "a": ft[1]} if ft else None),
            "winner": _winner_of(t1, t2, ft),
            "venue": m.get("ground"),
        })
    return out

def persist_knockout(matches):
    """Upsert knockout matches into the DB so picks/scoring survive feed outages."""
    with get_db() as db:
        for m in matches:
            if not m["is_knockout"] or m["num"] is None:
                continue
            db.execute("""
                INSERT INTO knockout_matches
                  (match_key, round, match_number, home, away, home_score, away_score, winner, date, time_et, venue, kickoff)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(match_key) DO UPDATE SET
                  round=excluded.round, match_number=excluded.match_number,
                  home=excluded.home, away=excluded.away,
                  home_score=excluded.home_score, away_score=excluded.away_score,
                  winner=excluded.winner, date=excluded.date,
                  time_et=excluded.time_et, venue=excluded.venue, kickoff=excluded.kickoff
            """, (
                str(m["num"]), m["round_code"], m["num"], m["home"], m["away"],
                (m["score"]["h"] if m["score"] else None),
                (m["score"]["a"] if m["score"] else None),
                m["winner"], m["date"], m["time_et"], m["venue"], m["kickoff"],
            ))

def sync_scores():
    global FEED_MATCHES, LAST_SYNC
    try:
        res = requests.get(f"{OFB_URL}?t={int(time.time())}", timeout=10)
        data = res.json()
        matches = normalize_feed(data)
        FEED_MATCHES = matches
        persist_knockout(matches)
        LAST_SYNC = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        ko = sum(1 for m in matches if m["is_knockout"])
        done = sum(1 for m in matches if m["score"])
        print(f"Synced: {len(matches)} matches ({ko} knockout, {done} finished)")
        return done
    except Exception as e:
        print(f"Sync error: {e}")
        return None

def sync_loop():
    while True:
        time.sleep(300)
        sync_scores()

# ── KNOCKOUT HELPERS ──────────────────────────────────────────────────────────

def knockout_rows():
    with get_db() as db:
        return db.execute("SELECT * FROM knockout_matches").fetchall()

def is_locked(row):
    """A match locks once it kicks off or a winner is known."""
    if row["winner"]:
        return True
    ko = row["kickoff"]
    return ko is not None and now_ms() >= ko

def player_score(picks_for_match_key, rows):
    """picks_for_match_key: {match_key: team}. Returns (total, correct, by_round)."""
    total = correct = 0
    by_round = {r: 0 for r in PICK_ROUNDS}
    for row in rows:
        if row["round"] not in ROUND_POINTS:
            continue
        pick = picks_for_match_key.get(row["match_key"])
        if pick and row["winner"] and pick == row["winner"]:
            pts = ROUND_POINTS[row["round"]]
            total += pts
            correct += 1
            by_round[row["round"]] += pts
    return total, correct, by_round

# ── API ROUTES ────────────────────────────────────────────────────────────────

@app.route("/api/config")
def get_config():
    return jsonify({
        "flags": FLAGS,
        "round_labels": ROUND_LABELS,
        "round_points": ROUND_POINTS,
        "pick_rounds": PICK_ROUNDS,
        "mode": "knockout",
    })

@app.route("/api/join", methods=["POST"])
def join():
    name = (request.json.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Name required"}), 400
    with get_db() as db:
        try:
            cur = db.execute("INSERT INTO players (name) VALUES (?)", (name,))
            return jsonify({"id": cur.lastrowid, "name": name})
        except sqlite3.IntegrityError:
            row = db.execute("SELECT id,name FROM players WHERE name=?", (name,)).fetchone()
            return jsonify({"id": row["id"], "name": row["name"]})

@app.route("/api/players")
def get_players():
    with get_db() as db:
        players = db.execute("SELECT id,name FROM players ORDER BY id").fetchall()
    return jsonify([{"id": p["id"], "name": p["name"]} for p in players])

@app.route("/api/schedule")
def get_schedule():
    """All remaining matches (today onward, ET) in date order, knockout + group."""
    scope = request.args.get("scope", "upcoming")
    today = et_today()
    now = now_ms()
    out = []
    for m in sorted(FEED_MATCHES, key=lambda x: (x["kickoff"] or 0)):
        if scope == "upcoming" and m["date"] and m["date"] < today and not m["score"]:
            # past & never played — skip stale rows; keep finished ones out too unless 'all'
            pass
        if scope == "upcoming" and m["date"] and m["date"] < today:
            continue
        live = (not m["score"] and m["kickoff"] is not None
                and now >= m["kickoff"] and now <= m["kickoff"] + 2 * 3600 * 1000)
        status = "done" if m["score"] else ("live" if live else "upcoming")
        out.append({
            "round": m["round_code"], "round_label": m["round_label"],
            "is_knockout": m["is_knockout"], "group": m["group"],
            "date": m["date"], "time_et": m["time_et"],
            "home": m["home"], "away": m["away"],
            "flag_home": m["flag_home"], "flag_away": m["flag_away"],
            "score": m["score"], "venue": m["venue"], "status": status,
        })
    return jsonify(out)

@app.route("/api/bracket")
def get_bracket():
    rows = knockout_rows()
    rounds = {r: [] for r in (PICK_ROUNDS + ["3P"])}
    for row in sorted(rows, key=lambda r: (r["match_number"] or 0)):
        rc = row["round"]
        if rc not in rounds:
            continue
        rounds[rc].append({
            "match_key": row["match_key"],
            "round": rc,
            "round_label": ROUND_LABELS.get(rc, rc),
            "points": ROUND_POINTS.get(rc, 0),
            "home": row["home"], "away": row["away"],
            "flag_home": flag(row["home"]), "flag_away": flag(row["away"]),
            "score": ({"h": row["home_score"], "a": row["away_score"]}
                      if row["home_score"] is not None else None),
            "winner": row["winner"],
            "date": row["date"], "time_et": row["time_et"], "venue": row["venue"],
            "locked": is_locked(row),
        })
    return jsonify({"rounds": rounds, "order": PICK_ROUNDS})

@app.route("/api/bracket/picks/<int:player_id>")
def get_bracket_picks(player_id):
    with get_db() as db:
        rows = db.execute("SELECT match_key,team_name FROM knockout_picks WHERE player_id=?",
                          (player_id,)).fetchall()
    return jsonify({r["match_key"]: r["team_name"] for r in rows})

@app.route("/api/bracket/pick", methods=["POST"])
def save_bracket_pick():
    data = request.json or {}
    player_id = data.get("player_id")
    match_key = str(data.get("match_key", ""))
    team = data.get("team_name")
    if not player_id or not match_key:
        return jsonify({"error": "player_id and match_key required"}), 400
    with get_db() as db:
        row = db.execute("SELECT * FROM knockout_matches WHERE match_key=?", (match_key,)).fetchone()
        if not row:
            return jsonify({"error": "Unknown match"}), 404
        if is_locked(row):
            return jsonify({"error": "This match is locked — it has kicked off.", "locked": True}), 403
        if team not in (row["home"], row["away"]):
            return jsonify({"error": "Pick must be one of the two teams in this match"}), 400
        db.execute("""INSERT INTO knockout_picks (player_id,match_key,team_name) VALUES (?,?,?)
                      ON CONFLICT(player_id,match_key) DO UPDATE SET team_name=excluded.team_name""",
                   (player_id, match_key, team))
    return jsonify({"ok": True})

@app.route("/api/leaderboard")
def get_leaderboard():
    rows = knockout_rows()
    with get_db() as db:
        players = db.execute("SELECT id,name FROM players").fetchall()
        all_picks = db.execute("SELECT player_id,match_key,team_name FROM knockout_picks").fetchall()
    picks_by_player = {}
    for p in all_picks:
        picks_by_player.setdefault(p["player_id"], {})[p["match_key"]] = p["team_name"]

    board = []
    for p in players:
        pk = picks_by_player.get(p["id"], {})
        total, correct, by_round = player_score(pk, rows)
        board.append({"id": p["id"], "name": p["name"],
                      "total_score": total, "correct": correct,
                      "by_round": by_round, "picks_made": len(pk)})
    board.sort(key=lambda x: (-x["total_score"], -x["correct"], x["name"].lower()))
    return jsonify(board)

@app.route("/api/me/<int:player_id>")
def get_me(player_id):
    with get_db() as db:
        p = db.execute("SELECT id,name FROM players WHERE id=?", (player_id,)).fetchone()
        if not p:
            return jsonify({"error": "Player not found"}), 404
        picks = {r["match_key"]: r["team_name"] for r in
                 db.execute("SELECT match_key,team_name FROM knockout_picks WHERE player_id=?",
                            (player_id,)).fetchall()}
    rows = knockout_rows()
    total, correct, by_round = player_score(picks, rows)
    # Per-match status for the personal dashboard.
    detail = []
    for row in sorted(rows, key=lambda r: (r["match_number"] or 0)):
        if row["round"] not in ROUND_POINTS:
            continue
        pick = picks.get(row["match_key"])
        if not pick:
            status = "none"
        elif not row["winner"]:
            status = "locked" if is_locked(row) else "pending"
        elif pick == row["winner"]:
            status = "correct"
        else:
            status = "wrong"
        detail.append({
            "match_key": row["match_key"], "round": row["round"],
            "round_label": ROUND_LABELS.get(row["round"]),
            "home": row["home"], "away": row["away"],
            "pick": pick, "flag": flag(pick) if pick else "",
            "winner": row["winner"], "status": status,
            "points": ROUND_POINTS.get(row["round"], 0),
        })
    return jsonify({"id": p["id"], "name": p["name"],
                    "total_score": total, "correct": correct, "by_round": by_round,
                    "picks": detail})

@app.route("/api/sync", methods=["POST"])
def manual_sync():
    done = sync_scores()
    return jsonify({"ok": done is not None, "finished": done, "last_sync": LAST_SYNC})

@app.route("/api/last-sync")
def last_sync():
    return jsonify({"last_sync": LAST_SYNC})

@app.route("/")
def index():
    return send_from_directory("static", "index.html")

# ── START ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    sync_scores()
    threading.Thread(target=sync_loop, daemon=True).start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
