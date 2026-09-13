"""
Root conftest.py — adds src/ to sys.path so 'alertiq' is importable
without a pip install when running pytest from the project root.

This is the standard src-layout pytest shim. It fires before any test
collection so all imports in test files resolve correctly.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))
