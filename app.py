# app.py - The Web Server Backend (Flask)

from flask import Flask, request, jsonify, send_from_directory

try:
    from matching import process_single_material
    from database import setup_database, get_common_materials_summary, get_all_materials, get_pending_review_items
except ImportError as e:
    print(f"Error importing necessary modules: {e}")
    print("Ensure all files (main.py, matching.py, database.py, gemma_helper.py) are in the same directory.")
    exit(1)

app = Flask(__name__, static_folder='static', static_url_path='')

# Make sure the DB/tables exist as soon as the server starts, so a fresh
# checkout works with just `python app.py` -- no separate setup step needed.
setup_database()


@app.route('/process', methods=['POST'])
def process_data():
    """Receives one material record from the frontend, runs it through the
    real AI-standardization + save pipeline, and returns the result."""
    try:
        data = request.get_json(silent=True) or {}

        required_fields = ['cpse_id', 'material_code', 'description', 'specification']
        missing = [f for f in required_fields if not data.get(f)]
        if missing:
            return jsonify({"error": f"Missing required field(s): {', '.join(missing)}"}), 400

        result = process_single_material(
            cpse_id=data['cpse_id'],
            material_code=data['material_code'],
            description=data['description'],
            specification=data['specification'],
            unit_of_measure=data.get('unit_of_measure'),
            material_type=data.get('material_type'),
            procurement_date=data.get('procurement_date'),
        )

        return jsonify({"status": "Success", **result}), 200

    except Exception as e:
        print(f"Error during request processing in app.py: {e}")
        return jsonify({"error": f"Server Error: {str(e)}"}), 500


@app.route('/materials', methods=['GET'])
def list_materials():
    """Returns one row per unique standardized (common-code) material, with
    a count of how many source records map to it -- i.e. the dedup result."""
    try:
        return jsonify(get_common_materials_summary()), 200
    except Exception as e:
        return jsonify({"error": f"Server Error: {str(e)}"}), 500


@app.route('/records', methods=['GET'])
def list_records():
    """Returns every individual source record (for a more detailed/audit view)."""
    try:
        return jsonify(get_all_materials()), 200
    except Exception as e:
        return jsonify({"error": f"Server Error: {str(e)}"}), 500


@app.route('/pending-review', methods=['GET'])
def get_pending_review():
    """Phase 3, Item 19: Returns all records flagged for human review."""
    try:
        pending = get_pending_review_items()
        return jsonify(pending), 200
    except Exception as e:
        return jsonify({"error": f"Server Error: {str(e)}"}), 500


@app.route('/admin-materials', methods=['GET'])
def get_admin_materials():
    """Returns every registry material row for admin management."""
    try:
        from database import get_registry_materials
        return jsonify(get_registry_materials()), 200
    except Exception as e:
        return jsonify({"error": f"Server Error: {str(e)}"}), 500


@app.route('/admin-materials', methods=['POST'])
def create_admin_material():
    """Create a new registry material entry from the admin interface."""
    try:
        data = request.get_json(silent=True) or {}
        from database import create_material_entry

        material = create_material_entry(
            common_code=data.get('common_code'),
            standard_description=data.get('standard_description', '').strip(),
            category=data.get('category', '').strip(),
            attributes=data.get('attributes') or {},
        )
        return jsonify({"status": "created", "material": material}), 201
    except Exception as e:
        return jsonify({"error": f"Server Error: {str(e)}"}), 500


@app.route('/admin-materials/<int:material_id>', methods=['PUT'])
def update_admin_material(material_id):
    """Update an existing registry material entry."""
    try:
        data = request.get_json(silent=True) or {}
        from database import update_material_entry

        material = update_material_entry(
            material_id,
            common_code=data.get('common_code'),
            standard_description=data.get('standard_description'),
            category=data.get('category'),
            attributes=data.get('attributes'),
        )
        return jsonify({"status": "updated", "material": material}), 200
    except Exception as e:
        return jsonify({"error": f"Server Error: {str(e)}"}), 500


@app.route('/admin-materials/<int:material_id>', methods=['DELETE'])
def delete_admin_material(material_id):
    """Delete a registry material entry and all linked source records."""
    try:
        from database import delete_material_entry
        result = delete_material_entry(material_id)
        return jsonify({"status": "deleted", **result}), 200
    except Exception as e:
        return jsonify({"error": f"Server Error: {str(e)}"}), 500


@app.route('/admin-records/<common_code>', methods=['GET'])
def get_records_by_code(common_code):
    """Get all individual material records for a specific common code."""
    try:
        from database import get_records_for_common_code
        records = get_records_for_common_code(common_code)
        return jsonify(records), 200
    except Exception as e:
        return jsonify({"error": f"Server Error: {str(e)}"}), 500


