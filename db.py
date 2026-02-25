"""
MongoDB connection utilities for the CLI app.

This keeps all DB-related configuration in one place.
"""

import os
from typing import Any

from pymongo import MongoClient


def get_db() -> Any:
    """
    Return a MongoDB database handle using env vars or sensible defaults.

    Env vars:
      - MONGO_URI (default: mongodb://localhost:27017)
      - MONGO_DB_NAME (default: debot_cli)
    """
    mongo_uri = os.getenv("MONGO_URI", "mongodb://localhost:27017")
    db_name = os.getenv("MONGO_DB_NAME", "debot_cli")
    client = MongoClient(mongo_uri)
    return client[db_name]


