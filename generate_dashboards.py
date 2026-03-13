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

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nb2_full.sqlite")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ---- TEAM CONFIGURATIONS ----
TEAMS = {
    "kozgaz-b": {
        "team_pattern": "%KÖZGÁZ%DSK/B%",
        "team_pattern_broad": "%KÖZGÁZ%",  # for groups where only one KÖZGÁZ team plays
        "comp_prefix": "F2KE%",
        "team_name": "KÖZGÁZ SC ÉS DSK/B",
        "team_short": "KÖZGÁZ B",
        "group_name": "NB2 Kelet",
        "out_dir": "dashboards",
        "mkosz_season": "x2526",
        "mkosz_comp": "hun3k",
        "mkosz_team_id": "9239",
    },
    "kozgaz-a": {
        "team_pattern": "%KÖZGÁZ%DSK/A%",
        "team_pattern_broad": "%KÖZGÁZ%",
        "comp_prefix": "F2KB%",
        "team_name": "KÖZGÁZ SC ÉS DSK/A",
        "team_short": "KÖZGÁZ A",
        "group_name": "NB2 Közép B",
        "out_dir": "dashboards-a",
        "mkosz_season": "x2526",
        "mkosz_comp": "hun3kob",
        "mkosz_team_id": "9219",
    },
}

# Navigation structure for the site
NAV_TEAMS = [
    {"key": "kozgaz-b", "label": "Öregek NB2", "href": "dashboards"},
    {"key": "kozgaz-a", "label": "Fiatalok NB2", "href": "dashboards-a"},
    {"key": "leftoverz", "label": "Leftoverz", "href": "leftoverz"},
]

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


def generate_html(player_data, game_log, quarter_stats, opp_stats, tech, unsport, cfg):
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
  .game-log {{ width:100%; border-collapse:collapse; font-size:0.82rem; }}
  .game-log th {{ text-align:left; font-size:0.7rem; text-transform:uppercase; letter-spacing:0.8px; color:var(--text-dim); padding:8px 10px; border-bottom:1px solid var(--border); font-weight:600; }}
  .game-log td {{ padding:8px 10px; border-bottom:1px solid var(--border); }}
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
  @media (max-width:900px) {{
    .grid-2,.grid-4 {{ grid-template-columns:1fr; }}
    .header {{ flex-direction:column; text-align:center; }}
    .header-stats {{ margin-left:0; justify-content:center; }}
  }}
</style>
</head>
<body>
<div class="dashboard">
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
    <table class="game-log">
      <thead><tr><th>Dátum</th><th>Ellenfél</th><th></th><th>Pont</th><th>2FG</th><th>3FG</th><th>FT</th><th>PF</th><th>Csapat%</th></tr></thead>
      <tbody id="gameLogBody"></tbody>
    </table>
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