@app.route('/admin-records/<int:record_id>', methods=['PUT'])
def update_material_record_route(record_id):
    """Update an individual material record."""
    try:
        data = request.get_json(silent=True) or {}
        from database import update_material_record
        
        record = update_material_record(
            record_id,
            cpse_id=data.get('cpse_id'),
            material_code=data.get('material_code'),
            description=data.get('description'),
            specification=data.get('specification'),
            unit_of_measure=data.get('unit_of_measure'),
            material_type=data.get('material_type'),
            procurement_date=data.get('procurement_date'),
        )
        return jsonify({"status": "updated", "record": record}), 200
    except Exception as e:
        return jsonify({"error": f"Server Error: {str(e)}"}), 500


@app.route('/admin-records/<int:record_id>', methods=['DELETE'])
def delete_material_record_route(record_id):
    """Delete an individual material record."""
    try:
        from database import delete_material_record
        result = delete_material_record(record_id)
        return jsonify({"status": "deleted", **result}), 200
    except Exception as e:
        return jsonify({"error": f"Server Error: {str(e)}"}), 500


@app.route('/approve-merge', methods=['POST'])
def approve_merge():
    """Phase 3, Item 19: Approve a pending review and confirm merge to common_code."""
    try:
        data = request.get_json(silent=True) or {}
        common_code = data.get('common_code')
        
        if not common_code:
            return jsonify({"error": "common_code required"}), 400
        
        from database import get_connection
        conn = get_connection()
        cur = conn.cursor()
        
        # Update all pending records for this code to confirmed
        cur.execute(
            "UPDATE material_records SET status = 'confirmed' WHERE common_code = ? AND status = 'pending_review'",
            (common_code,)
        )
        count = cur.rowcount
        conn.commit()
        conn.close()
        
        print(f"Approved merge: {count} pending record(s) for {common_code} now confirmed")
        return jsonify({"status": "approved", "updated_records": count}), 200
    except Exception as e:
        return jsonify({"error": f"Server Error: {str(e)}"}), 500


@app.route('/reject-merge', methods=['POST'])
def reject_merge():
    """Phase 3, Item 19: Reject pending merge - mark records to get new codes."""
    try:
        data = request.get_json(silent=True) or {}
        record_id = data.get('record_id')
        
        if not record_id:
            return jsonify({"error": "record_id required"}), 400
        
        from database import get_connection
        # This would typically trigger re-processing with force_new_code=True
        # For now, just update status and note for manual processing
        conn = get_connection()
        cur = conn.cursor()
        
        cur.execute(
            "UPDATE material_records SET status = 'rejected_needs_new_code' WHERE id = ?",
            (record_id,)
        )
        conn.commit()
        conn.close()
        
        return jsonify({"status": "rejected", "record_id": record_id}), 200
    except Exception as e:
        return jsonify({"error": f"Server Error: {str(e)}"}), 500


@app.route('/upload-csv', methods=['POST'])
def upload_csv():
    """Phase 4, Item 11-12: Bulk CSV upload.
    Sequential processing: each row checked against previous results in batch."""
    try:
        import io
        import csv as csvmodule
        from matching import process_single_material
        
        if 'file' not in request.files:
            return jsonify({"error": "No file provided"}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({"error": "No file selected"}), 400
        
        if not file.filename.endswith('.csv'):
            return jsonify({"error": "File must be CSV"}), 400
        
        # Read and process CSV
        stream = io.StringIO(file.stream.read().decode('utf-8'), newline=None)
        reader = csvmodule.DictReader(stream)
        
        results = []
        for index, row in enumerate(reader, start=1):
            try:
                result = process_single_material(
                    cpse_id=row.get('CPSE_ID', ''),
                    material_code=row.get('Material_Code', ''),
                    description=row.get('Description', ''),
                    specification=row.get('Specification', ''),
                    unit_of_measure=row.get('Unit_of_Measure'),
                    material_type=row.get('Material_Type'),
                    procurement_date=row.get('Procurement_Date'),
                )
                results.append({
                    'row': index,
                    'status': 'success',
                    'common_code': result.get('common_code'),
                    'match_status': result.get('status'),
                    'tolerance_score': result.get('tolerance_score'),
                })
            except Exception as e:
                results.append({
                    'row': index,
                    'status': 'error',
                    'error': str(e),
                })
        
        return jsonify({
            "total_rows": len(results),
            "successful": sum(1 for r in results if r['status'] == 'success'),
            "errors": sum(1 for r in results if r['status'] == 'error'),
            "results": results
        }), 200
    except Exception as e:
        return jsonify({"error": f"Server Error: {str(e)}"}), 500


@app.route('/')
def index():
    """Serves the frontend."""
    return send_from_directory('static', 'index.html')


if __name__ == '__main__':
    print("Starting Flask server on http://127.0.0.1:5000")
    app.run(debug=True, port=5000)
