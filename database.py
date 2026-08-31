# database.py
#
# Storage layer for the Material Master Framework.
#
# Schema design:
#   common_materials  -- one row per *unique* standardized material (the
#                         "National Unified Material Code" itself).
#   material_records  -- one row per *source* record fed in from a CPSE.
#                         Many records can point at the same common_code,
#                         which is exactly how duplicates/near-duplicates
#                         get consolidated.
#
# find_matching_common_code() does simple fuzzy text matching so that near
# duplicate descriptions ("SS Pipe 50mm" vs "Pipe SS 50MM Dia") collapse onto
# the same common code instead of each minting a brand new one.

import sqlite3
import json
import re
import os
import uuid
from typing import List, Dict, Optional
from difflib import SequenceMatcher

from categories import CATEGORY_SCHEMA, attribute_schema_for, register_category

DB_NAME = "material_master.db"

# Similarity threshold (0-1) above which a new material is considered a
# duplicate of an existing common material rather than a new one.
MATCH_THRESHOLD = 0.72
MATCH_THRESHOLDS = {
    "Pipe": 0.68,
    "Valve": 0.68,
    "Fastener": 0.68,
    "Bearing": 0.70,
    "default": 0.72,
}
ABBREVIATIONS = {
    "ss": "stainless steel", "cs": "carbon steel", "ms": "mild steel",
    "sch": "schedule", "dia": "diameter", "od": "outer diameter",
    "id": "inner diameter", "pn": "pressure nominal", "mm": "millimeter",
}


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def backup_database(destination: str) -> Dict:
    """Create and verify a consistent SQLite backup."""
    destination = os.path.abspath(destination)
    if os.path.abspath(DB_NAME) == destination:
        raise ValueError("Backup destination must differ from the live database")
    source = get_connection()
    target = sqlite3.connect(destination)
    try:
        source.backup(target)
        target.commit()
        verify_database_backup(destination)
        return {"path": destination, "size_bytes": os.path.getsize(destination), "verified": True}
    finally:
        target.close()
        source.close()


def verify_database_backup(path: str) -> bool:
    """Verify that a backup opens cleanly and passes SQLite integrity checks."""
    conn = sqlite3.connect(path)
    try:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if not {"common_materials", "material_records", "audit_log"}.issubset(tables) or integrity != "ok":
            raise RuntimeError("Backup verification failed")
        return True
    finally:
        conn.close()