def get_team_stats(conn, cfg, tp):
    """Gather all team-level statistics for the team dashboard."""
    cp = cfg["comp_prefix"]
    d = {}

    # Basic record
    r = conn.execute("""
        WITH kg AS (
            SELECT m.match_id, m.match_date,
                   CASE WHEN m.team_a LIKE ? THEN 'H' ELSE 'V' END as hv,
                   CASE WHEN m.team_a LIKE ? THEN m.team_b ELSE m.team_a END as opp,
                   CASE WHEN m.team_a LIKE ? THEN m.score_a ELSE m.score_b END as kg,
                   CASE WHEN m.team_a LIKE ? THEN m.score_b ELSE m.score_a END as op
            FROM matches m WHERE m.match_id LIKE ? AND (m.team_a LIKE ? OR m.team_b LIKE ?)
        )
        SELECT COUNT(*), SUM(CASE WHEN kg>op THEN 1 ELSE 0 END),
               SUM(CASE WHEN kg<op THEN 1 ELSE 0 END),
               SUM(kg), SUM(op),
               ROUND(1.0*SUM(kg)/COUNT(*),1), ROUND(1.0*SUM(op)/COUNT(*),1),
               MAX(kg), MIN(kg), MAX(op), MIN(op),
               MAX(kg-op), MIN(kg-op),
               SUM(CASE WHEN hv='H' AND kg>op THEN 1 ELSE 0 END),
               SUM(CASE WHEN hv='H' THEN 1 ELSE 0 END),
               SUM(CASE WHEN hv='V' AND kg>op THEN 1 ELSE 0 END),
               SUM(CASE WHEN hv='V' THEN 1 ELSE 0 END)
        FROM kg
    """, (tp, tp, tp, tp, cp, tp, tp)).fetchone()
    d["games"], d["wins"], d["losses"] = r[0], r[1], r[2]
    d["scored"], d["allowed"] = r[3], r[4]
    d["ppg"], d["opp_ppg"] = r[5], r[6]
    d["best_score"], d["worst_score"] = r[7], r[8]
    d["most_allowed"], d["least_allowed"] = r[9], r[10]
    d["biggest_win"], d["biggest_loss"] = r[11], r[12]
    d["home_w"], d["home_g"] = r[13], r[14]
    d["away_w"], d["away_g"] = r[15], r[16]

    # Game log
    d["game_log"] = conn.execute("""
        WITH kg AS (
            SELECT m.match_id, m.match_date,
                   CASE WHEN m.team_a LIKE ? THEN 'H' ELSE 'V' END as hv,
                   CASE WHEN m.team_a LIKE ? THEN m.team_b ELSE m.team_a END as opp,
                   CASE WHEN m.team_a LIKE ? THEN m.score_a ELSE m.score_b END as kg,
                   CASE WHEN m.team_a LIKE ? THEN m.score_b ELSE m.score_a END as op
            FROM matches m WHERE m.match_id LIKE ? AND (m.team_a LIKE ? OR m.team_b LIKE ?)
        )
        SELECT match_date, hv, opp, kg, op FROM kg ORDER BY match_date
    """, (tp, tp, tp, tp, cp, tp, tp)).fetchall()

    # Quarter averages
    d["quarters"] = conn.execute("""
        WITH kg AS (
            SELECT m.match_id,
                   CASE WHEN m.team_a LIKE ? THEN 'A' ELSE 'B' END as t
            FROM matches m WHERE m.match_id LIKE ? AND (m.team_a LIKE ? OR m.team_b LIKE ?)
        )
        SELECT qs.quarter,
               ROUND(1.0*SUM(CASE WHEN kg.t='A' THEN qs.score_a ELSE qs.score_b END)/COUNT(*),1),
               ROUND(1.0*SUM(CASE WHEN kg.t='A' THEN qs.score_b ELSE qs.score_a END)/COUNT(*),1),
               SUM(CASE WHEN (CASE WHEN kg.t='A' THEN qs.score_a ELSE qs.score_b END) >
                             (CASE WHEN kg.t='A' THEN qs.score_b ELSE qs.score_a END) THEN 1 ELSE 0 END),
               SUM(CASE WHEN (CASE WHEN kg.t='A' THEN qs.score_a ELSE qs.score_b END) <
                             (CASE WHEN kg.t='A' THEN qs.score_b ELSE qs.score_a END) THEN 1 ELSE 0 END)
        FROM quarter_scores qs JOIN kg ON qs.match_id=kg.match_id
        WHERE qs.quarter IN ('1','2','3','4')
        GROUP BY qs.quarter ORDER BY qs.quarter
    """, (tp, cp, tp, tp)).fetchall()

    # Scenario analysis: halftime lead/deficit
    d["scenarios"] = conn.execute("""
        WITH kg AS (
            SELECT m.match_id,
                   CASE WHEN m.team_a LIKE ? THEN 'A' ELSE 'B' END as t,
                   CASE WHEN m.team_a LIKE ? THEN m.score_a ELSE m.score_b END as kg_final,
                   CASE WHEN m.team_a LIKE ? THEN m.score_b ELSE m.score_a END as opp_final
            FROM matches m WHERE m.match_id LIKE ? AND (m.team_a LIKE ? OR m.team_b LIKE ?)
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
    """, (tp, tp, tp, cp, tp, tp)).fetchall()

    # Top 5 scoring runs FOR and AGAINST
    for label, is_team_val in [("runs_for", 1), ("runs_against", 0)]:
        opp_val = 1 - is_team_val
        rows = conn.execute(f"""
            WITH kg AS (
                SELECT m.match_id, m.match_date,
                       CASE WHEN m.team_a LIKE ? THEN 'A' ELSE 'B' END as t,
                       CASE WHEN m.team_a LIKE ? THEN m.team_b ELSE m.team_a END as opp
                FROM matches m WHERE m.match_id LIKE ? AND (m.team_a LIKE ? OR m.team_b LIKE ?)
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
        """, (tp, tp, cp, tp, tp)).fetchall()
        d[label] = rows

    # Team shooting totals
    r = conn.execute("""
        WITH kg AS (
            SELECT m.match_id,
                   CASE WHEN m.team_a LIKE ? THEN 'A' ELSE 'B' END as t
            FROM matches m WHERE m.match_id LIKE ? AND (m.team_a LIKE ? OR m.team_b LIKE ?)
        )
        SELECT SUM(CASE WHEN se.made=1 AND se.points=3 THEN 1 ELSE 0 END) as fg3,
               SUM(CASE WHEN se.made=1 AND se.points=2 THEN 1 ELSE 0 END) as fg2,
               SUM(CASE WHEN se.made=1 AND se.points=1 THEN 1 ELSE 0 END) as ftm,
               SUM(CASE WHEN se.points IN (0,1) THEN 1 ELSE 0 END) as fta
        FROM scoring_events se JOIN kg ON se.match_id=kg.match_id AND se.team=kg.t
    """, (tp, cp, tp, tp)).fetchone()
    d["fg3"], d["fg2"], d["ftm"], d["fta"] = r

    # Top scorers (for fun facts)
    d["top_scorers"] = conn.execute("""
        WITH kg AS (
            SELECT m.match_id,
                   CASE WHEN m.team_a LIKE ? THEN 'A' ELSE 'B' END as t
            FROM matches m WHERE m.match_id LIKE ? AND (m.team_a LIKE ? OR m.team_b LIKE ?)
        )
        SELECT pgs.name, SUM(pgs.points) as tp,
               ROUND(1.0*SUM(pgs.points)/COUNT(*),1) as ppg, COUNT(*) as gp
        FROM player_game_stats pgs JOIN kg ON pgs.match_id=kg.match_id AND pgs.team=kg.t
        GROUP BY pgs.license_number ORDER BY tp DESC LIMIT 3
    """, (tp, cp, tp, tp)).fetchall()

    # Players used count
    d["players_used"] = conn.execute("""
        WITH kg AS (
            SELECT m.match_id,
                   CASE WHEN m.team_a LIKE ? THEN 'A' ELSE 'B' END as t
            FROM matches m WHERE m.match_id LIKE ? AND (m.team_a LIKE ? OR m.team_b LIKE ?)
        )
        SELECT COUNT(DISTINCT pgs.license_number)
        FROM player_game_stats pgs JOIN kg ON pgs.match_id=kg.match_id AND pgs.team=kg.t
    """, (tp, cp, tp, tp)).fetchone()[0]

    # Closest games
    d["closest"] = conn.execute("""
        WITH kg AS (
            SELECT m.match_date,
                   CASE WHEN m.team_a LIKE ? THEN m.team_b ELSE m.team_a END as opp,
                   CASE WHEN m.team_a LIKE ? THEN m.score_a ELSE m.score_b END as kg,
                   CASE WHEN m.team_a LIKE ? THEN m.score_b ELSE m.score_a END as op
            FROM matches m WHERE m.match_id LIKE ? AND (m.team_a LIKE ? OR m.team_b LIKE ?)
        )
        SELECT match_date, opp, kg, op, ABS(kg-op) as diff
        FROM kg ORDER BY diff ASC LIMIT 3
    """, (tp, tp, tp, cp, tp, tp)).fetchall()

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
            played = True
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


