# SIH26099 Technical Deep-Dive — For Team Presentations

This document provides the "why" behind each major system component for peer explanations.

---

## Component 1: Category Classifier (Item 1)

**The Problem:**
Different CPSEs use different naming conventions for the same material type. "Pipe", "Tubes", "Piping", "tubing" all mean the same thing. Before we can apply smart matching logic, we need to normalize these into a fixed list.

**The Solution:**
We use an LLM (Gemma 7B via LM Studio) to classify each material into one of **18 fixed categories** (Pipe, Valve, Fastener, etc.). The LLM is **constrained to return only our fixed list** — it can't invent new categories.

**Technical Details:**
```python
CATEGORY_LIST = [
    "Pipe", "Valve", "Fastener", "Electrical Cable", "Electrical Switchgear",
    "Plate", "Bearing", "Motor", "Pump", "Chemical", "Lubricant", 
    "Gasket / Seal", "Instrument", "Structural Steel", "Paint / Coating",
    "Safety Equipment", "Tool", "Uncategorized"
]

# LLM prompt forces exact match
"Classify this into EXACTLY ONE of: {CATEGORY_LIST}\nRespond with category name only."

# If LLM can't decide, fallback to keyword matching
if "pipe" in text.lower(): return "Pipe"
if "valve" in text.lower(): return "Valve"
```

**Why This Matters:**
- Enables attribute schema lookups (each category has different critical attributes)
- Separates materials into buckets → faster matching
- Prevents "pipe" from matching "valve" by accident
- Provides semantic structure to the registry

**Resilience:**
If LM Studio is down, keyword matching still works. You never get stuck.

---

## Component 2: Attribute Schema (Item 2)

**The Problem:**
A "pipe" needs different attributes for matching than a "valve". Two pipes with different materials might be the same if all other attributes match. But two valves with different valve types are NEVER the same.

**The Solution:**
Define **per-category critical attributes** that determine whether two materials are the same:

```python
CATEGORY_SCHEMA = {
    "Pipe": {
        "diameter_mm": {"type": "numeric", "unit": "mm", "tolerance": 0.05},
        "schedule": {"type": "string"},
        "material": {"type": "string"},
        "length_mm": {"type": "numeric", "unit": "mm", "tolerance": 0.10}
    },
    "Valve": {
        "valve_type": {"type": "string"},
        "size_mm": {"type": "numeric", "unit": "mm", "tolerance": 0.05},
        "material": {"type": "string"},
        "pressure_rating_bar": {"type": "numeric", "unit": "bar", "tolerance": 0.10}
    }
}
```

**Numeric vs String:**
- **Numeric:** Compared after unit conversion with tolerance band
  - `50mm` and `2 inch` are same (both ~50.8mm, within 5% tolerance)
  - `50mm` and `51mm` are same (2% diff, within 5% tolerance)
  - `50mm` and `100mm` are different (100% diff, outside tolerance)

- **String:** Case-insensitive, typo-tolerant fuzzy match
  - "Stainless Steel" vs "SS" may not match (too different)
  - "Stainless Steel" vs "Stainless Steal" might match (80% similar)

**Why Tolerance Matters:**
Real-world materials have manufacturing variation. A "50mm" pipe might actually be 50.2mm. Setting tolerance to 5% means pipes from 47.5mm-52.5mm are equivalent.

---

## Component 3: Attribute Extraction (Item 3)

**The Problem:**
CPSEs send free-text descriptions like "Stainless steel pipe, 50 mm bore, 1.2m long, schedule 40". We need to **extract only the critical attributes** (diameter, schedule, material, length) as structured JSON.

**The Solution:**
Use LLM to parse the text and return only the schema fields:

```python
# For a Pipe, ask LLM:
{
    "diameter_mm": "50",
    "schedule": "40",
    "material": "Stainless Steel",
    "length_mm": "1200"
}

# If LLM sees a field in text but can't extract it clearly, return null
{
    "diameter_mm": "50",
    "schedule": null,  # ← Not mentioned, don't guess!
    "material": "Stainless Steel",
    "length_mm": null  # ← Too ambiguous, don't guess!
}
```

**Key Principle: Never Guess**
If an attribute isn't clearly in the text, return `null`. A wrong guess (saying diameter is 50mm when it's actually 100mm) breaks the entire matching logic.

**Fallback Heuristic:**
If LLM is unavailable, extract first number+unit found:
```python
"Pipe 50mm" → (50.0, 'mm')
"2 inch diameter" → (2.0, 'inch')
```

