"""Project configuration helpers."""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = BASE_DIR / "traffic_system.db"
SUMO_CONFIG_PATH = Path(os.getenv("SUMO_CONFIG_PATH", BASE_DIR / "sumo" / "RL.sumocfg"))

DEFAULT_ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "traffic@moi.gov.sa")
DEFAULT_ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "Admin@2025")
DEFAULT_ADMIN_NAME = os.getenv("ADMIN_NAME", "Traffic Administrator")

MOI_EMAIL_DOMAIN = "moi.gov.sa"
