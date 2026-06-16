from flask import Flask, request, jsonify, send_from_directory
import sqlite3, requests, threading, time, os
from datetime import datetime, timedelta, timezone

app = Flask(__name__, static_folder='static')
# DB path is configurable so it can live on a persistent volume in production.
# Locally it defaults to ./pool.db; on Railway set DB_PATH=/data/pool.db (mounted volume).
DB = os.environ.get("DB_PATH", "pool.db")

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
            CREATE TABLE IF NOT EXISTS picks (
                player_id INTEGER,
                group_letter TEXT,
                team_name TEXT,
                PRIMARY KEY (player_id, group_letter)
            );
            CREATE TABLE IF NOT EXISTS results (
                match_key TEXT PRIMARY KEY,
                home_score INTEGER,
                away_score INTEGER,
                updated_at TEXT DEFAULT (datetime('now'))
            );
        """)

# ── FIXTURE DATA ──────────────────────────────────────────────────────────────

GROUPS = {
  "A": {
    "teams": ["Mexico","South Africa","South Korea","Czechia"],
    "matches": [
      {"home":"Mexico","away":"South Africa","date":"2026-06-11","time":"3:00pm ET","venue":"Mexico City"},
      {"home":"South Korea","away":"Czechia","date":"2026-06-11","time":"10:00pm ET","venue":"Guadalajara"},
      {"home":"Czechia","away":"South Africa","date":"2026-06-18","time":"12:00pm ET","venue":"Atlanta"},
      {"home":"Mexico","away":"South Korea","date":"2026-06-18","time":"9:00pm ET","venue":"Guadalajara"},
      {"home":"Czechia","away":"Mexico","date":"2026-06-24","time":"9:00pm ET","venue":"Mexico City"},
      {"home":"South Africa","away":"South Korea","date":"2026-06-24","time":"9:00pm ET","venue":"Monterrey"},
    ]
  },
  "B": {
    "teams": ["Canada","Bosnia & Herz.","Qatar","Switzerland"],
    "matches": [
      {"home":"Canada","away":"Bosnia & Herz.","date":"2026-06-12","time":"3:00pm ET","venue":"Toronto"},
      {"home":"Qatar","away":"Switzerland","date":"2026-06-13","time":"3:00pm ET","venue":"San Francisco"},
      {"home":"Switzerland","away":"Bosnia & Herz.","date":"2026-06-18","time":"3:00pm ET","venue":"Los Angeles"},
      {"home":"Canada","away":"Qatar","date":"2026-06-18","time":"6:00pm ET","venue":"Vancouver"},
      {"home":"Switzerland","away":"Canada","date":"2026-06-24","time":"3:00pm ET","venue":"Vancouver"},
      {"home":"Bosnia & Herz.","away":"Qatar","date":"2026-06-24","time":"3:00pm ET","venue":"Seattle"},
    ]
  },
  "C": {
    "teams": ["Brazil","Morocco","Haiti","Scotland"],
    "matches": [
      {"home":"Brazil","away":"Morocco","date":"2026-06-13","time":"6:00pm ET","venue":"New York/NJ"},
      {"home":"Haiti","away":"Scotland","date":"2026-06-13","time":"9:00pm ET","venue":"Boston"},
      {"home":"Scotland","away":"Morocco","date":"2026-06-19","time":"6:00pm ET","venue":"Boston"},
      {"home":"Brazil","away":"Haiti","date":"2026-06-19","time":"8:30pm ET","venue":"Philadelphia"},
      {"home":"Scotland","away":"Brazil","date":"2026-06-24","time":"6:00pm ET","venue":"Miami"},
      {"home":"Morocco","away":"Haiti","date":"2026-06-24","time":"6:00pm ET","venue":"Atlanta"},
    ]
  },
  "D": {
    "teams": ["USA","Paraguay","Australia","Türkiye"],
    "matches": [
      {"home":"USA","away":"Paraguay","date":"2026-06-12","time":"9:00pm ET","venue":"Los Angeles"},
      {"home":"Australia","away":"Türkiye","date":"2026-06-14","time":"12:00am ET","venue":"Vancouver"},
      {"home":"USA","away":"Australia","date":"2026-06-19","time":"3:00pm ET","venue":"Seattle"},
      {"home":"Türkiye","away":"Paraguay","date":"2026-06-19","time":"12:00am ET","venue":"San Francisco"},
      {"home":"Türkiye","away":"USA","date":"2026-06-25","time":"10:00pm ET","venue":"Los Angeles"},
      {"home":"Paraguay","away":"Australia","date":"2026-06-25","time":"10:00pm ET","venue":"San Francisco"},
    ]
  },
  "E": {
    "teams": ["Germany","Curaçao","Ivory Coast","Ecuador"],
    "matches": [
      {"home":"Germany","away":"Curaçao","date":"2026-06-14","time":"1:00pm ET","venue":"Houston"},
      {"home":"Ivory Coast","away":"Ecuador","date":"2026-06-14","time":"7:00pm ET","venue":"Philadelphia"},
      {"home":"Germany","away":"Ivory Coast","date":"2026-06-20","time":"4:00pm ET","venue":"Toronto"},
      {"home":"Ecuador","away":"Curaçao","date":"2026-06-20","time":"8:00pm ET","venue":"Kansas City"},
      {"home":"Curaçao","away":"Ivory Coast","date":"2026-06-25","time":"4:00pm ET","venue":"Philadelphia"},
      {"home":"Ecuador","away":"Germany","date":"2026-06-25","time":"4:00pm ET","venue":"New York/NJ"},
    ]
  },
  "F": {
    "teams": ["Netherlands","Japan","Sweden","Tunisia"],
    "matches": [
      {"home":"Netherlands","away":"Japan","date":"2026-06-14","time":"4:00pm ET","venue":"Dallas"},
      {"home":"Sweden","away":"Tunisia","date":"2026-06-14","time":"10:00pm ET","venue":"Monterrey"},
      {"home":"Netherlands","away":"Sweden","date":"2026-06-20","time":"1:00pm ET","venue":"Houston"},
      {"home":"Tunisia","away":"Japan","date":"2026-06-21","time":"12:00am ET","venue":"Monterrey"},
      {"home":"Japan","away":"Sweden","date":"2026-06-25","time":"7:00pm ET","venue":"Dallas"},
      {"home":"Tunisia","away":"Netherlands","date":"2026-06-25","time":"7:00pm ET","venue":"Kansas City"},
    ]
  },
  "G": {
    "teams": ["Belgium","Egypt","Iran","New Zealand"],
    "matches": [
      {"home":"Belgium","away":"Egypt","date":"2026-06-15","time":"3:00pm ET","venue":"Seattle"},
      {"home":"Iran","away":"New Zealand","date":"2026-06-15","time":"9:00pm ET","venue":"Los Angeles"},
      {"home":"Belgium","away":"Iran","date":"2026-06-21","time":"3:00pm ET","venue":"Los Angeles"},
      {"home":"New Zealand","away":"Egypt","date":"2026-06-21","time":"9:00pm ET","venue":"Vancouver"},
      {"home":"Egypt","away":"Iran","date":"2026-06-26","time":"11:00pm ET","venue":"Seattle"},
      {"home":"New Zealand","away":"Belgium","date":"2026-06-26","time":"11:00pm ET","venue":"Vancouver"},
    ]
  },
  "H": {
    "teams": ["Spain","Cape Verde","Saudi Arabia","Uruguay"],
    "matches": [
      {"home":"Spain","away":"Cape Verde","date":"2026-06-15","time":"12:00pm ET","venue":"Atlanta"},
      {"home":"Saudi Arabia","away":"Uruguay","date":"2026-06-15","time":"6:00pm ET","venue":"Miami"},
      {"home":"Spain","away":"Saudi Arabia","date":"2026-06-21","time":"12:00pm ET","venue":"Atlanta"},
      {"home":"Uruguay","away":"Cape Verde","date":"2026-06-21","time":"6:00pm ET","venue":"Miami"},
      {"home":"Cape Verde","away":"Saudi Arabia","date":"2026-06-26","time":"8:00pm ET","venue":"Houston"},
      {"home":"Uruguay","away":"Spain","date":"2026-06-26","time":"8:00pm ET","venue":"Guadalajara"},
    ]
  },
  "I": {
    "teams": ["France","Senegal","Iraq","Norway"],
    "matches": [
      {"home":"France","away":"Senegal","date":"2026-06-16","time":"3:00pm ET","venue":"New York/NJ"},
      {"home":"Iraq","away":"Norway","date":"2026-06-16","time":"6:00pm ET","venue":"Boston"},
      {"home":"France","away":"Iraq","date":"2026-06-22","time":"5:00pm ET","venue":"Philadelphia"},
      {"home":"Norway","away":"Senegal","date":"2026-06-22","time":"8:00pm ET","venue":"New York/NJ"},
      {"home":"Norway","away":"France","date":"2026-06-26","time":"3:00pm ET","venue":"Boston"},
      {"home":"Senegal","away":"Iraq","date":"2026-06-26","time":"3:00pm ET","venue":"Toronto"},
    ]
  },
  "J": {
    "teams": ["Argentina","Algeria","Austria","Jordan"],
    "matches": [
      {"home":"Argentina","away":"Algeria","date":"2026-06-16","time":"9:00pm ET","venue":"Kansas City"},
      {"home":"Austria","away":"Jordan","date":"2026-06-17","time":"12:00am ET","venue":"San Francisco"},
      {"home":"Argentina","away":"Austria","date":"2026-06-22","time":"1:00pm ET","venue":"Dallas"},
      {"home":"Jordan","away":"Algeria","date":"2026-06-22","time":"11:00pm ET","venue":"San Francisco"},
      {"home":"Algeria","away":"Austria","date":"2026-06-27","time":"10:00pm ET","venue":"Kansas City"},
      {"home":"Jordan","away":"Argentina","date":"2026-06-27","time":"10:00pm ET","venue":"Dallas"},
    ]
  },
  "K": {
    "teams": ["Portugal","DR Congo","Uzbekistan","Colombia"],
    "matches": [
      {"home":"Portugal","away":"DR Congo","date":"2026-06-17","time":"1:00pm ET","venue":"Houston"},
      {"home":"Uzbekistan","away":"Colombia","date":"2026-06-17","time":"10:00pm ET","venue":"Mexico City"},
      {"home":"Portugal","away":"Uzbekistan","date":"2026-06-23","time":"1:00pm ET","venue":"Houston"},
      {"home":"Colombia","away":"DR Congo","date":"2026-06-23","time":"10:00pm ET","venue":"Guadalajara"},
      {"home":"Colombia","away":"Portugal","date":"2026-06-27","time":"7:30pm ET","venue":"Miami"},
      {"home":"DR Congo","away":"Uzbekistan","date":"2026-06-27","time":"7:30pm ET","venue":"Atlanta"},
    ]
  },
  "L": {
    "teams": ["England","Croatia","Ghana","Panama"],
    "matches": [
      {"home":"England","away":"Croatia","date":"2026-06-17","time":"4:00pm ET","venue":"Dallas"},
      {"home":"Ghana","away":"Panama","date":"2026-06-17","time":"7:00pm ET","venue":"Toronto"},
      {"home":"England","away":"Ghana","date":"2026-06-23","time":"4:00pm ET","venue":"Boston"},
      {"home":"Panama","away":"Croatia","date":"2026-06-23","time":"7:00pm ET","venue":"Toronto"},
      {"home":"Panama","away":"England","date":"2026-06-27","time":"5:00pm ET","venue":"New York/NJ"},
      {"home":"Croatia","away":"Ghana","date":"2026-06-27","time":"5:00pm ET","venue":"Philadelphia"},
    ]
  },
}

# Build fixture key lookup
FIXTURE_KEYS = {}
for g, data in GROUPS.items():
    for m in data["matches"]:
        FIXTURE_KEYS[m["home"] + "__" + m["away"]] = True

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

KNOCKOUT = [
  {"round": "Round of 32", "dates": "Jun 28 – Jul 3"},
  {"round": "Round of 16", "dates": "Jul 4 – 7"},
  {"round": "Quarterfinals", "dates": "Jul 9 – 11"},
  {"round": "Semifinals", "dates": "Jul 14 – 15"},
  {"round": "Third Place", "dates": "Jul 18"},
  {"round": "Final", "dates": "Jul 19 — MetLife Stadium, 3pm ET"},
]

# ── SCORE SYNC ────────────────────────────────────────────────────────────────

NAME_MAP = {
    "Czech Republic": "Czechia",
    "Bosnia & Herzegovina": "Bosnia & Herz.",
    "Turkey": "Türkiye",
}

OFB_URL = "https://raw.githubusercontent.com/openfootball/worldcup.json/master/2026/worldcup.json"

def sync_scores():
    try:
        res = requests.get(OFB_URL, timeout=10)
        data = res.json()
        count = 0
        with get_db() as db:
            for match in data.get("matches", []):
                if not match.get("score", {}).get("ft"):
                    continue
                h = NAME_MAP.get(match["team1"], match["team1"])
                a = NAME_MAP.get(match["team2"], match["team2"])
                hs, as_ = match["score"]["ft"]
                key = h + "__" + a
                rev = a + "__" + h
                if key in FIXTURE_KEYS:
                    db.execute("INSERT OR REPLACE INTO results (match_key,home_score,away_score,updated_at) VALUES (?,?,?,datetime('now'))", (key, hs, as_))
                    count += 1
                elif rev in FIXTURE_KEYS:
                    db.execute("INSERT OR REPLACE INTO results (match_key,home_score,away_score,updated_at) VALUES (?,?,?,datetime('now'))", (rev, as_, hs))
                    count += 1
        print(f"Scores synced ({count} finished matches)")
        return count
    except Exception as e:
        print(f"Sync error: {e}")
        return None

def sync_loop():
    while True:
        time.sleep(300)  # every 5 minutes
        sync_scores()

# ── STANDINGS HELPER ──────────────────────────────────────────────────────────

def compute_standings(group_letter, results_dict):
    rows = {t: {"name":t,"pts":0,"gf":0,"ga":0,"gd":0,"played":0} for t in GROUPS[group_letter]["teams"]}
    for m in GROUPS[group_letter]["matches"]:
        key = m["home"] + "__" + m["away"]
        r = results_dict.get(key)
        if not r: continue
        h, a = m["home"], m["away"]
        hs, as_ = r["h"], r["a"]
        rows[h]["played"] += 1; rows[a]["played"] += 1
        rows[h]["gf"] += hs; rows[h]["ga"] += as_; rows[h]["gd"] = rows[h]["gf"] - rows[h]["ga"]
        rows[a]["gf"] += as_; rows[a]["ga"] += hs; rows[a]["gd"] = rows[a]["gf"] - rows[a]["ga"]
        if hs > as_: rows[h]["pts"] += 3
        elif hs < as_: rows[a]["pts"] += 3
        else: rows[h]["pts"] += 1; rows[a]["pts"] += 1
    return sorted(rows.values(), key=lambda x: (-x["pts"], -x["gd"], -x["gf"], x["name"]))

def results_dict_from_db():
    with get_db() as db:
        rows = db.execute("SELECT match_key,home_score,away_score FROM results").fetchall()
    return {r["match_key"]: {"h": r["home_score"], "a": r["away_score"]} for r in rows}

# ── API ROUTES ────────────────────────────────────────────────────────────────

@app.route("/api/config")
def get_config():
    return jsonify({"groups": GROUPS, "flags": FLAGS, "knockout": KNOCKOUT})

@app.route("/api/join", methods=["POST"])
def join():
    name = (request.json.get("name") or "").strip()
    if not name: return jsonify({"error": "Name required"}), 400
    with get_db() as db:
        try:
            cur = db.execute("INSERT INTO players (name) VALUES (?)", (name,))
            return jsonify({"id": cur.lastrowid, "name": name})
        except sqlite3.IntegrityError:
            row = db.execute("SELECT id,name FROM players WHERE name=?", (name,)).fetchone()
            return jsonify({"id": row["id"], "name": row["name"]})

@app.route("/api/picks", methods=["POST"])
def save_picks():
    data = request.json
    player_id = data.get("player_id")
    picks = data.get("picks", {})
    if not player_id:
        return jsonify({"error": "player_id required"}), 400
    with get_db() as db:
        for g, team in picks.items():
            if g not in GROUPS:
                return jsonify({"error": f"Unknown group {g}"}), 400
            if team and team not in GROUPS[g]["teams"]:
                return jsonify({"error": f"{team} is not in group {g}"}), 400
            if team:
                db.execute("INSERT OR REPLACE INTO picks (player_id,group_letter,team_name) VALUES (?,?,?)", (player_id, g, team))
            else:
                db.execute("DELETE FROM picks WHERE player_id=? AND group_letter=?", (player_id, g))
    return jsonify({"ok": True})

@app.route("/api/players")
def get_players():
    with get_db() as db:
        players = db.execute("SELECT id,name FROM players ORDER BY id").fetchall()
        all_picks = db.execute("SELECT player_id,group_letter,team_name FROM picks").fetchall()
    picks_map = {}
    for p in all_picks:
        picks_map.setdefault(p["player_id"], {})[p["group_letter"]] = p["team_name"]
    return jsonify([{"id": p["id"], "name": p["name"], "picks": picks_map.get(p["id"], {})} for p in players])

@app.route("/api/results")
def get_results():
    return jsonify(results_dict_from_db())

@app.route("/api/standings")
def get_standings():
    results_dict = results_dict_from_db()
    return jsonify({g: compute_standings(g, results_dict) for g in GROUPS})

@app.route("/api/leaderboard")
def get_leaderboard():
    with get_db() as db:
        players = db.execute("SELECT id,name FROM players").fetchall()
        all_picks = db.execute("SELECT player_id,group_letter,team_name FROM picks").fetchall()
    results_dict = results_dict_from_db()
    picks_map = {}
    for p in all_picks:
        picks_map.setdefault(p["player_id"], {})[p["group_letter"]] = p["team_name"]

    # Precompute standings + each team's position per group once.
    standings = {g: compute_standings(g, results_dict) for g in GROUPS}
    position = {}   # group -> {team: index}
    started = {}    # group -> bool
    for g, st in standings.items():
        position[g] = {row["name"]: i for i, row in enumerate(st)}
        started[g] = any(row["played"] > 0 for row in st)

    board = []
    for p in players:
        picks = picks_map.get(p["id"], {})
        correct = total = 0
        pick_status = {}  # group -> "correct" | "trailing" | "pending"
        for g in GROUPS:
            pick = picks.get(g)
            if not pick:
                continue
            if not started[g]:
                pick_status[g] = "pending"
                continue
            total += 1
            pos = position[g].get(pick, 99)
            if pos == 0:
                correct += 1; pick_status[g] = "correct"
            elif pos >= 2:
                pick_status[g] = "trailing"   # 3rd or 4th
            else:
                pick_status[g] = "close"      # 2nd
        board.append({"id": p["id"], "name": p["name"], "picks": picks,
                      "correct": correct, "total": total, "status": pick_status})
    board.sort(key=lambda x: (-x["correct"], -x["total"], x["name"].lower()))
    return jsonify(board)

def et_today():
    # June/July 2026 is EDT (UTC-4). Use a fixed offset so behaviour is server-TZ independent.
    return (datetime.now(timezone.utc) - timedelta(hours=4)).date()

@app.route("/api/upcoming")
def get_upcoming():
    today = et_today()
    window_end = today + timedelta(days=2)
    results_dict = results_dict_from_db()
    upcoming = []
    for g, data in GROUPS.items():
        for m in data["matches"]:
            try:
                d = datetime.strptime(m["date"], "%Y-%m-%d").date()
            except ValueError:
                continue
            if today <= d <= window_end:
                key = m["home"] + "__" + m["away"]
                upcoming.append({**m, "group": g,
                                 "flag_home": FLAGS.get(m["home"], ""),
                                 "flag_away": FLAGS.get(m["away"], ""),
                                 "score": results_dict.get(key)})
    upcoming.sort(key=lambda x: (x["date"], x["time"]))
    return jsonify(upcoming)

@app.route("/api/sync", methods=["POST"])
def manual_sync():
    count = sync_scores()
    with get_db() as db:
        row = db.execute("SELECT MAX(updated_at) AS ts FROM results").fetchone()
    return jsonify({"ok": count is not None, "synced": count, "last_sync": row["ts"]})

@app.route("/api/last-sync")
def last_sync():
    with get_db() as db:
        row = db.execute("SELECT MAX(updated_at) AS ts FROM results").fetchone()
    return jsonify({"last_sync": row["ts"]})

@app.route("/")
def index():
    return send_from_directory("static", "index.html")

# ── START ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    sync_scores()  # sync on startup
    t = threading.Thread(target=sync_loop, daemon=True)
    t.start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
