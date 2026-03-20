#!/usr/bin/env python3
"""Generate individual player dashboards for any team in any NB2 group."""

import sqlite3
import os
import json
import re
import sys
import calendar as cal_module
from datetime import datetime
import urllib.request
import urllib.error
import csv
import io

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nb2_full.sqlite")
PBP_DB_PATH = os.environ.get(
    "PBP_DB_PATH",
    os.path.expanduser("~/Desktop/claudecode/mkosz-play-by-play/pbp.sqlite"),
)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ---- TEAM CONFIGURATIONS ----
# League definitions: label, color, border color, background tint
LEAGUES = {
    "nb2":       {"label": "NB2",        "color": "#C41E3A", "bg": "rgba(196,30,58,0.12)",  "border": "rgba(196,30,58,0.3)"},
    "budapesti": {"label": "Budapesti",   "color": "#6c5ce7", "bg": "rgba(108,92,231,0.12)", "border": "rgba(108,92,231,0.3)"},
    "mefob":     {"label": "MEFOB",      "color": "#00cec9", "bg": "rgba(0,206,201,0.12)",  "border": "rgba(0,206,201,0.3)"},
}


def _team_color_cfg(hex_color):
    """Derive color/bg/border dict from a hex color string like '#C41E3A'."""
    r, g, b = int(hex_color[1:3], 16), int(hex_color[3:5], 16), int(hex_color[5:7], 16)
    return {
        "color": hex_color,
        "bg": f"rgba({r},{g},{b},0.12)",
        "border": f"rgba({r},{g},{b},0.3)",
    }

TEAMS = {
    "kozgaz-b": {
        "team_pattern": "%KÖZGÁZ%DSK/B%",
        "team_pattern_broad": "%KÖZGÁZ%",  # for groups where only one KÖZGÁZ team plays
        "comp_prefix": "F2KE%",
        "team_name": "KÖZGÁZ SC ÉS DSK/B",
        "team_short": "KÖZGÁZ B",
        "group_name": "NB2 Kelet",
        "league": "nb2",
        "out_dir": "dashboards",
        "mkosz_season": "x2526",
        "mkosz_comp": "hun3k",
        "mkosz_team_id": "9239",
        "color": "#C41E3A",  # Közgáz piros
    },
    "kozgaz-a": {
        "team_pattern": "%KÖZGÁZ%DSK/A%",
        "team_pattern_broad": "%KÖZGÁZ%",
        "comp_prefix": "F2KB%",
        "team_name": "KÖZGÁZ SC ÉS DSK/A",
        "team_short": "KÖZGÁZ A",
        "group_name": "NB2 Közép B",
        "league": "nb2",
        "out_dir": "dashboards-a",
        "mkosz_season": "x2526",
        "mkosz_comp": "hun3kob",
        "mkosz_team_id": "9219",
        "color": "#e17055",  # narancs-piros
    },
    "kozgaz-noi": {
        "team_pattern": "%KÖZGÁZ%",
        "team_pattern_broad": "%KÖZGÁZ%",
        "comp_prefix": "NA%",
        "team_name": "KÖZGÁZ",
        "team_short": "Közgáz Női",
        "group_name": "Női A - Cziffra Mihály",
        "league": "budapesti",
        "out_dir": "dashboards-noi",
        "mkosz_season": "x2526",
        "mkosz_comp": "whun_bud_na",
        "mkosz_team_id": "79078",
        "county": "budapest",
        "color": "#6c5ce7",  # lila
    },
    "leftoverz": {
        "team_pattern": "%LEFTOVER%",
        "team_pattern_broad": "%LEFTOVER%",
        "comp_prefix": "RKFB%",
        "team_name": "KÖZGÁZ LEFTOVERZ",
        "team_short": "Leftoverz",
        "group_name": "Regionális Kiemelt Férfi - Cziffra Mihály",
        "league": "budapesti",
        "out_dir": "leftoverz",
        "mkosz_season": "x2526",
        "mkosz_comp": "hun_bud_rkfb",
        "mkosz_team_id": "79359",
        "county": "budapest",
        "color": "#fdcb6e",  # sárga
    },
    "kozgaz-mefob": {
        "team_pattern": "%Közgáz SC és DSK%",
        "team_pattern_broad": "%Közgáz%",
        "comp_prefix": "MFOB%",
        "team_name": "Közgáz SC és DSK",
        "team_short": "MEFOB Női",
        "group_name": "Leány egyetemi Nyugat",
        "league": "mefob",
        "out_dir": "dashboards-mefob",
        "mkosz_season": "x2526",
        "mkosz_comp": "whun_univn",
        "mkosz_team_id": "25113",
        "color": "#00cec9",  # teal
        "data_source": "pbp",
        "pbp_comp_code": "whun_univn",
    },
    "kozgaz-mefob-ferfi": {
        "team_pattern": "%Közgáz SC és DSK%",
        "team_pattern_broad": "%Közgáz%",
        "comp_prefix": "MFOF%",
        "team_name": "Közgáz SC és DSK",
        "team_short": "MEFOB Férfi",
        "group_name": "Fiú egyetemi Nyugat",
        "league": "mefob",
        "out_dir": "dashboards-mefob-ferfi",
        "mkosz_season": "x2526",
        "mkosz_comp": "hun_univn",
        "mkosz_team_id": "25102",
        "color": "#a0a0b0",  # szürke
        "data_source": "pbp",
        "pbp_comp_code": "hun_univn",
    },
}

# Navigation structure for the site
NAV_TEAMS = [
    {"key": "kozgaz-b", "label": "Öregek NB2", "href": "dashboards"},
    {"key": "kozgaz-a", "label": "Fiatalok NB2", "href": "dashboards-a"},
    {"key": "kozgaz-noi", "label": "Közgáz Női", "href": "dashboards-noi"},
    {"key": "leftoverz", "label": "Leftoverz", "href": "leftoverz"},
    {"key": "kozgaz-mefob", "label": "MEFOB Női", "href": "dashboards-mefob"},
    {"key": "kozgaz-mefob-ferfi", "label": "MEFOB Férfi", "href": "dashboards-mefob-ferfi"},
]

# ---- TRAINING ATTENDANCE (Közgáz B only, fetched from Google Sheets) ----
ATTENDANCE_SHEET_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "1CY9OV_JY4C5uzTcA621zs0-rd5gPO7ELau5yvrSsA-0/export?format=csv&gid=1405052111"
)
ATTENDANCE_NAME_MAP = {
    "Fodor András": "FODOR ANDRÁS",
    "Szalay András": "SZALAY ANDRÁS",
    "Lénárt Zoli": "LÉNÁRT ZOLTÁN",
    "Dudás Gergő": "DUDÁS GERGŐ",
    "Bartus Gergely": "BARTUS GERGELY",
    "Tóth Szabi": "TÓTH SZABOLCS ÁKOS",
    "Szakács Áron": "SZAKÁCS ÁRON LÁSZLÓ",
    "Bencze Máté": "BENCZE MÁTÉ",
    "Bernacchini Dániel": "BERNACCHINI DÁNIEL",
    "Kovács Kristóf": "KOVÁCS KRISTÓF",
    "Somogyi Gyuri": "SOMOGYI GYÖRGY",
    "Kadocsa Marci": "KADOCSA MÁRTON",
    "Matskási István": "MATSKÁSI ISTVÁN",
    "Essősy Matyi": "DR. ESSŐSY MÁTYÁS MIKLÓS",
    "Osama Alfaraj": "ALFARAG OSAMA FARAJ",
    "Horváth Márton": "HORVÁTH MÁRTON",
    "Földes Dániel": "FÖLDES DÁNIEL GÁBOR",
    "Virág Barnabás": "VIRÁG BARNABÁS",
    "Pozsik Dániel": "POZSIK DÁNIEL",
}

ATTENDANCE_COACH = "POZSIK DÁNIEL"

def fetch_training_attendance():
    """Fetch training attendance from Google Sheets CSV. Returns {DB_NAME: 'X/Y', ...}."""
    req = urllib.request.Request(ATTENDANCE_SHEET_URL, headers={"User-Agent": MKOSZ_USER_AGENT})
    try:
        raw = urllib.request.urlopen(req, timeout=15).read().decode("utf-8")
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
        print(f"  ⚠ Edzéslátogatás fetch hiba: {e}")
        return {}

    result = {}
    reader = csv.reader(io.StringIO(raw))
    for i, row in enumerate(reader):
        if i < 2 or len(row) < 5:
            continue
        name = row[2].strip()
        ratio = row[4].strip()
        if not name or not ratio or "/" not in ratio:
            continue
        db_name = ATTENDANCE_NAME_MAP.get(name)
        if db_name:
            result[db_name] = ratio
    return result

# ---- HUNGARIAN CALENDAR CONSTANTS ----
MONTH_NAMES_HU = {
    1: "JANUÁR", 2: "FEBRUÁR", 3: "MÁRCIUS", 4: "ÁPRILIS",
    5: "MÁJUS", 6: "JÚNIUS", 7: "JÚLIUS", 8: "AUGUSZTUS",
    9: "SZEPTEMBER", 10: "OKTÓBER", 11: "NOVEMBER", 12: "DECEMBER",
}
DAY_NAMES_HU = ["HÉT", "KED", "SZE", "CSÜ", "PÉN", "SZO", "VAS"]

CALENDAR_SHORT = {
    "SUNSHINE-NYÍKSE": "NYÍKSE",
    "ÚJPEST-MT": "Újpest",
    "BLF SE": "BLF",
    "SZERENCS VSE": "Szerencs",
    "BKG-PRIMA AKADÉMIA DEBRECEN": "Debrecen",
    "BUDAPESTI BIKÁK": "Bikák",
    "BKG-VERESEGYHÁZ": "V.egyház",
    "FKE SAS": "FKE Sas",
    "KÖZGÁZ SC ÉS DSK/B": "Közgáz B",
    "KÖZGÁZ SC ÉS DSK/A": "Közgáz A",
    "VASAS AKADÉMIA BUDAPEST": "Vasas",
    "EGER KOSÁRLABDA CLUB": "Eger KC",
    "VMG DSE": "VMG DSE",
    # Női A - Cziffra Mihály bajnokság
    "BEAC SENIOR": "BEAC Sr",
    "BEAC BICS": "BEAC Bics",
    "BEAC BLSE": "BEAC BLSE",
    "BEAC BUDAFOK": "Budafok",
    "BEAC MUFF": "BEAC Muff",
    "BKG VERESEGYHÁZ": "V.egyház",
    "JÓZSEFVÁROSI KC": "JKC",
    "KÉK RÓKÁK": "Kék Rókák",
    "KÜLKERESKEDELMI SC": "Külker",
    "PARTHUS SE": "Parthus",
    "PILIS BASKET": "Pilis",
    "RADOBASKET-CSEPEL": "Radobask.",
    "REGI WALDORF U23": "Waldorf",
    "SZPA - HSE": "SZPA-HSE",
    "TÖREKVÉS SE": "Törekvés",
    "VIHAROS SZENYÓRÁK": "Viharos",
    "EZÜST RÓKÁK": "Ezüst R.",
    "KÖZGÁZ": "Közgáz",
    # Regionális Kiemelt Férfi - Cziffra Mihály bajnokság
    "SZENTENDREI KSE": "Szt.endre",
    "MAFC KARDINÁLIS": "MAFC Kard.",
    "VASHÓDOK": "VasHódok",
    "MONOR SE": "Monor",
    "E5VÖS OKAPIK": "E5vös",
    "ZUGLÓI SASOK": "Zugl. Sasok",
    "CSEPEL TC": "Csepel",
    "MAFC MARTOS": "MAFC Mart.",
    "GOLDENHUSZ": "Goldenhusz",
    "LUDOVIKA SE": "Ludovika",
    "QPAC": "Qpac",
    "KÖZGÁZ LEFTOVERZ": "Leftoverz",
    # MEFOB bajnokságok (Leány + Fiú egyetemi Nyugat)
    "ELTE BEAC": "ELTE BEAC",
    "UNI Győr SZESE": "UNI Győr",
    "SzOESE": "SzOESE",
    "PTE-PEAC": "PTE-PEAC",
    "BME-MAFC": "BME-MAFC",
    "Közgáz SC és DSK": "Közgáz",
    # Fiú egyetemi Nyugat extra ellenfelek
    "Szombathelyi Egyetemi Sportegyesület": "Sz.hely",
    "SMAFC 1860 Soproni Egyetem": "SMAFC",
    "University of Pannonia Veszprém": "Pannonia",
    "Mosonmagyaróvár UNI-Győr": "M.óvár",
    "VESC": "VESC",
    "TFSE": "TFSE",
    "Ludovika Sportegyesület": "Ludovika",
}


def calendar_short_name(name):
    """Ultra-short opponent name for calendar cells."""
    n = name.strip()
    for k, v in CALENDAR_SHORT.items():
        if k in n.upper():
            return v
    parts = n.split()
    return parts[0][:10] if parts else n[:10]


def slugify(name):
    s = name.lower().strip()
    for src, dst in [("á","a"),("é","e"),("í","i"),("ó","o"),("ö","o"),("ő","o"),
                     ("ú","u"),("ü","u"),("ű","u")]:
        s = s.replace(src, dst)
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def get_connection():
    return sqlite3.connect(DB_PATH)


def _team_like(conn, cfg):
    """Determine which LIKE pattern to use. If broad pattern matches exactly
    one team in the competition, use it (simpler queries). Otherwise use specific."""
    broad = cfg["team_pattern_broad"]
    prefix = cfg["comp_prefix"]
    rows = conn.execute("""
        SELECT DISTINCT team_a FROM matches WHERE match_id LIKE ? AND team_a LIKE ?
        UNION
        SELECT DISTINCT team_b FROM matches WHERE match_id LIKE ? AND team_b LIKE ?
    """, (prefix, broad, prefix, broad)).fetchall()
    if len(rows) == 1:
        return broad
    return cfg["team_pattern"]


def get_roster(conn, cfg, tp):
    return conn.execute("""
        WITH kg AS (
            SELECT m.match_id,
                   CASE WHEN m.team_a LIKE ? THEN 'A' ELSE 'B' END as kg_team
            FROM matches m WHERE m.match_id LIKE ? AND (m.team_a LIKE ? OR m.team_b LIKE ?)
        )
        SELECT pgs.license_number, pgs.name, pgs.jersey_number,
               COUNT(*) as games,
               SUM(pgs.points) as total_pts,
               ROUND(1.0*SUM(pgs.points)/COUNT(*),1) as ppg,
               SUM(pgs.fg2_made) as fg2, SUM(pgs.fg3_made) as fg3,
               SUM(pgs.ft_made) as ft_made, SUM(pgs.ft_attempted) as ft_att,
               SUM(pgs.personal_fouls) as pf,
               MAX(pgs.points) as max_pts,
               SUM(pgs.starter) as starts
        FROM player_game_stats pgs
        JOIN kg ON pgs.match_id = kg.match_id AND pgs.team = kg.kg_team
        GROUP BY pgs.license_number
        ORDER BY total_pts DESC
    """, (tp, cfg["comp_prefix"], tp, tp)).fetchall()


def get_game_log(conn, cfg, tp, license_number):
    return conn.execute("""
        WITH kg AS (
            SELECT m.match_id, m.match_date,
                   CASE WHEN m.team_a LIKE ? THEN 'A' ELSE 'B' END as kg_team,
                   CASE WHEN m.team_a LIKE ? THEN 'H' ELSE 'V' END as hv,
                   CASE WHEN m.team_a LIKE ? THEN m.team_b ELSE m.team_a END as opponent,
                   CASE WHEN m.team_a LIKE ? THEN m.score_a ELSE m.score_b END as kg_score,
                   CASE WHEN m.team_a LIKE ? THEN m.score_b ELSE m.score_a END as opp_score
            FROM matches m WHERE m.match_id LIKE ? AND (m.team_a LIKE ? OR m.team_b LIKE ?)
        )
        SELECT kg.match_id, kg.match_date, kg.hv, kg.opponent, kg.kg_score, kg.opp_score,
               pgs.points, pgs.fg2_made, pgs.fg3_made, pgs.ft_made, pgs.ft_attempted,
               pgs.personal_fouls, pgs.starter
        FROM kg
        LEFT JOIN player_game_stats pgs
            ON pgs.match_id = kg.match_id AND pgs.license_number = ?
            AND pgs.team = kg.kg_team
        ORDER BY kg.match_date
    """, (tp, tp, tp, tp, tp, cfg["comp_prefix"], tp, tp, license_number)).fetchall()


def get_quarter_stats(conn, cfg, tp, license_number):
    return conn.execute("""
        WITH kg AS (
            SELECT m.match_id,
                   CASE WHEN m.team_a LIKE ? THEN 'A' ELSE 'B' END as kg_team
            FROM matches m WHERE m.match_id LIKE ? AND (m.team_a LIKE ? OR m.team_b LIKE ?)
        )
        SELECT se.quarter,
               SUM(CASE WHEN se.made=1 THEN se.points ELSE 0 END) as pts,
               SUM(CASE WHEN se.shot_type='3FG' AND se.made=1 THEN 1 ELSE 0 END) as threes,
               SUM(CASE WHEN se.shot_type='2FG' AND se.made=1 THEN 1 ELSE 0 END) as twos,
               SUM(CASE WHEN se.shot_type='FT' AND se.made=1 THEN 1 ELSE 0 END) as fts
        FROM scoring_events se
        JOIN kg ON se.match_id = kg.match_id AND se.team = kg.kg_team
        WHERE se.license_number = ?
        GROUP BY se.quarter ORDER BY se.quarter
    """, (tp, cfg["comp_prefix"], tp, tp, license_number)).fetchall()


def get_opponent_ppg(conn, cfg, tp, license_number):
    return conn.execute("""
        WITH kg AS (
            SELECT m.match_id,
                   CASE WHEN m.team_a LIKE ? THEN 'A' ELSE 'B' END as kg_team,
                   CASE WHEN m.team_a LIKE ? THEN m.team_b ELSE m.team_a END as opponent
            FROM matches m WHERE m.match_id LIKE ? AND (m.team_a LIKE ? OR m.team_b LIKE ?)
        )
        SELECT kg.opponent,
               ROUND(1.0*SUM(pgs.points)/COUNT(*),1) as ppg,
               COUNT(*) as games,
               SUM(pgs.points) as total
        FROM player_game_stats pgs
        JOIN kg ON pgs.match_id = kg.match_id AND pgs.team = kg.kg_team
        WHERE pgs.license_number = ?
        GROUP BY kg.opponent
        ORDER BY ppg DESC
    """, (tp, tp, cfg["comp_prefix"], tp, tp, license_number)).fetchall()


def get_tech_unsport(conn, cfg, tp, license_number):
    rows = conn.execute("""
        WITH kg AS (
            SELECT m.match_id,
                   CASE WHEN m.team_a LIKE ? THEN 'A' ELSE 'B' END as kg_team
            FROM matches m WHERE m.match_id LIKE ? AND (m.team_a LIKE ? OR m.team_b LIKE ?)
        )
        SELECT
            SUM(CASE WHEN pf.foul_category='T' THEN 1 ELSE 0 END) as tech,
            SUM(CASE WHEN pf.foul_category='U' THEN 1 ELSE 0 END) as unsport
        FROM personal_fouls pf
        JOIN kg ON pf.match_id = kg.match_id AND pf.team = kg.kg_team
        JOIN players p ON p.match_id = pf.match_id AND p.team = pf.team
            AND p.jersey_number = pf.jersey_number
        WHERE p.license_number = ? AND pf.foul_category IN ('T','U')
    """, (tp, cfg["comp_prefix"], tp, tp, license_number)).fetchone()
    return (rows[0] or 0, rows[1] or 0)


# ---- PBP DATA SOURCE FUNCTIONS (for MEFOB teams) ----