---

## Component 4: Unit Normalization (Item 4)

**The Problem:**
One CPSE reports "50mm", another reports "2 inch". They're the same material, but naive text matching fails.

**The Solution:**
Convert all measurements to a **canonical unit** before comparison:

```python
_UNIT_TABLES = {
    "mm": {"mm": 1, "inch": 25.4, "cm": 10, "m": 1000, ...},
    "bar": {"bar": 1, "psi": 0.0689, "kpa": 0.01, "mpa": 10},
    "kv": {"kv": 1, "v": 0.001, "volt": 0.001},
}

normalize(2, "inch", "mm") → 2 * 25.4 = 50.8 mm ✓
normalize(50, "mm", "mm") → 50 mm ✓
# Compare: 50.8 ≈ 50 (within 5% tolerance) ✓ MATCH
```

**Why This is Critical:**
Without unit normalization, diameter comparison fails completely:
- `50 mm` vs `2 inch` looks different
- With normalization: `50.8 mm` vs `50 mm` → obviously the same

---

## Component 5: Tiered Match Logic (Item 5)

**The Problem:**
How do we decide if two materials are the same? Must we compare every field? What if one field differs?

**The Solution:**
Three-tier filtering that progressively narrows the search:

### Tier 1: Category Mismatch → Disqualify Immediately
```
Input: Pipe vs Valve
Result: DISQUALIFIED (different categories, different attributes entirely)
```

### Tier 2: Attribute Conflict → Disqualify
```
Input: 50mm Pipe vs 100mm Pipe
Attributes: diameter 50 vs diameter 100
Result: 100% different → CONFLICT → DISQUALIFIED
```

### Tier 3: Text Similarity → Final Decision
```
Input: "Stainless Steel Pipe 50mm" vs "SS Pipe 50mm"
Attributes: All match
Text similarity: 85%
Result: MATCHED ✓

Threshold = 0.72 similarity required for match
```

**Word-Order Independence:**
Text matching uses **word-order-independent** comparison:
```
"Stainless Steel Pipe 50mm" → sorted words: ["50mm", "pipe", "steel", "stainless"]
"Pipe Stainless Steel 50mm" → sorted words: ["50mm", "pipe", "steel", "stainless"]
Result: 100% match (same words, different order) ✓
```

**Flow Chart:**
```
Material A
  ├─ Same category as B?  → No  → NEW CODE
  ├─ Same category
    ├─ Critical attrs conflict? → Yes → NEW CODE
    ├─ Critical attrs OK
      ├─ Text similarity >= 72%? → Yes → MATCHED
      └─ Text similarity < 72%? → No  → NEW CODE
```

---

## Component 6: Segmented Code Scheme (Item 6)

**The Problem:**
Old codes like `CNMC-0001`, `CNMC-0002` are meaningless. You can't tell what material each code represents without looking it up in the database.

**The Solution:**
Encode material information directly into the code:

### Format: `CATEGORY-MATERIAL-DIMENSION-SERIAL`

**Examples:**
```
PP-SS-050-0001  (Pipe, Stainless Steel, 50mm, serial 1)
VV-BR-100-0002  (Valve, Bronze, 100mm, serial 2)
FT-STL-006-0001 (Fastener, Steel, 6mm, serial 1)
EC-CU-025-0003  (Electrical Cable, Copper, 25sqmm, serial 3)
```

### Code Generation:
```python
def _generate_next_code(category, material, dimension):
    cat_prefix = category[:2].upper()          # "Pipe" → "PP"
    mat_prefix = material[:2].upper()          # "Steel" → "ST"
    dim_code = f"{int(float(dimension)):03d}" # 50mm → "050"
    
    # Find next serial for this bucket
    serial = db.count_codes_like(f"{cat_prefix}-{mat_prefix}-{dim_code}-%")
    serial += 1
    
    return f"{cat_prefix}-{mat_prefix}-{dim_code}-{serial:04d}"
```

**Advantage 1: Grouping**
All pipes (PP-...) sort together. All 50mm pipes (PP-...-050-...) are grouped.

**Advantage 2: Self-Documenting**
Code tells you something about the material at a glance.

**Advantage 3: Better for Reports**
Registry reports are inherently organized by type and size.

---

## Component 8: Three-Band Decision Logic (Item 8)

**The Problem:**
Not all matches are equally confident. An 85% similar match is much safer than a 72% similar match. Humans need to validate mid-confidence matches.

