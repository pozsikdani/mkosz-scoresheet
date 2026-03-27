#!/usr/bin/env python3
"""
Convert play-by-play data (pbp.sqlite) to scoresheet schema (scoresheet.sqlite)
for dashboard generation.

Usage:
    python3 pbp_to_scoresheet.py
    python3 pbp_to_scoresheet.py --pbp-db /path/to/pbp.sqlite --target-db scoresheet.sqlite
    python3 pbp_to_scoresheet.py --comp whun_univn --prefix MFOB
"""

import argparse
import hashlib
import json
import os
import sqlite3
import sys

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PBP_DB = os.path.join(
    os.path.dirname(SCRIPT_DIR), "mkosz-play-by-play", "pbp.sqlite"
)
DEFAULT_TARGET_DB = os.path.join(SCRIPT_DIR, "scoresheet.sqlite")

# Competition → match_id prefix mapping
COMP_CONFIG = {
    "whun_univn": {
        "prefix": "MFOB",
        "team_pattern": "%Közgáz SC és DSK%",
    },
    "hun_univn": {
        "prefix": "MFOF",
        "team_pattern": "%Közgáz SC és DSK%",
    },
}

# Optional jersey number overrides (player_name → jersey_number)
# Will be auto-populated on first run if empty
JERSEY_MAP = {
    # "CSOMA PETRA": 7,
}

# Auto-assigned jersey numbers (player_name_upper → sequential number)
_auto_jersey_map = {}
_auto_jersey_counter = 0

# 2-point scoring event types
TWO_POINT_TYPES = {"CLOSE_MADE", "MID_MADE", "DUNK_MADE"}
TWO_POINT_MISS_TYPES = {"CLOSE_MISS", "MID_MISS", "DUNK_MISS"}
THREE_POINT_TYPES = {"THREE_MADE"}
THREE_POINT_MISS_TYPES = {"THREE_MISS"}
FT_MADE_TYPES = {"FT_MADE"}
FT_MISS_TYPES = {"FT_MISS"}
FOUL_TYPES = {"FOUL"}


def synthetic_license(player_name):
    """Generate deterministic synthetic license number from player name."""
    normalized = player_name.strip().upper()
    h = hashlib.md5(normalized.encode("utf-8")).hexdigest()[:6].upper()
    return f"MFOB-{h}"


def get_jersey(player_name):
    """Get jersey number for player. Uses JERSEY_MAP overrides first,
    then auto-assigns a unique sequential number per player."""
    global _auto_jersey_counter
    upper = player_name.strip().upper()
    if upper in JERSEY_MAP:
        return JERSEY_MAP[upper]
    if upper not in _auto_jersey_map:
        _auto_jersey_counter += 1
        _auto_jersey_map[upper] = _auto_jersey_counter
    return _auto_jersey_map[upper]


def build_match_id_map(pbp_conn, comp_code, prefix):
    """Build mapping from PBP match_id → new scoresheet match_id, sorted by date.
    Only includes played matches (score > 0)."""
    rows = pbp_conn.execute(
        """SELECT match_id, match_date FROM matches
           WHERE comp_code = ? AND (score_a > 0 OR score_b > 0)
           ORDER BY match_date, match_id""",
        (comp_code,),
    ).fetchall()
    id_map = {}
    for i, (mid, _) in enumerate(rows, 1):
        id_map[mid] = f"{prefix}-{i:04d}"
    return id_map


def convert_matches(pbp_conn, target_conn, id_map):
    """Convert matches table."""
    for pbp_id, new_id in id_map.items():
        row = pbp_conn.execute(
            """SELECT team_a, team_b, score_a, score_b, match_date,
                      match_time, venue, source_url
               FROM matches WHERE match_id = ?""",
            (pbp_id,),
        ).fetchone()
        if not row:
            continue
        team_a, team_b, score_a, score_b, match_date, match_time, venue, source_url = row
        target_conn.execute(
            """INSERT OR REPLACE INTO matches
               (match_id, team_a, team_b, score_a, score_b,
                match_date, match_time, venue, source_pdf)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (new_id, team_a, team_b, score_a, score_b,
             match_date, match_time, venue, source_url),
        )


def convert_players(pbp_conn, target_conn, id_map):
    """Convert player data from PBP events + player_stats → players table."""
    for pbp_id, new_id in id_map.items():
        # Get all players from player_stats
        stats_rows = pbp_conn.execute(
            """SELECT team, player_name, is_starter
               FROM player_stats WHERE match_id = ?""",
            (pbp_id,),
        ).fetchall()

        for team, player_name, is_starter in stats_rows:
            lic = synthetic_license(player_name)
            jersey = get_jersey(player_name)

            # Determine entry_quarter from substitutions
            entry_q = None
            if is_starter:
                entry_q = 1
            else:
                sub_row = pbp_conn.execute(
                    """SELECT MIN(quarter) FROM substitutions
                       WHERE match_id = ? AND team = ? AND player_in = ?""",
                    (pbp_id, team, player_name),
                ).fetchone()
                if sub_row and sub_row[0]:
                    entry_q = sub_row[0]
                else:
                    # Fallback: first event quarter
                    ev_row = pbp_conn.execute(
                        """SELECT MIN(quarter) FROM events
                           WHERE match_id = ? AND team = ? AND player_name = ?""",
                        (pbp_id, team, player_name),
                    ).fetchone()
                    if ev_row and ev_row[0]:
                        entry_q = ev_row[0]

            target_conn.execute(
                """INSERT OR REPLACE INTO players
                   (match_id, team, license_number, name, jersey_number,
                    role, starter, entry_quarter)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (new_id, team, lic, player_name.upper(), jersey,
                 "player", is_starter, entry_q),
            )


