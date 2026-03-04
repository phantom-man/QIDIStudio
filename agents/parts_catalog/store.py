"""
agents/parts_catalog/store.py

Shared persistence helpers for all parts-catalog harvesters.

Storage layout:
    Firestore  : cnc_parts/{category}/{doc_id}
    GCS        : gs://qidistudio-parts/parts_catalog/{category}/{doc_id}/data.json
                 gs://qidistudio-parts/parts_catalog/{category}/{doc_id}/image.jpg
    LanceDB    : table 'cnc_parts'  (semantic embeddings for search)
    Progress   : gs://qidistudio-parts/_progress/{harvester_name}.json
"""

from __future__ import annotations

import json
import logging
import os
import time
import io
from datetime import datetime, timezone
from typing import Any

import requests

log = logging.getLogger("parts_catalog.store")

GCS_BUCKET = "qidistudio-parts"
FIRESTORE_PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "crafty-hook-483415-b3")


def _fs():
    from google.cloud import firestore

    return firestore.Client(project=FIRESTORE_PROJECT)


def _gcs():
    from google.cloud import storage

    client = storage.Client(project=FIRESTORE_PROJECT)
    bucket = client.bucket(GCS_BUCKET)
    try:
        bucket.reload()
    except Exception:
        try:
            bucket = client.create_bucket(GCS_BUCKET, location="US")
            log.info("Created GCS bucket %s", GCS_BUCKET)
        except Exception as e:
            log.warning("Could not create bucket: %s", e)
    return bucket


def write_part(part_dict: dict[str, Any]) -> None:
    """Write a normalised part dict to Firestore + GCS."""
    category = part_dict["category"]
    doc_id = part_dict["doc_id"]

    # ── Firestore ──────────────────────────────────────────────────────────────
    try:
        fs = _fs()
        doc_ref = (
            fs.collection("cnc_parts")
            .document(category)
            .collection("items")
            .document(doc_id)
        )
        doc_ref.set({k: v for k, v in part_dict.items() if k != "raw"}, merge=True)
        log.debug("Firestore write: cnc_parts/%s/%s", category, doc_id)
    except Exception as e:
        log.warning("Firestore write failed for %s/%s: %s", category, doc_id, e)

    # ── GCS raw JSON ───────────────────────────────────────────────────────────
    try:
        bucket = _gcs()
        blob = bucket.blob(f"parts_catalog/{category}/{doc_id}/data.json")
        blob.upload_from_string(
            json.dumps(part_dict, indent=2, default=str),
            content_type="application/json",
        )
        log.debug("GCS write: %s", blob.name)
    except Exception as e:
        log.warning("GCS write failed for %s/%s: %s", category, doc_id, e)


def download_image(url: str, category: str, doc_id: str) -> str:
    """Download an image from url, store to GCS, return gs:// path. Returns '' on failure."""
    if not url:
        return ""
    try:
        resp = requests.get(
            url, timeout=15, headers={"User-Agent": "NexusMill-Catalog/1.0"}
        )
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "image/jpeg")
        ext = "jpg" if "jpeg" in content_type else content_type.split("/")[-1]
        bucket = _gcs()
        blob_path = f"parts_catalog/{category}/{doc_id}/image.{ext}"
        blob = bucket.blob(blob_path)
        blob.upload_from_string(resp.content, content_type=content_type)
        gcs_path = f"gs://{GCS_BUCKET}/{blob_path}"
        log.info("Image stored: %s", gcs_path)
        return gcs_path
    except Exception as e:
        log.warning(
            "Image download failed for %s/%s from %s: %s", category, doc_id, url, e
        )
        return ""


def upsert_lancedb_embedding(part_dict: dict[str, Any]) -> None:
    """Add a parts record to the LanceDB cnc_parts table (GCS-backed).

    Mirrors the GCS connection pattern in memory/store.py:
    - detects gs:// URI and passes storage_options
    - never wraps a gs:// path in pathlib.Path (crashes on Windows)
    - uses a fixed pyarrow schema so the table is created correctly on first run
    """
    try:
        import lancedb
        import pyarrow as pa
        from sentence_transformers import SentenceTransformer

        EMBED_DIMS = 384  # all-MiniLM-L6-v2
        GCS_STORAGE_OPTIONS = {
            "timeout": "60s",
            "connect_timeout": "30s",
            "max_retries": "5",
        }

        lancedb_path = os.environ.get("LANCEDB_PATH", "lancedb")
        if lancedb_path.startswith(("gs://", "s3://", "az://", "gcs://")):
            db = lancedb.connect(lancedb_path, storage_options=GCS_STORAGE_OPTIONS)
        else:
            from pathlib import Path

            local_path = Path(lancedb_path)
            local_path.mkdir(parents=True, exist_ok=True)
            db = lancedb.connect(str(local_path))

        model = SentenceTransformer("all-MiniLM-L6-v2")
        text = (
            f"{part_dict.get('name', '')} {part_dict.get('description', '')} "
            f"{part_dict.get('brand', '')} {part_dict.get('model', '')} "
            f"{' '.join(part_dict.get('tags', []))}"
        ).strip()
        embedding = model.encode(text).tolist()

        record = {
            "doc_id": part_dict["doc_id"],
            "category": part_dict["category"],
            "name": part_dict.get("name", ""),
            "brand": part_dict.get("brand", ""),
            "model": part_dict.get("model", ""),
            "tier": str(part_dict.get("tier", "hobby")),
            "description": part_dict.get("description", "")[:500],
            "tags": ", ".join(part_dict.get("tags", [])),
            "vector": embedding,
        }

        schema = pa.schema(
            [
                pa.field("doc_id", pa.string()),
                pa.field("category", pa.string()),
                pa.field("name", pa.string()),
                pa.field("brand", pa.string()),
                pa.field("model", pa.string()),
                pa.field("tier", pa.string()),
                pa.field("description", pa.string()),
                pa.field("tags", pa.string()),
                pa.field("vector", pa.list_(pa.float32(), EMBED_DIMS)),
            ]
        )

        table_name = "cnc_parts"
        if table_name in db.table_names():
            table = db.open_table(table_name)
            table.add([record])
        else:
            table = db.create_table(table_name, schema=schema, data=[record])
        log.debug("LanceDB upsert: %s", part_dict["doc_id"])
    except Exception as e:
        log.warning("LanceDB upsert failed for %s: %s", part_dict.get("doc_id"), e)


def load_progress(name: str) -> dict[str, Any]:
    """Load progress checkpoint from GCS. Returns {} if not found."""
    try:
        bucket = _gcs()
        blob = bucket.blob(f"_progress/{name}.json")
        return json.loads(blob.download_as_text())
    except Exception:
        return {}


def save_progress(name: str, data: dict[str, Any]) -> None:
    """Save progress checkpoint to GCS."""
    try:
        bucket = _gcs()
        blob = bucket.blob(f"_progress/{name}.json")
        blob.upload_from_string(
            json.dumps(data, indent=2, default=str), content_type="application/json"
        )
    except Exception as e:
        log.warning("Could not save progress for %s: %s", name, e)


def slug(*parts: str) -> str:
    """Build a safe doc_id slug from parts."""
    import re

    combined = "_".join(str(p) for p in parts if p)
    combined = combined.lower().strip()
    combined = re.sub(r"[^a-z0-9_\-]", "_", combined)
    combined = re.sub(r"_+", "_", combined).strip("_")
    return combined[:200]
