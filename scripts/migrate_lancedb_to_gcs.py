"""
Migrate LanceDB from local disk to GCS.

Usage:
    memory_env\\Scripts\\python.exe scripts\\migrate_lancedb_to_gcs.py [--dry-run]

Reads LANCEDB_PATH and LANCEDB_TABLE from .env.
Destination is always gs://qidistudio-lancedb/lancedb.
"""

import os
import sys
import logging
from pathlib import Path

# ── env ────────────────────────────────────────────────────────────────────────
from dotenv import load_dotenv

load_dotenv(Path(__file__).parents[1] / ".env")

import lancedb

REPO_ROOT = Path(__file__).parents[1]
SRC_PATH = str(REPO_ROOT / "data" / "lancedb")  # always local for migration
DST_PATH = "gs://qidistudio-lancedb/lancedb"
TABLE_NAME = os.getenv("LANCEDB_TABLE", "qidistudio_learnings")
DRY_RUN = "--dry-run" in sys.argv

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)


def migrate():
    log.info("Source : %s", SRC_PATH)
    log.info("Dest   : %s", DST_PATH)
    log.info("Table  : %s", TABLE_NAME)
    if DRY_RUN:
        log.info("DRY RUN — no data will be written")

    # ── connect to local source ────────────────────────────────────────────────
    src_db = lancedb.connect(SRC_PATH)
    src_table = src_db.open_table(TABLE_NAME)
    row_count = src_table.count_rows()
    schema = src_table.schema
    log.info("Local table: %d rows, version %s", row_count, src_table.version)

    if row_count == 0:
        log.warning("Source table is empty — nothing to migrate.")
        return

    # ── read all data as Arrow (chunked to avoid OOM on large tables) ──────────
    log.info("Reading all rows …")
    arrow_table = src_table.to_arrow()
    log.info("Read %d rows (%d columns)", len(arrow_table), len(arrow_table.schema))

    if DRY_RUN:
        log.info(
            "DRY RUN complete — would write %d rows to %s", len(arrow_table), DST_PATH
        )
        return

    # ── connect to GCS destination ─────────────────────────────────────────────
    log.info("Connecting to GCS …")
    dst_db = lancedb.connect(DST_PATH)

    existing = list(dst_db.table_names())
    if TABLE_NAME in existing:
        log.warning("Table '%s' already exists in GCS — overwriting.", TABLE_NAME)
        dst_db.drop_table(TABLE_NAME)

    log.info("Creating table in GCS and writing %d rows …", len(arrow_table))
    dst_table = dst_db.create_table(TABLE_NAME, data=arrow_table, schema=schema)
    log.info(
        "GCS table created — version %s, rows %d",
        dst_table.version,
        dst_table.count_rows(),
    )

    # ── verify round-trip ─────────────────────────────────────────────────────
    verify_count = dst_table.count_rows()
    if verify_count == row_count:
        log.info("✓ Migration verified: %d rows in GCS match source.", verify_count)
    else:
        log.error("Row count mismatch! source=%d  gcs=%d", row_count, verify_count)
        sys.exit(1)

    # ── update .env to point at GCS ───────────────────────────────────────────
    env_path = REPO_ROOT / ".env"
    env_text = env_path.read_text()
    if "LANCEDB_PATH=" in env_text:
        import re

        env_text = re.sub(
            r"^LANCEDB_PATH=.*$",
            f"LANCEDB_PATH={DST_PATH}",
            env_text,
            flags=re.MULTILINE,
        )
    else:
        env_text += f"\nLANCEDB_PATH={DST_PATH}\n"
    env_path.write_text(env_text)
    log.info(".env updated: LANCEDB_PATH=%s", DST_PATH)

    log.info("Migration complete.")


if __name__ == "__main__":
    migrate()
