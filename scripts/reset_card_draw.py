"""
reset_card_draw.py — Rewind ONLY the card draw gate for all players.
Use this when a player was stuck past the card reveal due to a crash
(e.g. the top_k API error), but their interview is already complete.

Keeps: interview_done, interview_answers, alignment_tendency
Resets: cards_drawn, card_draw_phase, awakening_triggered

    uv run python reset_card_draw.py
"""
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import json, sqlite3

conn = sqlite3.connect("tarot.db")
c = conn.cursor()
c.execute("SELECT id, flags FROM mainstorystate")
rows = c.fetchall()

for row_id, flags_raw in rows:
    try:
        flags = json.loads(flags_raw) if flags_raw else {}
    except Exception:
        flags = {}

    # Only rewind players who completed the interview (so they don't repeat Q1-Q3)
    if not flags.get("interview_done", False):
        print(f"  Skipping id={row_id} — interview not done yet")
        continue

    flags["cards_drawn"] = False
    flags["card_draw_phase"] = 0
    flags["awakening_triggered"] = False

    c.execute(
        "UPDATE mainstorystate SET flags=? WHERE id=?",
        (json.dumps(flags), row_id),
    )
    alignment = flags.get("alignment_tendency", "unknown")
    print(f"  Rewound card draw for state id={row_id} (alignment={alignment})")

conn.commit()
conn.close()
print("\nDone. Players will re-enter the card draw sequence.")
