# gemma_helper.py
#
# Talks to your local LM Studio server (OpenAI-compatible API) to
# standardize material descriptions. If LM Studio isn't running/reachable,
# falls back to a deterministic offline heuristic so the rest of the
# pipeline still works.
#
# To use your real model:
#   1. Open LM Studio, load your model, and start the local server
#      (LM Studio > Developer tab > "Start Server"). Default port is 1234.
#   2. That's it -- this module talks to it automatically at
#      http://localhost:1234/v1/chat/completions
#   3. If your server runs on a different host/port, or you want to force a
#      specific model name, set env vars before running:
#        LM_STUDIO_HOST=http://localhost:1234
#        LM_STUDIO_MODEL=your-model-name   (optional -- LM Studio uses
#                                            whichever model is loaded even
#                                            if this doesn't match exactly)

import os
import re
import json
import hashlib
import time
from typing import List, Dict, Optional
from difflib import SequenceMatcher

try:
    import requests
except ImportError:
    requests = None

LM_STUDIO_HOST = os.environ.get("LM_STUDIO_HOST", "http://localhost:1234")
LM_STUDIO_MODEL = os.environ.get("LM_STUDIO_MODEL", "local-model")
REQUEST_TIMEOUT = 30
LLM_CACHE_TTL = 900
_response_cache = {}

import categories
from categories import attribute_schema_for
from units import parse_quantities, normalize as normalize_unit, unit_is_recognized

# Keyword table used by the offline fallback (and as a sanity check on the
# LLM's answer) to guess a category from the fixed CATEGORY_LIST.
CATEGORY_KEYWORDS = {
    "Pipe": ["pipe", "tube", "piping"],
    "Valve": ["valve", "cock"],
    "Fastener": ["bolt", "nut", "screw", "washer", "fastener", "rivet"],
    "Electrical Cable": ["cable", "wire", "conductor"],
    "Electrical Switchgear": ["switch", "breaker", "switchgear", "contactor", "relay", "fuse"],
    "Plate": ["plate", "sheet"],
    "Bearing": ["bearing"],
    "Motor": ["motor", "alternator", "generator"],
    "Pump": ["pump"],
    "Chemical": ["acid", "chemical", "solvent", "reagent"],
    "Lubricant": ["oil", "grease", "lubricant"],
    "Gasket / Seal": ["gasket", "seal", "o-ring", "oring"],
    "Instrument": ["gauge", "meter", "sensor", "transmitter", "instrument"],
    "Structural Steel": ["angle", "channel", "beam", "girder", "structural"],
    "Paint / Coating": ["paint", "coating", "primer", "enamel"],
    "Safety Equipment": ["helmet", "harness", "safety", "ppe", "extinguisher"],
    "Tool": ["wrench", "spanner", "drill", "tool", "hammer"],
}


def _guess_category(text: str) -> str:
    lowered = text.lower()
    for category, definition in categories.AUTO_CATEGORY_SUGGESTIONS.items():
        if any(keyword in lowered for keyword in definition["keywords"]):
            return category if category in categories.CATEGORY_LIST else "Uncategorized"
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            return category
    return "Uncategorized"


def _best_known_match(combined: str, known_materials: Optional[List[Dict]]) -> Optional[Dict]:
    """Word-order-independent check against materials already in the
    registry, so the offline fallback reuses an existing entry instead of
    minting a near-duplicate when LM Studio isn't available."""
    if not known_materials:
        return None
    candidate = " ".join(sorted(combined.lower().split()))
    best, best_score = None, 0.0
    for m in known_materials:
        other = " ".join(sorted((m.get("standard_description") or "").lower().split()))
        score = SequenceMatcher(None, candidate, other).ratio()
        if score > best_score:
            best, best_score = m, score
    return best if best_score >= 0.72 else None


def _combine_descriptions(descriptions: List[str]) -> str:
    """Combines raw description and specification without losing key phrases."""
    valid = [re.sub(r"\s+", " ", str(d).strip()) for d in descriptions if d and str(d).strip()]
    if not valid:
        return ""
    if len(valid) == 1:
        return valid[0]
    
    # If one string is entirely contained in the other, use the more detailed one
    if valid[0].lower() in valid[1].lower():
        return valid[1]
    if valid[1].lower() in valid[0].lower():
        return valid[0]
    
    # Otherwise combine clauses smoothly: "Hex bolt, M12, grade 8.8, size-12mm"
    return ", ".join(valid)