def _pbp_connection():
    """Open PBP database connection."""
    conn = sqlite3.connect(PBP_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _pbp_match_filter(cfg):
    """Return match_id LIKE pattern for PBP comp_code filtering."""
    return cfg["pbp_comp_code"] + "%"


def get_roster_pbp(conn, cfg, tp):
    """PBP equivalent of get_roster(). Returns same tuple format."""
    cc = _pbp_match_filter(cfg)
    return conn.execute("""
        WITH kg AS (
            SELECT m.match_id,
                   CASE WHEN m.team_a LIKE ? THEN 'A' ELSE 'B' END as kg_team
            FROM matches m WHERE m.match_id LIKE ? AND (m.team_a LIKE ? OR m.team_b LIKE ?)
              AND m.score_a + m.score_b > 0
        ),
        per_game AS (
            SELECT e.match_id, e.player_name,
                   SUM(CASE WHEN e.is_scoring=1 THEN e.points ELSE 0 END) as pts,
                   SUM(CASE WHEN e.event_type IN ('CLOSE_MADE','MID_MADE','DUNK_MADE') THEN 1 ELSE 0 END) as fg2,
                   SUM(CASE WHEN e.event_type='THREE_MADE' THEN 1 ELSE 0 END) as fg3,
                   SUM(CASE WHEN e.event_type='FT_MADE' THEN 1 ELSE 0 END) as ftm,
                   SUM(CASE WHEN e.event_type IN ('FT_MADE','FT_MISS') THEN 1 ELSE 0 END) as fta,
                   SUM(CASE WHEN e.event_type='FOUL' THEN 1 ELSE 0 END) as pf
            FROM events e JOIN kg ON e.match_id=kg.match_id AND e.team=kg.kg_team
            WHERE e.player_name IS NOT NULL
            GROUP BY e.match_id, e.player_name
        )
        SELECT pg.player_name as lic, pg.player_name as name, '' as jersey,
               COUNT(*) as games, SUM(pg.pts) as total_pts,
               ROUND(1.0*SUM(pg.pts)/COUNT(*),1) as ppg,
               SUM(pg.fg2) as fg2, SUM(pg.fg3) as fg3,
               SUM(pg.ftm) as ft_made, SUM(pg.fta) as ft_att,
               SUM(pg.pf) as pf, MAX(pg.pts) as max_pts,
               COALESCE((SELECT SUM(ps.is_starter) FROM player_stats ps
                         JOIN kg k2 ON ps.match_id=k2.match_id AND ps.team=k2.kg_team
                         WHERE ps.player_name=pg.player_name), 0) as starts
        FROM per_game pg
        GROUP BY pg.player_name
        ORDER BY total_pts DESC
    """, (tp, cc, tp, tp)).fetchall()


def get_game_log_pbp(conn, cfg, tp, player_name):
    """PBP equivalent of get_game_log(). Returns same tuple format."""
    cc = _pbp_match_filter(cfg)
    return conn.execute("""
        WITH kg AS (
            SELECT m.match_id, m.match_date,
                   CASE WHEN m.team_a LIKE ? THEN 'A' ELSE 'B' END as kg_team,
                   CASE WHEN m.team_a LIKE ? THEN 'H' ELSE 'V' END as hv,
                   CASE WHEN m.team_a LIKE ? THEN m.team_b ELSE m.team_a END as opponent,
                   CASE WHEN m.team_a LIKE ? THEN m.score_a ELSE m.score_b END as kg_score,
                   CASE WHEN m.team_a LIKE ? THEN m.score_b ELSE m.score_a END as opp_score
            FROM matches m WHERE m.match_id LIKE ? AND (m.team_a LIKE ? OR m.team_b LIKE ?)
              AND m.score_a + m.score_b > 0
        ),
        player_events AS (
            SELECT e.match_id,
                   SUM(CASE WHEN e.is_scoring=1 THEN e.points ELSE 0 END) as pts,
                   SUM(CASE WHEN e.event_type IN ('CLOSE_MADE','MID_MADE','DUNK_MADE') THEN 1 ELSE 0 END) as fg2,
                   SUM(CASE WHEN e.event_type='THREE_MADE' THEN 1 ELSE 0 END) as fg3,
                   SUM(CASE WHEN e.event_type='FT_MADE' THEN 1 ELSE 0 END) as ftm,
                   SUM(CASE WHEN e.event_type IN ('FT_MADE','FT_MISS') THEN 1 ELSE 0 END) as fta,
                   SUM(CASE WHEN e.event_type='FOUL' THEN 1 ELSE 0 END) as pf
            FROM events e JOIN kg ON e.match_id=kg.match_id AND e.team=kg.kg_team
            WHERE e.player_name = ?
            GROUP BY e.match_id
        )
        SELECT kg.match_id, kg.match_date, kg.hv, kg.opponent, kg.kg_score, kg.opp_score,
               pe.pts, pe.fg2, pe.fg3, pe.ftm, pe.fta, pe.pf,
               COALESCE(ps.is_starter, 0) as starter
        FROM kg
        LEFT JOIN player_events pe ON pe.match_id = kg.match_id
        LEFT JOIN player_stats ps ON ps.match_id = kg.match_id AND ps.player_name = ?
            AND ps.team = kg.kg_team
        ORDER BY kg.match_date
    """, (tp, tp, tp, tp, tp, cc, tp, tp, player_name, player_name)).fetchall()


def get_quarter_stats_pbp(conn, cfg, tp, player_name):
    """PBP equivalent of get_quarter_stats(). Returns same tuple format."""
    cc = _pbp_match_filter(cfg)
    return conn.execute("""
        WITH kg AS (
            SELECT m.match_id,
                   CASE WHEN m.team_a LIKE ? THEN 'A' ELSE 'B' END as kg_team
            FROM matches m WHERE m.match_id LIKE ? AND (m.team_a LIKE ? OR m.team_b LIKE ?)
              AND m.score_a + m.score_b > 0
        )
        SELECT e.quarter,
               SUM(CASE WHEN e.is_scoring=1 THEN e.points ELSE 0 END) as pts,
               SUM(CASE WHEN e.event_type='THREE_MADE' THEN 1 ELSE 0 END) as threes,
               SUM(CASE WHEN e.event_type IN ('CLOSE_MADE','MID_MADE','DUNK_MADE') THEN 1 ELSE 0 END) as twos,
               SUM(CASE WHEN e.event_type='FT_MADE' THEN 1 ELSE 0 END) as fts
        FROM events e
        JOIN kg ON e.match_id = kg.match_id AND e.team = kg.kg_team
        WHERE e.player_name = ?
        GROUP BY e.quarter ORDER BY e.quarter
    """, (tp, cc, tp, tp, player_name)).fetchall()


def get_opponent_ppg_pbp(conn, cfg, tp, player_name):
    """PBP equivalent of get_opponent_ppg(). Returns same tuple format."""
    cc = _pbp_match_filter(cfg)
    return conn.execute("""
        WITH kg AS (
            SELECT m.match_id,
                   CASE WHEN m.team_a LIKE ? THEN 'A' ELSE 'B' END as kg_team,
                   CASE WHEN m.team_a LIKE ? THEN m.team_b ELSE m.team_a END as opponent
            FROM matches m WHERE m.match_id LIKE ? AND (m.team_a LIKE ? OR m.team_b LIKE ?)
              AND m.score_a + m.score_b > 0
        ),
        per_game AS (
            SELECT kg.opponent, e.match_id,
                   SUM(CASE WHEN e.is_scoring=1 THEN e.points ELSE 0 END) as pts
            FROM events e JOIN kg ON e.match_id=kg.match_id AND e.team=kg.kg_team
            WHERE e.player_name = ?
            GROUP BY e.match_id
        )
        SELECT opponent,
               ROUND(1.0*SUM(pts)/COUNT(*),1) as ppg,
               COUNT(*) as games,
               SUM(pts) as total
        FROM per_game
        GROUP BY opponent
        ORDER BY ppg DESC
    """, (tp, tp, cc, tp, tp, player_name)).fetchall()


def get_tech_unsport_pbp(conn, cfg, tp, player_name):
    """PBP has no foul category distinction. Returns (0, 0)."""
    return (0, 0)


def get_team_stats_pbp(conn, cfg, tp, hv_filter=None):
    """PBP equivalent of get_team_stats(). Returns same dict format."""
    cc = _pbp_match_filter(cfg)
    d = {}

    # Build match filter
    if hv_filter == 'H':
        _mf = "m.team_a LIKE ?"
        _mp = (tp,)
    elif hv_filter == 'V':
        _mf = "m.team_b LIKE ?"
        _mp = (tp,)
    else:
        _mf = "(m.team_a LIKE ? OR m.team_b LIKE ?)"
        _mp = (tp, tp)

    # Basic record
    r = conn.execute(f"""
        WITH kg AS (
            SELECT m.match_id, m.match_date,
                   CASE WHEN m.team_a LIKE ? THEN 'H' ELSE 'V' END as hv,
                   CASE WHEN m.team_a LIKE ? THEN m.team_b ELSE m.team_a END as opp,
                   CASE WHEN m.team_a LIKE ? THEN m.score_a ELSE m.score_b END as kg,
                   CASE WHEN m.team_a LIKE ? THEN m.score_b ELSE m.score_a END as op
            FROM matches m WHERE m.match_id LIKE ? AND {_mf}
              AND m.score_a + m.score_b > 0
        )
        SELECT COUNT(*), SUM(CASE WHEN kg>op THEN 1 ELSE 0 END),
               SUM(CASE WHEN kg<op THEN 1 ELSE 0 END),
               SUM(kg), SUM(op),
               ROUND(1.0*SUM(kg)/NULLIF(COUNT(*),0),1), ROUND(1.0*SUM(op)/NULLIF(COUNT(*),0),1),
               MAX(kg), MIN(kg), MAX(op), MIN(op),
               MAX(kg-op), MIN(kg-op),
               SUM(CASE WHEN hv='H' AND kg>op THEN 1 ELSE 0 END),
               SUM(CASE WHEN hv='H' THEN 1 ELSE 0 END),
               SUM(CASE WHEN hv='V' AND kg>op THEN 1 ELSE 0 END),
               SUM(CASE WHEN hv='V' THEN 1 ELSE 0 END)
        FROM kg
    """, (tp, tp, tp, tp, cc, *_mp)).fetchone()
    d["games"], d["wins"], d["losses"] = r[0], r[1], r[2]
    d["scored"], d["allowed"] = r[3], r[4]
    d["ppg"], d["opp_ppg"] = r[5], r[6]
    d["best_score"], d["worst_score"] = r[7], r[8]
    d["most_allowed"], d["least_allowed"] = r[9], r[10]
    d["biggest_win"], d["biggest_loss"] = r[11], r[12]
    d["home_w"], d["home_g"] = r[13], r[14]
    d["away_w"], d["away_g"] = r[15], r[16]

    # Game log
    d["game_log"] = conn.execute(f"""
        WITH kg AS (
            SELECT m.match_id, m.match_date,
                   CASE WHEN m.team_a LIKE ? THEN 'H' ELSE 'V' END as hv,
                   CASE WHEN m.team_a LIKE ? THEN m.team_b ELSE m.team_a END as opp,
                   CASE WHEN m.team_a LIKE ? THEN m.score_a ELSE m.score_b END as kg,
                   CASE WHEN m.team_a LIKE ? THEN m.score_b ELSE m.score_a END as op
            FROM matches m WHERE m.match_id LIKE ? AND {_mf}
              AND m.score_a + m.score_b > 0
        )
        SELECT match_date, hv, opp, kg, op FROM kg ORDER BY match_date
    """, (tp, tp, tp, tp, cc, *_mp)).fetchall()

    # Quarter averages — PBP stores quarter_scores as JSON in matches table
    matches_qs = conn.execute(f"""
        SELECT m.quarter_scores,
               CASE WHEN m.team_a LIKE ? THEN 'A' ELSE 'B' END as t
        FROM matches m WHERE m.match_id LIKE ? AND {_mf}
          AND m.score_a + m.score_b > 0
    """, (tp, cc, *_mp)).fetchall()

    q_data = {str(i): {"kg": [], "op": []} for i in range(1, 5)}
    for row in matches_qs:
        qs_json = row[0]
        team_side = row[1]
        if not qs_json:
            continue
        try:
            quarters = json.loads(qs_json)
        except (json.JSONDecodeError, TypeError):
            continue
        for i, q in enumerate(quarters[:4], 1):
            if team_side == 'A':
                q_data[str(i)]["kg"].append(q[0])
                q_data[str(i)]["op"].append(q[1])
            else:
                q_data[str(i)]["kg"].append(q[1])
                q_data[str(i)]["op"].append(q[0])

    d["quarters"] = []
    for i in range(1, 5):
        qi = str(i)
        kg_vals = q_data[qi]["kg"]
        op_vals = q_data[qi]["op"]
        n = len(kg_vals) or 1
        kg_avg = round(sum(kg_vals) / n, 1) if kg_vals else 0
        op_avg = round(sum(op_vals) / n, 1) if op_vals else 0
        q_won = sum(1 for k, o in zip(kg_vals, op_vals) if k > o)
        q_lost = sum(1 for k, o in zip(kg_vals, op_vals) if k < o)
        d["quarters"].append((qi, kg_avg, op_avg, q_won, q_lost))

    # Scenario analysis — from quarter_scores JSON
    scenarios = {"HT_LEAD": [0, 0], "HT_TRAIL": [0, 0], "3Q_LEAD": [0, 0], "3Q_TRAIL": [0, 0]}
    match_finals = conn.execute(f"""
        SELECT m.quarter_scores,
               CASE WHEN m.team_a LIKE ? THEN 'A' ELSE 'B' END as t,
               CASE WHEN m.team_a LIKE ? THEN m.score_a ELSE m.score_b END as kg_final,
               CASE WHEN m.team_a LIKE ? THEN m.score_b ELSE m.score_a END as opp_final
        FROM matches m WHERE m.match_id LIKE ? AND {_mf}
          AND m.score_a + m.score_b > 0
    """, (tp, tp, tp, cc, *_mp)).fetchall()

    for row in match_finals:
        qs_json, team_side, kg_final, opp_final = row
        if not qs_json:
            continue
        try:
            quarters = json.loads(qs_json)
        except (json.JSONDecodeError, TypeError):
            continue
        if len(quarters) < 3:
            continue
        # Halftime
        if team_side == 'A':
            kg_half = sum(q[0] for q in quarters[:2])
            opp_half = sum(q[1] for q in quarters[:2])
            kg_3q = sum(q[0] for q in quarters[:3])
            opp_3q = sum(q[1] for q in quarters[:3])
        else:
            kg_half = sum(q[1] for q in quarters[:2])
            opp_half = sum(q[0] for q in quarters[:2])
            kg_3q = sum(q[1] for q in quarters[:3])
            opp_3q = sum(q[0] for q in quarters[:3])
        win = kg_final > opp_final
        if kg_half > opp_half:
            scenarios["HT_LEAD"][0] += 1
            if win: scenarios["HT_LEAD"][1] += 1
        elif kg_half < opp_half:
            scenarios["HT_TRAIL"][0] += 1
            if win: scenarios["HT_TRAIL"][1] += 1
        if kg_3q > opp_3q:
            scenarios["3Q_LEAD"][0] += 1
            if win: scenarios["3Q_LEAD"][1] += 1
        elif kg_3q < opp_3q:
            scenarios["3Q_TRAIL"][0] += 1
            if win: scenarios["3Q_TRAIL"][1] += 1

    d["scenarios"] = [(k, v[0], v[1]) for k, v in scenarios.items()]

    # Scoring runs — from PBP events
    for label, is_team_val in [("runs_for", 1), ("runs_against", 0)]:
        opp_val = 1 - is_team_val
        rows = conn.execute(f"""
            WITH kg AS (
                SELECT m.match_id, m.match_date,
                       CASE WHEN m.team_a LIKE ? THEN 'A' ELSE 'B' END as t,
                       CASE WHEN m.team_a LIKE ? THEN m.team_b ELSE m.team_a END as opp
                FROM matches m WHERE m.match_id LIKE ? AND {_mf}
                  AND m.score_a + m.score_b > 0
            ),
            made AS (
                SELECT e.match_id, e.event_seq, e.points, e.quarter,
                       kg.match_date, kg.opp,
                       CASE WHEN e.team = kg.t THEN 1 ELSE 0 END as is_team
                FROM events e JOIN kg ON e.match_id=kg.match_id
                WHERE e.is_scoring=1 AND e.points > 0
            ),
            with_rid AS (
                SELECT *,
                       SUM(CASE WHEN is_team={opp_val} THEN 1 ELSE 0 END) OVER (
                           PARTITION BY match_id ORDER BY event_seq) as rid
                FROM made
            )
            SELECT match_date, opp, MIN(quarter) as sq, MAX(quarter) as eq,
                   SUM(points) as run_pts, COUNT(*) as baskets
            FROM with_rid WHERE is_team={is_team_val}
            GROUP BY match_id, rid
            ORDER BY run_pts DESC LIMIT 5
        """, (tp, tp, cc, *_mp)).fetchall()
        d[label] = rows

    # Team shooting totals — from events
    r = conn.execute(f"""
        WITH kg AS (
            SELECT m.match_id,
                   CASE WHEN m.team_a LIKE ? THEN 'A' ELSE 'B' END as t
            FROM matches m WHERE m.match_id LIKE ? AND {_mf}
              AND m.score_a + m.score_b > 0
        )
        SELECT SUM(CASE WHEN e.event_type='THREE_MADE' THEN 1 ELSE 0 END) as fg3,
               SUM(CASE WHEN e.event_type IN ('CLOSE_MADE','MID_MADE','DUNK_MADE') THEN 1 ELSE 0 END) as fg2,
               SUM(CASE WHEN e.event_type='FT_MADE' THEN 1 ELSE 0 END) as ftm,
               SUM(CASE WHEN e.event_type IN ('FT_MADE','FT_MISS') THEN 1 ELSE 0 END) as fta
        FROM events e JOIN kg ON e.match_id=kg.match_id AND e.team=kg.t
    """, (tp, cc, *_mp)).fetchone()
    d["fg3"], d["fg2"], d["ftm"], d["fta"] = r

    # Top scorers
    d["top_scorers"] = conn.execute(f"""
        WITH kg AS (
            SELECT m.match_id,
                   CASE WHEN m.team_a LIKE ? THEN 'A' ELSE 'B' END as t
            FROM matches m WHERE m.match_id LIKE ? AND {_mf}
              AND m.score_a + m.score_b > 0
        ),
        per_game AS (
            SELECT e.player_name, e.match_id,
                   SUM(CASE WHEN e.is_scoring=1 THEN e.points ELSE 0 END) as pts
            FROM events e JOIN kg ON e.match_id=kg.match_id AND e.team=kg.t
            WHERE e.player_name IS NOT NULL
            GROUP BY e.match_id, e.player_name
        )
        SELECT player_name as name, SUM(pts) as tp,
               ROUND(1.0*SUM(pts)/NULLIF(COUNT(*),0),1) as ppg, COUNT(*) as gp
        FROM per_game
        GROUP BY player_name ORDER BY tp DESC LIMIT 3
    """, (tp, cc, *_mp)).fetchall()

    # Players used count
    d["players_used"] = conn.execute(f"""
        WITH kg AS (
            SELECT m.match_id,
                   CASE WHEN m.team_a LIKE ? THEN 'A' ELSE 'B' END as t
            FROM matches m WHERE m.match_id LIKE ? AND {_mf}
              AND m.score_a + m.score_b > 0
        )
        SELECT COUNT(DISTINCT e.player_name)
        FROM events e JOIN kg ON e.match_id=kg.match_id AND e.team=kg.t
        WHERE e.player_name IS NOT NULL
    """, (tp, cc, *_mp)).fetchone()[0]

    # Closest games
    d["closest"] = conn.execute(f"""
        WITH kg AS (
            SELECT m.match_date,
                   CASE WHEN m.team_a LIKE ? THEN m.team_b ELSE m.team_a END as opp,
                   CASE WHEN m.team_a LIKE ? THEN m.score_a ELSE m.score_b END as kg,
                   CASE WHEN m.team_a LIKE ? THEN m.score_b ELSE m.score_a END as op
            FROM matches m WHERE m.match_id LIKE ? AND {_mf}
              AND m.score_a + m.score_b > 0
        )
        SELECT match_date, opp, kg, op, ABS(kg-op) as diff
        FROM kg ORDER BY diff ASC LIMIT 3
    """, (tp, tp, tp, cc, *_mp)).fetchall()

    return d


def get_calendar_data_db_pbp(conn, cfg, tp):
    """PBP equivalent of get_calendar_data_db(). Returns same dict format."""
    cc = _pbp_match_filter(cfg)
    rows = conn.execute("""
        SELECT m.match_date, m.match_time,
               CASE WHEN m.team_a LIKE ? THEN 'H' ELSE 'A' END as home_away,
               CASE WHEN m.team_a LIKE ? THEN m.team_b ELSE m.team_a END as opponent,
               CASE WHEN m.team_a LIKE ? THEN m.score_a ELSE m.score_b END as our_score,
               CASE WHEN m.team_a LIKE ? THEN m.score_b ELSE m.score_a END as opp_score,
               m.match_id
        FROM matches m
        WHERE m.match_id LIKE ?
          AND (m.team_a LIKE ? OR m.team_b LIKE ?)
          AND m.score_a + m.score_b > 0
        ORDER BY m.match_date
    """, (tp, tp, tp, tp, cc, tp, tp)).fetchall()
    return [{
        "date": r[0], "time": r[1] or "",
        "home_team": cfg["team_name"] if r[2] == 'H' else r[3],
        "away_team": r[3] if r[2] == 'H' else cfg["team_name"],
        "home_score": r[4] if r[2] == 'H' else r[5],
        "away_score": r[5] if r[2] == 'H' else r[4],
        "match_id": r[6], "venue": "", "played": True,
        "is_home": r[2] == 'H',
    } for r in rows] if rows else None


def shorten_opponent(name):
    """Shorten long opponent names for charts."""
    n = name.strip()
    # Known shortenings
    replacements = {
        "BKG-PRIMA AKADÉMIA DEBRECEN": "BKG-Prima Deb.",
        "BKG-VERESEGYHÁZ": "BKG-Veresegyh.",
        "SUNSHINE-NYÍKSE": "Sunshine-NYÍKSE",
        "BUDAPESTI BIKÁK": "Bp. Bikák",
        "KÖZGÁZ SC ÉS DSK/B": "Közgáz B",
        "KÖZGÁZ SC ÉS DSK/A": "Közgáz A",
        "VASAS AKADÉMIA BUDAPEST": "Vasas Akad.",
        "EGER KOSÁRLABDA CLUB": "Eger KC",
    }
    for k, v in replacements.items():
        if k in n.upper():
            return v
    # Title case, max 20 chars
    t = n.title()
    if len(t) > 20:
        t = t[:18] + "."
    return t


def generate_insights(name, games_played, ppg, fg3, ft_made, ft_att, pf_per_game,
                       max_pts, quarter_pts, opp_data, game_log, total_pts, starts):
    strengths = []
    weaknesses = []

    ft_pct = round(100*ft_made/ft_att) if ft_att > 0 else 0

    if ft_pct >= 75 and ft_att >= 10:
        strengths.append(f'Megbízható büntetődobó ({ft_pct}%)')
    if fg3 >= 15:
        strengths.append(f'Hárompontos fenyegetés: {fg3} bedobott tripla')
    if pf_per_game <= 1.5:
        strengths.append(f'Fegyelmezett: {pf_per_game} fault/meccs')
    if ppg >= 12:
        strengths.append(f'Meghatározó pontszerző ({ppg} PPG)')
    if starts >= games_played * 0.7 and games_played >= 5:
        strengths.append(f'Stabil kezdő ({starts}/{games_played} meccs)')
    if max_pts >= 20:
        strengths.append(f'Nagy meccsekre képes (csúcs: {max_pts} pont)')

    played = [g for g in game_log if g[6] is not None]
    if len(played) >= 3:
        last3 = played[-3:]
        last3_ppg = round(sum(g[6] for g in last3) / 3, 1)
        if last3_ppg > ppg * 1.3:
            strengths.append(f'Formajavulás: utolsó 3 meccs {last3_ppg} PPG')
        elif last3_ppg < ppg * 0.6 and ppg > 3:
            weaknesses.append(f'Formaesés: utolsó 3 meccs {last3_ppg} PPG')

    pts_list = [g[6] for g in game_log if g[6] is not None]
    if len(pts_list) >= 5:
        mn, mx = min(pts_list), max(pts_list)
        if mx - mn >= 15:
            weaknesses.append(f'Inkonzisztens: {mn}-{mx} pont szórás')

    if ft_pct < 60 and ft_att >= 8:
        weaknesses.append(f'Gyenge büntető: {ft_pct}% ({ft_made}/{ft_att})')
    if pf_per_game >= 3:
        weaknesses.append(f'Faultgondok: {pf_per_game} fault/meccs')

    if opp_data:
        worst = opp_data[-1]
        if worst[1] <= ppg * 0.5 and worst[2] >= 2:
            weaknesses.append(f'{shorten_opponent(worst[0])} ellen gyenge: {worst[1]} PPG')

    q_dict = {str(q[0]): q[1] for q in quarter_pts if str(q[0]) in ('1','2','3','4')}
    if q_dict and games_played > 0:
        q_ppg = {k: round(v/games_played, 1) for k, v in q_dict.items()}
        weakest_q = min(q_ppg, key=q_ppg.get)
        strongest_q = max(q_ppg, key=q_ppg.get)
        if q_ppg[weakest_q] < q_ppg[strongest_q] * 0.5 and q_ppg[strongest_q] > 1:
            weaknesses.append(f'Q{weakest_q} a leggyengébb negyed ({q_ppg[weakest_q]} pont/meccs)')

    dnp_count = sum(1 for g in game_log if g[6] is None)
    if dnp_count >= 3:
        weaknesses.append(f'{dnp_count} meccsen nem kapott lehetőséget (DNP)')

    if not strengths:
        strengths.append(f'{games_played} meccsen lépett pályára')
    if not weaknesses:
        weaknesses.append('Kis mintaméret — több meccs szükséges az értékeléshez')

    return strengths[:5], weaknesses[:5]


def generate_html(player_data, game_log, quarter_stats, opp_stats, tech, unsport, cfg, training_att=None):
    lic, name, jersey, games, total_pts, ppg, fg2, fg3, ft_m, ft_a, pf, max_pts, starts = player_data

    ft_pct = round(100*ft_m/ft_a) if ft_a > 0 else 0
    pf_pg = round(pf/games, 1)

    played_games = [g for g in game_log if g[6] is not None]
    total_team_pts = sum(g[4] for g in played_games)
    share_pct = round(100*total_pts/total_team_pts, 1) if total_team_pts > 0 else 0

    pts_3fg = fg3 * 3
    pts_2fg = fg2 * 2
    pts_ft = ft_m

    q_pts = {str(q[0]): q[1] for q in quarter_stats if str(q[0]) in ('1','2','3','4')}
    q_3fg = {str(q[0]): q[2] for q in quarter_stats if str(q[0]) in ('1','2','3','4')}
    q_data = [q_pts.get(str(i), 0) for i in range(1, 5)]
    q_3fg_data = [q_3fg.get(str(i), 0) for i in range(1, 5)]

    opp_labels = [shorten_opponent(o[0]) for o in opp_stats]
    opp_ppg_data = [o[1] for o in opp_stats]

    js_games = []
    for g in game_log:
        match_id, date, hv, opp, kg_score, opp_score, pts, f2, f3, ftm, fta, pfg, starter = g
        win = kg_score > opp_score if kg_score and opp_score else False
        if pts is not None:
            share = round(100*pts/kg_score, 1) if kg_score else 0
            ft_str = f"{ftm}/{fta}" if fta else "0/0"
            js_games.append({
                "date": date[5:].replace("-", "."),
                "opp": shorten_opponent(opp),
                "res": "W" if win else "L",
                "pts": pts, "fg2": f2 or 0, "fg3": f3 or 0,
                "ft": ft_str, "pf": pfg or 0,
                "share": share, "start": bool(starter)
            })
        else:
            js_games.append({
                "date": date[5:].replace("-", "."),
                "opp": shorten_opponent(opp),
                "res": "W" if win else "L",
                "pts": None
            })

    strengths, weaknesses = generate_insights(
        name, games, ppg, fg3, ft_m, ft_a, pf_pg, max_pts,
        quarter_stats, opp_stats, game_log, total_pts, starts
    )

    opp_colors_bg = []
    opp_colors_border = []
    for val in opp_ppg_data:
        if val >= ppg * 1.2:
            opp_colors_bg.append("rgba(0,206,201,0.7)")
            opp_colors_border.append("#00cec9")
        elif val >= ppg * 0.7:
            opp_colors_bg.append("rgba(253,203,110,0.6)")
            opp_colors_border.append("#fdcb6e")
        else:
            opp_colors_bg.append("rgba(225,112,85,0.5)")
            opp_colors_border.append("#e17055")

    max_opp_ppg = max(opp_ppg_data) if opp_ppg_data else 10
    trend_pts = [g["pts"] for g in js_games if g["pts"] is not None]
    trend_max = max(trend_pts) if trend_pts else 1
    shot_max = max(pts_3fg, pts_2fg, pts_ft, 1)
    bar_3fg = round(100 * pts_3fg / shot_max)
    bar_2fg = round(100 * pts_2fg / shot_max)
    bar_ft = round(100 * pts_ft / shot_max) if pts_ft > 0 else 5

    tech_text = ""
    if tech > 0 or unsport > 0:
        parts = []
        if tech > 0: parts.append(f"{tech} technikai")
        if unsport > 0: parts.append(f"{unsport} sportszerűtlen")
        tech_text = f' | {", ".join(parts)} hiba'

    team_display = cfg["team_name"]
    group_display = cfg["group_name"]

    html = f"""<!DOCTYPE html>
<html lang="hu">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{name} — 2025/26 Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"></script>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap');
  :root {{
    --bg: #0a0b0e; --card: #151518; --card-hover: #1e1e24;
    --accent: #C41E3A; --accent2: #00cec9; --accent3: #ff6b6b; --accent4: #fdcb6e;
    --text: #e8e8f0; --text-dim: #8b8da0; --green: #00b894; --red: #e17055;
    --border: rgba(255,255,255,0.06);
  }}
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family:'Inter',-apple-system,sans-serif; background:var(--bg); color:var(--text); min-height:100vh; padding:24px; }}
  .dashboard {{ max-width:1200px; margin:0 auto; }}
  .header {{
    display:flex; align-items:center; gap:28px; padding:32px;
    background:linear-gradient(135deg,#151518 0%,#2a1218 100%);
    border-radius:20px; margin-bottom:20px; border:1px solid var(--border);
    position:relative; overflow:hidden;
  }}
  .header::after {{
    content:''; position:absolute; top:-60%; right:-10%;
    width:400px; height:400px;
    background:radial-gradient(circle,rgba(196,30,58,0.15),transparent 70%);
    pointer-events:none;
  }}
  .header-info {{ z-index:1; }}
  .header-info h1 {{
    font-size:2rem; font-weight:800; letter-spacing:-0.5px;
    background:linear-gradient(135deg,#fff 30%,var(--accent) 100%);
    -webkit-background-clip:text; -webkit-text-fill-color:transparent;
  }}
  .header-info .subtitle {{ font-size:0.95rem; color:var(--text-dim); margin-top:4px; }}
  .header-info .subtitle span {{ color:var(--accent2); font-weight:600; }}
  .header-stats {{ display:flex; gap:20px; margin-left:auto; z-index:1; flex-wrap:wrap; }}
  .header-stat {{
    text-align:center; padding:12px 20px; background:rgba(255,255,255,0.04);
    border-radius:14px; border:1px solid var(--border); min-width:80px;
  }}
  .header-stat .val {{ font-size:1.7rem; font-weight:800; color:#fff; }}
  .header-stat .val.accent {{ color:var(--accent); }}
  .header-stat .val.green {{ color:var(--green); }}
  .header-stat .val.pink {{ color:var(--accent3); }}
  .header-stat .label {{ font-size:0.7rem; color:var(--text-dim); text-transform:uppercase; letter-spacing:1px; margin-top:2px; }}
  .grid {{ display:grid; gap:20px; }}
  .grid-2 {{ grid-template-columns:1fr 1fr; }}
  .grid-4 {{ grid-template-columns:1fr 1fr 1fr 1fr; }}
  .card {{
    background:var(--card); border-radius:16px; padding:24px;
    border:1px solid var(--border); transition:background 0.2s;
  }}
  .card:hover {{ background:var(--card-hover); }}
  .card h3 {{ font-size:0.8rem; text-transform:uppercase; letter-spacing:1.2px; color:var(--text-dim); margin-bottom:16px; font-weight:600; }}
  .mini-stat {{ text-align:center; }}
  .mini-stat .big {{ font-size:2rem; font-weight:800; }}
  .mini-stat .desc {{ font-size:0.75rem; color:var(--text-dim); margin-top:4px; }}
  .game-log-wrap {{ overflow-x:auto; -webkit-overflow-scrolling:touch; }}
  .game-log {{ width:100%; border-collapse:collapse; font-size:0.82rem; }}
  .game-log th {{ text-align:left; font-size:0.7rem; text-transform:uppercase; letter-spacing:0.8px; color:var(--text-dim); padding:8px 10px; border-bottom:1px solid var(--border); font-weight:600; white-space:nowrap; }}
  .game-log td {{ padding:8px 10px; border-bottom:1px solid var(--border); white-space:nowrap; }}
  .game-log tr:last-child td {{ border-bottom:none; }}
  .game-log tr:hover {{ background:rgba(196,30,58,0.06); }}
  .badge {{ display:inline-block; padding:2px 8px; border-radius:6px; font-size:0.7rem; font-weight:700; }}
  .badge.w {{ background:rgba(0,184,148,0.15); color:var(--green); }}
  .badge.l {{ background:rgba(225,112,85,0.15); color:var(--red); }}
  .badge.dnp {{ background:rgba(139,141,160,0.15); color:var(--text-dim); }}
  .bar-cell {{ position:relative; }}
  .bar-bg {{ position:absolute; left:0; top:50%; transform:translateY(-50%); height:22px; border-radius:4px; opacity:0.2; }}
  .bar-val {{ position:relative; z-index:1; font-weight:600; }}
  .chart-wrap {{ position:relative; width:100%; }}
  .chart-wrap.h250 {{ height:250px; }}
  .shot-row {{ display:flex; align-items:center; gap:12px; margin-bottom:12px; }}
  .shot-label {{ font-size:0.8rem; font-weight:600; width:40px; flex-shrink:0; }}
  .shot-bar-outer {{ flex:1; height:28px; background:rgba(255,255,255,0.04); border-radius:8px; overflow:hidden; }}
  .shot-bar-inner {{ height:100%; border-radius:8px; display:flex; align-items:center; padding-left:10px; font-size:0.75rem; font-weight:700; color:#fff; }}
  .shot-pct {{ font-size:0.8rem; font-weight:600; width:45px; text-align:right; flex-shrink:0; }}
  .mb20 {{ margin-bottom:20px; }}
  .back-link {{
    display:inline-block; color:var(--text-dim); text-decoration:none;
    font-size:0.82rem; font-weight:600; margin-bottom:16px; opacity:0.7;
    transition:color 0.2s, opacity 0.2s;
  }}
  .back-link:hover {{ color:var(--accent); opacity:1; }}
  @media (max-width:900px) {{
    .grid-2,.grid-4 {{ grid-template-columns:1fr; }}
    .header {{ flex-direction:column; text-align:center; }}
    .header-stats {{ margin-left:0; justify-content:center; }}
  }}
  @media (max-width:600px) {{
    body {{ padding:10px; }}
    .game-log {{ font-size:0.72rem; }}
    .game-log th {{ padding:6px 6px; font-size:0.62rem; letter-spacing:0.3px; }}
    .game-log td {{ padding:6px 6px; }}
  }}
</style>
</head>
<body>
<div class="dashboard">
  <a href="index.html" class="back-link">&larr; Csapat áttekintő</a>
  <div class="header">
    <div class="header-info">
      <h1>{name}</h1>
      <div class="subtitle">
        <span>#{jersey}</span> &nbsp;|&nbsp; {team_display} &nbsp;|&nbsp; {group_display} &nbsp;|&nbsp; 2025/26 alapszakasz{tech_text}
      </div>
    </div>
    <div class="header-stats">
      <div class="header-stat"><div class="val accent">{ppg}</div><div class="label">PPG</div></div>
      <div class="header-stat"><div class="val green">{games}</div><div class="label">Meccs</div></div>
      <div class="header-stat"><div class="val pink">{fg3}</div><div class="label">3FG</div></div>
      <div class="header-stat"><div class="val" style="color:var(--accent4)">{max_pts}</div><div class="label">Csúcs</div></div>
      {"" if not training_att else (lambda r: f'<div class="header-stat"><div class="val" style="color:var(--accent2)">{training_att} ({round(int(r[0])/int(r[1])*100)}%)</div><div class="label">Edzés</div></div>')(training_att.split('/'))}
    </div>
  </div>
  <div class="grid grid-4 mb20">
    <div class="card mini-stat"><div class="big" style="color:var(--accent)">{total_pts}</div><div class="desc">Összes pont</div></div>
    <div class="card mini-stat"><div class="big" style="color:var(--accent2)">{ft_pct}%</div><div class="desc">FT% ({ft_m}/{ft_a})</div></div>
    <div class="card mini-stat"><div class="big" style="color:var(--accent3)">{pf_pg}</div><div class="desc">Fault / meccs</div></div>
    <div class="card mini-stat"><div class="big" style="color:var(--accent4)">{share_pct}%</div><div class="desc">Csapat pont részesedés</div></div>
  </div>
  <div class="grid grid-2 mb20">
    <div class="card">
      <h3>Pontszerzés meccsenként</h3>
      <div class="chart-wrap h250"><canvas id="scoringTrend"></canvas></div>
    </div>
    <div class="card">
      <h3>Dobásmegoszlás</h3>
      <div style="margin-top:20px;">
        <div class="shot-row">
          <div class="shot-label" style="color:var(--accent)">3FG</div>
          <div class="shot-bar-outer"><div class="shot-bar-inner" style="width:{bar_3fg}%;background:var(--accent);">{fg3} db</div></div>
          <div class="shot-pct" style="color:var(--accent)">{pts_3fg} pt</div>
        </div>
        <div class="shot-row">
          <div class="shot-label" style="color:var(--accent2)">2FG</div>
          <div class="shot-bar-outer"><div class="shot-bar-inner" style="width:{bar_2fg}%;background:var(--accent2);">{fg2} db</div></div>
          <div class="shot-pct" style="color:var(--accent2)">{pts_2fg} pt</div>
        </div>
        <div class="shot-row">
          <div class="shot-label" style="color:var(--accent4)">FT</div>
          <div class="shot-bar-outer"><div class="shot-bar-inner" style="width:{bar_ft}%;background:var(--accent4);">{ft_m}/{ft_a}</div></div>
          <div class="shot-pct" style="color:var(--accent4)">{pts_ft} pt</div>
        </div>
      </div>
      <div style="margin-top:20px;"><div class="chart-wrap" style="height:160px;"><canvas id="shotPie"></canvas></div></div>
    </div>
  </div>
  <div class="grid grid-2 mb20">
    <div class="card">
      <h3>Negyedenkénti teljesítmény</h3>
      <div class="chart-wrap h250"><canvas id="quarterChart"></canvas></div>
    </div>
    <div class="card">
      <h3>Ellenfél elleni átlag</h3>
      <div class="chart-wrap h250"><canvas id="opponentChart"></canvas></div>
    </div>
  </div>
  <div class="card mb20">
    <h3>Meccsenként részletezve</h3>
    <div class="game-log-wrap">
    <table class="game-log">
      <thead><tr><th>Dátum</th><th>Ellenfél</th><th></th><th>Pont</th><th>2FG</th><th>3FG</th><th>FT</th><th>PF</th><th>Csapat%</th></tr></thead>
      <tbody id="gameLogBody"></tbody>
    </table>
    </div>
  </div>
  <div class="card mb20">
    <h3>Elemzői meglátások</h3>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;font-size:0.85rem;line-height:1.7;">
      <div>
        <div style="color:var(--accent);font-weight:700;margin-bottom:6px;">Erősségek</div>
        <ul style="padding-left:18px;color:var(--text-dim);">
          {"".join(f'<li><span style="color:#fff;font-weight:600;">{s}</span></li>' for s in strengths)}
        </ul>
      </div>
      <div>
        <div style="color:var(--accent3);font-weight:700;margin-bottom:6px;">Fejlesztendő területek</div>
        <ul style="padding-left:18px;color:var(--text-dim);">
          {"".join(f'<li><span style="color:#fff;font-weight:600;">{w}</span></li>' for w in weaknesses)}
        </ul>
      </div>
    </div>
  </div>
</div>
<script>
Chart.defaults.color='#8b8da0';
Chart.defaults.borderColor='rgba(255,255,255,0.06)';
Chart.defaults.font.family="'Inter',sans-serif";

const games = {json.dumps(js_games, ensure_ascii=False)};
const maxPts = {max(trend_max, 1)};

const tbody = document.getElementById('gameLogBody');
games.forEach(g => {{
  const tr = document.createElement('tr');
  if (g.pts === null) {{
    tr.innerHTML = '<td>'+g.date+'</td><td>'+g.opp+'</td><td><span class="badge dnp">DNP</span></td><td colspan="6" style="color:var(--text-dim);font-style:italic;font-size:0.78rem;">Nem lépett pályára</td>';
  }} else {{
    const barW = Math.max((g.pts/maxPts)*100, 5);
    const barColor = g.pts >= {max(round(ppg*1.5), 8)} ? 'var(--accent)' : g.pts >= {max(round(ppg*0.8), 3)} ? 'var(--accent2)' : 'var(--text-dim)';
    tr.innerHTML = '<td>'+g.date+'</td><td>'+g.opp+'</td><td><span class="badge '+(g.res==='W'?'w':'l')+'">'+(g.res==='W'?'GY':'V')+'</span></td><td class="bar-cell" style="min-width:80px;"><div class="bar-bg" style="width:'+barW+'%;background:'+barColor+';"></div><span class="bar-val" style="color:'+barColor+';">'+g.pts+'</span></td><td>'+g.fg2+'</td><td style="color:var(--accent);font-weight:600;">'+g.fg3+'</td><td>'+g.ft+'</td><td>'+g.pf+'</td><td style="color:var(--text-dim)">'+g.share+'%</td>';
  }}
  tbody.appendChild(tr);
}});

const played = games.filter(g => g.pts !== null);
new Chart(document.getElementById('scoringTrend').getContext('2d'), {{
  type:'line',
  data: {{
    labels: played.map(g=>g.date),
    datasets: [{{
      label:'Pont', data:played.map(g=>g.pts),
      borderColor:'#C41E3A', backgroundColor:'rgba(196,30,58,0.1)',
      fill:true, tension:0.35,
      pointBackgroundColor:played.map(g=>g.res==='W'?'#00b894':'#e17055'),
      pointBorderColor:played.map(g=>g.res==='W'?'#00b894':'#e17055'),
      pointRadius:6, pointHoverRadius:9, borderWidth:3,
    }}, {{
      label:'Átlag ({ppg})', data:played.map(()=>{ppg}),
      borderColor:'rgba(255,255,255,0.2)', borderDash:[6,4],
      pointRadius:0, borderWidth:1, fill:false,
    }}]
  }},
  options: {{
    responsive:true, maintainAspectRatio:false,
    plugins: {{ legend:{{ display:false }},
      tooltip: {{ callbacks: {{ afterLabel: ctx => {{
        if(ctx.datasetIndex===0){{ const g=played[ctx.dataIndex]; return (g.res==='W'?'Győzelem':'Vereség')+' vs '+g.opp; }}
      }} }} }}
    }},
    scales: {{ y:{{ beginAtZero:true, max:{max(trend_max+5, 15)}, grid:{{color:'rgba(255,255,255,0.04)'}} }}, x:{{ grid:{{display:false}} }} }}
  }}
}});

new Chart(document.getElementById('shotPie').getContext('2d'), {{
  type:'doughnut',
  data: {{
    labels:['3FG ({pts_3fg} pt)','2FG ({pts_2fg} pt)','FT ({pts_ft} pt)'],
    datasets:[{{ data:[{pts_3fg},{pts_2fg},{pts_ft}], backgroundColor:['#C41E3A','#00cec9','#fdcb6e'], borderColor:'#151518', borderWidth:3, hoverOffset:8 }}]
  }},
  options: {{ responsive:true, maintainAspectRatio:false, cutout:'60%',
    plugins:{{ legend:{{ position:'right', labels:{{ padding:12, usePointStyle:true, font:{{size:11}} }} }} }}
  }}
}});

new Chart(document.getElementById('quarterChart').getContext('2d'), {{
  type:'bar',
  data: {{
    labels:['Q1','Q2','Q3','Q4'],
    datasets:[{{
      label:'Összes pont', data:{json.dumps(q_data)},
      backgroundColor:['rgba(196,30,58,0.7)','rgba(196,30,58,0.5)','rgba(196,30,58,0.55)','rgba(196,30,58,0.5)'],
      borderColor:'#C41E3A', borderWidth:2, borderRadius:6,
    }},{{
      label:'3FG bedobva', data:{json.dumps(q_3fg_data)},
      backgroundColor:'rgba(253,121,168,0.5)', borderColor:'#fd79a8', borderWidth:2, borderRadius:6,
    }}]
  }},
  options: {{
    responsive:true, maintainAspectRatio:false,
    plugins: {{ legend:{{ position:'top', labels:{{ usePointStyle:true, font:{{size:11}} }} }} }},
    scales: {{ y:{{ beginAtZero:true, grid:{{color:'rgba(255,255,255,0.04)'}} }}, x:{{ grid:{{display:false}} }} }}
  }}
}});

new Chart(document.getElementById('opponentChart').getContext('2d'), {{
  type:'bar',
  data: {{
    labels:{json.dumps(opp_labels, ensure_ascii=False)},
    datasets:[{{
      label:'PPG', data:{json.dumps(opp_ppg_data)},
      backgroundColor:{json.dumps(opp_colors_bg)},
      borderColor:{json.dumps(opp_colors_border)},
      borderWidth:2, borderRadius:6,
    }}]
  }},
  options: {{
    indexAxis:'y', responsive:true, maintainAspectRatio:false,
    plugins: {{ legend:{{display:false}} }},
    scales: {{ x:{{ beginAtZero:true, max:{max(round(max_opp_ppg)+5, 10)}, grid:{{color:'rgba(255,255,255,0.04)'}} }}, y:{{ grid:{{display:false}} }} }}
  }}
}});
</script>
</body>
</html>"""
    return html


def get_team_stats(conn, cfg, tp, hv_filter=None):
    """Gather all team-level statistics for the team dashboard.
    hv_filter: None=all, 'H'=home only, 'V'=away only.
    """
    cp = cfg["comp_prefix"]
    d = {}

    # Build match filter based on hv_filter
    if hv_filter == 'H':
        _mf = "m.team_a LIKE ?"
        _mp = (tp,)
    elif hv_filter == 'V':
        _mf = "m.team_b LIKE ?"
        _mp = (tp,)
    else:
        _mf = "(m.team_a LIKE ? OR m.team_b LIKE ?)"
        _mp = (tp, tp)

    # Basic record
    r = conn.execute(f"""
        WITH kg AS (
            SELECT m.match_id, m.match_date,
                   CASE WHEN m.team_a LIKE ? THEN 'H' ELSE 'V' END as hv,
                   CASE WHEN m.team_a LIKE ? THEN m.team_b ELSE m.team_a END as opp,
                   CASE WHEN m.team_a LIKE ? THEN m.score_a ELSE m.score_b END as kg,
                   CASE WHEN m.team_a LIKE ? THEN m.score_b ELSE m.score_a END as op
            FROM matches m WHERE m.match_id LIKE ? AND {_mf}
        )
        SELECT COUNT(*), SUM(CASE WHEN kg>op THEN 1 ELSE 0 END),
               SUM(CASE WHEN kg<op THEN 1 ELSE 0 END),
               SUM(kg), SUM(op),
               ROUND(1.0*SUM(kg)/NULLIF(COUNT(*),0),1), ROUND(1.0*SUM(op)/NULLIF(COUNT(*),0),1),
               MAX(kg), MIN(kg), MAX(op), MIN(op),
               MAX(kg-op), MIN(kg-op),
               SUM(CASE WHEN hv='H' AND kg>op THEN 1 ELSE 0 END),
               SUM(CASE WHEN hv='H' THEN 1 ELSE 0 END),
               SUM(CASE WHEN hv='V' AND kg>op THEN 1 ELSE 0 END),
               SUM(CASE WHEN hv='V' THEN 1 ELSE 0 END)
        FROM kg
    """, (tp, tp, tp, tp, cp, *_mp)).fetchone()
    d["games"], d["wins"], d["losses"] = r[0], r[1], r[2]
    d["scored"], d["allowed"] = r[3], r[4]
    d["ppg"], d["opp_ppg"] = r[5], r[6]
    d["best_score"], d["worst_score"] = r[7], r[8]
    d["most_allowed"], d["least_allowed"] = r[9], r[10]
    d["biggest_win"], d["biggest_loss"] = r[11], r[12]
    d["home_w"], d["home_g"] = r[13], r[14]
    d["away_w"], d["away_g"] = r[15], r[16]

    # Game log
    d["game_log"] = conn.execute(f"""
        WITH kg AS (
            SELECT m.match_id, m.match_date,
                   CASE WHEN m.team_a LIKE ? THEN 'H' ELSE 'V' END as hv,
                   CASE WHEN m.team_a LIKE ? THEN m.team_b ELSE m.team_a END as opp,
                   CASE WHEN m.team_a LIKE ? THEN m.score_a ELSE m.score_b END as kg,
                   CASE WHEN m.team_a LIKE ? THEN m.score_b ELSE m.score_a END as op
            FROM matches m WHERE m.match_id LIKE ? AND {_mf}
        )
        SELECT match_date, hv, opp, kg, op FROM kg ORDER BY match_date
    """, (tp, tp, tp, tp, cp, *_mp)).fetchall()

    # Quarter averages
    d["quarters"] = conn.execute(f"""
        WITH kg AS (
            SELECT m.match_id,
                   CASE WHEN m.team_a LIKE ? THEN 'A' ELSE 'B' END as t
            FROM matches m WHERE m.match_id LIKE ? AND {_mf}
        )
        SELECT qs.quarter,
               ROUND(1.0*SUM(CASE WHEN kg.t='A' THEN qs.score_a ELSE qs.score_b END)/NULLIF(COUNT(*),0),1),
               ROUND(1.0*SUM(CASE WHEN kg.t='A' THEN qs.score_b ELSE qs.score_a END)/NULLIF(COUNT(*),0),1),
               SUM(CASE WHEN (CASE WHEN kg.t='A' THEN qs.score_a ELSE qs.score_b END) >
                             (CASE WHEN kg.t='A' THEN qs.score_b ELSE qs.score_a END) THEN 1 ELSE 0 END),
               SUM(CASE WHEN (CASE WHEN kg.t='A' THEN qs.score_a ELSE qs.score_b END) <
                             (CASE WHEN kg.t='A' THEN qs.score_b ELSE qs.score_a END) THEN 1 ELSE 0 END)
        FROM quarter_scores qs JOIN kg ON qs.match_id=kg.match_id
        WHERE qs.quarter IN ('1','2','3','4')
        GROUP BY qs.quarter ORDER BY qs.quarter
    """, (tp, cp, *_mp)).fetchall()

    # Scenario analysis: halftime lead/deficit
    d["scenarios"] = conn.execute(f"""
        WITH kg AS (
            SELECT m.match_id,
                   CASE WHEN m.team_a LIKE ? THEN 'A' ELSE 'B' END as t,
                   CASE WHEN m.team_a LIKE ? THEN m.score_a ELSE m.score_b END as kg_final,
                   CASE WHEN m.team_a LIKE ? THEN m.score_b ELSE m.score_a END as opp_final
            FROM matches m WHERE m.match_id LIKE ? AND {_mf}
        ),
        halves AS (
            SELECT kg.match_id, kg.kg_final, kg.opp_final,
                   SUM(CASE WHEN qs.quarter IN ('1','2') THEN
                       CASE WHEN kg.t='A' THEN qs.score_a ELSE qs.score_b END ELSE 0 END) as kg_half,
                   SUM(CASE WHEN qs.quarter IN ('1','2') THEN
                       CASE WHEN kg.t='A' THEN qs.score_b ELSE qs.score_a END ELSE 0 END) as opp_half,
                   SUM(CASE WHEN qs.quarter IN ('1','2','3') THEN
                       CASE WHEN kg.t='A' THEN qs.score_a ELSE qs.score_b END ELSE 0 END) as kg_3q,
                   SUM(CASE WHEN qs.quarter IN ('1','2','3') THEN
                       CASE WHEN kg.t='A' THEN qs.score_b ELSE qs.score_a END ELSE 0 END) as opp_3q
            FROM kg JOIN quarter_scores qs ON qs.match_id=kg.match_id
            WHERE qs.quarter IN ('1','2','3','4')
            GROUP BY kg.match_id
        )
        SELECT 'HT_LEAD' as scenario,
               SUM(CASE WHEN kg_half>opp_half THEN 1 ELSE 0 END) as cnt,
               SUM(CASE WHEN kg_half>opp_half AND kg_final>opp_final THEN 1 ELSE 0 END) as wins
        FROM halves
        UNION ALL
        SELECT 'HT_TRAIL',
               SUM(CASE WHEN kg_half<opp_half THEN 1 ELSE 0 END),
               SUM(CASE WHEN kg_half<opp_half AND kg_final>opp_final THEN 1 ELSE 0 END)
        FROM halves
        UNION ALL
        SELECT '3Q_LEAD',
               SUM(CASE WHEN kg_3q>opp_3q THEN 1 ELSE 0 END),
               SUM(CASE WHEN kg_3q>opp_3q AND kg_final>opp_final THEN 1 ELSE 0 END)
        FROM halves
        UNION ALL
        SELECT '3Q_TRAIL',
               SUM(CASE WHEN kg_3q<opp_3q THEN 1 ELSE 0 END),
               SUM(CASE WHEN kg_3q<opp_3q AND kg_final>opp_final THEN 1 ELSE 0 END)
        FROM halves
    """, (tp, tp, tp, cp, *_mp)).fetchall()

    # Top 5 scoring runs FOR and AGAINST
    for label, is_team_val in [("runs_for", 1), ("runs_against", 0)]:
        opp_val = 1 - is_team_val
        rows = conn.execute(f"""
            WITH kg AS (
                SELECT m.match_id, m.match_date,
                       CASE WHEN m.team_a LIKE ? THEN 'A' ELSE 'B' END as t,
                       CASE WHEN m.team_a LIKE ? THEN m.team_b ELSE m.team_a END as opp
                FROM matches m WHERE m.match_id LIKE ? AND {_mf}
            ),
            made AS (
                SELECT se.match_id, se.event_seq, se.points, se.quarter,
                       kg.match_date, kg.opp,
                       CASE WHEN se.team = kg.t THEN 1 ELSE 0 END as is_team
                FROM scoring_events se JOIN kg ON se.match_id=kg.match_id WHERE se.made=1
            ),
            with_rid AS (
                SELECT *,
                       SUM(CASE WHEN is_team={opp_val} THEN 1 ELSE 0 END) OVER (
                           PARTITION BY match_id ORDER BY event_seq) as rid
                FROM made
            )
            SELECT match_date, opp, MIN(quarter) as sq, MAX(quarter) as eq,
                   SUM(points) as run_pts, COUNT(*) as baskets
            FROM with_rid WHERE is_team={is_team_val}
            GROUP BY match_id, rid
            ORDER BY run_pts DESC LIMIT 5
        """, (tp, tp, cp, *_mp)).fetchall()
        d[label] = rows

    # Team shooting totals
    r = conn.execute(f"""
        WITH kg AS (
            SELECT m.match_id,
                   CASE WHEN m.team_a LIKE ? THEN 'A' ELSE 'B' END as t
            FROM matches m WHERE m.match_id LIKE ? AND {_mf}
        )
        SELECT SUM(CASE WHEN se.made=1 AND se.points=3 THEN 1 ELSE 0 END) as fg3,
               SUM(CASE WHEN se.made=1 AND se.points=2 THEN 1 ELSE 0 END) as fg2,
               SUM(CASE WHEN se.made=1 AND se.points=1 THEN 1 ELSE 0 END) as ftm,
               SUM(CASE WHEN se.points IN (0,1) THEN 1 ELSE 0 END) as fta
        FROM scoring_events se JOIN kg ON se.match_id=kg.match_id AND se.team=kg.t
    """, (tp, cp, *_mp)).fetchone()
    d["fg3"], d["fg2"], d["ftm"], d["fta"] = r

    # Top scorers (for fun facts)
    d["top_scorers"] = conn.execute(f"""
        WITH kg AS (
            SELECT m.match_id,
                   CASE WHEN m.team_a LIKE ? THEN 'A' ELSE 'B' END as t
            FROM matches m WHERE m.match_id LIKE ? AND {_mf}
        )
        SELECT pgs.name, SUM(pgs.points) as tp,
               ROUND(1.0*SUM(pgs.points)/NULLIF(COUNT(*),0),1) as ppg, COUNT(*) as gp
        FROM player_game_stats pgs JOIN kg ON pgs.match_id=kg.match_id AND pgs.team=kg.t
        GROUP BY pgs.license_number ORDER BY tp DESC LIMIT 3
    """, (tp, cp, *_mp)).fetchall()

    # Players used count
    d["players_used"] = conn.execute(f"""
        WITH kg AS (
            SELECT m.match_id,
                   CASE WHEN m.team_a LIKE ? THEN 'A' ELSE 'B' END as t
            FROM matches m WHERE m.match_id LIKE ? AND {_mf}
        )
        SELECT COUNT(DISTINCT pgs.license_number)
        FROM player_game_stats pgs JOIN kg ON pgs.match_id=kg.match_id AND pgs.team=kg.t
    """, (tp, cp, *_mp)).fetchone()[0]

    # Closest games
    d["closest"] = conn.execute(f"""
        WITH kg AS (
            SELECT m.match_date,
                   CASE WHEN m.team_a LIKE ? THEN m.team_b ELSE m.team_a END as opp,
                   CASE WHEN m.team_a LIKE ? THEN m.score_a ELSE m.score_b END as kg,
                   CASE WHEN m.team_a LIKE ? THEN m.score_b ELSE m.score_a END as op
            FROM matches m WHERE m.match_id LIKE ? AND {_mf}
        )
        SELECT match_date, opp, kg, op, ABS(kg-op) as diff
        FROM kg ORDER BY diff ASC LIMIT 3
    """, (tp, tp, tp, cp, *_mp)).fetchall()

    return d


HU_MONTHS_PARSE = {
    "január": 1, "február": 2, "március": 3, "április": 4,
    "május": 5, "június": 6, "július": 7, "augusztus": 8,
    "szeptember": 9, "október": 10, "november": 11, "december": 12,
}

MKOSZ_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def _parse_hu_date(text):
    """Parse '2025. október 7.' → '2025-10-07'."""
    m = re.match(r'(\d{4})\.\s+(\w+)\s+(\d{1,2})\.?', text.strip())
    if not m:
        return None
    year, month_hu, day = m.group(1), m.group(2).lower(), m.group(3)
    month = HU_MONTHS_PARSE.get(month_hu)
    if not month:
        return None
    return f"{year}-{month:02d}-{int(day):02d}"


def scrape_schedule(cfg):
    """Scrape match schedule from MKOSZ website. Returns list of dicts."""
    season = cfg.get("mkosz_season")
    comp = cfg.get("mkosz_comp")
    team_id = cfg.get("mkosz_team_id")
    if not all([season, comp, team_id]):
        return None

    url = f"https://mkosz.hu/bajnoksag-musor/{season}/{comp}/phase/0/csapat/{team_id}"
    req = urllib.request.Request(url, headers={"User-Agent": MKOSZ_USER_AGENT})
    try:
        html = urllib.request.urlopen(req, timeout=15).read().decode("utf-8")
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
        print(f"  ⚠ MKOSZ scrape hiba: {e}")
        return None

    team_name_upper = cfg["team_name"].upper()
    matches = []
    trs = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL)
    for tr in trs:
        tds = re.findall(r'<td[^>]*>(.*?)</td>', tr, re.DOTALL)
        if len(tds) != 6:
            continue

        # Team names from title attributes
        teams = re.findall(r'title="([^"]+)"', tds[0] + tds[1])
        if len(teams) != 2:
            continue

        home_team, away_team = teams[0], teams[1]

        # Date
        date_m = re.search(r'<b>(.*?)</b>', tds[2])
        if not date_m:
            continue
        date_str = _parse_hu_date(date_m.group(1))
        if not date_str:
            continue

        # Time
        time_str = tds[3].strip()

        # Score + match_id
        score_m = re.search(r'(\d+)\s*-\s*(\d+)', tds[4])
        mid_m = re.search(r'href="[^"]*?/([^/"]+)"', tds[4])

        if score_m:
            home_score = int(score_m.group(1))
            away_score = int(score_m.group(2))
            # 0-0 is impossible in basketball → treat as unplayed
            played = not (home_score == 0 and away_score == 0)
            if not played:
                home_score = None
                away_score = None
        else:
            home_score = None
            away_score = None
            played = False

        match_id = mid_m.group(1) if mid_m else None

        # Venue
        venue_m = re.search(r'title="([^"]+)"', tds[5])
        if not venue_m:
            venue_m = re.search(r'<span>(.*?)</span>', tds[5])
        venue = venue_m.group(1).strip() if venue_m else ""

        # Determine home/away for our team
        is_home = home_team.upper().startswith(team_name_upper[:10])

        matches.append({
            "date": date_str,
            "time": time_str,
            "home_team": home_team,
            "away_team": away_team,
            "home_score": home_score,
            "away_score": away_score,
            "match_id": match_id,
            "venue": venue,
            "played": played,
            "is_home": is_home,
        })

    return matches if matches else None


