#!/usr/bin/env python3
"""Generate individual player dashboards for KÖZGÁZ B (NB2 Kelet 2025/26)."""

import sqlite3
import os
import json
import re

DB_PATH = os.path.join(os.path.dirname(__file__), "nb2_full.sqlite")
OUT_DIR = os.path.join(os.path.dirname(__file__), "dashboards")

TEAM_PATTERN = "%KÖZGÁZ%"
COMP_PREFIX = "F2KE%"

def slugify(name):
    """Convert name to filename-safe slug."""
    s = name.lower().strip()
    for src, dst in [("á","a"),("é","e"),("í","i"),("ó","o"),("ö","o"),("ő","o"),("ú","u"),("ü","u"),("ű","u")]:
        s = s.replace(src, dst)
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")

def get_connection():
    return sqlite3.connect(DB_PATH)

def get_roster(conn):
    """Get all players with summary stats."""
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
    """, (TEAM_PATTERN, COMP_PREFIX, TEAM_PATTERN, TEAM_PATTERN)).fetchall()

def get_game_log(conn, license_number):
    """Get per-game data for a player, including DNP games."""
    all_games = conn.execute("""
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
    """, (TEAM_PATTERN, TEAM_PATTERN, TEAM_PATTERN, TEAM_PATTERN, TEAM_PATTERN,
          COMP_PREFIX, TEAM_PATTERN, TEAM_PATTERN, license_number)).fetchall()
    return all_games

def get_quarter_stats(conn, license_number):
    """Points per quarter from scoring events."""
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
    """, (TEAM_PATTERN, COMP_PREFIX, TEAM_PATTERN, TEAM_PATTERN, license_number)).fetchall()

def get_opponent_ppg(conn, license_number):
    """PPG by opponent."""
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
    """, (TEAM_PATTERN, TEAM_PATTERN, COMP_PREFIX, TEAM_PATTERN, TEAM_PATTERN, license_number)).fetchall()

def get_tech_unsport(conn, license_number):
    """Technical and unsportsmanlike fouls."""
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
    """, (TEAM_PATTERN, COMP_PREFIX, TEAM_PATTERN, TEAM_PATTERN, license_number)).fetchone()
    return (rows[0] or 0, rows[1] or 0)

def shorten_opponent(name):
    """Shorten long opponent names for charts."""
    replacements = {
        "BKG-PRIMA AKADÉMIA DEBRECEN": "BKG-Prima Deb.",
        "BKG-VERESEGYHÁZ": "BKG-Veresegyh.",
        "SUNSHINE-NYÍKSE": "Sunshine-NYÍKSE",
        "BUDAPESTI BIKÁK": "Bp. Bikák",
        "KÖZGÁZ SC ÉS DSK/B": "Közgáz B",
    }
    for k, v in replacements.items():
        if k in name.upper():
            return v
    # Title case, max 20 chars
    n = name.title()
    if len(n) > 20:
        n = n[:18] + "."
    return n

def generate_insights(name, games_played, ppg, fg3, ft_made, ft_att, pf_per_game,
                       max_pts, quarter_pts, opp_data, game_log, total_pts, starts):
    """Generate textual insights for a player."""
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

    # Last 3 games form
    played = [g for g in game_log if g[6] is not None]
    if len(played) >= 3:
        last3 = played[-3:]
        last3_ppg = round(sum(g[6] for g in last3) / 3, 1)
        if last3_ppg > ppg * 1.3:
            strengths.append(f'Formajavulás: utolsó 3 meccs {last3_ppg} PPG')
        elif last3_ppg < ppg * 0.6 and ppg > 3:
            weaknesses.append(f'Formaesés: utolsó 3 meccs {last3_ppg} PPG')

    # Scoring variance
    pts_list = [g[6] for g in game_log if g[6] is not None]
    if len(pts_list) >= 5:
        mn, mx = min(pts_list), max(pts_list)
        if mx - mn >= 15:
            weaknesses.append(f'Inkonzisztens: {mn}-{mx} pont szórás')

    if ft_pct < 60 and ft_att >= 8:
        weaknesses.append(f'Gyenge büntető: {ft_pct}% ({ft_made}/{ft_att})')
    if pf_per_game >= 3:
        weaknesses.append(f'Faultgondok: {pf_per_game} fault/meccs')

    # Weak opponent
    if opp_data:
        worst = opp_data[-1]
        if worst[1] <= ppg * 0.5 and worst[2] >= 2:
            weaknesses.append(f'{shorten_opponent(worst[0])} ellen gyenge: {worst[1]} PPG')

    # Quarter weakness
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