def generate_team_dashboard(stats, cfg, team_key=None):
    """Generate team-level dashboard HTML."""
    d = stats
    games = d["games"]
    team_name = cfg["team_name"]
    group_name = cfg["group_name"]
    team_short = cfg["team_short"]

    # Game log JS
    js_gamelog = []
    for g in d["game_log"]:
        date, hv, opp, kg, op = g
        js_gamelog.append({
            "date": date[5:].replace("-", "."), "hv": hv,
            "opp": shorten_opponent(opp),
            "kg": kg, "op": op,
            "res": "W" if kg > op else "L"
        })

    # Quarter data for chart
    q_kg = [q[1] for q in d["quarters"]]
    q_op = [q[2] for q in d["quarters"]]
    q_won = [q[3] for q in d["quarters"]]
    q_lost = [q[4] for q in d["quarters"]]

    # Scenario map
    sc = {s[0]: (s[1], s[2]) for s in d["scenarios"]}

    # Shooting
    ft_pct = round(100 * d["ftm"] / d["fta"]) if d["fta"] > 0 else 0
    pts_from_3 = d["fg3"] * 3
    pts_from_2 = d["fg2"] * 2
    pts_from_ft = d["ftm"]
    total_shot_pts = pts_from_3 + pts_from_2 + pts_from_ft
    pct_3 = round(100 * pts_from_3 / total_shot_pts) if total_shot_pts else 0
    pct_2 = round(100 * pts_from_2 / total_shot_pts) if total_shot_pts else 0
    pct_ft = round(100 * pts_from_ft / total_shot_pts) if total_shot_pts else 0

    # Runs tables
    def run_rows(runs, label):
        rows = ""
        for i, r in enumerate(runs):
            dt, opp, sq, eq, pts, bsk = r
            qspan = f"Q{sq}" if sq == eq else f"Q{sq}→Q{eq}"
            rows += f'<tr><td>{dt[5:].replace("-",".")}</td><td>{shorten_opponent(opp)}</td><td style="font-weight:800;color:var(--accent)">{pts}-0</td><td>{qspan}</td><td>{bsk}</td></tr>'
        return rows

    runs_for_html = run_rows(d["runs_for"], "for")
    runs_agn_html = run_rows(d["runs_against"], "against")

    # Fun facts
    facts = []
    best_q = max(range(4), key=lambda i: q_kg[i])
    worst_q = min(range(4), key=lambda i: q_kg[i])
    facts.append(f'Legerősebb negyed: <b>Q{best_q+1}</b> ({q_kg[best_q]} pont/meccs)')
    facts.append(f'Leggyengébb negyed: <b>Q{worst_q+1}</b> ({q_kg[worst_q]} pont/meccs)')

    if d["runs_for"]:
        facts.append(f'Leghosszabb saját run: <b>{d["runs_for"][0][4]}-0</b> ({d["runs_for"][0][1][:15]} ellen)')
    if d["runs_against"]:
        facts.append(f'Leghosszabb kapott run: <b>{d["runs_against"][0][4]}-0</b> ({d["runs_against"][0][1][:15]} ellen)')

    ht_lead = sc.get("HT_LEAD", (0, 0))
    ht_trail = sc.get("HT_TRAIL", (0, 0))
    if ht_lead[0] > 0:
        facts.append(f'Félidőben vezetve: <b>{ht_lead[1]}/{ht_lead[0]} győzelem</b> ({round(100*ht_lead[1]/ht_lead[0])}%)')
    if ht_trail[0] > 0:
        forditas = ht_trail[1]
        facts.append(f'Félidős hátrányból: <b>{forditas} fordítás {ht_trail[0]}-ból</b>')

    facts.append(f'Hazai mérleg: <b>{d["home_w"]}-{d["home_g"]-d["home_w"]}</b> | Vendég: <b>{d["away_w"]}-{d["away_g"]-d["away_w"]}</b>')
    facts.append(f'<b>{d["players_used"]}</b> játékos fordult meg a keretben')
    facts.append(f'FT%: <b>{ft_pct}%</b> ({d["ftm"]}/{d["fta"]})')

    ts = d["top_scorers"]
    if len(ts) >= 2:
        top2_pts = ts[0][1] + ts[1][1]
        facts.append(f'Top 2 pontszerző ({ts[0][0].title()}, {ts[1][0].title()}) a csapat pontjainak <b>{round(100*top2_pts/d["scored"])}%</b>-át adja')

    if d["closest"]:
        c = d["closest"][0]
        facts.append(f'Legszorosabb meccs: <b>{c[2]}-{c[3]}</b> ({shorten_opponent(c[1])}, {c[0][5:].replace("-",".")})')

    facts_html = "".join(f'<div class="fact-item">{f}</div>' for f in facts)

    # Scoring trend for chart
    kg_scores = [g["kg"] for g in js_gamelog]
    op_scores = [g["op"] for g in js_gamelog]
    trend_labels = [g["date"] for g in js_gamelog]
    y_max = max(max(kg_scores, default=0), max(op_scores, default=0)) + 10

    # Closest/blowout for game log coloring
    max_scored = max(kg_scores, default=1)

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
  .game-log {{ width:100%; border-collapse:collapse; font-size:0.82rem; }}
  .game-log th {{ text-align:left; font-size:0.7rem; text-transform:uppercase; letter-spacing:0.8px; color:var(--text-dim); padding:8px 10px; border-bottom:1px solid var(--border); font-weight:600; }}
  .game-log td {{ padding:8px 10px; border-bottom:1px solid var(--border); }}
  .game-log tr:last-child td {{ border-bottom:none; }}
  .game-log tr:hover {{ background:rgba(196,30,58,0.06); }}
  .badge {{ display:inline-block; padding:2px 8px; border-radius:6px; font-size:0.7rem; font-weight:700; }}
  .badge.w {{ background:rgba(0,184,148,0.15); color:var(--green); }}
  .badge.l {{ background:rgba(225,112,85,0.15); color:var(--red); }}
  .badge.h {{ background:rgba(196,30,58,0.15); color:var(--accent); }}
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
  {NAV_CSS}
  .mb20 {{ margin-bottom:20px; }}
  @media (max-width:900px) {{
    .grid-2,.grid-3,.grid-4,.grid-5 {{ grid-template-columns:1fr; }}
    .header {{ flex-direction:column; text-align:center; }}
    .header-stats {{ margin-left:0; justify-content:center; }}
  }}
