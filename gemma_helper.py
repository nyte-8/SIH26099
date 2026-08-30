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
from typing import List, Dict, Optional
from difflib import SequenceMatcher

try:
    import requests
except ImportError:
    requests = None

LM_STUDIO_HOST = os.environ.get("LM_STUDIO_HOST", "http://localhost:1234")
LM_STUDIO_MODEL = os.environ.get("LM_STUDIO_MODEL", "local-model")
REQUEST_TIMEOUT = 30

from categories import CATEGORY_LIST, attribute_schema_for
from units import parse_quantity, normalize as normalize_unit

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


def _simulated_response(descriptions: List[str], known_materials: Optional[List[Dict]] = None) -> Dict:
    """Offline fallback used when LM Studio isn't reachable. Same input
    always produces the same code; different inputs produce different
    codes (the old version always returned one hardcoded result). Checks
    the existing registry first so obvious repeats reuse a code instead
    of minting a new one."""
    valid = [d for d in descriptions if d]
    combined = re.sub(r"\s+", " ", " ".join(valid)).strip()

    match = _best_known_match(combined, known_materials)
    if match:
        return {
            "standard_description": match["standard_description"],
            "common_code": match["common_code"],
            "category": match["category"],
        }

    base = max(valid, key=len, default=combined)
    digest = hashlib.sha1(combined.lower().encode()).hexdigest()
    code_num = int(digest, 16) % 9999
    return {
        "standard_description": base.strip(),
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

    category_list_str = ", ".join(CATEGORY_LIST)
    prompt = f"""Classify this material into EXACTLY ONE of the following categories (respond with the category name only, exactly as written, nothing else):
{category_list_str}

Material: {combined}"""

    raw_response = ask_gemma(prompt)
    if raw_response:
        answer = raw_response.strip().strip('."\'')
        for category in CATEGORY_LIST:
            if answer.lower() == category.lower():
                return category
        # Model answered with something close but not exact -- try a
        # substring match before giving up on it.
        for category in CATEGORY_LIST:
            if category.lower() in answer.lower():
                return category
        print(f"[gemma_helper] Category '{answer}' not in fixed list; using keyword fallback.")

    return _guess_category(combined)


def extract_attributes(category: str, descriptions: List[str]) -> Dict:
    """Item 3: pulls only the critical attributes defined for `category`
    (see categories.py) out of the descriptions, as structured data with
    numeric fields normalized to SI units (item 4). Missing attributes are
    None rather than guessed -- an unknown value must never masquerade as
    a confirmed match or mismatch in the tiered logic downstream."""
    schema = attribute_schema_for(category)
    if not schema:
        return {}

    combined = " ".join(d for d in descriptions if d).strip()
    attr_names = list(schema.keys())

    prompt = f"""Extract these attributes from the material description below. Respond with ONLY a valid JSON object, no other text, using exactly these keys: {", ".join(attr_names)}.
For any numeric attribute, output just the number converted to these units: {", ".join(f"{k} in {v['unit']}" for k, v in schema.items() if v.get('type') == 'numeric')}.
Use null for any attribute not mentioned in the description. Do not guess.

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
                return {name: parsed.get(name) for name in attr_names}
        except Exception as e:
            print(f"[gemma_helper] Could not parse attribute JSON ({e}); using offline fallback.")

    return _extract_attributes_offline(schema, combined)


def _extract_attributes_offline(schema: Dict, combined_text: str) -> Dict:
    """Best-effort attribute extraction with no LLM available: numeric
    attributes get the first number+unit found in the text (weak but
    functional for single-dimension descriptions); string attributes are
    left null rather than guessed, since a wrong guess is worse than an
    unknown value in the tiered matcher."""
    result = {}
    parsed = parse_quantity(combined_text)
    for name, meta in schema.items():
        if meta.get("type") == "numeric" and parsed:
            value, unit = parsed
            result[name] = normalize_unit(value, unit, meta["unit"])
        else:
            result[name] = None
    return result



def ask_gemma(prompt: str) -> Optional[str]:
    """Calls your local model via LM Studio's OpenAI-compatible
    /v1/chat/completions endpoint. Returns None on any connection/timeout
    error so the caller can fall back to the offline heuristic."""
    if requests is None:
        return None
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
        response.raise_for_status()
        data = response.json()
        return (data["choices"][0]["message"]["content"] or "").strip()
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
