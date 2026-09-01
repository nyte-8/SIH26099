# matching.py

import pandas as pd
from gemma_helper import generate_standard_info, classify_category, extract_attributes
from database import observe_category_candidate, save_material_data
import os
from typing import List, Dict

DATASET_PATH = "dataset.csv"


def load_dataset() -> pd.DataFrame:
    """Loads the material data from the CSV file."""
    if not os.path.exists(DATASET_PATH):
        raise FileNotFoundError(f"Dataset file not found at {DATASET_PATH}. Please ensure dataset.csv exists.")
    try:
        return pd.read_csv(DATASET_PATH)
    except Exception as e:
        print(f"Error reading CSV file: {e}")
        raise


def _row_get(row, key):
    value = row.get(key)
    return None if pd.isna(value) else value


def process_single_material(cpse_id: str, material_code: str, description: str, specification: str,
                             unit_of_measure: str = None, material_type: str = None,
                             procurement_date: str = None, source_system_id: str = "manual",
                             import_batch_id: str = None, source_record_id: str = None,
                             existing_record_id: int = None, changed_by: str = "system") -> Dict:
    """Runs one material record through the full pipeline. Used by both the
    CSV batch run and the /process web endpoint, so the web UI and the
    batch script always behave identically. Order matters here (this is
    Phase 1's tiered logic end to end):
      1. Classify into a fixed category (item 1).
      2. Extract only that category's critical attributes, SI-normalized
         (items 2-4).
      3. Standardize the free-text description (existing AI call).
      4. Hand category + attributes + description to save_material_data,
         which runs the tiered match (item 5) before minting/reusing a
         code."""
    descriptions = [description] + ([specification] if specification else [])
    descriptions = [d.strip() for d in descriptions if d and d.strip()]

    category = classify_category(descriptions)
    if category == "Uncategorized":
        promoted = observe_category_candidate(" ".join(descriptions))
        if promoted:
            category = promoted
    attrs, extraction_metadata = extract_attributes(category, descriptions, include_metadata=True)

    standard_info = generate_standard_info(descriptions)
    standard_desc = standard_info.get("standard_description", description)

    saved = save_material_data(
        common_code=None,
        standard_description=standard_desc,
        category=category,
        attrs=attrs,
        cpse_id=cpse_id,
        material_code=material_code,
        description=description,
        specification=specification,
        unit_of_measure=unit_of_measure,
        material_type=material_type,
        procurement_date=procurement_date,
        source_system_id=source_system_id,
        import_batch_id=import_batch_id,
        source_record_id=source_record_id,
        existing_record_id=existing_record_id,
        changed_by=changed_by,
    )

    return {
        "record_id": saved["record_id"],
        "common_code": saved["common_code"],
        "material_code": material_code,
        "standard_description": standard_desc,
        "category": category,
        "attributes": attrs,
        "status": saved["status"],
        "tolerance_score": saved["tolerance_score"],
        "candidates": saved.get("candidates", []),
        "extraction_metadata": extraction_metadata,
    }


def process_and_save_data():
    """Loads data, processes each row with the AI, and saves results to the DB."""
    print("--- Starting Data Processing Pipeline ---")
    try:
        df = load_dataset()
        results = []

        for index, row in df.iterrows():
            material_code = row['Material_Code']
            print(f"\nProcessing record {index + 1}: Material Code {material_code}")

            try:
                outcome = process_single_material(
                    cpse_id=_row_get(row, 'CPSE_ID'),
                    material_code=material_code,
                    description=row['Description'],
                    specification=row['Specification'],
                    unit_of_measure=_row_get(row, 'Unit_of_Measure'),
                    material_type=_row_get(row, 'Material_Type'),
                    procurement_date=_row_get(row, 'Procurement_Date'),
                )
                results.append({
                    'Material_Code': material_code,
                    'Common_Code': outcome['common_code'],
                    'Standard_Description': outcome['standard_description'],
                    'Category': outcome['category'],
                    'Status': 'Success'
                })

            except Exception as e:
                print(f"Failed to process record {material_code}. Error: {e}")
                saved = save_material_data(
                    common_code=None,
                    standard_description=row['Description'],
                    category="Uncategorized",
                    cpse_id=_row_get(row, 'CPSE_ID'),
                    material_code=material_code,
                    description=row['Description'],
                    specification=row.get('Specification'),
                    unit_of_measure=_row_get(row, 'Unit_of_Measure'),
                    material_type=_row_get(row, 'Material_Type'),
                    procurement_date=_row_get(row, 'Procurement_Date'),
                )
                results.append({
                    'Material_Code': material_code,
                    'Common_Code': saved['common_code'],
                    'Standard_Description': row['Description'],
                    'Category': "Uncategorized",
                    'Status': 'Fallback/Error'
                })

        print("\n--- Data Processing Complete ---")
        print(f"Total records processed: {len(df)}")
        return results

    except FileNotFoundError as e:
        print(f"\nFATAL ERROR: {e}")
        return []
    except Exception as e:
        print(f"\nAn unexpected error occurred during pipeline execution: {e}")
        return []


if __name__ == '__main__':
    process_and_save_data()