</style>
</head>
<body>
<div class="dashboard">
  {_nav_html(active_key=team_key, depth=1)}
  <div class="header">
    <div class="header-info">
      <h1>{team_name}</h1>
      <div class="subtitle">
        <span>CSAPAT STATISZTIKÁK</span> &nbsp;|&nbsp; {group_name} &nbsp;|&nbsp; 2025/26 alapszakasz
      </div>
    </div>
    <div class="header-stats">
      <div class="header-stat"><div class="val" style="color:var(--green)">{d["wins"]}</div><div class="label">Győzelem</div></div>
      <div class="header-stat"><div class="val" style="color:var(--red)">{d["losses"]}</div><div class="label">Vereség</div></div>
      <div class="header-stat"><div class="val" style="color:var(--accent)">{d["ppg"]}</div><div class="label">Dobott/m</div></div>
      <div class="header-stat"><div class="val" style="color:var(--accent3)">{d["opp_ppg"]}</div><div class="label">Kapott/m</div></div>
      <div class="header-stat"><div class="val" style="color:var(--accent4)">{round(d["ppg"]-d["opp_ppg"],1)}</div><div class="label">Kül./m</div></div>
    </div>
  </div>

  <div class="grid grid-5 mb20">
    <div class="card mini-stat"><div class="big" style="color:var(--accent)">{d["scored"]}</div><div class="desc">Összes dobott</div></div>
    <div class="card mini-stat"><div class="big" style="color:var(--accent3)">{d["allowed"]}</div><div class="desc">Összes kapott</div></div>
    <div class="card mini-stat"><div class="big" style="color:var(--green)">{d["best_score"]}</div><div class="desc">Legtöbb dobott</div></div>
    <div class="card mini-stat"><div class="big" style="color:var(--red)">{d["most_allowed"]}</div><div class="desc">Legtöbb kapott</div></div>
    <div class="card mini-stat"><div class="big" style="color:var(--accent4)">{d["players_used"]}</div><div class="desc">Játékos a keretben</div></div>
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
      <table class="scenario-tbl">
        <tr>
          <td>Félidőben <b style="color:var(--green)">vezet</b></td>
          <td style="font-weight:800;color:var(--green)">{sc.get('HT_LEAD',(0,0))[1]}/{sc.get('HT_LEAD',(0,0))[0]} győzelem</td>
          <td style="color:var(--text-dim)">{round(100*sc.get('HT_LEAD',(0,0))[1]/sc.get('HT_LEAD',(1,0))[0]) if sc.get('HT_LEAD',(1,0))[0] else 0}%</td>
        </tr>
        <tr>
          <td>Félidőben <b style="color:var(--red)">hátrányban</b></td>
          <td style="font-weight:800;color:var(--red)">{sc.get('HT_TRAIL',(0,0))[1]}/{sc.get('HT_TRAIL',(0,0))[0]} fordítás</td>
          <td style="color:var(--text-dim)">{round(100*sc.get('HT_TRAIL',(0,0))[1]/sc.get('HT_TRAIL',(1,0))[0]) if sc.get('HT_TRAIL',(1,0))[0] else 0}%</td>
        </tr>
        <tr>
          <td>3 negyed után <b style="color:var(--green)">vezet</b></td>
          <td style="font-weight:800;color:var(--green)">{sc.get('3Q_LEAD',(0,0))[1]}/{sc.get('3Q_LEAD',(0,0))[0]} győzelem</td>
          <td style="color:var(--text-dim)">{round(100*sc.get('3Q_LEAD',(0,0))[1]/sc.get('3Q_LEAD',(1,0))[0]) if sc.get('3Q_LEAD',(1,0))[0] else 0}%</td>
        </tr>
        <tr>
          <td>3 negyed után <b style="color:var(--red)">hátrányban</b></td>
          <td style="font-weight:800;color:var(--red)">{sc.get('3Q_TRAIL',(0,0))[1]}/{sc.get('3Q_TRAIL',(0,0))[0]} fordítás</td>
          <td style="color:var(--text-dim)">{round(100*sc.get('3Q_TRAIL',(0,0))[1]/sc.get('3Q_TRAIL',(1,0))[0]) if sc.get('3Q_TRAIL',(1,0))[0] else 0}%</td>
        </tr>
      </table>
    </div>
  </div>

  <div class="grid grid-2 mb20">
    <div class="card">
      <h3>Top 5 saját scoring run</h3>
      <table class="run-tbl">
        <thead><tr><th>Dátum</th><th>Ellenfél</th><th>Run</th><th>Negyed</th><th>Kosár</th></tr></thead>
        <tbody>{runs_for_html}</tbody>
      </table>
    </div>
    <div class="card">
      <h3>Top 5 kapott scoring run</h3>
      <table class="run-tbl">
        <thead><tr><th>Dátum</th><th>Ellenfél</th><th>Run</th><th>Negyed</th><th>Kosár</th></tr></thead>
        <tbody>{runs_agn_html}</tbody>
      </table>
    </div>
  </div>

  <div class="card mb20">
    <h3>Meccsek</h3>
    <table class="game-log">
      <thead><tr><th>Dátum</th><th></th><th>Ellenfél</th><th>Eredmény</th><th></th><th>Különbség</th></tr></thead>
      <tbody id="gameLogBody"></tbody>
    </table>
  </div>

  <div class="card mb20">
    <h3>Érdekességek &amp; Fun Facts</h3>
    {facts_html}
  </div>