def scrape_schedule_county(cfg):
    """Scrape match schedule from megye.hunbasket.hu for county-level competitions.

    The county site has a different HTML structure than mkosz.hu:
    - Each match is in a 'Műsor' section with date, opponent, home/away, score
    - Dates are in format: '2025. Október 29. szerda, 18:45'
    - Home/Away: O=otthon (home), I=idegen (away)
    - Scores: 'GY, 60 - 48' or 'V, 52 - 63'
    """
    county = cfg.get("county")
    season = cfg.get("mkosz_season")
    comp = cfg.get("mkosz_comp")
    team_id = cfg.get("mkosz_team_id")
    if not all([county, season, comp, team_id]):
        return None

    # The county team schedule URL needs a slug — derive from team_name
    # Use ASCII-safe slugs only
    team_slug = slugify(cfg.get("team_name", ""))
    # Try common slug patterns (ASCII-safe)
    for slug in [team_slug, "kozgaz"]:
        url = f"https://megye.hunbasket.hu/{county}/csapat-musor/{season}/{comp}/{team_id}/{slug}"
        req = urllib.request.Request(url, headers={"User-Agent": MKOSZ_USER_AGENT})
        try:
            html = urllib.request.urlopen(req, timeout=15).read().decode("utf-8")
            if "forduló" in html:
                break
        except (urllib.error.URLError, urllib.error.HTTPError, OSError):
            continue
    else:
        print(f"  ⚠ Megyei scrape hiba: nem sikerült elérni a csapat-műsor oldalt")
        return None

    team_name_upper = cfg["team_name"].upper()
    matches = []

    # Split by 'Műsor' sections — each match has its own section
    sections = re.split(r'Műsor\s*', html)[1:]

    for sec in sections:
        # Date + time: '- 2025. Október 29. szerda, 18:45'
        dm = re.search(r'-\s*(\d{4})\.\s*(\w+)\s*(\d{1,2})\.\s*\w+,?\s*(\d{1,2}:\d{2})', sec)
        if not dm:
            continue
        year = dm.group(1)
        month_hu = dm.group(2).lower()
        day = dm.group(3)
        time_str = dm.group(4)
        month = HU_MONTHS_PARSE.get(month_hu)
        if not month:
            continue
        date_str = f"{year}-{month:02d}-{int(day):02d}"

        # Opponent name from title attribute
        opp_m = re.search(r'title="\s*(.*?)\s*"', sec)
        if not opp_m:
            continue
        opponent = opp_m.group(1).strip()

        # Home/Away: O=otthon, I=idegen
        ha_m = re.search(r'<td width="30">(O|I)</td>', sec)
        is_home = (ha_m.group(1) == "O") if ha_m else True

        # Score: 'GY, 60 - 48' or 'V, 52 - 63'
        score_m = re.search(r'(?:GY|V),\s*(\d+)\s*-\s*(\d+)', sec)
        if score_m:
            home_score = int(score_m.group(1))
            away_score = int(score_m.group(2))
            played = True
        else:
            home_score = None
            away_score = None
            played = False

        # Match ID from merkozes link
        mid_m = re.search(r'/merkozes/[^/]+/[^/]+/(\d+)', sec)
        match_id = mid_m.group(1) if mid_m else None

        # Venue from 'Aréna: <b>...</b>'
        venue_m = re.search(r'Aréna:\s*<b>(.*?)</b>', sec, re.DOTALL)
        venue = venue_m.group(1).strip() if venue_m else ""

        # Build home/away team names
        if is_home:
            home_team = cfg["team_name"]
            away_team = opponent.upper()
        else:
            home_team = opponent.upper()
            away_team = cfg["team_name"]

        matches.append({
            "date": date_str,
            "time": time_str,
            "home_team": home_team,
            "away_team": away_team,
            "home_score": home_score,
            "away_score": away_score,
            "match_id": match_id,
            "venue": venue,
            "played": played,
            "is_home": is_home,
        })

    return matches if matches else None


