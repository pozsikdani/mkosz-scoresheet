#!/usr/bin/env python3
"""
Edzéslátogatás frissítő — HTML fájlok in-place módosítása Google Sheets adatokból.

Önálló script ami SQLite nélkül működik: a Google Sheets CSV-ből kinyert
edzéslátogatás adatokat közvetlenül a meglévő HTML fájlokban frissíti.
GitHub Actions-ben használható napi automatikus frissítésre.

Futtatás: python3 update_attendance.py
"""

import os
import re
import sys

# Import shared fetch logic from generate_dashboards
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from generate_dashboards import fetch_training_attendance

DASHBOARDS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboards")


def _att_pct(ratio):
    """Convert '26/34' to percentage integer."""
    parts = ratio.split("/")
    return round(int(parts[0]) / int(parts[1]) * 100)


def update_index(att_data):
    """Update attendance values in dashboards/index.html."""
    index_path = os.path.join(DASHBOARDS_DIR, "index.html")
    if not os.path.exists(index_path):
        print(f"  ⚠ {index_path} nem található")
        return False

    with open(index_path, "r", encoding="utf-8") as f:
        html = f.read()

    original = html

    for db_name, ratio in att_data.items():
        pct = _att_pct(ratio)

        # Pattern: player-name div with this name, followed by meta, then player-att
        # Replace the player-att div content
        pattern = (
            r'(<div class="player-name">'
            + re.escape(db_name)
            + r'</div>\s*'
            r'<div class="player-meta">.*?</div>)'
            r'(<div class="player-att">).*?(</div>)'
        )
        replacement = (
            r'\1'
            f'\\2🏋️ {ratio} <span class="att-pct">({pct}%)</span>\\3'
        )
        html = re.sub(pattern, replacement, html, flags=re.DOTALL)

    if html != original:
        with open(index_path, "w", encoding="utf-8") as f:
            f.write(html)
        return True
    return False


def update_player_dashboards(att_data):
    """Update attendance values in individual player HTML files."""
    changed_files = []

    for filepath in sorted(os.listdir(DASHBOARDS_DIR)):
        if not filepath.endswith(".html") or filepath in ("index.html", "csapat.html", "naptar.html"):
            continue

        full_path = os.path.join(DASHBOARDS_DIR, filepath)
        with open(full_path, "r", encoding="utf-8") as f:
            html = f.read()

        # Find player name from <h1>
        h1_match = re.search(r'<h1>(.*?)</h1>', html)
        if not h1_match:
            continue

        player_name = h1_match.group(1)
        ratio = att_data.get(player_name)
        if not ratio:
            continue

        pct = _att_pct(ratio)
        original = html

        # Pattern: the Edzés header stat
        pattern = (
            r'<div class="val" style="color:var\(--accent2\)">'
            r'.*?'
            r'</div><div class="label">Edzés</div>'
        )
        replacement = (
            f'<div class="val" style="color:var(--accent2)">'
            f'{ratio} ({pct}%)'
            f'</div><div class="label">Edzés</div>'
        )
        html = re.sub(pattern, replacement, html)

        if html != original:
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(html)
            changed_files.append(filepath)

    return changed_files


def main():
    print("Edzéslátogatás frissítés (Google Sheets → HTML)")
    print("=" * 50)

    # Fetch attendance data
    print("\n  Google Sheets CSV fetch...")
    att_data = fetch_training_attendance()
    if not att_data:
        print("  ⚠ Nem sikerült adatot lekérni, kilépés.")
        sys.exit(1)
    print(f"  ✓ {len(att_data)} játékos adata betöltve")

    # Update index
    print(f"\n  Index frissítés ({DASHBOARDS_DIR}/index.html)...")
    if update_index(att_data):
        print("  ✓ index.html frissítve")
    else:
        print("  — index.html nem változott")

    # Update player dashboards
    print(f"\n  Játékos dashboardok frissítése...")
    changed = update_player_dashboards(att_data)
    if changed:
        for f in changed:
            print(f"  ✓ {f} frissítve")
        print(f"\n  Összesen {len(changed)} fájl frissítve")
    else:
        print("  — Nincs változás")

    total_changed = (1 if update_index != False else 0) + len(changed)
    if changed or total_changed:
        print("\n✅ Kész! git add dashboards/ && git commit && git push a deploy-hoz.")
    else:
        print("\n✅ Minden naprakész, nincs teendő.")


if __name__ == "__main__":
    main()