def convert_player_game_stats(pbp_conn, target_conn, id_map):
    """Compute and insert player_game_stats from PBP events."""
    for pbp_id, new_id in id_map.items():
        # Get starters info
        starters = {}
        for team, pname, is_starter in pbp_conn.execute(
            "SELECT team, player_name, is_starter FROM player_stats WHERE match_id = ?",
            (pbp_id,),
        ):
            starters[(team, pname)] = is_starter

        # Aggregate events per player
        rows = pbp_conn.execute(
            """SELECT team, player_name, event_type
               FROM events
               WHERE match_id = ? AND player_name IS NOT NULL""",
            (pbp_id,),
        ).fetchall()

        player_stats = {}
        for team, pname, etype in rows:
            key = (team, pname)
            if key not in player_stats:
                player_stats[key] = {
                    "points": 0, "fg2_made": 0, "fg3_made": 0,
                    "ft_made": 0, "ft_attempted": 0, "personal_fouls": 0,
                }
            s = player_stats[key]

            if etype in TWO_POINT_TYPES:
                s["fg2_made"] += 1
                s["points"] += 2
            elif etype in THREE_POINT_TYPES:
                s["fg3_made"] += 1
                s["points"] += 3
            elif etype in FT_MADE_TYPES:
                s["ft_made"] += 1
                s["ft_attempted"] += 1
                s["points"] += 1
            elif etype in FT_MISS_TYPES:
                s["ft_attempted"] += 1
            elif etype in FOUL_TYPES:
                s["personal_fouls"] += 1

        # Insert
        for (team, pname), s in player_stats.items():
            lic = synthetic_license(pname)
            jersey = get_jersey(pname)
            is_starter = starters.get((team, pname), 0)

            # Entry quarter
            entry_q = None
            if is_starter:
                entry_q = 1
            else:
                sub_row = pbp_conn.execute(
                    """SELECT MIN(quarter) FROM substitutions
                       WHERE match_id = ? AND team = ? AND player_in = ?""",
                    (pbp_id, team, pname),
                ).fetchone()
                if sub_row and sub_row[0]:
                    entry_q = sub_row[0]

            target_conn.execute(
                """INSERT OR REPLACE INTO player_game_stats
                   (match_id, team, license_number, name, jersey_number,
                    points, fg2_made, fg3_made, ft_made, ft_attempted,
                    personal_fouls, starter, entry_quarter)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (new_id, team, lic, pname.upper(), jersey,
                 s["points"], s["fg2_made"], s["fg3_made"],
                 s["ft_made"], s["ft_attempted"],
                 s["personal_fouls"], is_starter, entry_q),
            )


def convert_scoring_events(pbp_conn, target_conn, id_map):
    """Convert PBP scoring events → scoring_events table.
    Includes: made FG (2FG/3FG) + made/missed FT only.
    FT misses have NULL score in PBP → fill from previous scoring event.
    """
    SCORING_TYPES = (
        TWO_POINT_TYPES | THREE_POINT_TYPES |
        FT_MADE_TYPES | FT_MISS_TYPES
    )

    for pbp_id, new_id in id_map.items():
        rows = pbp_conn.execute(
            """SELECT event_seq, quarter, team, player_name,
                      event_type, score_a, score_b
               FROM events
               WHERE match_id = ? AND event_type IN ({})
               ORDER BY event_seq""".format(
                ",".join(f"'{t}'" for t in SCORING_TYPES)
            ),
            (pbp_id,),
        ).fetchall()

        last_sc_a, last_sc_b = 0, 0
        for seq, quarter, team, pname, etype, sc_a, sc_b in rows:
            if pname is None:
                continue

            # Fill NULL scores (FT misses) with last known score
            if sc_a is not None:
                last_sc_a, last_sc_b = sc_a, sc_b
            else:
                sc_a, sc_b = last_sc_a, last_sc_b

            lic = synthetic_license(pname)
            jersey = get_jersey(pname)

            if etype in TWO_POINT_TYPES:
                shot_type, made, points = "2FG", 1, 2
            elif etype in THREE_POINT_TYPES:
                shot_type, made, points = "3FG", 1, 3
            elif etype in FT_MADE_TYPES:
                shot_type, made, points = "FT", 1, 1
            elif etype in FT_MISS_TYPES:
                shot_type, made, points = "FT", 0, 0
            else:
                continue

            target_conn.execute(
                """INSERT OR REPLACE INTO scoring_events
                   (match_id, event_seq, quarter, team, jersey_number,
                    license_number, points, shot_type, made, score_a, score_b)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (new_id, seq, quarter, team, jersey,
                 lic, points, shot_type, made, sc_a, sc_b),
            )