def _simulated_response(descriptions: List[str], known_materials: Optional[List[Dict]] = None) -> Dict:
    """Offline fallback used when LM Studio isn't reachable. Combines full
    description and specification context to prevent artificial score drops."""
    valid = [d for d in descriptions if d]
    combined = _combine_descriptions(valid)

    match = _best_known_match(combined, known_materials)
    if match:
        return {
            "standard_description": match["standard_description"],
            "common_code": match["common_code"],
            "category": match["category"],
        }

    digest = hashlib.sha1(combined.lower().encode()).hexdigest()
    code_num = int(digest, 16) % 9999
    return {
        "standard_description": combined.strip(),
        "common_code": f"CNMC-{code_num:04d}",
        "category": _guess_category(combined),
    }


def classify_category(descriptions: List[str]) -> str:
    """Item 1: tags a material into exactly one of the fixed CATEGORY_LIST
    buckets. Tries the LLM first (constrained to the fixed list so it
    can't invent new categories), falls back to keyword matching."""
    combined = " ".join(d for d in descriptions if d).strip()
    if not combined:
        return "Uncategorized"

    category_list_str = ", ".join(categories.CATEGORY_LIST)
    prompt = f"""Classify this material into EXACTLY ONE of the following categories (respond with the category name only, exactly as written, nothing else):
{category_list_str}

Material: {combined}"""

    raw_response = ask_gemma(prompt)
    if raw_response:
        answer = raw_response.strip().strip('."\'')
        for category in categories.CATEGORY_LIST:
            if answer.lower() == category.lower():
                return category
        # Model answered with something close but not exact -- try a
        # substring match before giving up on it.
        for category in categories.CATEGORY_LIST:
            if category.lower() in answer.lower():
                return category
        print(f"[gemma_helper] Category '{answer}' not in fixed list; using keyword fallback.")

    return _guess_category(combined)


def extract_attributes(category: str, descriptions: List[str], include_metadata: bool = False) -> Dict:
    """Item 3: pulls only the critical attributes defined for `category`
    (see categories.py) out of the descriptions, as structured data with
    numeric fields normalized to SI units (item 4). Missing attributes are
    None rather than guessed -- an unknown value must never masquerade as
    a confirmed match or mismatch in the tiered logic downstream."""
    schema = attribute_schema_for(category)
    if not schema:
        empty_result = {}
        metadata = {
            "source": "not_applicable",
            "model": None,
            "prompt_version": "attributes-v2",
            "field_confidence": {},
            "warnings": ["No attribute schema is defined for this category"],
        }
        return (empty_result, metadata) if include_metadata else empty_result

    combined = " ".join(d for d in descriptions if d).strip()
    attr_names = list(schema.keys())

    prompt = f"""Extract these attributes from the material description below. Respond with ONLY a valid JSON object, no other text, using exactly these keys: {", ".join(attr_names)}.
For any numeric attribute, output just the number converted to these units: {", ".join(f"{k} in {v['unit']}" for k, v in schema.items() if v.get('type') == 'numeric')}.
Use null for any attribute not mentioned in the description. Do not guess.
For the string field `material`, use values like `Stainless Steel`, `Carbon Steel`, `Bronze` when that material is explicitly named.
When a material is explicitly named, normalize it to its standard material family. Do not invent a material when it is absent.

Material description: {combined}"""

    raw_response = ask_gemma(prompt)
    if raw_response:
        try:
            cleaned = raw_response.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.strip("`")
                cleaned = cleaned[4:] if cleaned.lower().startswith("json") else cleaned
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict):
                normalized = {str(k).strip().lower(): v for k, v in parsed.items()}
                if not all(name.lower() in normalized for name in attr_names):
                    raise ValueError("Required extraction fields are missing")
                result = {}
                for name in attr_names:
                    value = parsed.get(name)
                    if value is None:
                        alias_candidates = [
                            name,
                            name.lower(),
                            name.upper(),
                            name.title(),
                            name.replace('_', ' '),
                            name.replace('_', ' ').title(),
                        ]
                        if 'material' in name.lower():
                            alias_candidates.extend(['material', 'Material', 'material_type', 'Material Type'])
                        for candidate in alias_candidates:
                            if candidate in normalized:
                                value = normalized[candidate]
                                break
                    if meta := schema.get(name):
                        if meta.get("type") == "numeric" and value is not None:
                            value = float(value)
                    result[name] = value
                if any(
                    schema[name].get("type") == "numeric" and value is not None and not isinstance(value, (int, float))
                    for name, value in result.items()
                ):
                    raise ValueError("Numeric attribute validation failed")
                metadata = {
                    "source": "llm",
                    "model": LM_STUDIO_MODEL,
                    "prompt_version": "attributes-v2",
                    "field_confidence": {name: 0.95 if value not in (None, "") else 0.0 for name, value in result.items()},
                    "warnings": [],
                }
                return (result, metadata) if include_metadata else result
        except Exception as e:
            print(f"[gemma_helper] Could not parse attribute JSON ({e}); using offline fallback.")

    result = _extract_attributes_offline(schema, combined)
    metadata = {
        "source": "offline_fallback",
        "model": None,
        "prompt_version": "attributes-v2",
        "field_confidence": {name: 0.45 if value not in (None, "") else 0.0 for name, value in result.items()},
        "warnings": ["LM Studio unavailable or returned invalid JSON"],
    }
    return (result, metadata) if include_metadata else result