def get_calendar_data_db(conn, cfg, tp):
    """Fallback: fetch match data from SQLite."""
    rows = conn.execute("""
        SELECT m.match_date, m.match_time,
               CASE WHEN m.team_a LIKE ? THEN 'H' ELSE 'A' END as home_away,
               CASE WHEN m.team_a LIKE ? THEN m.team_b ELSE m.team_a END as opponent,
               CASE WHEN m.team_a LIKE ? THEN m.score_a ELSE m.score_b END as our_score,
               CASE WHEN m.team_a LIKE ? THEN m.score_b ELSE m.score_a END as opp_score,
               m.match_id
        FROM matches m
        WHERE m.match_id LIKE ?
          AND (m.team_a LIKE ? OR m.team_b LIKE ?)
        ORDER BY m.match_date
    """, (tp, tp, tp, tp, cfg["comp_prefix"], tp, tp)).fetchall()
    # Convert to same dict format as scrape_schedule
    return [{
        "date": r[0], "time": r[1] or "",
        "home_team": cfg["team_name"] if r[2] == 'H' else r[3],
        "away_team": r[3] if r[2] == 'H' else cfg["team_name"],
        "home_score": r[4] if r[2] == 'H' else r[5],
        "away_score": r[5] if r[2] == 'H' else r[4],
        "match_id": r[6], "venue": "", "played": True,
        "is_home": r[2] == 'H',
    } for r in rows] if rows else None


