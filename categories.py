# categories.py
#
# The fixed category list (item 1) and per-category critical-attribute
# schema (item 2) that everything else in the matching pipeline hangs off
# of. Add a category here and the classifier, extractor, and tiered
# matcher all pick it up automatically -- no other file needs to change.
#
# Each attribute is either:
#   {"type": "numeric", "unit": "<canonical unit from units.py>", "tolerance": 0.05}
#     -- values are compared after converting to the canonical unit; a
#        relative difference under `tolerance` counts as a match.
#   {"type": "string"}
#     -- values are compared case-insensitively, with a small allowance
#        for near-miss spelling (e.g. "Stainless Steel" vs "SS" will NOT
#        auto-match here -- only typos/casing do; that's intentional,
#        material name normalization happens at the LLM extraction step).

CATEGORY_SCHEMA = {
    "Pipe": {
        "attributes": {
            "diameter_mm": {"type": "numeric", "unit": "mm", "tolerance": 0.05},
            "schedule": {"type": "string"},
            "material": {"type": "string"},
            "length_mm": {"type": "numeric", "unit": "mm", "tolerance": 0.10},
        }
    },
    "Valve": {
        "attributes": {
            "valve_type": {"type": "string"},
            "size_mm": {"type": "numeric", "unit": "mm", "tolerance": 0.05},
            "material": {"type": "string"},
            "pressure_rating_bar": {"type": "numeric", "unit": "bar", "tolerance": 0.10},
        }
    },
    "Fastener": {
        "attributes": {
            "fastener_type": {"type": "string"},
            "size_mm": {"type": "numeric", "unit": "mm", "tolerance": 0.02},
            "material": {"type": "string"},
            "grade": {"type": "string"},
        }
    },
    "Electrical Cable": {
        "attributes": {
            "core_count": {"type": "numeric", "unit": "count", "tolerance": 0.0},
            "cross_section_sqmm": {"type": "numeric", "unit": "sqmm", "tolerance": 0.05},
            "voltage_rating_kv": {"type": "numeric", "unit": "kv", "tolerance": 0.10},
            "material": {"type": "string"},
        }
    },
    "Electrical Switchgear": {
        "attributes": {
            "device_type": {"type": "string"},
            "rated_current_a": {"type": "numeric", "unit": "a", "tolerance": 0.10},
            "voltage_rating_kv": {"type": "numeric", "unit": "kv", "tolerance": 0.10},
            "poles": {"type": "numeric", "unit": "count", "tolerance": 0.0},
        }
    },
    "Plate": {
        "attributes": {
            "thickness_mm": {"type": "numeric", "unit": "mm", "tolerance": 0.05},
            "material": {"type": "string"},
            "length_mm": {"type": "numeric", "unit": "mm", "tolerance": 0.10},
            "width_mm": {"type": "numeric", "unit": "mm", "tolerance": 0.10},
        }
    },
    "Bearing": {
        "attributes": {
            "bearing_designation": {"type": "string"},
            "bore_mm": {"type": "numeric", "unit": "mm", "tolerance": 0.03},
            "outer_diameter_mm": {"type": "numeric", "unit": "mm", "tolerance": 0.03},
            "width_mm": {"type": "numeric", "unit": "mm", "tolerance": 0.05},
        }
    },
    "Motor": {
        "attributes": {
            "power_kw": {"type": "numeric", "unit": "kw", "tolerance": 0.05},
            "voltage_v": {"type": "numeric", "unit": "v", "tolerance": 0.05},
            "rpm": {"type": "numeric", "unit": "rpm", "tolerance": 0.05},
            "phase": {"type": "string"},
        }
    },
    "Pump": {
        "attributes": {
            "pump_type": {"type": "string"},
            "flow_rate_m3h": {"type": "numeric", "unit": "m3h", "tolerance": 0.10},
            "head_m": {"type": "numeric", "unit": "m", "tolerance": 0.10},
            "material": {"type": "string"},
        }
    },
    "Chemical": {
        "attributes": {
            "chemical_name": {"type": "string"},
            "concentration_pct": {"type": "numeric", "unit": "pct", "tolerance": 0.05},
            "grade": {"type": "string"},
            "packaging": {"type": "string"},
        }
    },
    "Lubricant": {
        "attributes": {
            "product_type": {"type": "string"},
            "viscosity_grade": {"type": "string"},
            "packaging": {"type": "string"},
        }
    },
    "Gasket / Seal": {
        "attributes": {
            "seal_type": {"type": "string"},
            "size_mm": {"type": "numeric", "unit": "mm", "tolerance": 0.05},
            "material": {"type": "string"},
        }
    },
    "Instrument": {
        "attributes": {
            "instrument_type": {"type": "string"},
            "range_value": {"type": "string"},
            "accuracy_class": {"type": "string"},
        }
    },
    "Structural Steel": {
        "attributes": {
            "section_type": {"type": "string"},
            "size_mm": {"type": "numeric", "unit": "mm", "tolerance": 0.05},
            "grade": {"type": "string"},
            "length_mm": {"type": "numeric", "unit": "mm", "tolerance": 0.10},
        }
    },
    "Paint / Coating": {
        "attributes": {
            "product_type": {"type": "string"},
            "color": {"type": "string"},
            "packaging": {"type": "string"},
        }
    },
    "Safety Equipment": {
        "attributes": {
            "equipment_type": {"type": "string"},
            "size": {"type": "string"},
            "standard": {"type": "string"},
        }
    },
    "Tool": {
        "attributes": {
            "tool_type": {"type": "string"},
            "size_mm": {"type": "numeric", "unit": "mm", "tolerance": 0.05},
            "material": {"type": "string"},
        }
    },
    "Uncategorized": {
        "attributes": {}
    },
}

CATEGORY_LIST = list(CATEGORY_SCHEMA.keys())


def attribute_schema_for(category: str) -> dict:
    """Critical-attribute schema for a category, or {} if the category
    is unrecognized (treated like Uncategorized -- no attribute gating)."""
    return CATEGORY_SCHEMA.get(category, {}).get("attributes", {})