</div>

<script>
Chart.defaults.color='#8b8da0';
Chart.defaults.borderColor='rgba(255,255,255,0.06)';
Chart.defaults.font.family="'Inter',sans-serif";

const games = {json.dumps(js_gamelog, ensure_ascii=False)};
const tbody = document.getElementById('gameLogBody');
games.forEach(g => {{
  const diff = g.kg - g.op;
  const diffStr = diff > 0 ? '+'+diff : ''+diff;
  const diffColor = diff > 0 ? 'var(--green)' : 'var(--red)';
  const barW = Math.min(Math.abs(diff), 40);
  const tr = document.createElement('tr');
  tr.innerHTML = '<td>'+g.date+'</td>'
    +'<td><span class="badge '+(g.hv==='H'?'h':'v')+'">'+g.hv+'</span></td>'
    +'<td>'+g.opp+'</td>'
    +'<td style="font-weight:700;">'+g.kg+'-'+g.op+'</td>'
    +'<td><span class="badge '+(g.res==='W'?'w':'l')+'">'+(g.res==='W'?'GY':'V')+'</span></td>'
    +'<td style="font-weight:700;color:'+diffColor+';">'+diffStr+'</td>';
  tbody.appendChild(tr);
}});

new Chart(document.getElementById('trendChart').getContext('2d'), {{
  type:'line',
  data: {{
    labels: {json.dumps(trend_labels)},
    datasets: [{{
      label:'Dobott', data:{json.dumps(kg_scores)},
      borderColor:'#C41E3A', backgroundColor:'rgba(196,30,58,0.1)',
      fill:true, tension:0.3, pointRadius:5, borderWidth:3,
      pointBackgroundColor: {json.dumps(["#00b894" if g["res"]=="W" else "#e17055" for g in js_gamelog])},
      pointBorderColor: {json.dumps(["#00b894" if g["res"]=="W" else "#e17055" for g in js_gamelog])},
    }}, {{
      label:'Kapott', data:{json.dumps(op_scores)},
      borderColor:'#fd79a8', backgroundColor:'rgba(253,121,168,0.05)',
      fill:true, tension:0.3, pointRadius:4, borderWidth:2, borderDash:[4,3],
      pointBackgroundColor:'#fd79a8', pointBorderColor:'#fd79a8',
    }}]
  }},
  options: {{
    responsive:true, maintainAspectRatio:false,
    plugins: {{ legend:{{ position:'top', labels:{{ usePointStyle:true, font:{{size:11}} }} }} }},
    scales: {{ y:{{ beginAtZero:true, max:{y_max}, grid:{{color:'rgba(255,255,255,0.04)'}} }}, x:{{ grid:{{display:false}} }} }}
  }}
}});

new Chart(document.getElementById('quarterChart').getContext('2d'), {{
  type:'bar',
  data: {{
    labels:['Q1','Q2','Q3','Q4'],
    datasets: [{{
      label:'Dobott', data:{json.dumps(q_kg)},
      backgroundColor:'rgba(196,30,58,0.7)', borderColor:'#C41E3A', borderWidth:2, borderRadius:6,
    }},{{
      label:'Kapott', data:{json.dumps(q_op)},
      backgroundColor:'rgba(253,121,168,0.5)', borderColor:'#fd79a8', borderWidth:2, borderRadius:6,
    }}]
  }},
  options: {{
    responsive:true, maintainAspectRatio:false,
    plugins: {{
      legend:{{ position:'top', labels:{{ usePointStyle:true, font:{{size:11}} }} }},
      tooltip: {{ callbacks: {{ afterBody: items => {{
        const idx = items[0].dataIndex;
        const won = {json.dumps(q_won)};
        const lost = {json.dumps(q_lost)};
        return 'Megnyert negyed: '+won[idx]+' | Elvesztett: '+lost[idx];
      }} }} }}
    }},
    scales: {{ y:{{ beginAtZero:true, grid:{{color:'rgba(255,255,255,0.04)'}} }}, x:{{ grid:{{display:false}} }} }}
  }}
}});