def _stats_to_js(d):
    """Convert a stats dict to a JSON-serializable dict for client-side rendering."""
    games = d["games"] or 0
    # Game log
    game_log = []
    for g in d["game_log"]:
        date, hv, opp, kg, op = g
        game_log.append({
            "date": date[5:].replace("-", "."), "hv": hv,
            "opp": shorten_opponent(opp),
            "kg": kg, "op": op,
            "res": "W" if kg > op else "L"
        })
    # Quarters
    q_kg = [q[1] or 0 for q in d["quarters"]] if d["quarters"] else [0,0,0,0]
    q_op = [q[2] or 0 for q in d["quarters"]] if d["quarters"] else [0,0,0,0]
    q_won = [q[3] or 0 for q in d["quarters"]] if d["quarters"] else [0,0,0,0]
    q_lost = [q[4] or 0 for q in d["quarters"]] if d["quarters"] else [0,0,0,0]
    # Scenarios
    sc = {s[0]: [s[1] or 0, s[2] or 0] for s in d["scenarios"]}
    # Shooting
    fg3 = d["fg3"] or 0; fg2 = d["fg2"] or 0; ftm = d["ftm"] or 0; fta = d["fta"] or 0
    pts3 = fg3 * 3; pts2 = fg2 * 2; tot = pts3 + pts2 + ftm
    # Runs
    def run_list(runs):
        return [{"date": r[0][5:].replace("-","."), "opp": shorten_opponent(r[1]),
                 "sq": r[2], "eq": r[3], "pts": r[4], "bsk": r[5]} for r in runs]
    # Fun facts
    facts = []
    if q_kg and len(q_kg) == 4:
        best_q = max(range(4), key=lambda i: q_kg[i])
        worst_q = min(range(4), key=lambda i: q_kg[i])
        facts.append(f'Legerősebb negyed: <b>Q{best_q+1}</b> ({q_kg[best_q]} pont/meccs)')
        facts.append(f'Leggyengébb negyed: <b>Q{worst_q+1}</b> ({q_kg[worst_q]} pont/meccs)')
    if d["runs_for"]:
        facts.append(f'Leghosszabb saját run: <b>{d["runs_for"][0][4]}-0</b> ({d["runs_for"][0][1][:15]} ellen)')
    if d["runs_against"]:
        facts.append(f'Leghosszabb kapott run: <b>{d["runs_against"][0][4]}-0</b> ({d["runs_against"][0][1][:15]} ellen)')
    ht_lead = sc.get("HT_LEAD", [0, 0])
    ht_trail = sc.get("HT_TRAIL", [0, 0])
    if ht_lead[0] > 0:
        facts.append(f'Félidőben vezetve: <b>{ht_lead[1]}/{ht_lead[0]} győzelem</b> ({round(100*ht_lead[1]/ht_lead[0])}%)')
    if ht_trail[0] > 0:
        facts.append(f'Félidős hátrányból: <b>{ht_trail[1]} fordítás {ht_trail[0]}-ból</b>')
    home_w = d["home_w"] or 0; home_g = d["home_g"] or 0
    away_w = d["away_w"] or 0; away_g = d["away_g"] or 0
    facts.append(f'Hazai mérleg: <b>{home_w}-{home_g-home_w}</b> | Vendég: <b>{away_w}-{away_g-away_w}</b>')
    facts.append(f'<b>{d["players_used"]}</b> játékos fordult meg a keretben')
    ft_pct = round(100 * ftm / fta) if fta > 0 else 0
    facts.append(f'FT%: <b>{ft_pct}%</b> ({ftm}/{fta})')
    ts = d["top_scorers"]
    scored = d["scored"] or 0
    if len(ts) >= 2 and scored > 0:
        top2_pts = ts[0][1] + ts[1][1]
        facts.append(f'Top 2 pontszerző ({ts[0][0].title()}, {ts[1][0].title()}) a csapat pontjainak <b>{round(100*top2_pts/scored)}%</b>-át adja')
    if d["closest"]:
        c = d["closest"][0]
        facts.append(f'Legszorosabb meccs: <b>{c[2]}-{c[3]}</b> ({shorten_opponent(c[1])}, {c[0][5:].replace("-",".")})')

    ppg = d["ppg"] or 0; opp_ppg = d["opp_ppg"] or 0
    return {
        "games": games, "wins": d["wins"] or 0, "losses": d["losses"] or 0,
        "scored": scored, "allowed": d["allowed"] or 0,
        "ppg": ppg, "opp_ppg": opp_ppg,
        "diff": round(ppg - opp_ppg, 1),
        "best_score": d["best_score"] or 0, "most_allowed": d["most_allowed"] or 0,
        "players_used": d["players_used"] or 0,
        "game_log": game_log,
        "trend_labels": [g["date"] for g in game_log],
        "trend_kg": [g["kg"] for g in game_log],
        "trend_op": [g["op"] for g in game_log],
        "trend_res": [g["res"] for g in game_log],
        "q_kg": q_kg, "q_op": q_op, "q_won": q_won, "q_lost": q_lost,
        "sc": sc,
        "pts3": pts3, "pts2": pts2, "pts_ft": ftm, "ftm": ftm, "fta": fta,
        "pct3": round(100 * pts3 / tot) if tot else 0,
        "pct2": round(100 * pts2 / tot) if tot else 0,
        "pct_ft": round(100 * ftm / tot) if tot else 0,
        "runs_for": run_list(d["runs_for"]),
        "runs_against": run_list(d["runs_against"]),
        "facts": facts,
        "home_w": home_w, "home_g": home_g, "away_w": away_w, "away_g": away_g,
    }


