import os
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.messages import BaseMessage
from langchain_core.outputs import LLMResult

LOGS_DIR = "logs"
os.makedirs(LOGS_DIR, exist_ok=True)


class SessionLLMLogger(AsyncCallbackHandler):
    """
    Logs LLM prompts, generations, and thinking (if applicable) 
    to both the terminal and a session-specific file.
    """

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.log_file = os.path.join(LOGS_DIR, f"{session_id}.log")

    def _write(self, text: str):
        # Print to terminal
        print(text, flush=True)
        # Append to log file
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(text + "\n")

    async def on_chat_model_start(
        self,
        serialized: Dict[str, Any],
        messages: List[List[BaseMessage]],
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Any:
        self._write(f"\n{'='*80}\n[{datetime.now().isoformat()}] LLM CALL START (Run: {run_id})\n{'='*80}")
        for i, msgs in enumerate(messages):
            for msg in msgs:
                self._write(f"\n--- {msg.type.upper()} MESSAGE ---")
                self._write(str(msg.content))
        self._write(f"\n{'-'*80}\n")

    async def on_llm_new_token(self, token: str, **kwargs: Any) -> Any:
        # We could stream to terminal here, but it might interfere with chainlit's stdout.
        # It's better to just log the final output in on_llm_end.
        pass

    async def on_llm_end(
        self,
        response: LLMResult,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> Any:
        self._write(f"\n[{datetime.now().isoformat()}] LLM CALL END (Run: {run_id})\n{'-'*80}")
        for generations in response.generations:
            for gen in generations:
                self._write("\n--- MODEL OUTPUT ---")
                self._write(gen.text)
        self._write(f"\n{'='*80}\n")

    async def on_llm_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> Any:
        self._write(f"\n[{datetime.now().isoformat()}] LLM ERROR (Run: {run_id})\n{'-'*80}")
        self._write(str(error))
        self._write(f"\n{'='*80}\n")
