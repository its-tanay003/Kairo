"""
Kairo Training Data Pipeline Package (Track B - Task 3.1).
Harvests ToolSpecs, event store triples, and counterfactual recovery chains,
converting them into verified SFT conversation datasets.
"""

from pathlib import Path

TRAINING_DIR = Path(__file__).resolve().parent
DATA_DIR = TRAINING_DIR / "data"