def generate_team_dashboard(stats_all, cfg, team_key=None, att_data=None,
                            stats_home=None, stats_away=None):
    """Generate team-level dashboard HTML with Home/Away/All toggle."""
    d = stats_all
    games = d["games"]
    team_name = cfg["team_name"]
    group_name = cfg["group_name"]
    team_short = cfg["team_short"]

    # Prepare JSON data for all three views
    js_all = _stats_to_js(stats_all)
    js_home = _stats_to_js(stats_home) if stats_home else js_all
    js_away = _stats_to_js(stats_away) if stats_away else js_all
    js_gamelog = js_all["game_log"]

    # Attendance chart data (Közgáz B only)
    _att_section = ""
    if att_data:
        att_items = []  # (label, attended, total, pct, is_coach)
        for name, ratio in att_data.items():
            parts = ratio.split("/")
            if len(parts) == 2:
                try:
                    attended, total = int(parts[0]), int(parts[1])
                    pct = round(100 * attended / total) if total > 0 else 0
                    is_coach = (name == ATTENDANCE_COACH)
                    # Use last name (first word of DB name, skip "DR." prefix); disambiguate duplicates
                    words = name.split()
                    last_idx = 1 if words[0].upper().rstrip(".") == "DR" and len(words) > 2 else 0
                    last = words[last_idx].title()
                    def _get_last(n):
                        w = n.split()
                        li = 1 if w[0].upper().rstrip(".") == "DR" and len(w) > 2 else 0
                        return w[li].title()
                    last_names = [_get_last(n) for n in att_data.keys() if " " in n]
                    if last_names.count(last) > 1:
                        last = f"{last} {words[-1][0].upper()}."
                    if is_coach:
                        last = f"{last} (edző)"
                    att_items.append((last, attended, total, pct, is_coach))
                except ValueError:
                    pass
        # Sort: players first (by pct desc), coach at bottom
        att_items.sort(key=lambda x: (x[4], -x[3]))
        att_labels = json.dumps([a[0] for a in att_items], ensure_ascii=False)
        att_values = json.dumps([a[3] for a in att_items])
        att_ratios = json.dumps([f"{a[1]}/{a[2]}" for a in att_items])
        def _att_color(item):
            if item[4]:  # coach
                return "rgba(253,203,110,0.7)"
            return "rgba(0,184,148,0.7)" if item[3] >= 80 else "rgba(225,112,85,0.7)"
        def _att_border(item):
            if item[4]:
                return "#fdcb6e"
            return "#00b894" if item[3] >= 80 else "#e17055"
        att_colors = json.dumps([_att_color(a) for a in att_items])
        att_borders = json.dumps([_att_border(a) for a in att_items])
        att_bar_h = max(len(att_items) * 28 + 40, 200)
        _att_section = f"""<div class="card mb20">
    <h3>Edzéslátogatás</h3>
    <div class="chart-wrap" style="height:{att_bar_h}px;"><canvas id="attChart"></canvas></div>
  </div>"""
        _att_chart_js = f"""
const attThresholdPlugin = {{
  id:'attThreshold',
  afterDraw(chart) {{
    const {{ ctx, chartArea:{{ top, bottom }}, scales:{{ x }} }} = chart;
    const xPos = x.getPixelForValue(80);
    ctx.save();
    ctx.strokeStyle='rgba(255,255,255,0.4)';
    ctx.lineWidth=2;
    ctx.setLineDash([6,4]);
    ctx.beginPath();
    ctx.moveTo(xPos, top);
    ctx.lineTo(xPos, bottom);
    ctx.stroke();
    ctx.fillStyle='rgba(255,255,255,0.5)';
    ctx.font="11px Inter,sans-serif";
    ctx.fillText('80%', xPos+4, top+12);
    ctx.restore();
  }}
}};
const attCtx = document.getElementById('attChart').getContext('2d');
new Chart(attCtx, {{
  type:'bar',
  plugins:[attThresholdPlugin],
  data: {{
    labels:{att_labels},
    datasets:[{{
      data:{att_values},
      backgroundColor:{att_colors},
      borderColor:{att_borders},
      borderWidth:2, borderRadius:4, borderSkipped:false,
    }}]
  }},
  options: {{
    indexAxis:'y', responsive:true, maintainAspectRatio:false,
    plugins: {{
      legend:{{ display:false }},
      tooltip:{{ callbacks:{{ label: function(ctx) {{
        const ratios = {att_ratios};
        return ratios[ctx.dataIndex] + ' (' + ctx.parsed.x + '%)';
      }} }} }},
    }},
    scales: {{
      x:{{ min:0, max:100, grid:{{ color:'rgba(255,255,255,0.04)' }},
        ticks:{{ callback:v=>v+'%' }} }},
      y:{{ grid:{{ display:false }}, ticks:{{ font:{{ size:11 }} }} }}
    }}
  }}
}});"""
    else:
        _att_chart_js = ""

    # (Chart data is embedded in STATS JSON, rendered via JS)

    html = f"""<!DOCTYPE html>
<html lang="hu">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{team_short} — Csapat Dashboard 2025/26</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"></script>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap');
  :root {{
    --bg:#0a0b0e; --card:#151518; --card-hover:#1e1e24;
    --accent:#C41E3A; --accent2:#00cec9; --accent3:#ff6b6b; --accent4:#fdcb6e;
    --text:#e8e8f0; --text-dim:#8b8da0; --green:#00b894; --red:#e17055;
    --border:rgba(255,255,255,0.06);
  }}
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family:'Inter',-apple-system,sans-serif; background:var(--bg); color:var(--text); min-height:100vh; padding:24px; }}
  .dashboard {{ max-width:1200px; margin:0 auto; }}
  .header {{
    display:flex; align-items:center; gap:28px; padding:32px;
    background:linear-gradient(135deg,#151518 0%,#2a1218 50%,#1a1518 100%);
    border-radius:20px; margin-bottom:20px; border:1px solid var(--border);
    position:relative; overflow:hidden;
  }}
  .header::after {{
    content:''; position:absolute; top:-60%; right:-10%;
    width:500px; height:500px;
    background:radial-gradient(circle,rgba(196,30,58,0.12),transparent 70%);
    pointer-events:none;
  }}
  .header-info {{ z-index:1; }}
  .header-info h1 {{
    font-size:2.2rem; font-weight:900; letter-spacing:-0.5px;
    background:linear-gradient(135deg,#fff 20%,var(--accent) 80%);
    -webkit-background-clip:text; -webkit-text-fill-color:transparent;
  }}
  .header-info .subtitle {{ font-size:0.95rem; color:var(--text-dim); margin-top:4px; }}
  .header-info .subtitle span {{ color:var(--accent2); font-weight:600; }}
  .header-stats {{ display:flex; gap:16px; margin-left:auto; z-index:1; flex-wrap:wrap; }}
  .header-stat {{
    text-align:center; padding:12px 18px; background:rgba(255,255,255,0.04);
    border-radius:14px; border:1px solid var(--border); min-width:75px;
  }}
  .header-stat .val {{ font-size:1.5rem; font-weight:800; color:#fff; }}
  .header-stat .label {{ font-size:0.65rem; color:var(--text-dim); text-transform:uppercase; letter-spacing:1px; margin-top:2px; }}
  .grid {{ display:grid; gap:20px; }}
  .grid-2 {{ grid-template-columns:1fr 1fr; }}
  .grid-3 {{ grid-template-columns:1fr 1fr 1fr; }}
  .grid-4 {{ grid-template-columns:1fr 1fr 1fr 1fr; }}
  .grid-5 {{ grid-template-columns:1fr 1fr 1fr 1fr 1fr; }}
  .card {{
    background:var(--card); border-radius:16px; padding:24px;
    border:1px solid var(--border); transition:background 0.2s;
  }}
  .card:hover {{ background:var(--card-hover); }}
  .card h3 {{ font-size:0.8rem; text-transform:uppercase; letter-spacing:1.2px; color:var(--text-dim); margin-bottom:16px; font-weight:600; }}
  .mini-stat {{ text-align:center; }}
  .mini-stat .big {{ font-size:1.8rem; font-weight:800; }}
  .mini-stat .desc {{ font-size:0.72rem; color:var(--text-dim); margin-top:4px; }}
  .chart-wrap {{ position:relative; width:100%; }}
  .chart-wrap.h250 {{ height:250px; }}
  .chart-wrap.h280 {{ height:280px; }}
  .game-log-wrap {{ overflow-x:auto; -webkit-overflow-scrolling:touch; }}
  .game-log {{ width:100%; border-collapse:collapse; font-size:0.82rem; }}
  .game-log th {{ text-align:left; font-size:0.7rem; text-transform:uppercase; letter-spacing:0.8px; color:var(--text-dim); padding:8px 10px; border-bottom:1px solid var(--border); font-weight:600; white-space:nowrap; }}
  .game-log td {{ padding:8px 10px; border-bottom:1px solid var(--border); white-space:nowrap; }}
  .game-log tr:last-child td {{ border-bottom:none; }}
  .game-log tr:hover {{ background:rgba(196,30,58,0.06); }}
  .badge {{ display:inline-block; padding:2px 8px; border-radius:6px; font-size:0.7rem; font-weight:700; }}
  .badge.w {{ background:rgba(0,184,148,0.15); color:var(--green); }}
  .badge.l {{ background:rgba(225,112,85,0.15); color:var(--red); }}
  .badge.h {{ background:rgba(143,168,200,0.15); color:#8fa8c8; }}
  .badge.v {{ background:rgba(253,203,110,0.15); color:var(--accent4); }}
  .run-tbl {{ width:100%; border-collapse:collapse; font-size:0.82rem; }}
  .run-tbl th {{ text-align:left; font-size:0.7rem; text-transform:uppercase; color:var(--text-dim); padding:6px 8px; border-bottom:1px solid var(--border); }}
  .run-tbl td {{ padding:6px 8px; border-bottom:1px solid var(--border); }}
  .run-tbl tr:last-child td {{ border-bottom:none; }}
  .fact-item {{
    padding:10px 14px; margin-bottom:8px;
    background:rgba(255,255,255,0.02); border-radius:10px;
    border-left:3px solid var(--accent); font-size:0.85rem;
    color:var(--text-dim); line-height:1.5;
  }}
  .fact-item b {{ color:#fff; }}
  .scenario-tbl {{ width:100%; border-collapse:collapse; font-size:0.82rem; }}
  .scenario-tbl td {{ padding:8px 10px; border-bottom:1px solid var(--border); }}
  .scenario-tbl tr:last-child td {{ border-bottom:none; }}
  .view-toggle {{
    display:flex; gap:4px; justify-content:center; margin-bottom:20px;
    background:var(--card); border-radius:12px; padding:4px; border:1px solid var(--border);
    width:fit-content; margin-left:auto; margin-right:auto;
  }}
  .view-btn {{
    padding:8px 20px; border-radius:10px; border:none; cursor:pointer;
    font-family:'Inter',sans-serif; font-size:0.8rem; font-weight:600;
    color:var(--text-dim); background:transparent; transition:all 0.2s;
    letter-spacing:0.5px;
  }}
  .view-btn:hover {{ color:var(--text); background:rgba(255,255,255,0.05); }}
  .view-btn.active {{ background:var(--accent); color:#fff; }}
  {NAV_CSS}
  .mb20 {{ margin-bottom:20px; }}
  @media (max-width:900px) {{
    .grid-2,.grid-3,.grid-4,.grid-5 {{ grid-template-columns:1fr; }}
    .header {{ flex-direction:column; text-align:center; }}
    .header-stats {{ margin-left:0; justify-content:center; }}
  }}
  @media (max-width:600px) {{
    body {{ padding:10px; }}
    .game-log {{ font-size:0.72rem; }}
    .game-log th {{ padding:6px 6px; font-size:0.62rem; letter-spacing:0.3px; }}
    .game-log td {{ padding:6px 6px; }}
    .run-tbl {{ font-size:0.72rem; }}
    .run-tbl th {{ padding:4px 5px; }}
    .run-tbl td {{ padding:4px 5px; }}
    .scenario-tbl {{ font-size:0.72rem; }}
    .scenario-tbl td {{ padding:6px 6px; }}
  }}
</style>
</head>
<body>
<div class="dashboard">
  {_nav_html(active_key=team_key, depth=1)}
  <a href="index.html" class="back-link">&larr; Csapat áttekintő</a>
  <div class="header">
    <div class="header-info">
      <h1>{team_name}</h1>
      <div class="subtitle">
        <span>CSAPAT STATISZTIKÁK</span> &nbsp;|&nbsp; {group_name} &nbsp;|&nbsp; 2025/26 alapszakasz
      </div>
    </div>
    <div class="header-stats" id="headerStats">
      <div class="header-stat"><div class="val" id="hWins" style="color:var(--green)">{d["wins"]}</div><div class="label">Győzelem</div></div>
      <div class="header-stat"><div class="val" id="hLosses" style="color:var(--red)">{d["losses"]}</div><div class="label">Vereség</div></div>
      <div class="header-stat"><div class="val" id="hPpg" style="color:var(--accent2)">{d["ppg"]}</div><div class="label">Dobott/m</div></div>
      <div class="header-stat"><div class="val" id="hOppPpg" style="color:var(--red)">{d["opp_ppg"]}</div><div class="label">Kapott/m</div></div>
      <div class="header-stat"><div class="val" id="hDiff" style="color:var(--{"green" if d["ppg"] >= d["opp_ppg"] else "red"})">{round(d["ppg"]-d["opp_ppg"],1)}</div><div class="label">Kül./m</div></div>
    </div>
  </div>

  <div class="view-toggle">
    <button class="view-btn active" onclick="switchView('all')">Összes</button>
    <button class="view-btn" onclick="switchView('home')">Hazai</button>
    <button class="view-btn" onclick="switchView('away')">Vendég</button>
  </div>

  <div class="grid grid-5 mb20">
    <div class="card mini-stat"><div class="big" id="mScored" style="color:var(--accent2)">{d["scored"]}</div><div class="desc">Összes dobott</div></div>
    <div class="card mini-stat"><div class="big" id="mAllowed" style="color:var(--red)">{d["allowed"]}</div><div class="desc">Összes kapott</div></div>
    <div class="card mini-stat"><div class="big" id="mBest" style="color:var(--green)">{d["best_score"]}</div><div class="desc">Legtöbb dobott</div></div>
    <div class="card mini-stat"><div class="big" id="mWorst" style="color:var(--red)">{d["most_allowed"]}</div><div class="desc">Legtöbb kapott</div></div>
    <div class="card mini-stat"><div class="big" id="mPlayers" style="color:var(--accent2)">{d["players_used"]}</div><div class="desc">Játékos a keretben</div></div>
  </div>

  <div class="grid grid-2 mb20">
    <div class="card">
      <h3>Dobott vs Kapott pontok meccsenként</h3>
      <div class="chart-wrap h280"><canvas id="trendChart"></canvas></div>
    </div>
    <div class="card">
      <h3>Negyedenkénti átlagok</h3>
      <div class="chart-wrap h280"><canvas id="quarterChart"></canvas></div>
    </div>
  </div>

  <div class="grid grid-2 mb20">
    <div class="card">
      <h3>Pontmegoszlás (dobástípus)</h3>
      <div class="chart-wrap" style="height:200px;"><canvas id="shotPie"></canvas></div>
    </div>
    <div class="card">
      <h3>Forgatókönyvek — ha félidőben...</h3>
      <div class="game-log-wrap"><table class="scenario-tbl" id="scenarioTbl"><tbody id="scenarioBody"></tbody></table></div>
    </div>
  </div>

  <div class="grid grid-2 mb20">
    <div class="card">
      <h3>Top 5 saját scoring run</h3>
      <div class="game-log-wrap"><table class="run-tbl">
        <thead><tr><th>Dátum</th><th>Ellenfél</th><th>Run</th><th>Negyed</th><th>Kosár</th></tr></thead>
        <tbody id="runsForBody"></tbody>
      </table></div>
    </div>
    <div class="card">
      <h3>Top 5 kapott scoring run</h3>
      <div class="game-log-wrap"><table class="run-tbl">
        <thead><tr><th>Dátum</th><th>Ellenfél</th><th>Run</th><th>Negyed</th><th>Kosár</th></tr></thead>
        <tbody id="runsAgnBody"></tbody>
      </table></div>
    </div>
  </div>

  {_att_section}

  <div class="card mb20">
    <h3>Meccsek</h3>
    <div class="game-log-wrap">
    <table class="game-log">
      <thead><tr><th>Dátum</th><th></th><th>Ellenfél</th><th>Eredmény</th><th></th><th>Különbség</th></tr></thead>
      <tbody id="gameLogBody"></tbody>
    </table>
    </div>
  </div>

  <div class="card mb20">
    <h3>Érdekességek &amp; Fun Facts</h3>
    <div id="factsBody"></div>
  </div>
</div>

<script>
Chart.defaults.color='#8b8da0';
Chart.defaults.borderColor='rgba(255,255,255,0.06)';
Chart.defaults.font.family="'Inter',sans-serif";

const STATS = {{
  all: {json.dumps(js_all, ensure_ascii=False)},
  home: {json.dumps(js_home, ensure_ascii=False)},
  away: {json.dumps(js_away, ensure_ascii=False)}
}};

let trendChart, quarterChart, shotChart;
let currentView = 'all';

function renderGameLog(s) {{
  const tbody = document.getElementById('gameLogBody');
  tbody.innerHTML = '';
  s.game_log.forEach(g => {{
    const diff = g.kg - g.op;
    const diffStr = diff > 0 ? '+'+diff : ''+diff;
    const diffColor = diff > 0 ? 'var(--green)' : 'var(--red)';
    const tr = document.createElement('tr');
    tr.innerHTML = '<td>'+g.date+'</td>'
      +'<td><span class="badge '+(g.hv==='H'?'h':'v')+'">'+g.hv+'</span></td>'
      +'<td>'+g.opp+'</td>'
      +'<td style="font-weight:700;">'+g.kg+'-'+g.op+'</td>'
      +'<td><span class="badge '+(g.res==='W'?'w':'l')+'">'+(g.res==='W'?'GY':'V')+'</span></td>'
      +'<td style="font-weight:700;color:'+diffColor+';">'+diffStr+'</td>';
    tbody.appendChild(tr);
  }});
}}

function renderRuns(runs, bodyId, color) {{
  const tbody = document.getElementById(bodyId);
  tbody.innerHTML = '';
  runs.forEach(r => {{
    const qspan = r.sq === r.eq ? 'Q'+r.sq : 'Q'+r.sq+'\u2192Q'+r.eq;
    const tr = document.createElement('tr');
    tr.innerHTML = '<td>'+r.date+'</td><td>'+r.opp+'</td>'
      +'<td style="font-weight:800;color:var(--'+color+')">'+r.pts+'-0</td>'
      +'<td>'+qspan+'</td><td>'+r.bsk+'</td>';
    tbody.appendChild(tr);
  }});
}}

function renderScenarios(sc) {{
  const tbody = document.getElementById('scenarioBody');
  const rows = [
    ['Félidőben <b style="color:var(--green)">vezet</b>', 'HT_LEAD', 'green', 'győzelem'],
    ['Félidőben <b style="color:var(--red)">hátrányban</b>', 'HT_TRAIL', 'red', 'fordítás'],
    ['3 negyed után <b style="color:var(--green)">vezet</b>', '3Q_LEAD', 'green', 'győzelem'],
    ['3 negyed után <b style="color:var(--red)">hátrányban</b>', '3Q_TRAIL', 'red', 'fordítás'],
  ];
  tbody.innerHTML = '';
  rows.forEach(([label, key, color, word]) => {{
    const d = sc[key] || [0, 0];
    const pct = d[0] > 0 ? Math.round(100*d[1]/d[0]) : 0;
    const tr = document.createElement('tr');
    tr.innerHTML = '<td>'+label+'</td>'
      +'<td style="font-weight:800;color:var(--'+color+')">'+d[1]+'/'+d[0]+' '+word+'</td>'
      +'<td style="color:var(--text-dim)">'+pct+'%</td>';
    tbody.appendChild(tr);
  }});
}}

function renderFacts(facts) {{
  document.getElementById('factsBody').innerHTML =
    facts.map(f => '<div class="fact-item">'+f+'</div>').join('');
}}

function buildTrendChart(s) {{
  if (trendChart) trendChart.destroy();
  const yMax = Math.max(...s.trend_kg, ...s.trend_op, 0) + 10;
  const ptColors = s.trend_res.map(r => r==='W' ? '#00b894' : '#e17055');
  trendChart = new Chart(document.getElementById('trendChart').getContext('2d'), {{
    type:'line',
    data: {{
      labels: s.trend_labels,
      datasets: [{{
        label:'Dobott', data:s.trend_kg,
        borderColor:'#00cec9', backgroundColor:'rgba(0,206,201,0.08)',
        fill:true, tension:0.3, pointRadius:5, borderWidth:3,
        pointBackgroundColor:ptColors, pointBorderColor:ptColors,
      }}, {{
        label:'Kapott', data:s.trend_op,
        borderColor:'#e17055', backgroundColor:'rgba(225,112,85,0.05)',
        fill:true, tension:0.3, pointRadius:4, borderWidth:2, borderDash:[4,3],
        pointBackgroundColor:'#e17055', pointBorderColor:'#e17055',
      }}]
    }},
    options: {{
      responsive:true, maintainAspectRatio:false,
      plugins: {{ legend:{{ position:'top', labels:{{ usePointStyle:true, font:{{size:11}} }} }} }},
      scales: {{ y:{{ beginAtZero:true, max:yMax, grid:{{color:'rgba(255,255,255,0.04)'}} }}, x:{{ grid:{{display:false}} }} }}
    }}
  }});
}}

function buildQuarterChart(s) {{
  if (quarterChart) quarterChart.destroy();
  quarterChart = new Chart(document.getElementById('quarterChart').getContext('2d'), {{
    type:'bar',
    data: {{
      labels:['Q1','Q2','Q3','Q4'],
      datasets: [{{
        label:'Dobott', data:s.q_kg,
        backgroundColor:'rgba(0,206,201,0.6)', borderColor:'#00cec9', borderWidth:2, borderRadius:6,
      }},{{
        label:'Kapott', data:s.q_op,
        backgroundColor:'rgba(225,112,85,0.5)', borderColor:'#e17055', borderWidth:2, borderRadius:6,
      }}]
    }},
    options: {{
      responsive:true, maintainAspectRatio:false,
      plugins: {{
        legend:{{ position:'top', labels:{{ usePointStyle:true, font:{{size:11}} }} }},
        tooltip: {{ callbacks: {{ afterBody: items => {{
          const idx = items[0].dataIndex;
          return 'Megnyert negyed: '+s.q_won[idx]+' | Elvesztett: '+s.q_lost[idx];
        }} }} }}
      }},
      scales: {{ y:{{ beginAtZero:true, grid:{{color:'rgba(255,255,255,0.04)'}} }}, x:{{ grid:{{display:false}} }} }}
    }}
  }});
}}

function buildShotChart(s) {{
  if (shotChart) shotChart.destroy();
  shotChart = new Chart(document.getElementById('shotPie').getContext('2d'), {{
    type:'doughnut',
    data: {{
      labels:['3FG ('+s.pct3+'% \u2014 '+s.pts3+' pt)','2FG ('+s.pct2+'% \u2014 '+s.pts2+' pt)','FT ('+s.pct_ft+'% \u2014 '+s.pts_ft+' pt)'],
      datasets:[{{ data:[s.pts3,s.pts2,s.pts_ft], backgroundColor:['#00cec9','#fdcb6e','#8b8da0'], borderColor:'#151518', borderWidth:3, hoverOffset:8 }}]
    }},
    options: {{ responsive:true, maintainAspectRatio:false, cutout:'55%',
      plugins:{{ legend:{{ position:'right', labels:{{ padding:14, usePointStyle:true, font:{{size:11}} }} }} }}
    }}
  }});
}}

function switchView(mode) {{
  currentView = mode;
  const s = STATS[mode];

  // Toggle buttons
  document.querySelectorAll('.view-btn').forEach(b => b.classList.remove('active'));
  document.querySelector('.view-btn[onclick*="\\\''+mode+'\\\'"]').classList.add('active');

  // Header stats
  document.getElementById('hWins').textContent = s.wins;
  document.getElementById('hLosses').textContent = s.losses;
  document.getElementById('hPpg').textContent = s.ppg;
  document.getElementById('hOppPpg').textContent = s.opp_ppg;
  document.getElementById('hDiff').textContent = s.diff;
  document.getElementById('hDiff').style.color = s.diff >= 0 ? 'var(--green)' : 'var(--red)';

  // Mini stats
  document.getElementById('mScored').textContent = s.scored;
  document.getElementById('mAllowed').textContent = s.allowed;
  document.getElementById('mBest').textContent = s.best_score;
  document.getElementById('mWorst').textContent = s.most_allowed;
  document.getElementById('mPlayers').textContent = s.players_used;

  // Charts
  buildTrendChart(s);
  buildQuarterChart(s);
  buildShotChart(s);

  // Scenarios, runs, game log, facts
  renderScenarios(s.sc);
  renderRuns(s.runs_for, 'runsForBody', 'green');
  renderRuns(s.runs_against, 'runsAgnBody', 'red');
  renderGameLog(s);
  renderFacts(s.facts);
}}

// Initial render
switchView('all');
{_att_chart_js}
</script>
</body>
</html>"""
    return html


# ── Shared calendar CSS & grid builder ──────────────────────────────────

CALENDAR_CSS = """
/* Calendar shared styles */
.cal-legend {
  display:flex; gap:24px; justify-content:center; flex-wrap:wrap;
  margin-bottom:20px; font-size:.78rem; color:var(--text-dim);
}
.legend-item { display:flex; align-items:center; gap:6px; }
.cal-month {
  background:var(--card); border-radius:16px; padding:20px;
  border:1px solid var(--border); margin-bottom:16px;
}
.cal-month h3 {
  font-size:.85rem; text-transform:uppercase; letter-spacing:2.5px;
  color:var(--accent); margin-bottom:14px; font-weight:700; text-align:center;
  cursor:pointer; user-select:none; transition:color .2s;
}
.cal-month h3:hover { color:#e8e8f0; }
.cal-toggle {
  font-size:.7rem; display:inline-block; transition:transform .2s;
  margin-left:6px; opacity:.6;
}
.cal-month.collapsed { padding:14px 20px; }
.cal-month.collapsed h3 { margin-bottom:0; opacity:.5; }
.cal-month.collapsed h3:hover { opacity:.8; }
.cal-month.collapsed .cal-grid { display:none; }
.cal-month.collapsed .cal-toggle { transform:rotate(-90deg); }
.cal-grid {
  display:grid; grid-template-columns:repeat(7,1fr); gap:3px;
}
.cal-hd {
  text-align:center; font-size:.65rem; font-weight:700; color:var(--text-dim);
  text-transform:uppercase; letter-spacing:1px; padding:6px 0 8px;
}
.cal-day {
  min-height:80px; padding:6px 5px; border-radius:8px;
  background:rgba(255,255,255,.015); position:relative;
}
.cal-day.empty { background:transparent; min-height:0; }
.day-num { font-size:.68rem; color:var(--text-dim); font-weight:500; }
.cal-day.has-match { border:1px solid rgba(255,255,255,0.08); }
.cal-day.past { opacity:0.35; }
.cal-day.past:hover { opacity:0.65; }
.cal-day.today { border:1.5px solid #f39c12 !important; background:rgba(243,156,18,0.08); position:relative; }
.cal-day.today .day-num { color:#f39c12; font-weight:700; }
.cal-day.today::after {
  content:'MA'; position:absolute; top:4px; right:5px;
  font-size:.45rem; font-weight:800; color:#f39c12; letter-spacing:.5px; opacity:.8;
}
.match-info { display:flex; flex-direction:column; gap:2px; margin-top:4px; }
.cal-match-sep { border-top:1px solid rgba(255,255,255,0.08); margin:2px 0; }
.cal-match {
  display:flex; align-items:center; gap:3px; flex-wrap:wrap;
}
.cal-team-tag {
  font-size:.52rem; font-weight:700; padding:1px 5px; border-radius:4px;
  border:1px solid; white-space:nowrap; line-height:1.3;
}
.match-opp { font-size:.62rem; font-weight:600; color:var(--text); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.match-time { font-size:.55rem; color:var(--text-dim); }
.match-score { font-size:.62rem; font-weight:700; }
.match-score.win { color:var(--green); }
.match-score.loss { color:var(--red); }
.match-badge {
  font-size:.5rem; font-weight:800; padding:1px 4px; border-radius:4px;
  min-width:18px; text-align:center; line-height:1.4;
}
.match-badge.w { background:rgba(0,184,148,.2); color:var(--green); }
.match-badge.l { background:rgba(225,112,85,.2); color:var(--red); }

@media(max-width:900px) {
  .cal-day { min-height:65px; padding:4px; }
  .match-opp { font-size:.55rem; }
  .cal-team-tag { font-size:.48rem; padding:1px 3px; }
}
@media(max-width:600px) {
  .cal-day { min-height:50px; padding:3px; }
  .day-num { font-size:.58rem; }
  .match-opp { font-size:.5rem; }
  .match-time { display:none; }
  .match-score { font-size:.52rem; }
  .match-badge { font-size:.45rem; padding:1px 3px; }
  .cal-team-tag { font-size:.44rem; padding:1px 2px; }
  .cal-hd { font-size:.55rem; }
}
"""


