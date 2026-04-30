"""
conftest.py — makes pytest aware of the project root so `app` is importable.
Place this at the project root (same level as `app/`).
"""
import sys
import os

# Ensure the project root is in sys.path
sys.path.insert(0, os.path.dirname(__file__))