def generate_html(player_data, game_log, quarter_stats, opp_stats, tech, unsport):
    """Generate the full HTML dashboard for one player."""
    lic, name, jersey, games, total_pts, ppg, fg2, fg3, ft_m, ft_a, pf, max_pts, starts = player_data

    ft_pct = round(100*ft_m/ft_a) if ft_a > 0 else 0
    pf_pg = round(pf/games, 1)

    # Team scores for share calculation
    played_games = [g for g in game_log if g[6] is not None]
    total_team_pts = sum(g[4] for g in played_games)
    share_pct = round(100*total_pts/total_team_pts, 1) if total_team_pts > 0 else 0

    # Points from each shot type
    pts_3fg = fg3 * 3
    pts_2fg = fg2 * 2
    pts_ft = ft_m

    # Quarter data (Q1-Q4 only)
    q_pts = {str(q[0]): q[1] for q in quarter_stats if str(q[0]) in ('1','2','3','4')}
    q_3fg = {str(q[0]): q[2] for q in quarter_stats if str(q[0]) in ('1','2','3','4')}
    q_data = [q_pts.get(str(i), 0) for i in range(1, 5)]
    q_3fg_data = [q_3fg.get(str(i), 0) for i in range(1, 5)]

    # Opponent chart data
    opp_labels = [shorten_opponent(o[0]) for o in opp_stats]
    opp_ppg_data = [o[1] for o in opp_stats]

    # Game log JS data
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
                "res": "L" if not win else "W",
                "pts": None
            })

    # Insights
    strengths, weaknesses = generate_insights(
        name, games, ppg, fg3, ft_m, ft_a, pf_pg, max_pts,
        quarter_stats, opp_stats, game_log, total_pts, starts
    )

    # Build opponent bar colors
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

    # Point bar colors in trend chart
    trend_pts = [g["pts"] for g in js_games if g["pts"] is not None]
    trend_max = max(trend_pts) if trend_pts else 1

    # Shot distribution bar widths (relative to max)
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
    --bg: #0f1117; --card: #1a1d27; --card-hover: #22263a;
    --accent: #6c5ce7; --accent2: #00cec9; --accent3: #fd79a8; --accent4: #fdcb6e;
    --text: #e8e8f0; --text-dim: #8b8da0; --green: #00b894; --red: #e17055;
    --border: rgba(255,255,255,0.06);
  }}
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family:'Inter',-apple-system,sans-serif; background:var(--bg); color:var(--text); min-height:100vh; padding:24px; }}
  .dashboard {{ max-width:1200px; margin:0 auto; }}

  .header {{
    display:flex; align-items:center; gap:28px; padding:32px;
    background:linear-gradient(135deg,#1a1d27 0%,#2d1f4e 100%);
    border-radius:20px; margin-bottom:20px; border:1px solid var(--border);
    position:relative; overflow:hidden;
  }}
  .header::after {{
    content:''; position:absolute; top:-60%; right:-10%;
    width:400px; height:400px;
    background:radial-gradient(circle,rgba(108,92,231,0.15),transparent 70%);
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
  .grid-3 {{ grid-template-columns:1fr 1fr 1fr; }}
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
  .game-log tr:hover {{ background:rgba(108,92,231,0.06); }}

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
    .grid-2,.grid-3,.grid-4 {{ grid-template-columns:1fr; }}
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
        <span>#{jersey}</span> &nbsp;|&nbsp; KÖZGÁZ SC ÉS DSK/B &nbsp;|&nbsp; NB2 Kelet &nbsp;|&nbsp; 2025/26 alapszakasz{tech_text}
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
      borderColor:'#6c5ce7', backgroundColor:'rgba(108,92,231,0.1)',
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
    datasets:[{{ data:[{pts_3fg},{pts_2fg},{pts_ft}], backgroundColor:['#6c5ce7','#00cec9','#fdcb6e'], borderColor:'#1a1d27', borderWidth:3, hoverOffset:8 }}]
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
      backgroundColor:['rgba(108,92,231,0.7)','rgba(108,92,231,0.5)','rgba(108,92,231,0.55)','rgba(108,92,231,0.5)'],
      borderColor:'#6c5ce7', borderWidth:2, borderRadius:6,
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


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    conn = get_connection()
    roster = get_roster(conn)

    generated = []
    for player in roster:
        lic = player[0]
        name = player[1]
        slug = slugify(name)

        game_log = get_game_log(conn, lic)
        quarter_stats = get_quarter_stats(conn, lic)
        opp_stats = get_opponent_ppg(conn, lic)
        tech, unsport = get_tech_unsport(conn, lic)

        html = generate_html(player, game_log, quarter_stats, opp_stats, tech, unsport)

        filename = f"{slug}.html"
        filepath = os.path.join(OUT_DIR, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(html)

        generated.append((name, filename, player[3], player[5]))  # name, file, games, ppg
        print(f"  ✓ {name} → {filename}")

    # Generate index page
    index_html = generate_index(generated)
    with open(os.path.join(OUT_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(index_html)
    print(f"\n  ✓ index.html (csapat áttekintő)")

    conn.close()
    print(f"\nÖsszesen {len(generated)} dashboard generálva → {OUT_DIR}/")


def generate_index(players):
    """Generate team index page linking to all player dashboards."""
    cards = ""
    for i, (name, filename, games, ppg) in enumerate(players):
        rank = i + 1
        cards += f"""
      <a href="{filename}" class="player-card">
        <div class="rank">#{rank}</div>
        <div class="player-name">{name}</div>
        <div class="player-meta">{games} meccs &nbsp;|&nbsp; {ppg} PPG</div>
      </a>"""

    return f"""<!DOCTYPE html>
<html lang="hu">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>KÖZGÁZ B — Játékos Dashboardok 2025/26</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap');
  :root {{
    --bg:#0f1117; --card:#1a1d27; --card-hover:#22263a;
    --accent:#6c5ce7; --accent2:#00cec9; --text:#e8e8f0; --text-dim:#8b8da0;
    --border:rgba(255,255,255,0.06);
  }}
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family:'Inter',-apple-system,sans-serif; background:var(--bg); color:var(--text); min-height:100vh; padding:24px; }}
  .container {{ max-width:900px; margin:0 auto; }}
  .team-header {{
    text-align:center; padding:40px 20px 30px;
    background:linear-gradient(135deg,#1a1d27 0%,#2d1f4e 100%);
    border-radius:20px; margin-bottom:30px; border:1px solid var(--border);
  }}
  .team-header h1 {{
    font-size:2.2rem; font-weight:900;
    background:linear-gradient(135deg,#fff 30%,var(--accent) 100%);
    -webkit-background-clip:text; -webkit-text-fill-color:transparent;
  }}
  .team-header .sub {{ color:var(--text-dim); margin-top:6px; font-size:0.95rem; }}
  .team-header .sub span {{ color:var(--accent2); font-weight:600; }}

  .player-grid {{ display:grid; grid-template-columns:repeat(auto-fill, minmax(260px, 1fr)); gap:16px; }}
  .player-card {{
    display:flex; align-items:center; gap:16px;
    background:var(--card); border-radius:14px; padding:18px 20px;
    border:1px solid var(--border); text-decoration:none; color:var(--text);
    transition:all 0.2s;
  }}
  .player-card:hover {{
    background:var(--card-hover); border-color:var(--accent);
    transform:translateY(-2px); box-shadow:0 8px 24px rgba(108,92,231,0.15);
  }}
  .rank {{
    font-size:1.1rem; font-weight:800; color:var(--accent);
    min-width:36px;
  }}
  .player-name {{ font-weight:700; font-size:0.95rem; }}
  .player-meta {{ font-size:0.75rem; color:var(--text-dim); margin-top:2px; }}
</style>
</head>
<body>
<div class="container">
  <div class="team-header">
    <h1>KÖZGÁZ SC ÉS DSK/B</h1>
    <div class="sub">NB2 Kelet &nbsp;|&nbsp; <span>2025/26 alapszakasz</span> &nbsp;|&nbsp; Játékos dashboardok</div>
  </div>
  <div class="player-grid">{cards}
  </div>
</div>
</body>
</html>"""


if __name__ == "__main__":
    main()
