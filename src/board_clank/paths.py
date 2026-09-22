from __future__ import annotations
import os
from pathlib import Path
REPO_ROOT = Path(__file__).resolve().parents[2]

def default_data_dir() -> Path:
    raw = os.environ.get("BOARD_CLANK_DATA_DIR")
    if raw:
        return Path(raw)
    container = Path("/app/data")
    if container.exists():
        return container
    return REPO_ROOT / "data"

def default_db_path() -> Path:
    raw = os.environ.get("BOARD_CLANK_DB")
    if raw:
        return Path(raw)
    return default_data_dir() / "board_clank.db"
