"""
reset_prologue.py — Reset prologue flags so all existing players restart from Q1.
Run once after applying the sequential-interview fix.

    uv run python reset_prologue.py
"""
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
    # Clear interview sub-state so player starts fresh from Q1
    flags["interview_done"] = False
    flags["interview_phase"] = 0
    flags["interview_answers"] = []
    flags["cards_drawn"] = False
    flags["card_draw_phase"] = 0
    flags["awakening_triggered"] = False
    c.execute("UPDATE mainstorystate SET flags=? WHERE id=?", (json.dumps(flags), row_id))
    print(f"  Reset story state id={row_id}")
conn.commit()
conn.close()
print("\nDone. All players will restart the prologue from Question 1.")