new Chart(document.getElementById('shotPie').getContext('2d'), {{
  type:'doughnut',
  data: {{
    labels:['3FG ({pct_3}%  — {pts_from_3} pt)','2FG ({pct_2}% — {pts_from_2} pt)','FT ({pct_ft}% — {pts_from_ft} pt)'],
    datasets:[{{ data:[{pts_from_3},{pts_from_2},{pts_from_ft}], backgroundColor:['#C41E3A','#00cec9','#fdcb6e'], borderColor:'#151518', borderWidth:3, hoverOffset:8 }}]
  }},
  options: {{ responsive:true, maintainAspectRatio:false, cutout:'55%',
    plugins:{{ legend:{{ position:'right', labels:{{ padding:14, usePointStyle:true, font:{{size:11}} }} }} }}
  }}
}});
</script>
</body>
</html>"""
    return html


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

    # Determine month range from data
    dates = [datetime.strptime(m["date"], "%Y-%m-%d").date() for m in matches]
    min_date, max_date = min(dates), max(dates)

    months_to_show = []
    y, mo = min_date.year, min_date.month
    while (y, mo) <= (max_date.year, max_date.month):
        months_to_show.append((y, mo))
        mo += 1
        if mo > 12:
            mo = 1
            y += 1

    # Build HTML for each month
    months_html = ""
    for year, month in months_to_show:
        month_name = MONTH_NAMES_HU[month]
        first_weekday, num_days = cal_module.monthrange(year, month)

        headers = "".join(f'<div class="cal-hd">{d}</div>' for d in DAY_NAMES_HU)
        cells = '<div class="cal-day empty"></div>' * first_weekday

        for day in range(1, num_days + 1):
            key = (year, month, day)
            if key in match_by_date:
                mi = match_by_date[key]
                ha_class = "home" if mi["home"] else "away"

                if mi["played"] and mi["win"] is not None:
                    wl = "win" if mi["win"] else "loss"
                    badge = "W" if mi["win"] else "L"
                    bc = "w" if mi["win"] else "l"
                    sc_class = "win" if mi["win"] else "loss"
                    score_line = f'<span class="match-score {sc_class}">{mi["score"]}</span>'
                else:
                    wl = "upcoming"
                    badge = ""
                    bc = "tbd"
                    score_line = ""

                badge_html = f'<span class="match-badge {bc}">{badge}</span>' if badge else ""

                cells += f'''<div class="cal-day has-match {wl} {ha_class}">
  <span class="day-num">{day}</span>{badge_html}
  <div class="match-info">
    <span class="match-opp">{mi["opp"]}</span>
    <span class="match-time">{mi["time"]}</span>
    {score_line}
  </div>
</div>'''
            else:
                cells += f'<div class="cal-day"><span class="day-num">{day}</span></div>'

        trailing = (7 - (first_weekday + num_days) % 7) % 7
        cells += '<div class="cal-day empty"></div>' * trailing

        months_html += f'''
  <div class="cal-month">
    <h3>{month_name} {year}</h3>
    <div class="cal-grid">
      {headers}
      {cells}
    </div>
  </div>'''

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

/* Legend */
.cal-legend{{
  display:flex;gap:24px;justify-content:center;flex-wrap:wrap;
  margin-bottom:28px;font-size:.8rem;color:var(--text-dim);
}}
.legend-item{{display:flex;align-items:center;gap:6px}}
.legend-dot{{width:14px;height:14px;border-radius:5px}}
.legend-dot.win{{background:rgba(0,184,148,.2);border:1.5px solid var(--green)}}
.legend-dot.loss{{background:rgba(225,112,85,.2);border:1.5px solid var(--red)}}
.legend-dot.upcoming{{background:rgba(139,141,160,.2);border:1.5px solid var(--text-dim)}}

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

/* Calendar grid */
.cal-month{{
  background:var(--card);border-radius:16px;padding:24px;
  border:1px solid var(--border);margin-bottom:20px;
}}
.cal-month h3{{
  font-size:.95rem;text-transform:uppercase;letter-spacing:2.5px;
  color:var(--accent);margin-bottom:16px;font-weight:700;text-align:center;
}}
.cal-grid{{
  display:grid;grid-template-columns:repeat(7,1fr);gap:4px;
}}
.cal-hd{{
  text-align:center;font-size:.7rem;font-weight:700;color:var(--text-dim);
  text-transform:uppercase;letter-spacing:1px;padding:8px 0 10px;
}}
.cal-day{{
  min-height:85px;padding:7px 8px;border-radius:10px;
  background:rgba(255,255,255,.015);position:relative;
  transition:background .2s;
}}
.cal-day:hover:not(.empty){{background:rgba(255,255,255,.035)}}
.cal-day.empty{{background:transparent;min-height:0;pointer-events:none}}
.day-num{{font-size:.72rem;color:var(--text-dim);font-weight:500}}

/* Match cells */
.cal-day.has-match{{
  border:1px solid var(--border);cursor:default;
}}
.cal-day.has-match.win{{
  border-color:rgba(0,184,148,.35);
  background:rgba(0,184,148,.06);
}}
.cal-day.has-match.loss{{
  border-color:rgba(225,112,85,.3);
  background:rgba(225,112,85,.05);
}}
.match-badge{{
  position:absolute;top:6px;right:7px;
  width:22px;height:22px;line-height:22px;text-align:center;
  border-radius:6px;font-size:.65rem;font-weight:800;
}}
.match-badge.w{{background:rgba(0,184,148,.2);color:var(--green)}}
.match-badge.l{{background:rgba(225,112,85,.2);color:var(--red)}}

/* Upcoming (not yet played) */
.cal-day.has-match.upcoming{{
  border-color:rgba(139,141,160,.3);
  background:rgba(139,141,160,.06);
}}
.cal-day.upcoming .match-opp{{color:var(--accent2)}}
.cal-day.upcoming .match-time{{color:var(--text-dim)}}
.match-info{{display:flex;flex-direction:column;gap:1px;margin-top:6px}}
.match-opp{{font-size:.74rem;font-weight:700;color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.match-time{{font-size:.62rem;color:var(--text-dim)}}
.match-score{{font-size:.72rem;font-weight:700;margin-top:1px}}
.match-score.win{{color:var(--green)}}
.match-score.loss{{color:var(--red)}}

/* Away indicator */
.cal-day.away .match-opp{{color:var(--text-dim)}}

/* Responsive */
@media(max-width:900px){{
  .cal-day{{min-height:70px;padding:5px 6px}}
  .match-opp{{font-size:.66rem}}
  .match-score{{font-size:.66rem}}
  .header{{flex-direction:column;text-align:center}}
  .header-stats{{justify-content:center}}
}}
@media(max-width:600px){{
  body{{padding:12px}}
  .cal-day{{min-height:56px;padding:4px 5px}}
  .cal-hd{{font-size:.6rem;padding:6px 0}}
  .day-num{{font-size:.62rem}}
  .match-opp{{font-size:.58rem}}
  .match-time{{display:none}}
  .match-score{{font-size:.6rem}}
  .match-badge{{width:18px;height:18px;line-height:18px;font-size:.55rem;top:4px;right:4px}}
  .header h1{{font-size:1.4rem}}
  .header-stat .val{{font-size:1.3rem}}
}}
</style>
</head>
<body>
<div class="dashboard">
  {_nav_html(active_key=team_key, depth=1)}
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
    <span class="legend-item"><span class="legend-dot win"></span> Győzelem</span>
    <span class="legend-item"><span class="legend-dot loss"></span> Vereség</span>
    <span class="legend-item"><span class="legend-dot upcoming"></span> Következő</span>
    <span class="legend-item">@ = Idegen pálya</span>
  </div>
  {months_html}
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
        disabled = ' class="disabled"' if t["key"] == "leftoverz" else ''
        if t["key"] == "leftoverz":
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
    # Build team cards
    cards_html = ""
    for ts in team_summaries:
        w = ts.get("wins", 0)
        l = ts.get("losses", 0)
        upcoming = ts.get("upcoming", [])
        next_match = ""
        if upcoming:
            nm = upcoming[0]
            opp = nm["away_team"] if nm["is_home"] else nm["home_team"]
            next_match = f'<div class="next-match">Következő: <strong>{calendar_short_name(opp)}</strong> — {nm["date"][5:].replace("-",".")} {nm.get("time","")}</div>'

        record_html = f'<span class="rec-w">{w}W</span> – <span class="rec-l">{l}L</span>'

        cards_html += f"""
      <a href="{ts['href']}/index.html" class="home-card">
        <div class="home-card-header">
          <div class="home-card-title">{ts['label']}</div>
          <div class="home-card-group">{ts['group']}</div>
        </div>
        <div class="home-card-record">{record_html}</div>
        {next_match}
        <div class="home-card-arrow">&rarr;</div>
      </a>"""

    # Build upcoming matches list (all teams combined)
    all_upcoming = []
    for ts in team_summaries:
        for m in ts.get("upcoming", [])[:3]:
            opp = m["away_team"] if m["is_home"] else m["home_team"]
            all_upcoming.append({
                "date": m["date"],
                "time": m.get("time", ""),
                "opp": calendar_short_name(opp),
                "team_short": ts["short"],
                "is_home": m["is_home"],
            })
    all_upcoming.sort(key=lambda x: x["date"])
    all_upcoming = all_upcoming[:6]

    upcoming_rows = ""
    for u in all_upcoming:
        hv = "H" if u["is_home"] else "V"
        hv_cls = "home" if u["is_home"] else "away"
        upcoming_rows += f"""
        <div class="up-row">
          <div class="up-date">{u['date'][5:].replace('-','.')}</div>
          <div class="up-time">{u['time']}</div>
          <div class="up-team">{u['team_short']}</div>
          <div class="up-opp">{('@' if not u['is_home'] else '')}{u['opp']}</div>
          <span class="up-badge {hv_cls}">{hv}</span>
        </div>"""

    upcoming_section = ""
    if upcoming_rows:
        upcoming_section = f"""
    <div class="section-title">KÖVETKEZŐ MECCSEK</div>
    <div class="upcoming-list">{upcoming_rows}
    </div>"""

    # Build recent results (all teams combined)
    all_recent = []
    for ts in team_summaries:
        for m in ts.get("recent", [])[-3:]:
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
            all_recent.append({
                "date": m["date"],
                "matchup": matchup,
                "score": score_str,
                "win": win,
            })
    all_recent.sort(key=lambda x: x["date"], reverse=True)
    all_recent = all_recent[:6]

    recent_rows = ""
    for r in all_recent:
        wl = "W" if r["win"] else "L"
        wl_cls = "w" if r["win"] else "l"
        sc_cls = "win" if r["win"] else "loss"
        recent_rows += f"""
        <div class="res-row">
          <div class="res-date">{r['date'][5:].replace('-','.')}</div>
          <div class="res-matchup">{r['matchup']}</div>
          <div class="res-score {sc_cls}">{r['score']}</div>
          <span class="res-badge {wl_cls}">{wl}</span>
        </div>"""

    recent_section = ""
    if recent_rows:
        recent_section = f"""
    <div class="section-title">LEGUTÓBBI EREDMÉNYEK</div>
    <div class="recent-list">{recent_rows}
    </div>"""

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
  .hero h1 {{
    font-size:2.6rem; font-weight:900; letter-spacing:2px;
    background:linear-gradient(135deg,#fff 30%,var(--accent) 100%);
    -webkit-background-clip:text; -webkit-text-fill-color:transparent;
  }}
  .hero .sub {{
    color:var(--text-dim); margin-top:10px; font-size:0.95rem;
    letter-spacing:0.5px;
  }}

  .home-cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); gap:20px; margin-bottom:36px; }}
  .home-card {{
    background:linear-gradient(135deg,#2a1218 0%,#1a1518 100%);
    border-radius:16px; padding:24px; text-decoration:none; color:var(--text);
    border:1px solid rgba(196,30,58,0.2);
    transition:all .25s; position:relative; overflow:hidden;
  }}
  .home-card:hover {{
    border-color:var(--accent); transform:translateY(-3px);
    box-shadow:0 12px 32px rgba(196,30,58,0.2);
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
  .home-card.placeholder {{
    opacity:0.35; pointer-events:none;
    border-style:dashed;
  }}

  .section-title {{
    font-size:0.75rem; font-weight:700; text-transform:uppercase;
    letter-spacing:1.5px; color:var(--text-dim); margin-bottom:14px;
  }}

  .upcoming-list, .recent-list {{
    background:var(--card); border-radius:14px; padding:6px;
    margin-bottom:32px; border:1px solid var(--border);
  }}
  .up-row, .res-row {{
    display:grid; grid-template-columns:60px 48px 70px 1fr auto;
    align-items:center; padding:12px 16px; gap:8px;
    border-bottom:1px solid var(--border);
    font-size:0.85rem;
  }}
  .up-row:last-child, .res-row:last-child {{ border-bottom:none; }}
  .up-date, .res-date {{ color:var(--text-dim); font-size:0.8rem; font-weight:500; }}
  .up-time {{ color:var(--text-dim); font-size:0.78rem; }}
  .up-team {{ font-weight:700; font-size:0.78rem; color:var(--accent); }}
  .up-opp {{ font-weight:600; }}
  .res-matchup {{ font-weight:600; }}
  .up-badge, .res-badge {{
    font-size:0.7rem; font-weight:800; padding:3px 8px; border-radius:6px;
    text-align:center; min-width:28px;
  }}
  .up-badge.home {{ background:rgba(196,30,58,0.15); color:var(--accent); }}
  .up-badge.away {{ background:rgba(253,203,110,0.15); color:var(--accent4); }}
  .res-badge.w {{ background:rgba(0,184,148,0.15); color:var(--green); }}
  .res-badge.l {{ background:rgba(225,112,85,0.15); color:var(--red); }}
  .res-score.win {{ font-weight:700; color:var(--green); }}
  .res-score.loss {{ font-weight:700; color:var(--red); }}
  .res-row {{ grid-template-columns:60px 1fr auto auto; }}

  @media(max-width:600px) {{
    .hero h1 {{ font-size:1.8rem; }}
    .home-cards {{ grid-template-columns:1fr; }}
    .up-row, .res-row {{ font-size:0.78rem; gap:4px; padding:10px 12px; }}
  }}
</style>
</head>
<body>
<div class="container">
  {_nav_html(depth=0)}
  <div class="hero">
    <h1>KÖZGÁZ BASKETBALL</h1>
    <div class="sub">2025/26 szezon</div>
  </div>
  <div class="home-cards">
    {cards_html}
    <div class="home-card placeholder">
      <div class="home-card-header">
        <div class="home-card-title">Leftoverz</div>
        <div class="home-card-group">Hamarosan...</div>
      </div>
    </div>
  </div>
  {upcoming_section}
  {recent_section}
</div>
</body>
</html>"""


