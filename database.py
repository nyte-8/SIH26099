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
from typing import List, Dict, Optional
from difflib import SequenceMatcher

from categories import attribute_schema_for

DB_NAME = "material_master.db"

# Similarity threshold (0-1) above which a new material is considered a
# duplicate of an existing common material rather than a new one.
MATCH_THRESHOLD = 0.72


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (common_code) REFERENCES common_materials (common_code)
        )
    ''')

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
                             ("attribute_flags", "TEXT")]:
        try:
            cur.execute(f"ALTER TABLE material_records ADD COLUMN {column} {coltype}")
            conn.commit()
        except sqlite3.OperationalError:
            pass

    conn.close()
    print("Database setup complete: 'common_materials' and 'material_records' tables ready.")


def _normalize(text: str) -> str:
    return " ".join((text or "").lower().split())


def _token_sorted(text: str) -> str:
    """Word-order-independent form: same words in alphabetical order, so
    'Gate Valve, Cast Iron, 100mm' and 'Cast Iron Gate Valve, 100mm' compare
    as near-identical instead of being penalized for differing word order."""
    return " ".join(sorted(_normalize(text).split()))


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


def find_matching_common_code(candidate_description: str, category: str = None,
                               attrs: Dict = None, threshold: float = MATCH_THRESHOLD) -> Optional[Dict]:
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
    best_row, best_score, best_flags = None, 0.0, {}

    for row in rows:
        flags = {}
        if schema:
            existing_attrs = json.loads(row["attributes"]) if row["attributes"] else {}
            flags = _attribute_flags(attrs or {}, existing_attrs, schema)
            if any(f == "conflict" for f in flags.values()):
                continue  # tier 2: disqualified, don't even consider text similarity

        seq_score = SequenceMatcher(None, candidate_norm, _normalize(row["standard_description"])).ratio()
        sorted_score = SequenceMatcher(None, candidate_sorted, _token_sorted(row["standard_description"])).ratio()
        score = max(seq_score, sorted_score)
        if score > best_score:
            best_row, best_score, best_flags = row, score, flags

    if best_row and best_score >= threshold:
        return {
            "common_code": best_row["common_code"],
            "standard_description": best_row["standard_description"],
            "category": best_row["category"],
            "score": best_score,
            "attribute_flags": best_flags,
        }
    return None


def _generate_next_code(category: str = None, material: str = None, dimension: str = None) -> str:
    """Phase 2, Item 6: Segmented code scheme
    Format: CATEGORY-MATERIAL-DIM-SERIAL
    Example: PP-SS-020-0001 (Pipe, stainless steel, 20mm diameter, serial 1)
    
    If category/material/dimension not provided, falls back to CNMC-XXXX format."""
    if not category or not material or not dimension:
        # Fallback to old format
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS c FROM common_materials")
        count = cur.fetchone()["c"]
        conn.close()
        return f"CNMC-{count + 1:04d}"
    
    # Extract first 2-3 chars from category and material for code prefix
    cat_prefix = "".join(word[0].upper() for word in category.split()) if category else "X"
    mat_prefix = "".join(word[0].upper() for word in material.split()[:2]) if material else "X"
    
    # Normalize dimension to 3 digits
    try:
        dim_num = int(float(str(dimension).split()[0])) if dimension else 0
        dim_code = f"{dim_num:03d}"
    except (ValueError, AttributeError):
        dim_code = "000"
    
    # Find next serial for this bucket
    conn = get_connection()
    cur = conn.cursor()
    code_prefix = f"{cat_prefix}-{mat_prefix}-{dim_code}"
    cur.execute(
        "SELECT COUNT(*) AS c FROM common_materials WHERE common_code LIKE ?",
        (f"{code_prefix}-%",)
    )
    serial = cur.fetchone()["c"] + 1
    conn.close()
    
    return f"{code_prefix}-{serial:04d}"


def get_or_create_common_material(standard_description: str, category: str, attrs: Dict = None) -> Dict:
    """Phase 3, Item 8: Returns {"common_code", "score", "attribute_flags", "is_new", "status"}
    
    Three-band decision logic (Phase 3):
      - High tolerance (score >= 0.85) → auto-merge, status="confirmed"
      - Mid-band (0.70 <= score < 0.85) → flag for review, status="pending_review"
      - Low tolerance (score < 0.70) → auto new code, status="confirmed"
    
    If no match found → new code with status="confirmed"."""
    match = find_matching_common_code(standard_description, category, attrs)
    
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
                "is_new": True,
                "status": "confirmed",
            }
        
        return {
            "common_code": match["common_code"],
            "score": match["score"],
            "attribute_flags": match["attribute_flags"],
            "is_new": False,
            "status": status,
        }

    # No match found: create new code
    common_code = _generate_next_code(category, _extract_material(attrs), _extract_dimension(attrs))
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO common_materials (common_code, standard_description, category, attributes) VALUES (?, ?, ?, ?)",
            (common_code, standard_description, category, json.dumps(attrs or {})),
        )
        conn.commit()
        print(f"Created new common code {common_code}: {standard_description} [{category}]")
    finally:
        conn.close()
    return {"common_code": common_code, "score": None, "attribute_flags": {}, "is_new": True, "status": "confirmed"}


def _extract_material(attrs: Dict) -> str:
    """Extract material type from attributes for code generation."""
    if not attrs:
        return "UNKN"
    # Look for 'material' field in attributes
    material = attrs.get("material") or attrs.get("material_type") or ""
    if material:
        return str(material)[:4].upper()
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
                        material_type: str = None, procurement_date: str = None) -> Dict:
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
    score, flags, status = None, {}, "confirmed"

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
        status = resolved["status"]  # Now includes three-band decision logic

    conn = get_connection()
    cur = conn.cursor()
    cur.execute('''
        INSERT INTO material_records
            (common_code, cpse_id, material_code, description, specification,
             unit_of_measure, material_type, procurement_date,
             status, tolerance_score, attribute_flags)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (resolved_code, cpse_id, material_code, description, specification,
          unit_of_measure, material_type, procurement_date,
          status, score, json.dumps(flags)))
    new_id = cur.lastrowid
    conn.commit()
    conn.close()

    print(f"Saved material record #{new_id} under common code {resolved_code} (status={status})")
    return {"record_id": new_id, "common_code": resolved_code, "tolerance_score": score, "status": status}


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