_UNIT_SUFFIXES_BY_LENGTH = sorted(
    ["_mm", "_kv", "_kw", "_bar", "_pct", "_rpm", "_m3h", "_sqmm", "_v", "_a", "_m", "_count"],
    key=len, reverse=True,
)


def _keyword_for_field(name: str) -> str:
    """Best-guess plain-English keyword for a schema field name, e.g.
    'outer_diameter_mm' -> 'outer diameter', 'power_kw' -> 'power'. Used to
    find the number actually next to that word in the text, rather than
    just the nearest same-unit number, when a description mentions several
    values that share a unit (diameter/length/width all in mm, say)."""
    for suffix in _UNIT_SUFFIXES_BY_LENGTH:
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    return name.replace("_", " ").strip()


def _find_near_keyword(text_lower: str, keyword: str, max_distance: int = 10):
    """Looks for a number sitting right next to `keyword`, in either order,
    within a short window -- e.g. 'nominal diameter 50mm' (keyword first)
    or '10mm thickness' (number first). Returns (value, unit) for whichever
    pattern is found earliest in the text, or None if neither matches.
    
    Enhanced: Uses stricter matching with configurable max distance to avoid
    grabbing wrong numbers from other clauses."""
    if not keyword:
        return None
    import re
    kw = re.escape(keyword)
    # [^0-9,] so the window can't cross a comma -- commas separate distinct
    # spec clauses (e.g. "bore 25mm, OD 52mm"). Reduced default window from
    # 15 to 10 chars for tighter matching.
    forward = re.search(kw + r'[^0-9,]{0,' + str(max_distance) + r'}(-?\d+(?:\.\d+)?)\s*([a-zA-Z"%]*)', text_lower)
    backward = re.search(r'(-?\d+(?:\.\d+)?)\s*([a-zA-Z"%]*)[^0-9,]{0,' + str(max_distance) + r'}' + kw, text_lower)
    candidates = [m for m in (forward, backward) if m]
    if not candidates:
        return None
    match = min(candidates, key=lambda m: m.start())
    return float(match.group(1)), match.group(2).lower()