def generate_index(players, cfg, team_key=None):
    cards = ""
    for i, (name, filename, games, ppg) in enumerate(players):
        rank = i + 1
        cards += f"""
      <a href="{filename}" class="player-card">
        <div class="rank">#{rank}</div>
        <div class="pinfo"><div class="player-name">{name}</div>
        <div class="player-meta">{games} meccs &nbsp;|&nbsp; {ppg} PPG</div></div>
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
</style>
</head>
<body>
<div class="container">
  {nav}
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

    conn = get_connection()
    tp = _team_like(conn, cfg)
    print(f"\n{'='*50}")
    print(f"  {cfg['team_name']} — {cfg['group_name']}")
    print(f"  Pattern: {tp}  |  Comp: {cfg['comp_prefix']}")
    print(f"{'='*50}")

    roster = get_roster(conn, cfg, tp)
    if not roster:
        print(f"  ⚠ Nincs játékos adat!")
        conn.close()
        return

    generated = []
    for player in roster:
        lic = player[0]
        name = player[1]
        slug = slugify(name)

        game_log = get_game_log(conn, cfg, tp, lic)
        quarter_stats = get_quarter_stats(conn, cfg, tp, lic)
        opp_stats = get_opponent_ppg(conn, cfg, tp, lic)
        tech, unsport = get_tech_unsport(conn, cfg, tp, lic)

        html = generate_html(player, game_log, quarter_stats, opp_stats, tech, unsport, cfg)

        filename = f"{slug}.html"
        filepath = os.path.join(out_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(html)

        generated.append((name, filename, player[3], player[5]))
        print(f"  ✓ {name} → {filename}")

    # Team dashboard
    team_stats = get_team_stats(conn, cfg, tp)
    team_html = generate_team_dashboard(team_stats, cfg, team_key=team_key)
    with open(os.path.join(out_dir, "csapat.html"), "w", encoding="utf-8") as f:
        f.write(team_html)
    print(f"\n  ✓ csapat.html (csapat dashboard)")

    # Calendar — scrape from MKOSZ, fall back to SQLite
    print(f"\n  Meccsnaptár scraping (mkosz.hu)...")
    cal_data = scrape_schedule(cfg)
    if cal_data:
        played = sum(1 for m in cal_data if m["played"])
        upcoming = len(cal_data) - played
        print(f"  ✓ {len(cal_data)} meccs scraped ({played} lejátszott, {upcoming} következő)")
    else:
        print(f"  ⚠ Scraping sikertelen, SQLite fallback...")
        cal_data = get_calendar_data_db(conn, cfg, tp)
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
            "wins": wins,
            "losses": losses,
            "upcoming": upcoming,
            "recent": recent,
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
