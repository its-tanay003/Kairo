"""
Kairo Lab & Evaluation Benchmark Package.
"""

from lab.version import LAB_VERSION, ENVIRONMENT_NAME
from lab.targets import lab_targets, LabTargetManager
from lab.tasks import LAB_TASKS, LabTask

__all__ = [
    "LAB_VERSION",
    "ENVIRONMENT_NAME",
    "lab_targets",
    "LabTargetManager",
    "LAB_TASKS",
    "LabTask",
]
