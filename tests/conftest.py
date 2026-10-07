"""
Pytest configuration and environment fixtures for Kairo test suite.
Ensures repository root is added to sys.path so all package imports work seamlessly.
"""

import sys
from pathlib import Path

# Add repository root to Python path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