def _extract_attributes_offline(schema: Dict, combined_text: str) -> Dict:
    """Best-effort attribute extraction with no LLM available.

    Numeric attributes are filled in three passes so a value doesn't get
    assigned to the wrong field just because it appears first in the text,
    or because another field happens to share its unit:
      Pass 1 (keyword-adjacent): for each numeric attribute, look for its
        own name (e.g. "diameter" for diameter_mm, "length" for length_mm)
        sitting right next to a number in the text. This is what
        disambiguates "nominal diameter 50mm, ... length 6000mm" correctly
        even though both numbers are in mm -- a plain unit match alone
        can't tell them apart.
      Pass 2 (confident unit match): for whatever pass 1 didn't resolve,
        take the next not-yet-used parsed number whose unit is an
        explicit, recognized spelling of that attribute's canonical unit.
      Pass 3 (positional fallback): anything still empty (usually because
        the text used a bare/unitless number, e.g. "PN16") takes the next
        unused parsed value in order.
    A field with nothing left to draw from stays None -- intentional; an
    unknown value must never masquerade as a guess here.

    Material string values are recognized from common material names so
    the field does not stay stuck as null when the model is unreachable.
    """
    result = {name: None for name in schema}
    combined_lower_for_keywords = (combined_text or "").lower()
    parsed_values = parse_quantities(combined_text)
    used = [False] * len(parsed_values)
    numeric_fields = [name for name, meta in schema.items() if meta.get("type") == "numeric"]

    def _claim_matching_parsed(value, unit):
        """Marks the first unused parsed entry equal to (value, unit) as
        used, so passes 2/3 don't also hand it out to another field."""
        for i, (pv, pu) in enumerate(parsed_values):
            if not used[i] and pv == value and pu == unit:
                used[i] = True
                return

    # Pass 1: keyword-adjacent matches -- the field's own name next to a number.
    # Skipped when the derived keyword IS the canonical unit itself (e.g. a
    # field literally named "rpm"): in that case the "keyword" would just
    # match the unit letters attached to some unrelated number elsewhere in
    # the text, and the direct unit-suffix match in pass 2 is more reliable.
    for name in numeric_fields:
        keyword = _keyword_for_field(name)
        if keyword == schema[name]["unit"].lower():
            continue
        found = _find_near_keyword(combined_lower_for_keywords, keyword) if keyword else None
        if found:
            value, unit = found
            result[name] = normalize_unit(value, unit, schema[name]["unit"])
            _claim_matching_parsed(value, unit)

    # Pass 2: confident, unit-verified matches for whatever's still empty.
    for name in numeric_fields:
        if result[name] is not None:
            continue
        canonical_unit = schema[name]["unit"]
        for i, (value, unit) in enumerate(parsed_values):
            if used[i]:
                continue
            if unit_is_recognized(unit, canonical_unit):
                result[name] = normalize_unit(value, unit, canonical_unit)
                used[i] = True
                break

    # Pass 3: positional fallback using whatever numbers are still unclaimed.
    # Prefer a bare/unitless leftover (e.g. the "16" in "PN16") over one that
    # already carries an explicit, different unit (e.g. a stray "50mm") --
    # a number tagged with someone else's unit is a worse guess than one
    # with no unit at all for a field expecting yet another unit.
    # ENHANCED: Skip values that are clearly too large/small for the field
    # (e.g., skip 50 for a percentage field expecting 0-100).
    for name in numeric_fields:
        if result[name] is not None:
            continue
        unused = [i for i, used_flag in enumerate(used) if not used_flag]
        # Sort by: prefer bare units, then by value plausibility
        def sort_key(i):
            val, unit = parsed_values[i]
            # Tier 1: bare units (unit == "")
            bare_tier = 0 if unit == "" else 1
            # Tier 2: reject obviously implausible values
            # (e.g., percentage > 100, negative where not allowed)
            canonical = schema[name].get("unit", "")
            is_plausible = True
            if canonical in {"pct", "%"}:
                is_plausible = 0 <= val <= 100
            elif canonical in {"bar", "psi", "mpa", "kpa"}:
                is_plausible = val >= 0
            # Return (bare_tier, is_plausible_tier, value_order)
            plausible_tier = 0 if is_plausible else 1
            return (bare_tier, plausible_tier, i)
        
        unused.sort(key=sort_key)
        if unused:
            i = unused[0]
            value, unit = parsed_values[i]
            result[name] = normalize_unit(value, unit, schema[name]["unit"])
            used[i] = True

    combined_lower = combined_lower_for_keywords
    material_aliases = {
        "stainless steel": "Stainless Steel",
        "ss316": "Stainless Steel",
        "ss304": "Stainless Steel",
        "ss": "Stainless Steel",
        "carbon steel": "Carbon Steel",
        "cs": "Carbon Steel",
        "mild steel": "Mild Steel",
        "ms": "Mild Steel",
        "bronze": "Bronze",
        "brass": "Brass",
        "copper": "Copper",
        "cu": "Copper",
        "cast iron": "Cast Iron",
        "ci": "Cast Iron",
        "galvanized steel": "Galvanized Steel",
        "aluminium": "Aluminium",
        "aluminum": "Aluminum",
        "alloy steel": "Alloy Steel",
        "pvc": "PVC",
        "ptfe": "PTFE",
        "xlpe": "XLPE",
    }
    import re as _re
    if "material" in schema and result.get("material") is None:
        for phrase, canonical in material_aliases.items():
            if _re.search(r'\b' + _re.escape(phrase) + r'\b', combined_lower):
                result["material"] = canonical
                break

    if "conductor_material" in schema and result.get("conductor_material") is None:
        if _re.search(r'\b(copper|cu)\b', combined_lower):
            result["conductor_material"] = "Copper"
        elif _re.search(r'\b(aluminum|aluminium|al)\b', combined_lower):
            result["conductor_material"] = "Aluminum"

    # Fastener type & Grade
    if "fastener_type" in schema and result.get("fastener_type") is None:
        m_ft = _re.search(r'\b(hex bolt|stud bolt|anchor bolt|u-bolt|socket head|cap screw|bolt|nut|washer|screw|rivet)\b', combined_lower)
        if m_ft:
            result["fastener_type"] = m_ft.group(1).title()

    if "grade" in schema and result.get("grade") is None:
        m_gr = _re.search(r'\b(?:grade|gr|class)\s*([0-9]+(?:\.[0-9]+)?|[A-Za-z0-9-]+)\b', combined_lower)
        if m_gr:
            result["grade"] = m_gr.group(1).upper()

    # Valve & Pump types
    if "valve_type" in schema and result.get("valve_type") is None:
        m_vt = _re.search(r'\b(ball valve|gate valve|globe valve|check valve|butterfly valve|needle valve|plug valve|control valve)\b', combined_lower)
        if m_vt:
            result["valve_type"] = m_vt.group(1).title()

    if "pump_type" in schema and result.get("pump_type") is None:
        m_pt = _re.search(r'\b(centrifugal|submersible|gear pump|positive displacement|reciprocating)\b', combined_lower)
        if m_pt:
            result["pump_type"] = m_pt.group(1).title()

    # Seal & Fitting types
    if "seal_type" in schema and result.get("seal_type") is None:
        m_st = _re.search(r'\b(spiral wound|o-ring|oring|gasket|mechanical seal|lip seal)\b', combined_lower)
        if m_st:
            result["seal_type"] = m_st.group(1).title()

    if "fitting_type" in schema and result.get("fitting_type") is None:
        m_fit = _re.search(r'\b(elbow|tee|reducer|flange|coupling|nipple|union|cap)\b', combined_lower)
        if m_fit:
            result["fitting_type"] = m_fit.group(1).title()

    # Pipe Schedule
    if "schedule" in schema and result.get("schedule") is None:
        m_sch = _re.search(r'\bsch(?:edule)?\s*([0-9]+[A-Za-z]*|std|xs|xxs)\b', combined_lower)
        if m_sch:
            result["schedule"] = m_sch.group(1).upper()

    return result



