import os
import sys

sys.path.append(os.path.abspath(os.path.dirname(__file__)))

from sqlmodel import Session, select
from app.db.database import engine
from app.db.models import DialogueLog

with Session(engine) as session:
    logs = session.exec(select(DialogueLog).order_by(DialogueLog.timestamp.desc()).limit(10)).all()
    with open("logs_output.txt", "w", encoding="utf-8") as f:
        for log in reversed(logs):
            f.write(f"[{log.role}] {log.message[:200]}...\n")