def convert_quarter_scores(pbp_conn, target_conn, id_map):
    """Convert quarter_scores from PBP matches JSON → quarter_scores table."""
    for pbp_id, new_id in id_map.items():
        row = pbp_conn.execute(
            "SELECT quarter_scores FROM matches WHERE match_id = ?",
            (pbp_id,),
        ).fetchone()
        if not row or not row[0]:
            continue
        qs = json.loads(row[0])
        for i, (sa, sb) in enumerate(qs, 1):
            target_conn.execute(
                """INSERT OR REPLACE INTO quarter_scores
                   (match_id, quarter, score_a, score_b)
                   VALUES (?,?,?,?)""",
                (new_id, str(i), sa, sb),
            )


def convert_personal_fouls(pbp_conn, target_conn, id_map):
    """Convert FOUL events → personal_fouls table."""
    for pbp_id, new_id in id_map.items():
        rows = pbp_conn.execute(
            """SELECT team, player_name, quarter, minute, counter
               FROM events
               WHERE match_id = ? AND event_type = 'FOUL'
                 AND player_name IS NOT NULL
               ORDER BY event_seq""",
            (pbp_id,),
        ).fetchall()

        # Track foul count per player
        foul_counts = {}
        for team, pname, quarter, minute, counter in rows:
            key = (team, pname)
            foul_counts[key] = foul_counts.get(key, 0) + 1
            jersey = get_jersey(pname)

            target_conn.execute(
                """INSERT INTO personal_fouls
                   (match_id, team, jersey_number, foul_number,
                    minute, quarter, foul_type, foul_category)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (new_id, team, jersey, foul_counts[key],
                 minute, quarter, "defensive", None),
            )


def clean_existing(target_conn, prefix):
    """Remove previously converted data for re-runnability."""
    pattern = f"{prefix}-%"
    for table in [
        "scoring_events", "player_game_stats", "personal_fouls",
        "quarter_scores", "players", "matches",
    ]:
        target_conn.execute(
            f"DELETE FROM {table} WHERE match_id LIKE ?", (pattern,)
        )
    target_conn.commit()
    print(f"  Korábbi {prefix}-* adatok törölve")


def main():
    parser = argparse.ArgumentParser(
        description="Convert PBP data to scoresheet schema"
    )
    parser.add_argument(
        "--pbp-db", default=DEFAULT_PBP_DB,
        help=f"PBP database path (default: {DEFAULT_PBP_DB})",
    )
    parser.add_argument(
        "--target-db", default=DEFAULT_TARGET_DB,
        help=f"Target scoresheet database path (default: {DEFAULT_TARGET_DB})",
    )
    parser.add_argument(
        "--comp", default="whun_univn",
        help="PBP competition code (default: whun_univn)",
    )
    parser.add_argument(
        "--prefix", default=None,
        help="Match ID prefix (default: from COMP_CONFIG)",
    )
    args = parser.parse_args()

    comp = args.comp
    if comp not in COMP_CONFIG:
        print(f"Hiba: ismeretlen comp kód '{comp}'. Ismert: {list(COMP_CONFIG)}")
        sys.exit(1)

    cfg = COMP_CONFIG[comp]
    prefix = args.prefix or cfg["prefix"]

    if not os.path.exists(args.pbp_db):
        print(f"Hiba: PBP adatbázis nem található: {args.pbp_db}")
        sys.exit(1)
    if not os.path.exists(args.target_db):
        print(f"Hiba: Cél adatbázis nem található: {args.target_db}")
        sys.exit(1)

    pbp_conn = sqlite3.connect(args.pbp_db)

    # Ensure player_stats table exists (might be missing if PBP processing failed)
    tables = [r[0] for r in pbp_conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    if 'player_stats' not in tables:
        print(f"  ⚠ player_stats tábla hiányzik a PBP adatbázisban, létrehozás...")
        pbp_conn.executescript("""
            CREATE TABLE IF NOT EXISTS player_stats (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                match_id        TEXT NOT NULL,
                team            TEXT NOT NULL CHECK (team IN ('A', 'B')),
                player_name     TEXT NOT NULL,
                is_starter      INTEGER NOT NULL DEFAULT 0,
                minutes         INTEGER NOT NULL DEFAULT 0,
                plus_minus      INTEGER NOT NULL DEFAULT 0,
                val             INTEGER NOT NULL DEFAULT 0,
                ts_pct          REAL,
                efg_pct         REAL,
                game_score      REAL,
                usg_pct         REAL,
                ast_to          REAL,
                tov_pct         REAL,
                UNIQUE(match_id, team, player_name)
            );
        """)
        pbp_conn.commit()

    target_conn = sqlite3.connect(args.target_db)

    print(f"PBP → Scoresheet konverzió")
    print(f"  Forrás: {args.pbp_db}")
    print(f"  Cél: {args.target_db}")
    print(f"  Comp: {comp}, Prefix: {prefix}")

    # Clean existing data
    clean_existing(target_conn, prefix)

    # Build match ID mapping
    id_map = build_match_id_map(pbp_conn, comp, prefix)
    print(f"  {len(id_map)} lejátszott meccs konvertálása:")
    for old, new in id_map.items():
        row = pbp_conn.execute(
            "SELECT team_a, team_b, score_a, score_b, match_date FROM matches WHERE match_id=?",
            (old,),
        ).fetchone()
        print(f"    {old} → {new}: {row[0]} vs {row[1]} ({row[2]}-{row[3]}, {row[4]})")

    # Convert all tables
    print("\n  Konvertálás...")
    convert_matches(pbp_conn, target_conn, id_map)
    print("    ✓ matches")

    convert_players(pbp_conn, target_conn, id_map)
    print("    ✓ players")

    convert_player_game_stats(pbp_conn, target_conn, id_map)
    print("    ✓ player_game_stats")

    convert_scoring_events(pbp_conn, target_conn, id_map)
    print("    ✓ scoring_events")

    convert_quarter_scores(pbp_conn, target_conn, id_map)
    print("    ✓ quarter_scores")

    convert_personal_fouls(pbp_conn, target_conn, id_map)
    print("    ✓ personal_fouls")

    target_conn.commit()

    # Verification
    print("\n  Verifikáció:")
    n_matches = target_conn.execute(
        "SELECT COUNT(*) FROM matches WHERE match_id LIKE ?",
        (f"{prefix}-%",),
    ).fetchone()[0]
    n_players = target_conn.execute(
        "SELECT COUNT(DISTINCT license_number) FROM players WHERE match_id LIKE ?",
        (f"{prefix}-%",),
    ).fetchone()[0]
    n_pgs = target_conn.execute(
        "SELECT COUNT(*) FROM player_game_stats WHERE match_id LIKE ?",
        (f"{prefix}-%",),
    ).fetchone()[0]
    n_se = target_conn.execute(
        "SELECT COUNT(*) FROM scoring_events WHERE match_id LIKE ?",
        (f"{prefix}-%",),
    ).fetchone()[0]
    n_qs = target_conn.execute(
        "SELECT COUNT(*) FROM quarter_scores WHERE match_id LIKE ?",
        (f"{prefix}-%",),
    ).fetchone()[0]
    n_pf = target_conn.execute(
        "SELECT COUNT(*) FROM personal_fouls WHERE match_id LIKE ?",
        (f"{prefix}-%",),
    ).fetchone()[0]

    print(f"    Meccsek: {n_matches}")
    print(f"    Egyedi játékosok: {n_players}")
    print(f"    Player game stats sorok: {n_pgs}")
    print(f"    Scoring events: {n_se}")
    print(f"    Quarter scores: {n_qs}")
    print(f"    Personal fouls: {n_pf}")

    pbp_conn.close()
    target_conn.close()
    print("\n✓ Konverzió kész!")


if __name__ == "__main__":
    main()