def _build_calendar_grid(matches_by_date, multi_team=False):
    """Build shared calendar grid HTML + JS.

    Args:
        matches_by_date: dict keyed by (year, month, day).
            - If multi_team=False: value = single dict with keys: opp, time, score, win, home, played
            - If multi_team=True: value = list of dicts, each also having: team_short, league, lg_cfg
        multi_team: if True, show team tags and handle multiple matches per day.

    Returns:
        (months_html, calendar_js) tuple — HTML for month grids and JS for past/today/collapsible.
    """
    if not matches_by_date:
        return "", ""

    # Determine month range
    all_keys = list(matches_by_date.keys())
    min_y, min_m = min((k[0], k[1]) for k in all_keys)
    max_y, max_m = max((k[0], k[1]) for k in all_keys)

    months_to_show = []
    y, mo = min_y, min_m
    while (y, mo) <= (max_y, max_m):
        months_to_show.append((y, mo))
        mo += 1
        if mo > 12:
            mo = 1
            y += 1

    months_html = ""
    for year, month in months_to_show:
        month_name = MONTH_NAMES_HU[month]
        first_weekday, num_days = cal_module.monthrange(year, month)

        headers = "".join(f'<div class="cal-hd">{d}</div>' for d in DAY_NAMES_HU)
        cells = '<div class="cal-day empty"></div>' * first_weekday

        for day in range(1, num_days + 1):
            key = (year, month, day)
            date_str = f"{year}-{month:02d}-{day:02d}"

            if key in matches_by_date:
                if multi_team:
                    # Multi-team: list of matches per day
                    day_matches = matches_by_date[key]
                    match_items = ""
                    for idx, mi in enumerate(day_matches):
                        lcfg = mi["lg_cfg"]
                        tag = f'<span class="cal-team-tag" style="color:{lcfg["color"]};background:{lcfg["bg"]};border-color:{lcfg["border"]}">{mi["team_short"]}</span>'

                        if mi["played"] and mi["win"] is not None:
                            badge_letter = "W" if mi["win"] else "L"
                            bc = "w" if mi["win"] else "l"
                            sc_cls = "win" if mi["win"] else "loss"
                            detail = f'<span class="match-opp">{mi["opp"]}</span><span class="match-score {sc_cls}">{mi["score"]}</span><span class="match-badge {bc}">{badge_letter}</span>'
                        else:
                            detail = f'<span class="match-opp">{mi["opp"]}</span><span class="match-time">{mi["time"]}</span>'

                        sep = '<div class="cal-match-sep"></div>' if idx > 0 else ''
                        match_items += f'{sep}<div class="cal-match">{tag}{detail}</div>'

                    cells += f'''<div class="cal-day has-match" data-date="{date_str}">
  <span class="day-num">{day}</span>
  <div class="match-info">{match_items}</div>
</div>'''
                else:
                    # Single-team: one match per day
                    mi = matches_by_date[key]
                    if mi["played"] and mi["win"] is not None:
                        badge_letter = "W" if mi["win"] else "L"
                        bc = "w" if mi["win"] else "l"
                        sc_cls = "win" if mi["win"] else "loss"
                        score_line = f'<span class="match-score {sc_cls}">{mi["score"]}</span>'
                        badge_html = f'<span class="match-badge {bc}">{badge_letter}</span>'
                    else:
                        score_line = ""
                        badge_html = ""

                    cells += f'''<div class="cal-day has-match" data-date="{date_str}">
  <span class="day-num">{day}</span>
  <div class="match-info">
    <div class="cal-match">
      <span class="match-opp">{mi["opp"]}</span>
      {score_line}
      {badge_html}
    </div>
    <span class="match-time">{mi["time"]}</span>
  </div>
</div>'''
            else:
                cells += f'<div class="cal-day" data-date="{date_str}"><span class="day-num">{day}</span></div>'

        trailing = (7 - (first_weekday + num_days) % 7) % 7
        cells += '<div class="cal-day empty"></div>' * trailing

        months_html += f'''
      <div class="cal-month" data-month="{year}-{month:02d}">
        <h3>{month_name} {year} <span class="cal-toggle">▾</span></h3>
        <div class="cal-grid">
          {headers}
          {cells}
        </div>
      </div>'''

    calendar_js = """
    <script>
    (function(){
      var today = new Date(); today.setHours(0,0,0,0);
      var todayStr = today.getFullYear()+'-'+String(today.getMonth()+1).padStart(2,'0')+'-'+String(today.getDate()).padStart(2,'0');
      var curMonth = today.getFullYear()+'-'+String(today.getMonth()+1).padStart(2,'0');
      document.querySelectorAll('.cal-day[data-date]').forEach(function(el){
        if(el.dataset.date < todayStr) el.classList.add('past');
        else if(el.dataset.date === todayStr) el.classList.add('today');
      });
      document.querySelectorAll('.cal-month[data-month]').forEach(function(el){
        if(el.dataset.month < curMonth) el.classList.add('collapsed');
        el.querySelector('h3').addEventListener('click', function(){
          el.classList.toggle('collapsed');
        });
      });
    })();
    </script>"""

    return months_html, calendar_js


def generate_calendar(matches, cfg, team_key=None):
    """Generate calendar HTML page. matches = list of dicts from scrape or DB."""
    # Parse matches into dict keyed by (year, month, day)
    match_by_date = {}
    for m in matches:
        d = datetime.strptime(m["date"], "%Y-%m-%d").date()
        is_home = m["is_home"]
        opponent = m["away_team"] if is_home else m["home_team"]
        opp_short = calendar_short_name(opponent)
        display_opp = opp_short if is_home else f"@{opp_short}"

        if m["played"] and m["home_score"] is not None:
            our_score = m["home_score"] if is_home else m["away_score"]
            opp_score = m["away_score"] if is_home else m["home_score"]
            is_win = our_score > opp_score
            score_str = f"{our_score}-{opp_score}"
        else:
            is_win = None
            score_str = None

        match_by_date[(d.year, d.month, d.day)] = {
            "opp": display_opp,
            "time": m.get("time", ""),
            "score": score_str,
            "win": is_win,
            "home": is_home,
            "played": m["played"],
        }

    # Use shared calendar builder
    months_html, calendar_js = _build_calendar_grid(match_by_date, multi_team=False)

    # Summary stats
    played = [m for m in matches if m["played"] and m["home_score"] is not None]
    upcoming_count = len(matches) - len(played)
    total = len(matches)
    wins = sum(1 for m in played if (m["home_score"] > m["away_score"]) == m["is_home"])
    losses = len(played) - wins
    home_played = [m for m in played if m["is_home"]]
    away_played = [m for m in played if not m["is_home"]]
    home_w = sum(1 for m in home_played if m["home_score"] > m["away_score"])
    home_l = len(home_played) - home_w
    away_w = sum(1 for m in away_played if m["away_score"] > m["home_score"])
    away_l = len(away_played) - away_w
    upcoming_html = f'<div class="header-stat"><div class="val accent">{upcoming_count}</div><div class="label">Hátralévő</div></div>' if upcoming_count else ""

    return f"""<!DOCTYPE html>
<html lang="hu">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{cfg["team_short"]} — Menetrend 2025/26</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap');
:root {{
  --bg:#0a0b0e; --card:#151518; --card-hover:#1e1e24;
  --accent:#C41E3A; --accent2:#00cec9; --accent3:#ff6b6b; --accent4:#fdcb6e;
  --green:#00b894; --red:#e17055;
  --text:#e8e8f0; --text-dim:#8b8da0;
  --border:rgba(255,255,255,0.06);
}}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'Inter',-apple-system,sans-serif;background:var(--bg);color:var(--text);min-height:100vh;padding:24px}}
.dashboard{{max-width:960px;margin:0 auto}}
{NAV_CSS}

/* Header */
.header{{
  background:linear-gradient(135deg,#151518 0%,#2a1218 50%,#1a1518 100%);
  border-radius:20px;padding:32px 28px;margin-bottom:28px;
  border:1px solid var(--border);position:relative;overflow:hidden;
  display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:20px;
}}
.header::after{{
  content:'';position:absolute;top:-50%;right:-20%;width:60%;height:200%;
  background:radial-gradient(circle,rgba(196,30,58,.12) 0%,transparent 70%);pointer-events:none;
}}
.header h1{{
  font-size:2rem;font-weight:900;letter-spacing:-.5px;
  background:linear-gradient(135deg,#fff 30%,var(--accent) 100%);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;
}}
.header .subtitle{{color:var(--text-dim);font-size:.85rem;margin-top:4px}}
.header .subtitle span{{color:var(--accent2);font-weight:600}}
.header-stats{{display:flex;gap:24px;position:relative;z-index:1}}
.header-stat{{text-align:center}}
.header-stat .val{{font-size:1.8rem;font-weight:800}}
.header-stat .label{{font-size:.7rem;color:var(--text-dim);text-transform:uppercase;letter-spacing:.8px;margin-top:2px}}
.green{{color:var(--green)}} .red{{color:var(--red)}} .accent{{color:var(--accent)}}

/* Record badges */
.record-row{{
  display:flex;gap:16px;justify-content:center;flex-wrap:wrap;
  margin-bottom:28px;
}}
.record-badge{{
  background:var(--card);border:1px solid var(--border);border-radius:12px;
  padding:10px 20px;font-size:.8rem;display:flex;align-items:center;gap:8px;
}}
.record-badge .rval{{font-weight:800;font-size:1rem}}

{CALENDAR_CSS}

/* Responsive header */
@media(max-width:900px){{
  .header{{flex-direction:column;text-align:center}}
  .header-stats{{justify-content:center}}
}}
@media(max-width:600px){{
  body{{padding:12px}}
  .header h1{{font-size:1.4rem}}
  .header-stat .val{{font-size:1.3rem}}
}}
</style>
</head>
<body>
<div class="dashboard">
  {_nav_html(active_key=team_key, depth=1)}
  <a href="index.html" class="back-link">&larr; Csapat áttekintő</a>
  <div class="header">
    <div>
      <h1>Menetrend</h1>
      <div class="subtitle">{cfg["team_name"]} &nbsp;|&nbsp; <span>{cfg["group_name"]}</span> &nbsp;|&nbsp; 2025/26 alapszakasz</div>
    </div>
    <div class="header-stats">
      <div class="header-stat"><div class="val green">{wins}</div><div class="label">Győzelem</div></div>
      <div class="header-stat"><div class="val red">{losses}</div><div class="label">Vereség</div></div>
      <div class="header-stat"><div class="val accent">{total}</div><div class="label">Meccs</div></div>
      {upcoming_html}
    </div>
  </div>
  <div class="record-row">
    <div class="record-badge">Hazai <span class="rval green">{home_w}W</span>–<span class="rval red">{home_l}L</span></div>
    <div class="record-badge">Idegen <span class="rval green">{away_w}W</span>–<span class="rval red">{away_l}L</span></div>
  </div>
  <div class="cal-legend">
    <span class="legend-item"><span class="match-badge w" style="font-size:.65rem">W</span> Győzelem</span>
    <span class="legend-item"><span class="match-badge l" style="font-size:.65rem">L</span> Vereség</span>
    <span class="legend-item" style="opacity:.4">▪ Múltbeli</span>
    <span class="legend-item">@ = Idegen pálya</span>
  </div>
  {months_html}
  {calendar_js}
</div>
</body>
</html>"""


def _nav_html(active_key=None, depth=0):
    """Generate navigation bar HTML. depth=0 for root, depth=1 for team subdirs."""
    prefix = "../" if depth == 1 else ""
    items = f'<a href="{prefix}index.html" class="nav-logo">KÖZGÁZ BASKETBALL</a><div class="nav-links">'
    for t in NAV_TEAMS:
        href = f'{prefix}{t["href"]}/index.html'
        cls = ' class="active"' if t["key"] == active_key else ''
        # Disable nav items that don't have a TEAMS config (placeholder)
        if t["key"] not in TEAMS:
            items += f'<span class="nav-link disabled">{t["label"]}</span>'
        else:
            items += f'<a href="{href}"{cls}>{t["label"]}</a>'
    items += '</div>'
    return f'<nav class="site-nav">{items}</nav>'


NAV_CSS = """
.site-nav {
  display:flex; align-items:center; justify-content:space-between;
  margin:0 auto 28px; padding:14px 0;
  border-bottom:1px solid rgba(255,255,255,0.06);
}
.nav-logo {
  font-weight:900; font-size:1rem; letter-spacing:1.5px;
  color:var(--accent); text-decoration:none;
  transition:opacity .2s;
}
.nav-logo:hover { opacity:0.8; }
.nav-links { display:flex; gap:24px; }
.nav-links a, .nav-links .nav-link {
  font-size:0.82rem; font-weight:600; color:var(--text-dim);
  text-decoration:none; text-transform:uppercase; letter-spacing:0.8px;
  transition:color .2s;
}
.nav-links a:hover { color:var(--text); }
.nav-links a.active { color:var(--accent); }
.nav-links .disabled { opacity:0.3; cursor:default; }
@media(max-width:600px) {
  .site-nav { flex-direction:column; gap:12px; text-align:center; }
  .nav-links { gap:16px; flex-wrap:wrap; justify-content:center; }
}
"""


def generate_homepage(team_summaries):
    """Generate the main club homepage with team cards and upcoming matches."""
    # Group team summaries by league, preserving order
    from collections import OrderedDict
    league_order = ["nb2", "budapesti", "mefob"]
    grouped = OrderedDict()
    for lg in league_order:
        grouped[lg] = []
    for ts in team_summaries:
        lg = ts.get("league", "nb2")
        if lg not in grouped:
            grouped[lg] = []
        grouped[lg].append(ts)

    # Build team cards grouped by league
    cards_html = ""
    for lg, teams in grouped.items():
        if not teams:
            continue
        lg_cfg = LEAGUES.get(lg, LEAGUES["nb2"])
        cards_html += f"""
    <div class="league-section">
      <div class="league-header">
        <span class="league-badge" style="background:{lg_cfg['bg']};color:{lg_cfg['color']};border-color:{lg_cfg['border']}">{lg_cfg['label']}</span>
      </div>
      <div class="home-cards">"""
        for ts in teams:
            w = ts.get("wins", 0)
            l = ts.get("losses", 0)
            upcoming = ts.get("upcoming", [])
            next_match = ""
            if upcoming:
                nm = upcoming[0]
                opp = nm["away_team"] if nm["is_home"] else nm["home_team"]
                next_match = f'<div class="next-match">Következő: <strong>{calendar_short_name(opp)}</strong> — {nm["date"][5:].replace("-",".")} {nm.get("time","")}</div>'

            record_html = f'<span class="rec-w">{w}W</span> – <span class="rec-l">{l}L</span>'
            tcfg = _team_color_cfg(TEAMS.get(ts.get("team_key", ""), {}).get("color", lg_cfg["color"]))

            cards_html += f"""
        <a href="{ts['href']}/index.html" class="home-card" style="border-color:{tcfg['border']}">
          <div class="home-card-header">
            <div class="home-card-title">{ts['label']}</div>
            <div class="home-card-group">{ts['group']}</div>
          </div>
          <div class="home-card-record">{record_html}</div>
          {next_match}
          <div class="home-card-arrow">&rarr;</div>
        </a>"""
        cards_html += """
      </div>
    </div>"""

    # Build ALL match rows (all teams), JS will pick the right 5+5 per filter
    all_matches = []
    for ts in team_summaries:
        lg = ts.get("league", "nb2")
        tcfg = _team_color_cfg(TEAMS.get(ts.get("team_key", ""), {}).get("color", LEAGUES.get(lg, LEAGUES["nb2"])["color"]))
        for m in ts.get("recent", []):
            is_home = m["is_home"]
            opp = m["away_team"] if is_home else m["home_team"]
            our = m["home_score"] if is_home else m["away_score"]
            their = m["away_score"] if is_home else m["home_score"]
            win = our > their
            opp_short = calendar_short_name(opp)
            if is_home:
                matchup = f'{ts["short"]} – {opp_short}'
                score_str = f"{our}-{their}"
            else:
                matchup = f'{opp_short} – {ts["short"]}'
                score_str = f"{their}-{our}"
            all_matches.append({
                "date": m["date"], "type": "played", "matchup": matchup,
                "score": score_str, "win": win, "is_home": is_home,
                "team_short": ts["short"], "league": lg, "tcfg": tcfg,
            })
        for m in ts.get("upcoming", []):
            opp = m["away_team"] if m["is_home"] else m["home_team"]
            all_matches.append({
                "date": m["date"], "type": "upcoming",
                "time": m.get("time", ""), "opp": calendar_short_name(opp),
                "is_home": m["is_home"], "team_short": ts["short"],
                "league": lg, "tcfg": tcfg,
            })
    # Sort: played desc by date, then upcoming asc — but we render all and let JS pick
    all_matches.sort(key=lambda x: (x["date"], 0 if x["type"] == "played" else 1))

    # Collect unique team names for filter
    team_names = []
    seen_teams = set()
    for ts in team_summaries:
        if ts["short"] not in seen_teams:
            seen_teams.add(ts["short"])
            tcfg = _team_color_cfg(TEAMS.get(ts.get("team_key", ""), {}).get("color", LEAGUES.get(ts.get("league", "nb2"), LEAGUES["nb2"])["color"]))
            team_names.append({"short": ts["short"], "tcfg": tcfg})

    filter_buttons = '<button class="match-filter active" data-team="all">Mind</button>'
    for tn in team_names:
        filter_buttons += f'<button class="match-filter" data-team="{tn["short"]}" style="--fc:{tn["tcfg"]["color"]};--fb:{tn["tcfg"]["bg"]};--fbd:{tn["tcfg"]["border"]}">{tn["short"]}</button>'

    match_rows = ""
    for item in all_matches:
        tcfg = item["tcfg"]
        tag = f'<span class="row-league-tag" style="color:{tcfg["color"]};background:{tcfg["bg"]};border-color:{tcfg["border"]}">{item["team_short"]}</span>'
        date_str = item["date"][5:].replace("-", ".")
        hv = "vs" if item["is_home"] else "@"
        hv_badge = f'<span class="m-hv">{hv}</span>'
        if item["type"] == "played":
            wl = "W" if item["win"] else "L"
            wl_cls = "w" if item["win"] else "l"
            sc_cls = "win" if item["win"] else "loss"
            match_rows += f"""
        <div class="match-row played" data-team="{item['team_short']}" data-type="played" data-date="{item['date']}" style="display:none">
          <div class="m-date">{date_str}</div>
          {hv_badge}
          {tag}
          <div class="m-detail">{item['matchup']}</div>
          <div class="m-score {sc_cls}">{item['score']}</div>
          <span class="m-badge {wl_cls}">{wl}</span>
        </div>"""
        else:
            opp_display = ('@' if not item['is_home'] else '') + item['opp']
            match_rows += f"""
        <div class="match-row upcoming" data-team="{item['team_short']}" data-type="upcoming" data-date="{item['date']}" style="display:none">
          <div class="m-date">{date_str}</div>
          {hv_badge}
          {tag}
          <div class="m-detail">{opp_display}</div>
          <div class="m-time">{item.get('time','')}</div>
          <span class="m-badge">&nbsp;</span>
        </div>"""

    matches_section = ""
    if match_rows:
        matches_section = f"""
    <div class="section-title">MECCSEK</div>
    <div class="match-filters">{filter_buttons}</div>
    <div class="matches-list">{match_rows}
    </div>
    <script>
    (function(){{
      var btns = document.querySelectorAll('.match-filter');
      var allRows = Array.from(document.querySelectorAll('.match-row'));
      function applyFilter(team) {{
        // Hide all
        allRows.forEach(function(r){{ r.style.display = 'none'; }});
        // Filter by team
        var pool = team === 'all' ? allRows : allRows.filter(function(r){{ return r.dataset.team === team; }});
        // Split played (newest first) and upcoming (soonest first)
        var played = pool.filter(function(r){{ return r.dataset.type === 'played'; }});
        var upcoming = pool.filter(function(r){{ return r.dataset.type === 'upcoming'; }});
        played.sort(function(a,b){{ return b.dataset.date.localeCompare(a.dataset.date); }});
        upcoming.sort(function(a,b){{ return a.dataset.date.localeCompare(b.dataset.date); }});
        // Take last 5 played (show chronologically) + next 5 upcoming
        var last5 = played.slice(0,5).reverse();
        var next5 = upcoming.slice(0,5);
        last5.concat(next5).forEach(function(r){{ r.style.display = ''; }});
      }}
      applyFilter('all');
      btns.forEach(function(btn){{
        btn.addEventListener('click', function(){{
          btns.forEach(function(b){{ b.classList.remove('active'); }});
          btn.classList.add('active');
          applyFilter(btn.dataset.team);
        }});
      }});
    }})();
    </script>"""

    # ── Combined calendar (all teams) ──
    all_matches_by_date = {}  # (year, month, day) → list of match dicts
    for ts in team_summaries:
        lg = ts.get("league", "nb2")
        tcfg = _team_color_cfg(TEAMS.get(ts.get("team_key", ""), {}).get("color", LEAGUES.get(lg, LEAGUES["nb2"])["color"]))
        for m in ts.get("cal_data", []):
            d = datetime.strptime(m["date"], "%Y-%m-%d").date()
            is_home = m["is_home"]
            opponent = m["away_team"] if is_home else m["home_team"]
            opp_short = calendar_short_name(opponent)
            display_opp = opp_short if is_home else f"@{opp_short}"

            if m["played"] and m["home_score"] is not None:
                our_score = m["home_score"] if is_home else m["away_score"]
                opp_score = m["away_score"] if is_home else m["home_score"]
                is_win = our_score > opp_score
                score_str = f"{our_score}-{opp_score}"
            else:
                is_win = None
                score_str = None

            key = (d.year, d.month, d.day)
            if key not in all_matches_by_date:
                all_matches_by_date[key] = []
            all_matches_by_date[key].append({
                "opp": display_opp,
                "time": m.get("time", ""),
                "score": score_str,
                "win": is_win,
                "home": is_home,
                "played": m["played"],
                "team_short": ts["short"],
                "league": lg,
                "lg_cfg": tcfg,
            })

    calendar_section = ""
    if all_matches_by_date:
        months_html, calendar_js = _build_calendar_grid(all_matches_by_date, multi_team=True)

        legend_html = """
    <div class="cal-legend">
      <span class="legend-item"><span class="match-badge w" style="font-size:.65rem">W</span> Győzelem</span>
      <span class="legend-item"><span class="match-badge l" style="font-size:.65rem">L</span> Vereség</span>
      <span class="legend-item" style="opacity:.4">▪ Múltbeli</span>
      <span class="legend-item">@ = Idegen pálya</span>
    </div>"""

        calendar_section = f"""
    <div class="section-title">MECCSNAPTÁR</div>
    {legend_html}
    {months_html}
    {calendar_js}"""

    return f"""<!DOCTYPE html>
<html lang="hu">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Közgáz Basketball</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap');
  :root {{
    --bg:#0a0b0e; --card:#151518; --card-hover:#1e1e24;
    --accent:#C41E3A; --accent2:#00cec9; --accent3:#ff6b6b; --accent4:#fdcb6e;
    --text:#e8e8f0; --text-dim:#8b8da0; --green:#00b894; --red:#e17055;
    --border:rgba(255,255,255,0.06);
  }}
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family:'Inter',-apple-system,sans-serif; background:var(--bg); color:var(--text); min-height:100vh; padding:24px; }}
  .container {{ max-width:900px; margin:0 auto; }}
  {NAV_CSS}

  .hero {{
    text-align:center; padding:48px 20px 40px;
    background:linear-gradient(135deg,#151518 0%,#2a1218 100%);
    border-radius:20px; margin-bottom:36px;
    border:1px solid rgba(196,30,58,0.15);
  }}
  .hero-logo {{
    width:100px; height:100px; border-radius:50%;
    margin-bottom:18px; object-fit:cover;
    box-shadow:0 4px 20px rgba(196,30,58,0.25);
  }}
  .hero h1 {{
    font-size:2.6rem; font-weight:900; letter-spacing:2px;
    background:linear-gradient(135deg,#fff 30%,var(--accent) 100%);
    -webkit-background-clip:text; -webkit-text-fill-color:transparent;
  }}
  .hero .sub {{
    color:var(--text-dim); margin-top:10px; font-size:0.95rem;
    letter-spacing:0.5px;
  }}

  .league-section {{ margin-bottom:32px; }}
  .league-header {{ margin-bottom:14px; }}
  .league-badge {{
    display:inline-block; font-size:0.72rem; font-weight:700; text-transform:uppercase;
    letter-spacing:1.2px; padding:5px 14px; border-radius:20px;
    border:1px solid; background:rgba(255,255,255,0.05);
  }}
  .home-cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); gap:20px; }}
  .home-card {{
    background:linear-gradient(135deg,#1c1820 0%,#151518 100%);
    border-radius:16px; padding:24px; text-decoration:none; color:var(--text);
    border:1px solid rgba(255,255,255,0.08);
    transition:all .25s; position:relative; overflow:hidden;
  }}
  .home-card:hover {{
    transform:translateY(-3px);
    box-shadow:0 12px 32px rgba(0,0,0,0.3);
  }}
  .home-card-header {{ margin-bottom:16px; }}
  .home-card-title {{ font-size:1.3rem; font-weight:800; }}
  .home-card-group {{ font-size:0.78rem; color:var(--text-dim); margin-top:4px; }}
  .home-card-record {{ font-size:1.5rem; font-weight:800; margin-bottom:12px; }}
  .rec-w {{ color:var(--green); }}
  .rec-l {{ color:var(--red); }}
  .next-match {{
    font-size:0.8rem; color:var(--text-dim);
    padding:8px 12px; background:rgba(255,255,255,0.03); border-radius:8px;
  }}
  .next-match strong {{ color:var(--text); }}
  .home-card-arrow {{
    position:absolute; top:24px; right:24px;
    font-size:1.4rem; color:var(--accent); opacity:0.4;
    transition:opacity .2s, transform .2s;
  }}
  .home-card:hover .home-card-arrow {{ opacity:1; transform:translateX(4px); }}

  .section-title {{
    font-size:0.75rem; font-weight:700; text-transform:uppercase;
    letter-spacing:1.5px; color:var(--text-dim); margin-bottom:14px;
  }}

  .match-filters {{
    display:flex; gap:8px; flex-wrap:wrap; margin-bottom:14px;
  }}
  .match-filter {{
    font-family:inherit; font-size:0.72rem; font-weight:700; padding:5px 14px;
    border-radius:20px; border:1px solid rgba(255,255,255,0.12);
    background:rgba(255,255,255,0.04); color:var(--text-dim);
    cursor:pointer; transition:all .2s; letter-spacing:.5px;
  }}
  .match-filter:hover {{ background:rgba(255,255,255,0.08); color:var(--text); }}
  .match-filter.active {{
    background:rgba(196,30,58,0.2); color:var(--accent); border-color:var(--accent);
  }}
  .match-filter[data-team]:not([data-team="all"]).active {{
    background:var(--fb); color:var(--fc); border-color:var(--fbd);
  }}
  .matches-list {{
    background:var(--card); border-radius:14px; padding:6px;
    margin-bottom:32px; border:1px solid var(--border);
  }}
  .match-row {{
    display:grid; grid-template-columns:60px 30px auto 1fr auto 36px;
    align-items:center; padding:12px 16px; gap:8px;
    border-bottom:1px solid var(--border);
    font-size:0.85rem;
  }}
  .match-row:last-child {{ border-bottom:none; }}
  .match-row.played {{ opacity:.45; }}
  .match-row.played:hover {{ opacity:.7; }}
  .m-date {{ color:var(--text-dim); font-size:0.8rem; font-weight:500; }}
  .m-hv {{
    font-size:0.68rem; font-weight:800; text-align:center;
    color:var(--text);
  }}
  .m-detail {{ font-weight:600; }}
  .m-time {{ color:var(--text-dim); font-size:0.78rem; text-align:right; }}
  .m-score {{ text-align:right; }}
  .m-score.win {{ font-weight:700; color:var(--green); }}
  .m-score.loss {{ font-weight:700; color:var(--red); }}
  .row-league-tag {{
    font-size:0.72rem; font-weight:700; padding:3px 8px; border-radius:6px;
    border:1px solid; white-space:nowrap;
  }}
  .m-badge {{
    font-size:0.7rem; font-weight:800; padding:3px 8px; border-radius:6px;
    text-align:center; min-width:28px;
  }}
  .m-badge.home {{ background:rgba(196,30,58,0.15); color:var(--accent); }}
  .m-badge.away {{ background:rgba(253,203,110,0.15); color:var(--accent4); }}
  .m-badge.w {{ background:rgba(0,184,148,0.15); color:var(--green); }}
  .m-badge.l {{ background:rgba(225,112,85,0.15); color:var(--red); }}

  {CALENDAR_CSS}

  @media(max-width:600px) {{
    body {{ padding:10px; }}
    .container {{ overflow-x:hidden; }}
    .hero h1 {{ font-size:1.8rem; }}
    .home-cards {{ grid-template-columns:1fr; }}
    .up-row, .res-row {{ font-size:0.78rem; gap:4px; padding:10px 12px; }}
    .match-filters {{ gap:5px; }}
    .match-filter {{ font-size:0.65rem; padding:4px 9px; letter-spacing:0; }}
    .matches-list {{ padding:4px; overflow:hidden; }}
    .match-row {{ grid-template-columns:48px 22px 1fr auto 32px; padding:10px 8px; gap:5px; font-size:0.78rem; }}
    .row-league-tag {{ display:none; }}
    .m-date {{ font-size:0.7rem; }}
    .m-hv {{ font-size:0.6rem; }}
    .m-badge {{ font-size:0.62rem; padding:2px 6px; min-width:24px; }}
    .m-time {{ font-size:0.7rem; }}
    .section-title {{ font-size:0.68rem; letter-spacing:1px; }}
  }}
</style>
</head>
<body>
<div class="container">
  {_nav_html(depth=0)}
  <div class="hero">
    <img src="kozgaz_logo.png" alt="Közgáz Basketball" class="hero-logo">
    <h1>KÖZGÁZ BASKETBALL</h1>
    <div class="sub">2025/26 szezon</div>
  </div>
  <div class="home-cards">
    {cards_html}
  </div>
  {matches_section}
  {calendar_section}
</div>
</body>
</html>"""