def get_common_materials_summary() -> List[Dict]:
    """One row per unique common code, with a count of source records
    mapped to it, plus how many of those are still pending_review (item 9)
    -- counts records with status='pending_review'."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute('''
        SELECT cm.common_code, cm.standard_description, cm.category,
               COUNT(r.id) AS record_count,
               COUNT(CASE WHEN r.status = 'pending_review' THEN 1 END) AS pending_count
        FROM common_materials cm
        LEFT JOIN material_records r ON cm.common_code = r.common_code
        GROUP BY cm.common_code
        ORDER BY cm.common_code
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


def create_material_entry(common_code: str = None, standard_description: str = '',
                          category: str = '', attributes: Dict = None) -> Dict:
    """Create a new registry entry and return the stored record."""
    if not standard_description or not category:
        raise ValueError('standard_description and category are required')

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
                          attributes: Dict = None) -> Dict:
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

    new_code = (common_code or row['common_code']).strip()
    new_desc = standard_description if standard_description is not None else row['standard_description']
    new_category = category if category is not None else row['category']
    new_attrs = attributes if attributes is not None else (json.loads(row['attributes']) if row['attributes'] else {})

    old_code = row['common_code']
    if old_code != new_code:
        cur.execute(
            'UPDATE material_records SET common_code = ? WHERE common_code = ?',
            (new_code, old_code),
        )

    cur.execute(
        'UPDATE common_materials SET common_code = ?, standard_description = ?, category = ?, attributes = ? WHERE id = ?',
        (new_code, new_desc, new_category, json.dumps(new_attrs), material_id),
    )
    conn.commit()
    conn.close()

    return {
        'id': material_id,
        'common_code': new_code,
        'standard_description': new_desc,
        'category': new_category,
        'attributes': new_attrs,
    }


def delete_material_entry(material_id: int) -> Dict:
    """Delete a registry entry and all linked source records."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute('SELECT common_code FROM common_materials WHERE id = ?', (material_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        raise ValueError(f'Material #{material_id} not found')

    common_code = row['common_code']
    cur.execute('DELETE FROM material_records WHERE common_code = ?', (common_code,))
    cur.execute('DELETE FROM common_materials WHERE id = ?', (material_id,))
    conn.commit()
    conn.close()

    return {'deleted_id': material_id, 'common_code': common_code, 'record_rows_removed': True}


def get_records_for_common_code(common_code: str) -> List[Dict]:
    """Get all individual material records linked to a specific common code."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute('''
        SELECT id, common_code, cpse_id, material_code, description, specification,
               unit_of_measure, material_type, procurement_date, status, created_at
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
                          procurement_date: str = None) -> Dict:
    """Update an individual material record."""
    conn = get_connection()
    cur = conn.cursor()
    
    # First get the current record
    cur.execute('SELECT * FROM material_records WHERE id = ?', (record_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        raise ValueError(f'Record #{record_id} not found')
    
    current = dict(row)
    
    # Update only non-None fields
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
    
    # Build UPDATE query
    set_clause = ', '.join([f'{k} = ?' for k in updates.keys()])
    values = list(updates.values()) + [record_id]
    
    cur.execute(f'UPDATE material_records SET {set_clause} WHERE id = ?', values)
    conn.commit()
    
    # Fetch and return updated record
    cur.execute('SELECT * FROM material_records WHERE id = ?', (record_id,))
    updated_row = cur.fetchone()
    conn.close()
    
    return dict(updated_row)


def delete_material_record(record_id: int) -> Dict:
    """Delete an individual material record."""
    conn = get_connection()
    cur = conn.cursor()
    
    cur.execute('SELECT id, common_code FROM material_records WHERE id = ?', (record_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        raise ValueError(f'Record #{record_id} not found')
    
    common_code = row['common_code']
    cur.execute('DELETE FROM material_records WHERE id = ?', (record_id,))
    conn.commit()
    conn.close()
    
    return {'deleted_id': record_id, 'common_code': common_code}


if __name__ == '__main__':
    setup_database()
    print("Database is ready for use.")