def ask_gemma(prompt: str) -> Optional[str]:
    """Calls your local model via LM Studio's OpenAI-compatible
    /v1/chat/completions endpoint. Returns None on any connection/timeout
    error so the caller can fall back to the offline heuristic."""
    if requests is None:
        return None
    cache_key = hashlib.sha256(prompt.encode('utf-8')).hexdigest()
    cached = _response_cache.get(cache_key)
    if cached and time.time() - cached[0] < LLM_CACHE_TTL:
        return cached[1]
    try:
        response = None
        for attempt in range(2):
            try:
                response = requests.post(
                    f"{LM_STUDIO_HOST}/v1/chat/completions",
                    json={
                        "model": LM_STUDIO_MODEL,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.2,
                    },
                    timeout=REQUEST_TIMEOUT,
                )
                break
            except requests.RequestException:
                if attempt == 1:
                    raise
        response.raise_for_status()
        data = response.json()
        result = (data["choices"][0]["message"]["content"] or "").strip()
        _response_cache[cache_key] = (time.time(), result)
        return result
    except Exception as e:
        print(f"[gemma_helper] LM Studio call failed ({e}); using offline fallback.")
        return None


def generate_standard_info(descriptions: List[str]) -> Dict:
    """Analyzes a list of material descriptions and returns standardized
    info: {standard_description, common_code, category}."""
    if not descriptions:
        return {"error": "No descriptions provided"}

    description_string = "\n".join(d for d in descriptions if d)
    prompt = f"""Analyze the following material descriptions from multiple sources to identify identical, duplicate, near-duplicate, and functionally equivalent materials.
Then respond with EXACTLY this format and nothing else:
Standard description: <one clean, standardized description>
Common code: CNMC-<a 4 digit number you choose>
Category: <one word category, e.g. Pipes, Valves, Electrical, Fasteners>

Material Descriptions:
{description_string}"""

    raw_response = ask_gemma(prompt)

    if raw_response:
        try:
            standard_info = {}
            for line in raw_response.strip().split("\n"):
                if line.startswith("Standard description:"):
                    standard_info["standard_description"] = line.split(":", 1)[1].strip()
                elif line.startswith("Common code:"):
                    standard_info["common_code"] = line.split(":", 1)[1].strip()
                elif line.startswith("Category:"):
                    standard_info["category"] = line.split(":", 1)[1].strip()

            if all(k in standard_info for k in ("standard_description", "common_code", "category")):
                return standard_info
            print("[gemma_helper] Model response missing expected fields; using offline fallback.")
        except Exception as e:
            print(f"[gemma_helper] Error parsing model response ({e}); using offline fallback.")

    return _simulated_response(descriptions)


if __name__ == '__main__':
    sample_descriptions = [
        "SS Pipe 50mm",
        "Stainless Steel Pipe 2 inch",
        "Pipe SS 50MM Dia"
    ]
    result = generate_standard_info(sample_descriptions)
    print("\n--- Final Result ---")
    print(json.dumps(result, indent=4))