**The Solution:**
Three-band logic:

```
Score >= 85%
├─ Very high confidence
├─ Example: "SS Pipe 50mm" vs "Stainless Steel Pipe 50mm"
├─ Decision: Auto-merge → status = "CONFIRMED"
└─ No human review needed

70% <= Score < 85%
├─ Mid-band, probably same but worth verifying
├─ Example: "Pipe 50mm steel" vs "Steel pipe 50 diameter"
├─ Decision: Flag for review → status = "PENDING_REVIEW"
└─ Humans review in Tab 3

Score < 70%
├─ Low confidence, probably different
├─ Example: "Pipe 50mm" vs "Valve 100mm"
├─ Decision: Auto new code → status = "CONFIRMED"
└─ But actually doesn't hit match threshold (0.72 by default)
```

### Why Three Bands?

**Too Many Human Reviews:**
If we send everything 70%+ to humans, admins get 1000s of trivial decisions.

**Too Few Human Reviews:**
If we only review 90%+, we miss mistakes and lose user trust.

**Sweet Spot: 70-85%**
- High enough that most are correct
- Low enough that clear conflicts are caught
- Realistic for humans to handle

### Implementation:
```python
def get_or_create_common_material(description, category, attrs):
    match = find_matching_common_code(description, category, attrs)
    
    if match:
        score = match["score"]
        
        if score >= 0.85:
            return {"common_code": match["common_code"], "status": "confirmed"}
        elif score >= 0.70:
            return {"common_code": match["common_code"], "status": "pending_review"}
        else:
            return None  # Keep searching, score too low
    
    # No match found
    return create_new_code()
```

---

## Phase Flow Summary

### Upload Material
```
User input (description) → Categorize → Extract attributes → Lookup registry

If found:
  - Score >= 85% → Auto-confirm
  - 70% <= Score < 85% → Flag for review
  - Score < 70% → New code

If not found:
  - Create new code
  - Add to registry
```

### Review Phase
```
Humans browse Tab 3 (pending items)
  → Verify attributes match
  → See tolerance score + breakdown
  → Click Approve → status="confirmed"
  → Click Reject → status="rejected_needs_new_code"
```

### End Result
```
Registry grows
  Unique codes: 10 → 15 → 20 (as new materials are discovered)
  Deduplication rate: 40% → 50% → 60% (as duplicates are merged)
  Pending queue: 5 → 0 (as humans approve/reject)
```

---

## Key Takeaways for Team Presentations

### "Why Categorize?"
Categories enable attribute schemas. A pipe's "diameter" is critical; a lubricant's "viscosity" is critical. Same category = compatible matching rules.

### "Why Attributes?"
Attributes are the **source of truth** for whether two materials are the same. Text similarity is just a tiebreaker.

### "Why Three Bands?"
Confidence varies. High-confidence matches are safe to auto-approve. Mid-band needs human eyes. The sweet spot is 70-85%.

### "Why Segmented Codes?"
Self-documenting codes make the registry more usable. You can reason about materials even without looking them up.

### "Why Pending Review?"
Not all AI decisions should be trusted. Humans validate mid-confidence matches before they become "official" in the registry.

---

## Testing Your Understanding

### Q1: Why would two materials with different dimensions still be considered the same?
**A:** They wouldn't. Dimension is a critical attribute (Tier 2). If dimensions conflict (50mm vs 100mm), match fails before text similarity is even checked.

### Q2: What happens if LM Studio is offline?
**A:** Falls back to keyword matching for categorization, offline heuristics for attribute extraction. System still works, just less accurately.

### Q3: How is "Stainless Steel" vs "SS" handled?
**A:** As a string attribute. Fuzzy match with 80% similarity threshold. "SS" is quite different from "Stainless Steel" as strings, so might not auto-match. But if other attributes align perfectly, mid-band logic catches it for human review.

### Q4: Why not just approve all 70%+ matches automatically?
**A:** Risk of false merges. A "Pipe 50mm" might match "Pipe 5mm" at 70% (same words, different digits). Human review catches these mistakes.

### Q5: What's the difference between rejection and a low-score new code?
**A:** Rejection (Tab 3) = human-triggered. Already had a match suggested, human said "no". New code from low score = no match was ever suggested.

---

**Prepared for:** SIH26099 Team Presentations  
**Last Updated:** 2026-08-30  
**Use For:** "Why" explanations during nodal round presentation
