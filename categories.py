# categories.py
#
# Fixed category registry and attribute schema metadata used by the matching
# and extraction pipeline.

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

AUTO_CATEGORY_SUGGESTIONS = {
    "Circuits": {
        "keywords": ["circuit", "pcb", "printed circuit", "integrated circuit"],
        "attributes": {
            "circuit_type": {"type": "string"},
            "voltage_v": {"type": "numeric", "unit": "v", "tolerance": 0.05},
            "current_a": {"type": "numeric", "unit": "a", "tolerance": 0.10},
        },
    },
    "Car": {
        "keywords": ["car", "automobile", "vehicle", "sedan", "suv", "hatchback"],
        "attributes": {
            "vehicle_type": {"type": "string"},
            "make": {"type": "string"},
            "model": {"type": "string"},
            "year": {"type": "numeric", "unit": "year", "tolerance": 0.0},
        },
    },
    "Engine": {
        "keywords": ["engine", "motor", "combustion", "diesel", "petrol"],
        "attributes": {
            "engine_type": {"type": "string"},
            "displacement_cc": {"type": "numeric", "unit": "cc", "tolerance": 0.05},
            "power_hp": {"type": "numeric", "unit": "hp", "tolerance": 0.05},
        },
    },
    "Battery": {
        "keywords": ["battery", "cell", "accumulator", "rechargeable"],
        "attributes": {
            "battery_type": {"type": "string"},
            "voltage_v": {"type": "numeric", "unit": "v", "tolerance": 0.05},
            "capacity_ah": {"type": "numeric", "unit": "ah", "tolerance": 0.05},
        },
    },
    "Composite": {
        "keywords": ["composite", "fiber", "carbon", "fiberglass", "laminate"],
        "attributes": {
            "composite_type": {"type": "string"},
            "fiber_type": {"type": "string"},
            "resin_type": {"type": "string"},
        },
    },
}


def suggested_category_for(text: str) -> str:
    """Return a candidate category for a frequent previously unknown family."""
    lowered = (text or "").lower()
    for category, definition in AUTO_CATEGORY_SUGGESTIONS.items():
        if any(keyword in lowered for keyword in definition["keywords"]):
            return category
    return ""


def suggested_category_definition(category_name: str) -> dict:
    definition = AUTO_CATEGORY_SUGGESTIONS.get(category_name, {})
    return definition.get("attributes", {})


def register_category(category_name: str, attributes: dict = None) -> dict:
    """Register a new material category at runtime."""
    if not category_name or not str(category_name).strip():
        raise ValueError("Category name is required")

    normalized_name = str(category_name).strip()
    if normalized_name in CATEGORY_SCHEMA:
        return {
            "name": normalized_name,
            "attributes": CATEGORY_SCHEMA[normalized_name].get("attributes", {}),
            "created": False,
        }

    CATEGORY_SCHEMA[normalized_name] = {"attributes": attributes or {}}
    global CATEGORY_LIST
    CATEGORY_LIST = list(CATEGORY_SCHEMA.keys())
    return {
        "name": normalized_name,
        "attributes": CATEGORY_SCHEMA[normalized_name].get("attributes", {}),
        "created": True,
    }


def attribute_schema_for(category: str) -> dict:
    """Return the schema for a category, or {} if unknown."""
    return CATEGORY_SCHEMA.get(category, {}).get("attributes", {})
