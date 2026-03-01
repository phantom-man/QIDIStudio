import lancedb
import logging
from pathlib import Path
import os
from dotenv import load_dotenv

# Load .env so LANCEDB_PATH picks up the GCS URI if set there
load_dotenv(Path(__file__).parent / ".env")

# Use QIDIStudio LanceDB defaults
REPO_ROOT = Path(__file__).parent
_raw_path = os.getenv("LANCEDB_PATH", str(REPO_ROOT / "data" / "lancedb"))
if _raw_path.startswith(("gs://", "s3://", "az://", "gcs://")):
    LANCEDB_PATH = _raw_path
else:
    LANCEDB_PATH = (
        str(REPO_ROOT / _raw_path) if not os.path.isabs(_raw_path) else _raw_path
    )
LANCEDB_TABLE = os.getenv("LANCEDB_TABLE", "qidistudio_learnings")


def verify_lancedb_integrity(uri, table_name):
    try:
        db = lancedb.connect(uri)
        table = db.open_table(table_name)
        # Check current version and metadata
        current_version = table.version
        versions = table.list_versions()
        latest = next(
            (v for v in reversed(versions) if v["version"] == current_version),
            versions[-1],
        )
        timestamp = latest.get("timestamp", "unknown")
        print(f"LanceDB Healthy: Version {current_version} at {timestamp}")
        return True
    except Exception as e:
        logging.error(f"LanceDB Corruption Detected: {e}")
        print(f"LanceDB Corruption Detected: {e}")
        # Trigger Auto-Rollback if possible (not implemented)
        return False


if __name__ == "__main__":
    verify_lancedb_integrity(LANCEDB_PATH, LANCEDB_TABLE)