def create_import_batch(batch_id: str, source_system_id: str, filename: str,
                        rows: List[Dict], created_by: str = "system", dry_run: bool = False) -> Dict:
    """Stage validated source rows before any material records are written."""
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO import_batches (batch_id, source_system_id, filename, dry_run, total_rows, created_by) VALUES (?, ?, ?, ?, ?, ?)",
            (batch_id, source_system_id, filename, int(dry_run), len(rows), created_by or "system"),
        )
        conn.executemany(
            "INSERT INTO import_rows (batch_id, row_number, payload) VALUES (?, ?, ?)",
            [(batch_id, index, json.dumps(row)) for index, row in enumerate(rows, start=1)],
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return get_import_batch(batch_id)


def get_import_batch(batch_id: str) -> Dict:
    conn = get_connection()
    batch = conn.execute("SELECT * FROM import_batches WHERE batch_id = ?", (batch_id,)).fetchone()
    rows = conn.execute("SELECT id, row_number, status, error, result FROM import_rows WHERE batch_id = ? ORDER BY row_number", (batch_id,)).fetchall()
    conn.close()
    if not batch:
        raise ValueError(f"Import batch {batch_id} not found")
    result = dict(batch)
    result["rows"] = [dict(row) for row in rows]
    for row in result["rows"]:
        if row.get("result"):
            row["result"] = json.loads(row["result"])
    return result


def update_import_row(row_id: int, status: str, result: Dict = None, error: str = None) -> None:
    conn = get_connection()
    conn.execute("UPDATE import_rows SET status = ?, result = ?, error = ? WHERE id = ?", (status, json.dumps(result) if result else None, error, row_id))
    conn.commit()
    conn.close()


def refresh_import_batch_counts(batch_id: str, status: str = None) -> Dict:
    conn = get_connection()
    conn.execute("UPDATE import_batches SET successful_rows = (SELECT COUNT(*) FROM import_rows WHERE batch_id = ? AND status = 'success'), error_rows = (SELECT COUNT(*) FROM import_rows WHERE batch_id = ? AND status IN ('error', 'validation_error')), status = COALESCE(?, status), updated_at = CURRENT_TIMESTAMP WHERE batch_id = ?", (batch_id, batch_id, status, batch_id))
    conn.commit()
    conn.close()
    return get_import_batch(batch_id)


def rollback_import_batch(batch_id: str) -> Dict:
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        exists = conn.execute("SELECT 1 FROM import_batches WHERE batch_id = ?", (batch_id,)).fetchone()
        if not exists:
            raise ValueError(f"Import batch {batch_id} not found")
        batch_codes = [row[0] for row in conn.execute("SELECT DISTINCT common_code FROM material_records WHERE import_batch_id = ?", (batch_id,)).fetchall()]
        deleted = conn.execute("DELETE FROM material_records WHERE import_batch_id = ?", (batch_id,)).rowcount
        for common_code in batch_codes:
            conn.execute(
                "DELETE FROM common_materials WHERE common_code = ? AND NOT EXISTS (SELECT 1 FROM material_records WHERE common_code = ?)",
                (common_code, common_code),
            )
        conn.execute("UPDATE import_batches SET status = 'rolled_back', updated_at = CURRENT_TIMESTAMP WHERE batch_id = ?", (batch_id,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {"batch_id": batch_id, "deleted_records": deleted, "status": "rolled_back"}


def create_integration_job(adapter: str = "generic-erp") -> Dict:
    job_id = str(uuid.uuid4())
    conn = get_connection()
    conn.execute("INSERT INTO integration_jobs (job_id, adapter, status) VALUES (?, ?, 'queued')", (job_id, adapter))
    conn.commit()
    conn.close()
    return {"job_id": job_id, "adapter": adapter, "status": "queued", "attempt_count": 0}


def update_integration_job(job_id: str, status: str, error: str = None, acknowledgement: str = None) -> Dict:
    conn = get_connection()
    conn.execute("UPDATE integration_jobs SET status = ?, attempt_count = attempt_count + 1, last_error = ?, acknowledgement = ?, updated_at = CURRENT_TIMESTAMP WHERE job_id = ?", (status, error, acknowledgement, job_id))
    conn.commit()
    row = conn.execute("SELECT * FROM integration_jobs WHERE job_id = ?", (job_id,)).fetchone()
    conn.close()
    if not row:
        raise ValueError(f"Integration job {job_id} not found")
    return dict(row)


def get_integration_job(job_id: str) -> Dict:
    conn = get_connection()
    row = conn.execute("SELECT * FROM integration_jobs WHERE job_id = ?", (job_id,)).fetchone()
    conn.close()
    if not row:
        raise ValueError(f"Integration job {job_id} not found")
    return dict(row)


def setup_database():
    """Initializes the SQLite database and creates the necessary tables."""
    conn = get_connection()
    cur = conn.cursor()

    cur.execute('''
        CREATE TABLE IF NOT EXISTS common_materials (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            common_code TEXT UNIQUE NOT NULL,
            standard_description TEXT NOT NULL,
            category TEXT NOT NULL,
            lifecycle_status TEXT NOT NULL DEFAULT 'active',
            retired_at TIMESTAMP,
            replacement_code TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cur.execute('''
        CREATE TABLE IF NOT EXISTS material_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            common_code TEXT NOT NULL,
            cpse_id TEXT,
            material_code TEXT,
            description TEXT,
            specification TEXT,
            unit_of_measure TEXT,
            material_type TEXT,
            procurement_date TEXT,
            source_system_id TEXT NOT NULL DEFAULT 'manual',
            import_batch_id TEXT,
            source_record_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (common_code) REFERENCES common_materials (common_code)
        )
    ''')

    cur.execute('''
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_type TEXT NOT NULL,
            entity_id INTEGER NOT NULL,
            field TEXT,
            old_value TEXT,
            new_value TEXT,
            changed_by TEXT DEFAULT 'system',
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cur.execute('''
        CREATE TABLE IF NOT EXISTS material_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            material_name TEXT UNIQUE NOT NULL,
            material_code TEXT UNIQUE NOT NULL,
            aliases TEXT NOT NULL DEFAULT '[]',
            owner TEXT NOT NULL DEFAULT 'system',
            approved INTEGER NOT NULL DEFAULT 1,
            usage_count INTEGER NOT NULL DEFAULT 0,
            is_common INTEGER NOT NULL DEFAULT 0,
            last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cur.execute('''
        CREATE TABLE IF NOT EXISTS category_catalog (
            category_name TEXT PRIMARY KEY,
            attributes TEXT NOT NULL DEFAULT '{}',
            version INTEGER NOT NULL DEFAULT 1,
            owner TEXT NOT NULL DEFAULT 'system',
            approved INTEGER NOT NULL DEFAULT 1,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cur.execute('''
        CREATE TABLE IF NOT EXISTS category_candidates (
            category_name TEXT PRIMARY KEY,
            observation_count INTEGER NOT NULL DEFAULT 0,
            last_observed TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            promoted INTEGER NOT NULL DEFAULT 0
        )
    ''')

    cur.execute('''
        CREATE TABLE IF NOT EXISTS review_decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            record_id INTEGER NOT NULL,
            previous_common_code TEXT NOT NULL,
            new_common_code TEXT,
            decision TEXT NOT NULL,
            reason TEXT,
            reviewer TEXT NOT NULL DEFAULT 'admin',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (record_id) REFERENCES material_records (id)
        )
    ''')

    cur.execute('''
        CREATE TABLE IF NOT EXISTS import_batches (
            batch_id TEXT PRIMARY KEY,
            source_system_id TEXT NOT NULL,
            filename TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'staged',
            dry_run INTEGER NOT NULL DEFAULT 0,
            total_rows INTEGER NOT NULL DEFAULT 0,
            successful_rows INTEGER NOT NULL DEFAULT 0,
            error_rows INTEGER NOT NULL DEFAULT 0,
            created_by TEXT NOT NULL DEFAULT 'system',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cur.execute('''
        CREATE TABLE IF NOT EXISTS import_rows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id TEXT NOT NULL,
            row_number INTEGER NOT NULL,
            payload TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'staged',
            error TEXT,
            result TEXT,
            UNIQUE(batch_id, row_number),
            FOREIGN KEY (batch_id) REFERENCES import_batches(batch_id) ON DELETE CASCADE
        )
    ''')

    cur.execute('''
        CREATE TABLE IF NOT EXISTS integration_jobs (
            job_id TEXT PRIMARY KEY,
            adapter TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued',
            attempt_count INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            acknowledgement TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    conn.commit()

    for name, definition in CATEGORY_SCHEMA.items():
        cur.execute(
            "INSERT OR IGNORE INTO category_catalog (category_name, attributes) VALUES (?, ?)",
            (name, json.dumps(definition.get("attributes", {}))),
        )
    for row in cur.execute("SELECT category_name, attributes FROM category_catalog WHERE approved = 1"):
        try:
            register_category(row["category_name"], json.loads(row["attributes"] or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
    conn.commit()

    # Migration: add the 'attributes' column (JSON) if this DB predates
    # item 2/3's attribute schema. SQLite has no "ADD COLUMN IF NOT
    # EXISTS", so we just try it and ignore the "already exists" error.
    try:
        cur.execute("ALTER TABLE common_materials ADD COLUMN attributes TEXT")
        conn.commit()
    except sqlite3.OperationalError:
        pass

    # Migration: item 9's status field, plus item 13's traceability data
    # (tolerance score + attribute-match flags per source record). The
    # roadmap calls for a separate `source_entries` table for this, but
    # material_records already IS one row per CPSE submission with a FK
    # to the harmonized code -- a second table storing the same rows
    # would just be two tables to keep in sync. Extending this one instead.
    for column, coltype in [("status", "TEXT DEFAULT 'confirmed'"),
                             ("tolerance_score", "REAL"),
                             ("attribute_flags", "TEXT"),
                             ("source_system_id", "TEXT NOT NULL DEFAULT 'manual'"),
                             ("import_batch_id", "TEXT"),
                             ("source_record_id", "TEXT"),
                             ("replacement_for_code", "TEXT")]:
        try:
            cur.execute(f"ALTER TABLE material_records ADD COLUMN {column} {coltype}")
            conn.commit()
        except sqlite3.OperationalError:
            pass

    for column, coltype in [("lifecycle_status", "TEXT NOT NULL DEFAULT 'active'"),
                            ("retired_at", "TIMESTAMP"),
                            ("replacement_code", "TEXT")]:
        try:
            cur.execute(f"ALTER TABLE common_materials ADD COLUMN {column} {coltype}")
            conn.commit()
        except sqlite3.OperationalError:
            pass

    for column, coltype in [("aliases", "TEXT NOT NULL DEFAULT '[]'"),
                            ("owner", "TEXT NOT NULL DEFAULT 'system'"),
                            ("approved", "INTEGER NOT NULL DEFAULT 1")]:
        try:
            cur.execute(f"ALTER TABLE material_codes ADD COLUMN {column} {coltype}")
            conn.commit()
        except sqlite3.OperationalError:
            pass

    try:
        cur.execute("ALTER TABLE common_materials ADD COLUMN replacement_for_code TEXT")
        conn.commit()
    except sqlite3.OperationalError:
        pass

    _deduplicate_source_records(conn)
    cur.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_material_source_identity "
        "ON material_records(source_system_id, cpse_id, material_code) "
        "WHERE cpse_id IS NOT NULL AND material_code IS NOT NULL"
    )

    _migrate_legacy_common_codes(conn)
    _repair_ambiguous_material_codes(conn)
    _backfill_material_codes(conn)

    conn.close()
    print("Database setup complete: 'common_materials' and 'material_records' tables ready.")


def _normalize(text: str) -> str:
    return " ".join((text or "").lower().split())


def _serialize_audit_value(value):
    if value is None:
        return None
    if isinstance(value, (dict, list, bool, int, float)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _deserialize_audit_value(value):
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    try:
        parsed = json.loads(value)
        if isinstance(parsed, (dict, list, int, float, bool)):
            return parsed
    except (TypeError, ValueError):
        pass
    return value


def log_audit(entity_type: str, entity_id: int, field: str, old_value, new_value, changed_by: str = "system") -> Dict:
    """Insert a single audit entry for a manually edited entity."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO audit_log (entity_type, entity_id, field, old_value, new_value, changed_by) VALUES (?, ?, ?, ?, ?, ?)",
        (
            entity_type,
            entity_id,
            field,
            _serialize_audit_value(old_value),
            _serialize_audit_value(new_value),
            changed_by,
        ),
    )
    conn.commit()
    row_id = cur.lastrowid
    conn.close()
    return {
        "id": row_id,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "field": field,
        "old_value": _deserialize_audit_value(_serialize_audit_value(old_value)),
        "new_value": _deserialize_audit_value(_serialize_audit_value(new_value)),
        "changed_by": changed_by,
    }


def get_recent_audit_log(limit: int = 50) -> List[Dict]:
    """Return the most recent audit entries, newest first."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, entity_type, entity_id, field, old_value, new_value, changed_by, timestamp FROM audit_log ORDER BY id DESC LIMIT ?",
        (limit,),
    )
    rows = cur.fetchall()
    conn.close()
    results = []
    for row in rows:
        item = dict(row)
        item["old_value"] = _deserialize_audit_value(item.get("old_value"))
        item["new_value"] = _deserialize_audit_value(item.get("new_value"))
        results.append(item)
    return results


def _token_sorted(text: str) -> str:
    """Word-order-independent form: same words in alphabetical order, so
    'Gate Valve, Cast Iron, 100mm' and 'Cast Iron Gate Valve, 100mm' compare
    as near-identical instead of being penalized for differing word order."""
    return " ".join(sorted(_normalize(text).split()))


def _expand_abbreviations(text: str) -> str:
    tokens = re.findall(r"[a-z0-9.]+", (text or "").lower())
    return " ".join(ABBREVIATIONS.get(token, token) for token in tokens)


def _semantic_text_score(left: str, right: str) -> float:
    left_tokens = set(_expand_abbreviations(left).split())
    right_tokens = set(_expand_abbreviations(right).split())
    if not left_tokens or not right_tokens:
        return 0.0
    overlap = len(left_tokens & right_tokens) / len(left_tokens | right_tokens)
    sequence = SequenceMatcher(None, _expand_abbreviations(left), _expand_abbreviations(right)).ratio()
    return (overlap * 0.6) + (sequence * 0.4)


def _attribute_flags(new_attrs: Dict, existing_attrs: Dict, schema: Dict) -> Dict[str, str]:
    """Compares new_attrs to existing_attrs per critical attribute in
    `schema`, returning {attr_name: "match" | "conflict" | "unknown"} for
    each. Used both to gate matches (tier 2) and, once merged, to store
    exactly which attributes fed the decision (item 13's traceability)."""
    flags = {}
    for name, meta in schema.items():
        new_val, old_val = new_attrs.get(name), existing_attrs.get(name)
        if new_val in (None, "", "null") or old_val in (None, "", "null"):
            flags[name] = "unknown"
            continue

        if meta.get("type") == "numeric":
            try:
                new_num, old_num = float(new_val), float(old_val)
            except (TypeError, ValueError):
                flags[name] = "unknown"
                continue
            tol = meta.get("tolerance", 0.05)
            if old_num == 0:
                flags[name] = "match" if new_num == 0 else "conflict"
            else:
                flags[name] = "match" if abs(new_num - old_num) / abs(old_num) <= tol else "conflict"
        else:
            if str(new_val).strip().lower() == str(old_val).strip().lower():
                flags[name] = "match"
            else:
                ratio = SequenceMatcher(None, str(new_val).lower(), str(old_val).lower()).ratio()
                flags[name] = "match" if ratio >= 0.8 else "conflict"
    return flags


def _attrs_agree(new_attrs: Dict, existing_attrs: Dict, schema: Dict) -> bool:
    """Tier 2 of item 5: True if no critical attribute conflicts."""
    flags = _attribute_flags(new_attrs, existing_attrs, schema)
    return all(f != "conflict" for f in flags.values())


def find_matching_candidates(candidate_description: str, category: str = None,
                             attrs: Dict = None, limit: int = 5) -> List[Dict]:
    """Item 5's tiered match logic:
      Tier 1 - category mismatch -> this candidate is disqualified.
      Tier 2 - a populated critical attribute conflicts -> disqualified.
      Tier 3 - otherwise, text similarity on the standardized description
               makes the final call.
    If `category` is None, falls back to matching across all categories
    (kept for callers that haven't been updated to pass one)."""
    conn = get_connection()
    cur = conn.cursor()
    if category:
        cur.execute(
            "SELECT common_code, standard_description, category, attributes FROM common_materials WHERE category = ?",
            (category,),
        )
    else:
        cur.execute("SELECT common_code, standard_description, category, attributes FROM common_materials")
    rows = cur.fetchall()
    conn.close()

    schema = attribute_schema_for(category) if category else {}
    candidate_norm = _normalize(candidate_description)
    candidate_sorted = _token_sorted(candidate_description)
    candidates = []

    for row in rows:
        flags = {}
        if schema:
            existing_attrs = json.loads(row["attributes"]) if row["attributes"] else {}
            flags = _attribute_flags(attrs or {}, existing_attrs, schema)
            if any(f == "conflict" for f in flags.values()):
                continue  # tier 2: disqualified, don't even consider text similarity

        semantic_score = _semantic_text_score(candidate_description, row["standard_description"])
        sorted_score = SequenceMatcher(None, candidate_sorted, _token_sorted(row["standard_description"])).ratio()
        text_score = max(semantic_score, sorted_score)
        matched = sum(flag == "match" for flag in flags.values())
        known = sum(flag != "unknown" for flag in flags.values())
        attribute_score = matched / known if known else 0.0
        score = (text_score * 0.65) + (attribute_score * 0.35 if known else 0.0)
        reasons = []
        if category:
            reasons.append("Same category")
        if flags.get("material") == "match":
            reasons.append("Same material")
        for name, flag in flags.items():
            if flag == "match" and name != "material":
                reasons.append(f"{name.replace('_', ' ').title()} within tolerance")
            elif flag == "conflict":
                reasons.append(f"Conflicting {name.replace('_', ' ')}")
        if text_score >= 0.68:
            reasons.append("Similar description")
        candidates.append({
            "common_code": row["common_code"],
            "standard_description": row["standard_description"],
            "category": row["category"],
            "score": score,
            "text_score": text_score,
            "attribute_score": attribute_score,
            "attribute_flags": flags,
            "reasons": reasons,
        })

    threshold = MATCH_THRESHOLDS.get(category, MATCH_THRESHOLDS["default"])
    return [candidate for candidate in sorted(candidates, key=lambda item: item["score"], reverse=True)
            if candidate["score"] >= threshold][:limit]


def find_matching_common_code(candidate_description: str, category: str = None,
                               attrs: Dict = None, threshold: float = None) -> Optional[Dict]:
    """Compatibility wrapper returning the best explainable candidate."""
    candidates = find_matching_candidates(candidate_description, category, attrs)
    if not candidates:
        return None
    best = candidates[0]
    if threshold is not None and best["score"] < threshold:
        return None
    return best


def _generate_next_code(category: str = None, material: str = None, dimension: str = None,
                        conn: sqlite3.Connection = None) -> str:
    """Phase 2, Item 6: Segmented code scheme
    Format: CATEGORY-MATERIAL-DIM-SERIAL
    Example: PP-SS-020-0001 (Pipe, stainless steel, 20mm diameter, serial 1)

    If category/material/dimension not provided, falls back to CNMC-XXXX format."""
    if not category or not material or not dimension:
        owns_connection = conn is None
        conn = conn or get_connection()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS c FROM common_materials")
        count = cur.fetchone()["c"]
        if owns_connection:
            conn.close()
        return f"CNMC-{count + 1:04d}"

    cat_prefix = "".join(word[0].upper() for word in category.split()[:3]) if category else "X"
    mat_prefix = str(material).strip().upper()
    if len(mat_prefix) > 4:
        mat_prefix = mat_prefix[:4]

    try:
        dim_num = int(float(str(dimension).split()[0])) if dimension else 0
        dim_code = f"{dim_num:03d}"
    except (ValueError, AttributeError):
        dim_code = "000"

    owns_connection = conn is None
    conn = conn or get_connection()
    cur = conn.cursor()
    code_prefix = f"{cat_prefix}-{mat_prefix}-{dim_code}"
    cur.execute(
        "SELECT COUNT(*) AS c FROM common_materials WHERE common_code LIKE ?",
        (f"{code_prefix}-%",)
    )
    serial = cur.fetchone()["c"] + 1
    if owns_connection:
        conn.close()

    return f"{code_prefix}-{serial:04d}"


def _deduplicate_source_records(conn: sqlite3.Connection) -> None:
    """Keep the earliest row for legacy duplicate source identities."""
    groups = conn.execute(
        "SELECT source_system_id, cpse_id, material_code, MIN(id) AS keep_id "
        "FROM material_records WHERE source_system_id IS NOT NULL AND cpse_id IS NOT NULL "
        "AND material_code IS NOT NULL GROUP BY source_system_id, cpse_id, material_code "
        "HAVING COUNT(*) > 1"
    ).fetchall()
    for group in groups:
        duplicates = conn.execute(
            "SELECT id FROM material_records WHERE source_system_id = ? AND cpse_id = ? "
            "AND material_code = ? AND id != ?",
            (group["source_system_id"], group["cpse_id"], group["material_code"], group["keep_id"]),
        ).fetchall()
        for duplicate in duplicates:
            conn.execute("UPDATE review_decisions SET record_id = ? WHERE record_id = ?", (group["keep_id"], duplicate["id"]))
            conn.execute("DELETE FROM material_records WHERE id = ?", (duplicate["id"],))
            conn.execute(
                "INSERT INTO audit_log (entity_type, entity_id, field, old_value, new_value, changed_by) VALUES (?, ?, ?, ?, ?, ?)",
                ("material_record", duplicate["id"], "duplicate_source_identity", "duplicate", "removed", "migration"),
            )
    conn.commit()


def _migrate_legacy_common_codes(conn: sqlite3.Connection) -> None:
    """Replace legacy category-U-dimension codes with material-aware codes."""
    cur = conn.cursor()
    cur.execute(
        "SELECT id, common_code, standard_description, category, attributes "
        "FROM common_materials WHERE common_code LIKE '%-U-%' ORDER BY id"
    )
    legacy_rows = cur.fetchall()
    if not legacy_rows:
        return

    used_codes = {row[0] for row in cur.execute("SELECT common_code FROM common_materials")}

    for row in legacy_rows:
        segments = row["common_code"].split("-")
        if len(segments) != 4 or segments[1] != "U":
            continue

        try:
            attributes = json.loads(row["attributes"] or "{}")
        except (TypeError, ValueError):
            attributes = {}

        material = _extract_material(attributes, row["standard_description"])
        prefix = f"{segments[0]}-{material}-{segments[2]}"
        serial = segments[3] if segments[3].isdigit() else "0001"
        new_code = f"{prefix}-{serial}"
        next_serial = int(serial)
        while new_code in used_codes and new_code != row["common_code"]:
            next_serial += 1
            new_code = f"{prefix}-{next_serial:04d}"

        if new_code == row["common_code"]:
            continue

        cur.execute(
            "UPDATE material_records SET common_code = ? WHERE common_code = ?",
            (new_code, row["common_code"]),
        )
        cur.execute(
            "UPDATE common_materials SET common_code = ? WHERE id = ?",
            (new_code, row["id"]),
        )
        used_codes.add(new_code)

    conn.commit()


def _repair_ambiguous_material_codes(conn: sqlite3.Connection) -> None:
    """Replace migration tokens that were copied from a description's first word."""
    cur = conn.cursor()
    cur.execute(
        "SELECT id, common_code, standard_description FROM common_materials "
        "WHERE common_code LIKE '%-%-%-%'"
    )
    for row in cur.fetchall():
        segments = row["common_code"].split("-")
        first_word = re.search(r"[A-Za-z]{2,}", row["standard_description"] or "")
        if len(segments) != 4 or not first_word or segments[1] != first_word.group(0).upper()[:4]:
            continue

        material = _extract_material({}, row["standard_description"])
        new_code = f"{segments[0]}-{material}-{segments[2]}-{segments[3]}"
        if new_code == row["common_code"]:
            continue
        if cur.execute("SELECT 1 FROM common_materials WHERE common_code = ?", (new_code,)).fetchone():
            continue

        cur.execute(
            "UPDATE material_records SET common_code = ? WHERE common_code = ?",
            (new_code, row["common_code"]),
        )
        cur.execute(
            "UPDATE common_materials SET common_code = ? WHERE id = ?",
            (new_code, row["id"]),
        )

    conn.commit()


def _backfill_material_codes(conn: sqlite3.Connection) -> None:
    """Seed the material catalog from existing descriptions once per family."""
    rows = conn.execute("SELECT standard_description FROM common_materials").fetchall()
    known_codes = {row["material_code"] for row in conn.execute("SELECT material_code FROM material_codes")}
    for row in rows:
        token = _extract_material({}, row["standard_description"])
        if token == "UNKN" or token in known_codes:
            continue
        register_material_usage(token)
        known_codes.add(token)


def get_or_create_common_material(standard_description: str, category: str, attrs: Dict = None) -> Dict:
    """Phase 3, Item 8: Returns {"common_code", "score", "attribute_flags", "is_new", "status"}
    
    Three-band decision logic (Phase 3):
      - High tolerance (score >= 0.85) → auto-merge, status="confirmed"
      - Mid-band (0.70 <= score < 0.85) → flag for review, status="pending_review"
      - Low tolerance (score < 0.70) → auto new code, status="confirmed"
    
    If no match found → new code with status="confirmed"."""
    material_token = _extract_material(attrs, standard_description)
    material_value = next((attrs.get(key) for key in ["material", "material_type", "base_material", "raw_material"] if attrs and attrs.get(key)), None)
    if material_value:
        register_material_usage(str(material_value))
    elif material_token != "UNKN":
        register_material_usage(material_token)
    candidates = find_matching_candidates(standard_description, category, attrs)
    match = candidates[0] if candidates else None

    if match:
        score = match["score"]
        # Phase 3: Three-band decision logic
        if score >= 0.85:
            # High confidence: auto-merge
            status = "confirmed"
            print(f"HIGH CONFIDENCE (score={score:.2f}): Auto-merged to {match['common_code']}")
        elif score >= 0.70:
            # Mid-band: flag for human review
            status = "pending_review"
            print(f"MID-BAND (score={score:.2f}): Flagged {match['common_code']} for review")
        else:
            # Low confidence: should not reach here (threshold is 0.72), but handle anyway
            return {
                "common_code": None,
                "score": None,
                "attribute_flags": {},
                "candidates": candidates,
                "is_new": True,
                "status": "confirmed",
            }
        
        return {
            "common_code": match["common_code"],
            "score": match["score"],
            "attribute_flags": match["attribute_flags"],
            "candidates": candidates,
            "is_new": False,
            "status": status,
        }

    # No match found: create new code
    conn = get_connection()
    cur = conn.cursor()
    try:
        conn.execute("BEGIN IMMEDIATE")
        common_code = _generate_next_code(category, material_token, _extract_dimension(attrs), conn=conn)
        cur.execute(
            "INSERT INTO common_materials (common_code, standard_description, category, attributes) VALUES (?, ?, ?, ?)",
            (common_code, standard_description, category, json.dumps(attrs or {})),
        )
        conn.commit()
        print(f"Created new common code {common_code}: {standard_description} [{category}]")
    finally:
        conn.close()
    return {"common_code": common_code, "score": None, "attribute_flags": {}, "candidates": [], "is_new": True, "status": "confirmed"}


def _material_token(value: str, allow_generic: bool = False) -> str:
    """Short material token used in code generation (e.g. SS, CS, BR)."""
    text = (value or "").strip()
    if not text:
        return "UNKN"

    lowered = text.lower()
    aliases = {
        "stainless steel": "SS",
        "ss": "SS",
        "carbon steel": "CS",
        "c s": "CS",
        "mild steel": "MS",
        "bronze": "BR",
        "brass": "BR",
        "cast iron": "CI",
        "copper": "CU",
        "galvanized steel": "GS",
        "aluminium": "AL",
        "aluminum": "AL",
        "polypropylene": "PP",
        "polyethylene": "PE",
        "galvanized": "GS",
    }

    for key, token in aliases.items():
        if key in lowered:
            return token

    match = re.search(r"\b(?:SS|CS|MS|CI|CU|AL|BR|GS|PE|PP)\d*\b", text, re.IGNORECASE)
    if match:
        return re.sub(r"\d", "", match.group(0)).upper()

    if allow_generic:
        match = re.search(r"[A-Za-z]{2,}", text)
        if match:
            return match.group(0).upper()[:4]
    return "UNKN"


def register_material_usage(material_name: str) -> Optional[Dict]:
    """Persist a detected material and mark it common after repeated use."""
    material_name = (material_name or "").strip()
    token = _material_token(material_name, allow_generic=True)
    if not material_name or token == "UNKN":
        return None

    canonical_names = {
        "SS": "stainless steel", "CS": "carbon steel", "MS": "mild steel",
        "BR": "bronze", "CI": "cast iron", "CU": "copper", "GS": "galvanized steel",
        "AL": "aluminium", "PP": "polypropylene", "PE": "polyethylene",
    }
    material_name = canonical_names.get(token, material_name.lower())

    conn = get_connection()
    cur = conn.cursor()
    raw_name = material_name.lower()
    cur.execute("SELECT id, material_name, material_code, aliases, usage_count FROM material_codes WHERE material_name = ? OR material_code = ?", (material_name.lower(), token))
    row = cur.fetchone()
    if row:
        usage_count = row["usage_count"] + 1
        aliases = json.loads(row["aliases"] or "[]")
        if raw_name != row["material_name"] and raw_name not in aliases:
            aliases.append(raw_name)
        cur.execute(
            "UPDATE material_codes SET aliases = ?, usage_count = ?, is_common = ?, last_seen = CURRENT_TIMESTAMP WHERE id = ?",
            (json.dumps(aliases), usage_count, int(usage_count >= 2), row["id"]),
        )
        material_code = row["material_code"]
    else:
        usage_count = 1
        cur.execute(
            "INSERT INTO material_codes (material_name, material_code, aliases, usage_count, is_common) VALUES (?, ?, '[]', ?, 0)",
            (material_name.lower(), token, usage_count),
        )
        material_code = token
    conn.commit()
    conn.close()
    return {"material_name": material_name.lower(), "material_code": material_code, "usage_count": usage_count, "is_common": usage_count >= 2}


def get_material_codes() -> List[Dict]:
    """Return the material-token catalog for the admin mapping view."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, material_name, material_code, aliases, owner, approved, usage_count, is_common, last_seen "
        "FROM material_codes ORDER BY is_common DESC, usage_count DESC, material_name"
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def observe_category_candidate(text: str, threshold: int = 3) -> Optional[str]:
    """Promote a recognizable new family after repeated Uncategorized inputs."""
    from categories import suggested_category_for, suggested_category_definition
    category_name = suggested_category_for(text)
    if not category_name:
        return None
    conn = get_connection()
    conn.execute(
        "INSERT INTO category_candidates (category_name, observation_count) VALUES (?, 1) "
        "ON CONFLICT(category_name) DO UPDATE SET observation_count = observation_count + 1, last_observed = CURRENT_TIMESTAMP",
        (category_name,),
    )
    count = conn.execute("SELECT observation_count FROM category_candidates WHERE category_name = ?", (category_name,)).fetchone()[0]
    if count >= threshold:
        register_category(category_name, suggested_category_definition(category_name))
        conn.execute("UPDATE category_candidates SET promoted = 1 WHERE category_name = ?", (category_name,))
        conn.execute(
            "INSERT INTO category_catalog (category_name, attributes, owner, approved) VALUES (?, ?, 'auto-promotion', 1) "
            "ON CONFLICT(category_name) DO UPDATE SET attributes = excluded.attributes, approved = 1, updated_at = CURRENT_TIMESTAMP",
            (category_name, json.dumps(suggested_category_definition(category_name))),
        )
    conn.commit()
    conn.close()
    return category_name if count >= threshold else None


def save_category_definition(category_name: str, attributes: Dict = None, owner: str = "admin") -> Dict:
    """Persist an approved category definition for future application starts."""
    conn = get_connection()
    conn.execute(
        "INSERT INTO category_catalog (category_name, attributes, owner, approved) VALUES (?, ?, ?, 1) "
        "ON CONFLICT(category_name) DO UPDATE SET attributes = excluded.attributes, version = category_catalog.version + 1, owner = excluded.owner, updated_at = CURRENT_TIMESTAMP",
        (category_name.strip(), json.dumps(attributes or {}), owner or "admin"),
    )
    conn.commit()
    conn.close()
    return {"category_name": category_name.strip(), "attributes": attributes or {}, "owner": owner or "admin"}


def retire_common_code(common_code: str, replacement_code: str, changed_by: str = "admin") -> Dict:
    """Retire a code without deleting history and point it to its replacement."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = cur.execute("SELECT common_code, lifecycle_status FROM common_materials WHERE common_code = ?", (common_code,)).fetchone()
        replacement = cur.execute("SELECT common_code FROM common_materials WHERE common_code = ?", (replacement_code,)).fetchone()
        if not row or not replacement:
            raise ValueError("Both the existing and replacement common codes are required")
        cur.execute(
            "UPDATE common_materials SET lifecycle_status = 'retired', retired_at = CURRENT_TIMESTAMP, replacement_code = ? WHERE common_code = ?",
            (replacement_code, common_code),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    log_audit("common_material", 0, "lifecycle_status", row["lifecycle_status"], "retired", changed_by)
    return {"common_code": common_code, "replacement_code": replacement_code, "status": "retired"}


def _extract_material(attrs: Dict, fallback_text: str = "") -> str:
    """Extract material type from attributes or text for code generation."""
    if attrs:
        for key in ["material", "material_type", "base_material", "raw_material"]:
            if key in attrs and attrs.get(key):
                return _material_token(str(attrs.get(key)), allow_generic=True)

    if fallback_text:
        return _material_token(fallback_text)

    return "UNKN"


def _extract_dimension(attrs: Dict) -> str:
    """Extract primary dimension from attributes for code generation."""
    if not attrs:
        return "000"
    # Priority: diameter, size, bore, thickness, etc.
    for key in ["diameter_mm", "size_mm", "bore_mm", "thickness_mm", "cross_section_sqmm"]:
        if key in attrs and attrs[key]:
            try:
                return str(int(float(attrs[key])))
            except (ValueError, TypeError):
                pass
    return "000"


def save_material_data(common_code: Optional[str], standard_description: str, category: str,
                        attrs: Dict = None, cpse_id: str = None, material_code: str = None,
                        description: str = None, specification: str = None, unit_of_measure: str = None,
                        material_type: str = None, procurement_date: str = None,
                        source_system_id: str = "manual", import_batch_id: str = None,
                        source_record_id: str = None, existing_record_id: int = None,
                        changed_by: str = "system") -> Dict:
    """Links a source material record to a (possibly newly created / possibly
    reused) common material code, and records the traceability data behind
    that decision: tolerance_score (tier 3's text-similarity score, if a
    match was made), attribute_flags (per-attribute match/conflict/unknown
    from tier 2), and status.

    Phase 3 (Item 8) implementation: status is now set by three-band logic:
      - High confidence (score >= 0.85) → 'confirmed'
      - Mid-band (0.70 <= score < 0.85) → 'pending_review' (for human validation)
      - Low confidence (score < 0.70) or new code → 'confirmed'

    Returns {"record_id", "common_code", "tolerance_score", "status"}."""
    score, flags, status, candidates = None, {}, "confirmed", []

    if cpse_id and material_code and not existing_record_id:
        existing_conn = get_connection()
        existing = existing_conn.execute(
            "SELECT id, common_code, status, tolerance_score FROM material_records "
            "WHERE source_system_id = ? AND cpse_id = ? AND material_code = ?",
            (source_system_id or "manual", cpse_id, material_code),
        ).fetchone()
        existing_conn.close()
        if existing:
            return {
                "record_id": existing["id"],
                "common_code": existing["common_code"],
                "tolerance_score": existing["tolerance_score"],
                "status": existing["status"],
                "candidates": [],
                "idempotent": True,
            }

    if common_code:
        resolved_code = common_code
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM common_materials WHERE common_code = ?", (resolved_code,))
        if not cur.fetchone():
            cur.execute(
                "INSERT INTO common_materials (common_code, standard_description, category, attributes) VALUES (?, ?, ?, ?)",
                (resolved_code, standard_description, category, json.dumps(attrs or {})),
            )
            conn.commit()
        conn.close()
    else:
        resolved = get_or_create_common_material(standard_description, category, attrs)
        resolved_code = resolved["common_code"]
        score = resolved["score"]
        flags = resolved["attribute_flags"]
        status = resolved["status"]
        candidates = resolved.get("candidates", [])

    conn = get_connection()
    cur = conn.cursor()
    if existing_record_id:
        old_row = cur.execute("SELECT common_code FROM material_records WHERE id = ?", (existing_record_id,)).fetchone()
        if not old_row:
            conn.close()
            raise ValueError(f"Record #{existing_record_id} not found")
        cur.execute('''
            UPDATE material_records
            SET common_code = ?, description = ?, specification = ?,
                unit_of_measure = ?, material_type = ?, procurement_date = ?,
                source_system_id = ?, import_batch_id = ?, source_record_id = ?,
                status = ?, tolerance_score = ?, attribute_flags = ?
            WHERE id = ?
        ''', (resolved_code, description, specification, unit_of_measure, material_type,
              procurement_date, source_system_id or "manual", import_batch_id,
              source_record_id, status, score, json.dumps(flags), existing_record_id))
        conn.commit()
        conn.close()
        if old_row["common_code"] != resolved_code:
            log_audit("material_record", existing_record_id, "common_code", old_row["common_code"], resolved_code, changed_by)
        return {"record_id": existing_record_id, "common_code": resolved_code, "tolerance_score": score, "status": status, "candidates": candidates, "reprocessed": True}

    cur.execute('''
        INSERT INTO material_records
            (common_code, cpse_id, material_code, description, specification,
               unit_of_measure, material_type, procurement_date,
               source_system_id, import_batch_id, source_record_id,
               status, tolerance_score, attribute_flags)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (resolved_code, cpse_id, material_code, description, specification,
            unit_of_measure, material_type, procurement_date,
            source_system_id or "manual", import_batch_id, source_record_id,
          status, score, json.dumps(flags)))
    new_id = cur.lastrowid
    conn.commit()
    conn.close()

    print(f"Saved material record #{new_id} under common code {resolved_code} (status={status})")
    return {"record_id": new_id, "common_code": resolved_code, "tolerance_score": score, "status": status, "candidates": candidates}


def get_all_materials() -> List[Dict]:
    """Every source record, joined with its resolved standardized info.
    Includes each record's status, tolerance_score, and attribute_flags
    (item 13) -- this is what Tab 2's expandable per-code dropdown will
    read from once that's built."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute('''
        SELECT r.id, r.common_code, cm.standard_description, cm.category,
               r.cpse_id, r.material_code, r.description, r.specification,
               r.unit_of_measure, r.material_type, r.procurement_date, r.created_at,
               r.status, r.tolerance_score, r.attribute_flags
        FROM material_records r
        JOIN common_materials cm ON r.common_code = cm.common_code
        ORDER BY r.id
    ''')
    rows = cur.fetchall()
    conn.close()
    results = []
    for row in rows:
        d = dict(row)
        d["attribute_flags"] = json.loads(d["attribute_flags"]) if d.get("attribute_flags") else {}
        results.append(d)
    return results


def get_common_materials_summary(sort: str = "latest") -> List[Dict]:
    """One row per unique common code, with a count of source records
    mapped to it, plus how many of those are still pending_review (item 9)
    -- counts records with status='pending_review'."""
    conn = get_connection()
    cur = conn.cursor()
    order_by = "cm.common_code COLLATE NOCASE ASC" if sort == "alphabetical" else "created_at DESC, cm.common_code COLLATE NOCASE ASC"
    cur.execute(f'''
         SELECT cm.common_code, cm.standard_description, cm.category,
             COALESCE(MAX(r.created_at), cm.created_at) AS created_at,
               COUNT(r.id) AS record_count,
               COUNT(CASE WHEN r.status = 'pending_review' THEN 1 END) AS pending_count
        FROM common_materials cm
        LEFT JOIN material_records r ON cm.common_code = r.common_code
        GROUP BY cm.common_code
        ORDER BY {order_by}
    ''')
    rows = cur.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_pending_review_items() -> List[Dict]:
    """Phase 3, Item 19: Returns all records with status='pending_review'
    grouped by common_code with details for admin review."""
    conn = get_connection()
    cur = conn.cursor()
    
    # Get all pending records
    cur.execute('''
        SELECT r.id, r.common_code, cm.standard_description, cm.category, cm.attributes,
               r.cpse_id, r.material_code, r.description, r.specification,
               r.tolerance_score, r.attribute_flags, r.created_at
        FROM material_records r
        JOIN common_materials cm ON r.common_code = cm.common_code
        WHERE r.status = 'pending_review'
        ORDER BY r.common_code, r.tolerance_score DESC
    ''')
    
    rows = cur.fetchall()
    conn.close()
    
    # Parse JSON fields
    pending = []
    for row in rows:
        item = dict(row)
        item['attribute_flags'] = json.loads(item.get('attribute_flags', '{}'))
        item['attributes'] = json.loads(item.get('attributes', '{}'))
        pending.append(item)
    
    return pending


def approve_pending_merge(common_code: str, reviewer: str = "admin", reason: str = "") -> Dict:
    """Confirm all pending records for a common code and record the decision."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        conn.execute("BEGIN IMMEDIATE")
        rows = cur.execute(
            "SELECT id, common_code FROM material_records WHERE common_code = ? AND status = 'pending_review'",
            (common_code,),
        ).fetchall()
        for row in rows:
            cur.execute(
                "UPDATE material_records SET status = 'confirmed' WHERE id = ?",
                (row["id"],),
            )
            cur.execute(
                "INSERT INTO review_decisions (record_id, previous_common_code, new_common_code, decision, reason, reviewer) VALUES (?, ?, ?, ?, ?, ?)",
                (row["id"], common_code, common_code, "approved", reason, reviewer or "admin"),
            )
            cur.execute(
                "INSERT INTO audit_log (entity_type, entity_id, field, old_value, new_value, changed_by) VALUES (?, ?, ?, ?, ?, ?)",
                ("material_record", row["id"], "review_decision", "pending_review", f"approved: {reason or 'No reason provided'}", reviewer or "admin"),
            )
        conn.commit()
        return {"status": "approved", "updated_records": len(rows), "common_code": common_code, "message": f"{len(rows)} source record(s) confirmed under {common_code}"}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def reject_pending_merge(record_id: int, reviewer: str = "admin", reason: str = "") -> Dict:
    """Create a replacement code and move one rejected record to it."""
    reason = (reason or "").strip()
    if not reason:
        raise ValueError("A rejection reason is required")
    conn = get_connection()
    cur = conn.cursor()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = cur.execute(
            "SELECT r.id, r.common_code, r.source_system_id, r.import_batch_id, r.source_record_id, "
            "cm.standard_description, cm.category, cm.attributes "
            "FROM material_records r JOIN common_materials cm ON cm.common_code = r.common_code "
            "WHERE r.id = ?",
            (record_id,),
        ).fetchone()
        if not row:
            raise ValueError(f"Record #{record_id} not found")

        try:
            attrs = json.loads(row["attributes"] or "{}")
        except (TypeError, ValueError):
            attrs = {}
        material = _extract_material(attrs, row["standard_description"])
        replacement_code = _generate_next_code(row["category"], material, _extract_dimension(attrs), conn=conn)
        cur.execute(
            "INSERT INTO common_materials (common_code, standard_description, category, attributes, replacement_for_code) VALUES (?, ?, ?, ?, ?)",
            (replacement_code, row["standard_description"], row["category"], json.dumps(attrs), row["common_code"]),
        )
        cur.execute(
            "UPDATE material_records SET common_code = ?, status = 'confirmed' WHERE id = ?",
            (replacement_code, record_id),
        )
        cur.execute(
            "INSERT INTO review_decisions (record_id, previous_common_code, new_common_code, decision, reason, reviewer) VALUES (?, ?, ?, ?, ?, ?)",
            (record_id, row["common_code"], replacement_code, "rejected_new_code", reason, reviewer or "admin"),
        )
        cur.execute(
            "INSERT INTO audit_log (entity_type, entity_id, field, old_value, new_value, changed_by) VALUES (?, ?, ?, ?, ?, ?)",
            ("material_record", record_id, "review_decision", "pending_review", f"rejected_new_code: {reason}", reviewer or "admin"),
        )
        conn.commit()
        return {"status": "reassigned", "record_id": record_id, "previous_common_code": row["common_code"], "new_common_code": replacement_code}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_registry_materials() -> List[Dict]:
    """Return all registry entries for full admin editing."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute('''
        SELECT id, common_code, standard_description, category, attributes, created_at
        FROM common_materials
        ORDER BY common_code
    ''')
    rows = cur.fetchall()
    conn.close()

    items = []
    for row in rows:
        item = dict(row)
        item['attributes'] = json.loads(item.get('attributes', '{}')) if item.get('attributes') else {}
        items.append(item)
    return items


def get_analytics_summary(start_date: str = None, end_date: str = None) -> Dict:
    """Return date-filtered operational and data-quality analytics."""
    conn = get_connection()
    cur = conn.cursor()
    conditions = []
    params = []
    if start_date:
        conditions.append("r.created_at >= ?")
        params.append(start_date)
    if end_date:
        conditions.append("r.created_at < datetime(?, '+1 day')")
        params.append(end_date)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    cur.execute(f'SELECT COUNT(*) AS total_records FROM material_records r {where}', params)
    total_records = cur.fetchone()['total_records'] or 0

    cur.execute(f'SELECT COUNT(DISTINCT r.common_code) AS total_unique_codes FROM material_records r {where}', params)
    total_unique_codes = cur.fetchone()['total_unique_codes'] or 0

    duplicate_reduction_pct = 0.0
    if total_records:
        duplicate_reduction_pct = 1 - (total_unique_codes / total_records)

    cur.execute(f'''
        SELECT cm.category, COUNT(r.id) AS record_count
        FROM material_records r
        JOIN common_materials cm ON cm.common_code = r.common_code
        {where}
        GROUP BY cm.category
        ORDER BY cm.category
    ''', params)
    category_rows = cur.fetchall()

    def grouped(column):
        cur.execute(f'SELECT COALESCE(r.{column}, \'Unknown\') AS name, COUNT(*) AS count FROM material_records r {where} GROUP BY r.{column} ORDER BY count DESC', params)
        return {row['name']: row['count'] for row in cur.fetchall()}

    cur.execute(f"SELECT status, COUNT(*) AS count FROM material_records r {where} GROUP BY status", params)
    status_breakdown = {row['status'] or 'Unknown': row['count'] for row in cur.fetchall()}
    cur.execute(f"SELECT CASE WHEN tolerance_score IS NULL THEN 'new_code' WHEN tolerance_score < 0.70 THEN 'low' WHEN tolerance_score < 0.85 THEN 'review_band' ELSE 'high' END AS band, COUNT(*) AS count FROM material_records r {where} GROUP BY band", params)
    confidence_breakdown = {row['band']: row['count'] for row in cur.fetchall()}
    cur.execute(f"SELECT source_system_id, COUNT(*) AS count FROM material_records r {where} GROUP BY source_system_id", params)
    source_breakdown = {row['source_system_id']: row['count'] for row in cur.fetchall()}
    cur.execute(f"SELECT COUNT(*) AS count FROM material_records r {where} AND (r.description IS NULL OR TRIM(r.description) = '' OR r.specification IS NULL OR TRIM(r.specification) = '')" if where else "SELECT COUNT(*) AS count FROM material_records r WHERE r.description IS NULL OR TRIM(r.description) = '' OR r.specification IS NULL OR TRIM(r.specification) = ''", params)
    incomplete_records = cur.fetchone()['count'] or 0
    category_breakdown = {row['category']: row['record_count'] for row in category_rows}
    cpse_breakdown = grouped('cpse_id')
    material_family_breakdown = grouped('material_type')
    pending_review_ageing = get_pending_review_ageing(conn)
    conn.close()

    return {
        'total_records_processed': total_records,
        'total_unique_common_codes': total_unique_codes,
        'duplicate_reduction_pct': duplicate_reduction_pct,
        'category_breakdown': category_breakdown,
        'cpse_breakdown': cpse_breakdown,
        'material_family_breakdown': material_family_breakdown,
        'status_breakdown': status_breakdown,
        'confidence_breakdown': confidence_breakdown,
        'source_breakdown': source_breakdown,
        'incomplete_records': incomplete_records,
        'data_completeness_pct': round((1 - incomplete_records / total_records) * 100, 1) if total_records else 100.0,
        'new_code_rate_pct': round(status_breakdown.get('confirmed', 0) / total_records * 100, 1) if total_records else 0.0,
        'pending_review_ageing': pending_review_ageing,
    }


def get_pending_review_ageing(conn: sqlite3.Connection = None) -> Dict:
    owns_connection = conn is None
    conn = conn or get_connection()
    rows = conn.execute("SELECT CASE WHEN julianday('now') - julianday(created_at) < 1 THEN 'under_1_day' WHEN julianday('now') - julianday(created_at) < 7 THEN '1_to_7_days' ELSE 'over_7_days' END AS age_band, COUNT(*) AS count FROM material_records WHERE status = 'pending_review' GROUP BY age_band").fetchall()
    if owns_connection:
        conn.close()
    return {row['age_band']: row['count'] for row in rows}


def create_material_entry(common_code: str = None, standard_description: str = '',
                          category: str = '', attributes: Dict = None) -> Dict:
    """Create a new registry entry and return the stored record."""
    if not standard_description or not category:
        raise ValueError('standard_description and category are required')

    material_value = next((attributes.get(key) for key in ["material", "material_type", "base_material", "raw_material"] if attributes and attributes.get(key)), None)
    if material_value:
        register_material_usage(str(material_value))

    code = (common_code or '').strip()
    if not code:
        code = _generate_next_code(category=category, material=_extract_material(attributes or {}), dimension=_extract_dimension(attributes or {}))

    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO common_materials (common_code, standard_description, category, attributes) VALUES (?, ?, ?, ?)",
            (code, standard_description, category, json.dumps(attributes or {})),
        )
        conn.commit()
        new_id = cur.lastrowid
    finally:
        conn.close()

    return {
        'id': new_id,
        'common_code': code,
        'standard_description': standard_description,
        'category': category,
        'attributes': attributes or {},
    }


def update_material_entry(material_id: int, common_code: str = None,
                          standard_description: str = None, category: str = None,
                          attributes: Dict = None, changed_by: str = "system") -> Dict:
    """Update an existing registry entry."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        'SELECT id, common_code, standard_description, category, attributes FROM common_materials WHERE id = ?',
        (material_id,),
    )
    row = cur.fetchone()
    if not row:
        conn.close()
        raise ValueError(f'Material #{material_id} not found')

    old_code = row['common_code']
    old_desc = row['standard_description']
    old_category = row['category']
    old_attrs = json.loads(row['attributes']) if row['attributes'] else {}

    new_code = (common_code or row['common_code']).strip()
    new_desc = standard_description if standard_description is not None else row['standard_description']
    new_category = category if category is not None else row['category']
    new_attrs = attributes if attributes is not None else old_attrs

    if old_code != new_code:
        linked_count = cur.execute(
            'SELECT COUNT(*) AS count FROM material_records WHERE common_code = ?',
            (old_code,),
        ).fetchone()['count']
        if linked_count:
            conn.close()
            raise ValueError('A common code with linked source records cannot be changed; retire it and assign a replacement instead')
        cur.execute(
            'UPDATE common_materials SET common_code = ? WHERE id = ?',
            (new_code, material_id),
        )

    cur.execute(
        'UPDATE common_materials SET standard_description = ?, category = ?, attributes = ? WHERE id = ?',
        (new_desc, new_category, json.dumps(new_attrs), material_id),
    )
    conn.commit()
    conn.close()
    if old_code != new_code:
        log_audit('common_material', material_id, 'common_code', old_code, new_code, changed_by)
    if old_desc != new_desc:
        log_audit('common_material', material_id, 'standard_description', old_desc, new_desc, changed_by)
    if old_category != new_category:
        log_audit('common_material', material_id, 'category', old_category, new_category, changed_by)
    if old_attrs != new_attrs:
        log_audit('common_material', material_id, 'attributes', old_attrs, new_attrs, changed_by)

    return {
        'id': material_id,
        'common_code': new_code,
        'standard_description': new_desc,
        'category': new_category,
        'attributes': new_attrs,
    }


def delete_material_entry(material_id: int, changed_by: str = "system") -> Dict:
    """Delete a registry entry and all linked source records."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute('SELECT * FROM common_materials WHERE id = ?', (material_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        raise ValueError(f'Material #{material_id} not found')

    deleted_record = dict(row)
    common_code = row['common_code']
    cur.execute('DELETE FROM material_records WHERE common_code = ?', (common_code,))
    cur.execute('DELETE FROM common_materials WHERE id = ?', (material_id,))
    conn.commit()
    conn.close()

    log_audit('common_material', material_id, 'record', deleted_record, None, changed_by)

    return {'deleted_id': material_id, 'common_code': common_code, 'record_rows_removed': True}


def get_records_for_common_code(common_code: str) -> List[Dict]:
    """Get all individual material records linked to a specific common code."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute('''
        SELECT id, common_code, cpse_id, material_code, description, specification,
             unit_of_measure, material_type, procurement_date, source_system_id,
             import_batch_id, source_record_id, status, created_at
        FROM material_records
        WHERE common_code = ?
        ORDER BY created_at DESC
    ''', (common_code,))
    rows = cur.fetchall()
    conn.close()

    items = []
    for row in rows:
        item = dict(row)
        items.append(item)
    return items


def update_material_record(record_id: int, cpse_id: str = None, material_code: str = None,
                          description: str = None, specification: str = None,
                          unit_of_measure: str = None, material_type: str = None,
                          procurement_date: str = None, changed_by: str = "system") -> Dict:
    """Update an individual material record."""
    conn = get_connection()
    cur = conn.cursor()

    cur.execute('SELECT * FROM material_records WHERE id = ?', (record_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        raise ValueError(f'Record #{record_id} not found')

    current = dict(row)

    updates = {}
    if cpse_id is not None:
        updates['cpse_id'] = cpse_id
    if material_code is not None:
        updates['material_code'] = material_code
    if description is not None:
        updates['description'] = description
    if specification is not None:
        updates['specification'] = specification
    if unit_of_measure is not None:
        updates['unit_of_measure'] = unit_of_measure
    if material_type is not None:
        updates['material_type'] = material_type
    if procurement_date is not None:
        updates['procurement_date'] = procurement_date

    if not updates:
        conn.close()
        return current

    new_source_system = current.get('source_system_id', 'manual')
    new_cpse_id = updates.get('cpse_id', current.get('cpse_id'))
    new_material_code = updates.get('material_code', current.get('material_code'))
    if new_cpse_id and new_material_code:
        duplicate = cur.execute(
            'SELECT id FROM material_records WHERE source_system_id = ? AND cpse_id = ? AND material_code = ? AND id != ?',
            (new_source_system, new_cpse_id, new_material_code, record_id),
        ).fetchone()
        if duplicate:
            conn.close()
            raise ValueError('Another source record already uses this CPSE ID and material code')

    for field, new_value in updates.items():
        old_value = current.get(field)
        if old_value != new_value:
            log_audit('material_record', record_id, field, old_value, new_value, changed_by)

    set_clause = ', '.join([f'{k} = ?' for k in updates.keys()])
    values = list(updates.values()) + [record_id]

    cur.execute(f'UPDATE material_records SET {set_clause} WHERE id = ?', values)
    conn.commit()

    cur.execute('SELECT * FROM material_records WHERE id = ?', (record_id,))
    updated_row = cur.fetchone()
    conn.close()

    return dict(updated_row)


def delete_material_record(record_id: int, changed_by: str = "system") -> Dict:
    """Delete an individual material record."""
    conn = get_connection()
    cur = conn.cursor()

    cur.execute('SELECT * FROM material_records WHERE id = ?', (record_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        raise ValueError(f'Record #{record_id} not found')

    deleted_record = dict(row)
    common_code = row['common_code']
    cur.execute('DELETE FROM material_records WHERE id = ?', (record_id,))
    conn.commit()
    conn.close()

    log_audit('material_record', record_id, 'record', deleted_record, None, changed_by)

    return {'deleted_id': record_id, 'common_code': common_code}


if __name__ == '__main__':
    setup_database()
    print("Database is ready for use.")
