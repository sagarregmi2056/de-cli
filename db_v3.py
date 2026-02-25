"""
MongoDB connection utilities for the v3 web dashboard.

This is intentionally separate from db.py so existing pipelines/routes keep
their current behavior.
"""

from __future__ import annotations

import os
from typing import Any

from pymongo import MongoClient


def get_db_v3() -> Any:
    """
    Return a MongoDB database handle for v3 dashboard data.

    Env vars:
      - MONGO_URI (default: mongodb://localhost:27017)
      - MONGO_DB_NAME_V3 (default: debot_cli_v3)
    """
    mongo_uri = os.getenv("MONGO_URI", "mongodb://localhost:27017")
    db_name = os.getenv("MONGO_DB_NAME_V3", "debot_cli_v3")
    client = MongoClient(mongo_uri)
    return client[db_name]