def generate_index(players, cfg, team_key=None):
    cards = ""
    for name, filename, games, ppg, jersey, *rest in players:
        att = rest[0] if rest else None
        att_html = (lambda r: f'<div class="player-att">🏋️ {att} <span class="att-pct">({round(int(r[0])/int(r[1])*100)}%)</span></div>')(att.split('/')) if att else ''
        rank_html = f'<div class="rank">#{jersey}</div>' if jersey else ''
        cards += f"""
      <a href="{filename}" class="player-card">
        {rank_html}
        <div class="pinfo"><div class="player-name">{name}</div>
        <div class="player-meta">{games} meccs &nbsp;|&nbsp; {ppg} PPG</div>{att_html}</div>
      </a>"""

    nav = _nav_html(active_key=team_key, depth=1)
    return f"""<!DOCTYPE html>
<html lang="hu">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{cfg["team_short"]} — Játékos Dashboardok 2025/26</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap');
  :root {{
    --bg:#0a0b0e; --card:#151518; --card-hover:#1e1e24;
    --accent:#C41E3A; --accent2:#00cec9; --text:#e8e8f0; --text-dim:#8b8da0;
    --border:rgba(255,255,255,0.06);
  }}
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family:'Inter',-apple-system,sans-serif; background:var(--bg); color:var(--text); min-height:100vh; padding:24px; }}
  .container {{ max-width:900px; margin:0 auto; }}
  {NAV_CSS}
  .team-header {{
    text-align:center; padding:40px 20px 30px;
    background:linear-gradient(135deg,#151518 0%,#2a1218 100%);
    border-radius:20px; margin-bottom:30px; border:1px solid var(--border);
  }}
  .team-header h1 {{
    font-size:2.2rem; font-weight:900;
    background:linear-gradient(135deg,#fff 30%,var(--accent) 100%);
    -webkit-background-clip:text; -webkit-text-fill-color:transparent;
  }}
  .team-header .sub {{ color:var(--text-dim); margin-top:6px; font-size:0.95rem; }}
  .team-header .sub span {{ color:var(--accent2); font-weight:600; }}
  .team-card {{
    display:flex; align-items:center; gap:20px;
    background:linear-gradient(135deg,#2a1218 0%,#1a1518 100%);
    border-radius:16px; padding:22px 28px; margin-bottom:24px;
    border:1px solid rgba(196,30,58,0.3); text-decoration:none; color:var(--text);
    transition:all 0.25s;
  }}
  .team-card:hover {{
    border-color:var(--accent); transform:translateY(-2px);
    box-shadow:0 10px 30px rgba(196,30,58,0.2);
  }}
  .team-card .team-icon {{
    font-size:2.2rem; min-width:50px; text-align:center;
  }}
  .team-card .team-title {{ font-weight:800; font-size:1.1rem; }}
  .team-card .team-desc {{ font-size:0.78rem; color:var(--text-dim); margin-top:2px; }}
  .team-card .team-arrow {{
    margin-left:auto; font-size:1.4rem; color:var(--accent); opacity:0.5;
    transition:opacity 0.2s, transform 0.2s;
  }}
  .team-card:hover .team-arrow {{ opacity:1; transform:translateX(4px); }}
  .player-grid {{ display:grid; grid-template-columns:repeat(auto-fill, minmax(260px, 1fr)); gap:16px; }}
  .player-card {{
    display:flex; align-items:center; gap:16px;
    background:var(--card); border-radius:14px; padding:18px 20px;
    border:1px solid var(--border); text-decoration:none; color:var(--text);
    transition:all 0.2s;
  }}
  .player-card:hover {{
    background:var(--card-hover); border-color:var(--accent);
    transform:translateY(-2px); box-shadow:0 8px 24px rgba(196,30,58,0.15);
  }}
  .rank {{ font-size:1.1rem; font-weight:800; color:var(--accent); min-width:36px; }}
  .player-name {{ font-weight:700; font-size:0.95rem; }}
  .player-meta {{ font-size:0.75rem; color:var(--text-dim); margin-top:2px; }}
  .player-att {{ font-size:0.7rem; color:var(--accent2); margin-top:3px; }}
  .att-pct {{ opacity:0.7; }}
  .back-link {{
    display:inline-block; color:var(--text-dim); text-decoration:none;
    font-size:0.82rem; font-weight:600; margin-bottom:16px; opacity:0.7;
    transition:color 0.2s, opacity 0.2s;
  }}
  .back-link:hover {{ color:var(--accent); opacity:1; }}
</style>
</head>
<body>
<div class="container">
  {nav}
  <a href="../index.html" class="back-link">&larr; Főoldal</a>
  <div class="team-header">
    <h1>{cfg["team_name"]}</h1>
    <div class="sub">{cfg["group_name"]} &nbsp;|&nbsp; <span>2025/26 alapszakasz</span> &nbsp;|&nbsp; Játékos dashboardok</div>
  </div>
  <a href="csapat.html" class="team-card">
    <div class="team-icon">📊</div>
    <div><div class="team-title">Csapat Statisztikák</div>
    <div class="team-desc">Eredmények, negyedek, run-ok, forgatókönyvek, érdekességek</div></div>
    <div class="team-arrow">→</div>
  </a>
  <a href="naptar.html" class="team-card">
    <div class="team-icon">📅</div>
    <div><div class="team-title">Menetrend / Naptár</div>
    <div class="team-desc">Meccsek havi naptár nézetben, eredmények, hazai/idegen jelölés</div></div>
    <div class="team-arrow">→</div>
  </a>
  <div class="player-grid">{cards}
  </div>
</div>
</body>
</html>"""


def generate_team(team_key):
    cfg = TEAMS[team_key]
    out_dir = os.path.join(BASE_DIR, cfg["out_dir"])
    os.makedirs(out_dir, exist_ok=True)

    is_pbp = cfg.get("data_source") == "pbp"

    if is_pbp:
        conn = _pbp_connection()
        tp = cfg["team_pattern_broad"]
        src_label = f"PBP ({cfg['pbp_comp_code']})"
    else:
        conn = get_connection()
        tp = _team_like(conn, cfg)
        src_label = f"Scoresheet ({cfg['comp_prefix']})"

    print(f"\n{'='*50}")
    print(f"  {cfg['team_name']} — {cfg['group_name']}")
    print(f"  Pattern: {tp}  |  Forrás: {src_label}")
    print(f"{'='*50}")

    roster = get_roster_pbp(conn, cfg, tp) if is_pbp else get_roster(conn, cfg, tp)
    if not roster:
        print(f"  ⚠ Nincs játékos adat!")
        conn.close()
        return

    # Fetch training attendance from Google Sheets (Közgáz B only)
    att_data = {}
    if team_key == "kozgaz-b":
        print(f"\n  Edzéslátogatás fetch (Google Sheets)...")
        att_data = fetch_training_attendance()
        if att_data:
            print(f"  ✓ {len(att_data)} játékos edzéslátogatása betöltve")
        else:
            print(f"  ⚠ Nem sikerült betölteni az edzéslátogatást")

    generated = []
    for idx, player in enumerate(roster):
        lic = player[0]  # license_number (scoresheet) or player_name (PBP)
        name = player[1]
        slug = slugify(name)

        if is_pbp:
            game_log = get_game_log_pbp(conn, cfg, tp, lic)
            quarter_stats = get_quarter_stats_pbp(conn, cfg, tp, lic)
            opp_stats = get_opponent_ppg_pbp(conn, cfg, tp, lic)
            tech, unsport = get_tech_unsport_pbp(conn, cfg, tp, lic)
        else:
            game_log = get_game_log(conn, cfg, tp, lic)
            quarter_stats = get_quarter_stats(conn, cfg, tp, lic)
            opp_stats = get_opponent_ppg(conn, cfg, tp, lic)
            tech, unsport = get_tech_unsport(conn, cfg, tp, lic)

        # Training attendance (Közgáz B only)
        att = att_data.get(name)

        html = generate_html(player, game_log, quarter_stats, opp_stats, tech, unsport, cfg, training_att=att)

        filename = f"{slug}.html"
        filepath = os.path.join(out_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(html)

        # For PBP: no jersey number available, use empty string
        jersey_display = player[2] if player[2] else ''
        generated.append((name, filename, player[3], player[5], jersey_display, att))
        print(f"  ✓ {name} → {filename}")

    # Team dashboard (3 views: all / home / away)
    if is_pbp:
        team_stats = get_team_stats_pbp(conn, cfg, tp)
        team_stats_home = get_team_stats_pbp(conn, cfg, tp, hv_filter='H')
        team_stats_away = get_team_stats_pbp(conn, cfg, tp, hv_filter='V')
    else:
        team_stats = get_team_stats(conn, cfg, tp)
        team_stats_home = get_team_stats(conn, cfg, tp, hv_filter='H')
        team_stats_away = get_team_stats(conn, cfg, tp, hv_filter='V')
    team_html = generate_team_dashboard(team_stats, cfg, team_key=team_key, att_data=att_data,
                                        stats_home=team_stats_home, stats_away=team_stats_away)
    with open(os.path.join(out_dir, "csapat.html"), "w", encoding="utf-8") as f:
        f.write(team_html)
    print(f"\n  ✓ csapat.html (csapat dashboard)")

    # Calendar — scrape from MKOSZ (or megye for county), fall back to SQLite/PBP
    if cfg.get("county"):
        print(f"\n  Meccsnaptár scraping (megye.hunbasket.hu)...")
        cal_data = scrape_schedule_county(cfg)
    else:
        print(f"\n  Meccsnaptár scraping (mkosz.hu)...")
        cal_data = scrape_schedule(cfg)
    if cal_data:
        played = sum(1 for m in cal_data if m["played"])
        upcoming = len(cal_data) - played
        print(f"  ✓ {len(cal_data)} meccs scraped ({played} lejátszott, {upcoming} következő)")
    else:
        print(f"  ⚠ Scraping sikertelen, DB fallback...")
        cal_data = get_calendar_data_db_pbp(conn, cfg, tp) if is_pbp else get_calendar_data_db(conn, cfg, tp)
    if cal_data:
        cal_html = generate_calendar(cal_data, cfg, team_key=team_key)
        with open(os.path.join(out_dir, "naptar.html"), "w", encoding="utf-8") as f:
            f.write(cal_html)
        print(f"  ✓ naptar.html (meccsnaptár, {len(cal_data)} meccs)")

    index_html = generate_index(generated, cfg, team_key=team_key)
    with open(os.path.join(out_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write(index_html)
    print(f"  ✓ index.html")

    conn.close()
    print(f"  Összesen {len(generated)} játékos + 1 csapat dashboard → {cfg['out_dir']}/")

    # Return schedule data for homepage
    return cal_data


def generate_site():
    """Generate all team dashboards and the homepage."""
    team_data = {}
    for key in TEAMS:
        cal = generate_team(key)
        team_data[key] = cal or []

    # Build homepage summaries
    summaries = []
    for t in NAV_TEAMS:
        key = t["key"]
        if key not in TEAMS:
            continue
        cfg = TEAMS[key]
        matches = team_data.get(key, [])
        played = [m for m in matches if m.get("played") and m.get("home_score") is not None]
        upcoming = [m for m in matches if not m.get("played") or m.get("home_score") is None]
        upcoming.sort(key=lambda x: x["date"])

        wins = sum(1 for m in played if (m["home_score"] > m["away_score"]) == m["is_home"])
        losses = len(played) - wins

        recent = sorted(played, key=lambda x: x["date"])

        summaries.append({
            "key": key,
            "label": t["label"],
            "href": t["href"],
            "group": cfg["group_name"],
            "short": cfg["team_short"],
            "league": cfg.get("league", "nb2"),
            "team_key": key,
            "wins": wins,
            "losses": losses,
            "upcoming": upcoming,
            "recent": recent,
            "cal_data": matches,
        })

    hp = generate_homepage(summaries)
    with open(os.path.join(BASE_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(hp)
    print(f"\n  ✓ index.html (főoldal)")


def main():
    if len(sys.argv) > 1:
        keys = sys.argv[1:]
        if "all" in keys or "site" in keys:
            generate_site()
        else:
            for key in keys:
                if key in TEAMS:
                    generate_team(key)
                else:
                    print(f"  ⚠ Ismeretlen csapat: {key}. Elérhető: {', '.join(TEAMS.keys())}, all, site")
    else:
        generate_site()


if __name__ == "__main__":
    main()
