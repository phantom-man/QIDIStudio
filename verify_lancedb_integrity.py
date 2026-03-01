import lancedb
import logging
from pathlib import Path
import os

# Use QIDIStudio LanceDB defaults
REPO_ROOT = Path(__file__).parent
LANCEDB_PATH = os.getenv("LANCEDB_PATH", str(REPO_ROOT / "data" / "lancedb"))
LANCEDB_TABLE = os.getenv("LANCEDB_TABLE", "qidistudio_learnings")


def verify_lancedb_integrity(uri, table_name):
    try:
        db = lancedb.connect(uri)
        table = db.open_table(table_name)
        # Check current version and metadata
        version = table.version_history()[-1]
        print(
            f"LanceDB Healthy: Version {version['version']} at {version['timestamp']}"
        )
        return True
    except Exception as e:
        logging.error(f"LanceDB Corruption Detected: {e}")
        print(f"LanceDB Corruption Detected: {e}")
        # Trigger Auto-Rollback if possible (not implemented)
        return False


if __name__ == "__main__":
    verify_lancedb_integrity(LANCEDB_PATH, LANCEDB_TABLE)
