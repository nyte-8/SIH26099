# app.py - The Web Server Backend (Flask)

import csv
import io
import json
import os
import threading
from functools import wraps
from uuid import uuid4
from flask import Flask, request, jsonify, send_from_directory, session, Response

from categories import CATEGORY_SCHEMA, register_category

try:
    from matching import process_single_material
    from database import setup_database, get_common_materials_summary, get_all_materials, get_pending_review_items
except ImportError as e:
    print(f"Error importing necessary modules: {e}")
    print("Ensure all files (main.py, matching.py, database.py, gemma_helper.py) are in the same directory.")
    exit(1)

app = Flask(__name__, static_folder='static', static_url_path='')
app.secret_key = os.environ.get('APP_SECRET_KEY', 'development-only-change-me')
AUTH_ENABLED = os.environ.get('ENFORCE_AUTH', '0') == '1'
MAX_IMPORT_BYTES = 10 * 1024 * 1024

# Make sure the DB/tables exist as soon as the server starts, so a fresh
# checkout works with just `python app.py` -- no separate setup step needed.
setup_database()


def _authenticated_user():
    if request.headers.get('X-API-Key') and request.headers.get('X-API-Key') == os.environ.get('APP_API_KEY'):
        return {'username': 'api-client', 'role': 'administrator', 'cpse_ids': ['*'], 'api_key': True}
    return session.get('user')


def _current_username() -> str:
    """Who to record as the author of an admin edit/delete in the audit
    trail. Falls back to 'system' so routes still work with auth disabled
    in local/dev use, but a real logged-in session is what actually shows
    up here -- this is the piece that ties '/login' to governance instead
    of every audit row just saying 'system' regardless of who acted."""
    user = _authenticated_user()
    return (user or {}).get('username', 'system')


def _required_role(path: str, method: str):
    if path in {'/login', '/logout', '/me', '/'}:
        return None
    if path.startswith('/migration') or path.startswith('/admin-categories') or path.startswith('/admin-materials'):
        return 'administrator'
    if path == '/process':
        return 'operator'
    if path in {'/approve-merge', '/reject-merge'}:
        return 'reviewer'
    if path in {'/audit-log', '/analytics', '/material-codes'} or path.startswith('/api/v1/'):
        return 'auditor'
    return None


@app.before_request
def enforce_access_control():
    if not AUTH_ENABLED:
        return None
    required = _required_role(request.path, request.method)
    if not required:
        return None
    user = _authenticated_user()
    role_order = {'operator': 1, 'reviewer': 2, 'auditor': 3, 'administrator': 4}
    if not user or role_order.get(user.get('role'), 0) < role_order[required]:
        return jsonify({'error': 'Authentication and authorization required'}), 401
    if request.path == '/process' and user.get('cpse_ids', ['*']) != ['*']:
        source_cpse = (request.get_json(silent=True) or {}).get('cpse_id')
        if source_cpse not in user.get('cpse_ids', []):
            return jsonify({'error': 'CPSE access denied'}), 403
    if request.method in {'POST', 'PUT', 'PATCH', 'DELETE'} and not user.get('api_key'):
        if request.headers.get('X-CSRF-Token') != session.get('csrf_token'):
            return jsonify({'error': 'CSRF token required'}), 403
    return None


@app.route('/login', methods=['POST'])
def login():
    data = request.get_json(silent=True) or {}
    expected_user = os.environ.get('APP_ADMIN_USER', 'admin')
    expected_password = os.environ.get('APP_ADMIN_PASSWORD', 'admin')
    if data.get('username') != expected_user or data.get('password') != expected_password:
        return jsonify({'error': 'Invalid credentials'}), 401
    csrf_token = uuid4().hex
    session['user'] = {'username': expected_user, 'role': 'administrator', 'cpse_ids': ['*']}
    session['csrf_token'] = csrf_token
    from database import log_audit
    log_audit('authentication', 0, 'login', None, expected_user, expected_user)
    return jsonify({'status': 'authenticated', 'user': session['user'], 'csrf_token': csrf_token}), 200


@app.route('/logout', methods=['POST'])
def logout():
    user = session.get('user', {}).get('username', 'anonymous')
    session.clear()
    from database import log_audit
    log_audit('authentication', 0, 'logout', user, None, user)
    return jsonify({'status': 'logged_out'}), 200


@app.route('/me', methods=['GET'])
def current_user():
    user = _authenticated_user()
    return jsonify({
        **(user or {'authenticated': False}),
        'auth_enabled': AUTH_ENABLED,
    }), 200


REQUIRED_IMPORT_HEADERS = {'CPSE_ID', 'Material_Code', 'Description', 'Specification'}


def _read_csv_upload(file_storage, mapping=None):
    raw = file_storage.read(MAX_IMPORT_BYTES + 1)
    if len(raw) > MAX_IMPORT_BYTES:
        raise ValueError('CSV file exceeds the 10 MB limit')
    decoded = None
    for encoding in ('utf-8-sig', 'utf-8', 'cp1252'):
        try:
            decoded = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if decoded is None:
        raise ValueError('CSV encoding must be UTF-8 or Windows-1252')
    reader = csv.DictReader(io.StringIO(decoded, newline=''))
    headers = {header.strip() for header in (reader.fieldnames or []) if header}
    expected_headers = {mapping.get(field, field) for field in REQUIRED_IMPORT_HEADERS} if mapping else REQUIRED_IMPORT_HEADERS
    missing = sorted(expected_headers - headers)
    if missing:
        raise ValueError(f'Missing required CSV header(s): {", ".join(missing)}')
    return list(reader)


def _mapped_import_row(row, mapping):
    mapping = mapping or {}
    def value(name):
        source_name = mapping.get(name, name)
        return (row.get(source_name) or '').strip()
    return {
        'CPSE_ID': value('CPSE_ID'),
        'Material_Code': value('Material_Code'),
        'Description': value('Description'),
        'Specification': value('Specification'),
        'Unit_of_Measure': value('Unit_of_Measure') or None,
        'Material_Type': value('Material_Type') or None,
        'Procurement_Date': value('Procurement_Date') or None,
        'Source_Record_ID': value('Source_Record_ID') or None,
    }


def _validate_import_row(row, index, seen):
    errors = []
    for field in ('CPSE_ID', 'Material_Code', 'Description', 'Specification'):
        if not row.get(field):
            errors.append(f'{field} is required')
    identity = (row.get('CPSE_ID'), row.get('Material_Code'))
    if identity in seen:
        errors.append('duplicate source record in this batch')
    elif all(identity):
        seen.add(identity)
    return errors


def _preview_import_row(row):
    from gemma_helper import classify_category, extract_attributes, generate_standard_info
    from database import find_matching_candidates
    descriptions = [row['Description'], row['Specification']]
    category = classify_category(descriptions)
    attributes, metadata = extract_attributes(category, descriptions, include_metadata=True)
    standard = generate_standard_info(descriptions)
    candidates = find_matching_candidates(standard.get('standard_description', row['Description']), category, attributes)
    return {
        'category': category,
        'standard_description': standard.get('standard_description', row['Description']),
        'proposed_common_code': candidates[0]['common_code'] if candidates else None,
        'candidates': candidates,
        'extraction_metadata': metadata,
    }


def _process_import_batch(batch_id):
    from database import get_import_batch, update_import_row, refresh_import_batch_counts
    batch = get_import_batch(batch_id)
    for row in batch['rows']:
        if row['status'] in {'success', 'preview', 'validation_error'}:
            continue
        payload = None
        try:
            from database import get_connection
            conn = get_connection()
            stored = conn.execute('SELECT payload FROM import_rows WHERE id = ?', (row['id'],)).fetchone()
            conn.close()
            payload = json.loads(stored['payload'])
            if batch['dry_run']:
                result = _preview_import_row(payload)
                update_import_row(row['id'], 'preview', result)
            else:
                result = process_single_material(
                    cpse_id=payload['CPSE_ID'], material_code=payload['Material_Code'],
                    description=payload['Description'], specification=payload['Specification'],
                    unit_of_measure=payload.get('Unit_of_Measure'), material_type=payload.get('Material_Type'),
                    procurement_date=payload.get('Procurement_Date'), source_system_id=batch['source_system_id'],
                    import_batch_id=batch_id, source_record_id=payload.get('Source_Record_ID') or str(row['row_number']),
                )
                update_import_row(row['id'], 'success', result)
        except Exception as error:
            update_import_row(row['id'], 'error', error=str(error))
    refresh_import_batch_counts(batch_id, 'preview' if batch['dry_run'] else 'completed')


@app.route('/migration/stage', methods=['POST'])
def stage_migration():
    """Stage a CSV and return validation results plus a first-row preview."""
    try:
        file = request.files.get('file')
        if not file or not file.filename:
            return jsonify({'error': 'CSV file is required'}), 400
        mapping = json.loads(request.form.get('field_mapping', '{}'))
        rows = [_mapped_import_row(row, mapping) for row in _read_csv_upload(file, mapping)]
        seen = set()
        errors = []
        for index, row in enumerate(rows, start=1):
            row_errors = _validate_import_row(row, index, seen)
            if row_errors:
                errors.append({'row': index, 'errors': row_errors})
        batch_id = str(uuid4())
        from database import create_import_batch
        batch = create_import_batch(batch_id, request.form.get('source_system_id', 'csv-migration'), file.filename, rows, session.get('user', {}).get('username', 'system'), request.form.get('dry_run', 'false').lower() == 'true')
        for item in batch['rows']:
            row_errors = next((entry['errors'] for entry in errors if entry['row'] == item['row_number']), None)
            if row_errors:
                from database import update_import_row
                update_import_row(item['id'], 'validation_error', error='; '.join(row_errors))
        batch['validation_errors'] = errors
        batch['preview_rows'] = rows[:10]
        return jsonify(batch), 201
    except (ValueError, json.JSONDecodeError) as error:
        return jsonify({'error': str(error)}), 400
    except Exception as error:
        return jsonify({'error': f'Server Error: {error}'}), 500


@app.route('/migration/batches/<batch_id>', methods=['GET'])
def migration_batch_status(batch_id):
    try:
        from database import get_import_batch
        return jsonify(get_import_batch(batch_id)), 200
    except Exception as error:
        return jsonify({'error': str(error)}), 404


@app.route('/migration/batches/<batch_id>/process', methods=['POST'])
def process_migration_batch(batch_id):
    try:
        from database import get_import_batch, refresh_import_batch_counts
        batch = get_import_batch(batch_id)
        if batch['status'] in {'completed', 'rolled_back'}:
            return jsonify({'error': f"Batch is already {batch['status']}"}), 409
        if request.args.get('background', 'false').lower() == 'true' or batch['total_rows'] > 100:
            threading.Thread(target=_process_import_batch, args=(batch_id,), daemon=True).start()
            refresh_import_batch_counts(batch_id, 'processing')
            return jsonify({'batch_id': batch_id, 'status': 'processing'}), 202
        _process_import_batch(batch_id)
        return jsonify(get_import_batch(batch_id)), 200
    except Exception as error:
        return jsonify({'error': str(error)}), 404


@app.route('/migration/batches/<batch_id>/rollback', methods=['POST'])
def rollback_migration_batch(batch_id):
    try:
        from database import rollback_import_batch
        return jsonify(rollback_import_batch(batch_id)), 200
    except Exception as error:
        return jsonify({'error': str(error)}), 404


@app.route('/migration/batches/<batch_id>/errors.csv', methods=['GET'])
def migration_error_report(batch_id):
    try:
        from database import get_import_batch
        batch = get_import_batch(batch_id)
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['row', 'status', 'error'])
        writer.writerows((row['row_number'], row['status'], row.get('error') or '') for row in batch['rows'] if row['status'] == 'error')
        return Response(output.getvalue(), mimetype='text/csv', headers={'Content-Disposition': f'attachment; filename={batch_id}-errors.csv'})
    except Exception as error:
        return jsonify({'error': str(error)}), 404


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
            source_system_id=data.get('source_system_id', 'manual'),
            import_batch_id=data.get('import_batch_id'),
            source_record_id=data.get('source_record_id'),
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
        sort = request.args.get('sort', 'latest')
        if sort not in {'latest', 'alphabetical'}:
            return jsonify({'error': 'sort must be latest or alphabetical'}), 400
        materials = get_common_materials_summary(sort)
        page = max(request.args.get('page', 1, type=int), 1)
        per_page = min(max(request.args.get('per_page', 50, type=int), 1), 200)
        start = (page - 1) * per_page
        if request.args.get('page') is None:
            return jsonify(materials), 200
        return jsonify({'items': materials[start:start + per_page], 'page': page, 'per_page': per_page, 'total': len(materials), 'has_next': start + per_page < len(materials)}), 200
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


@app.route('/admin-categories', methods=['GET'])
def get_admin_categories():
    """Return the runtime category registry for admin controls."""
    try:
        return jsonify({"categories": sorted(CATEGORY_SCHEMA.keys())}), 200
    except Exception as e:
        return jsonify({"error": f"Server Error: {str(e)}"}), 500


@app.route('/material-codes', methods=['GET'])
def list_material_codes():
    """Return stable material tokens and their observed usage."""
    try:
        from database import get_material_codes
        return jsonify(get_material_codes()), 200
    except Exception as e:
        return jsonify({"error": f"Server Error: {str(e)}"}), 500


@app.route('/admin-categories', methods=['POST'])
def create_admin_category():
    """Create a new category at runtime when the business adds a frequent new class."""
    try:
        data = request.get_json(silent=True) or {}
        category_name = (data.get('category_name') or '').strip()
        if not category_name:
            return jsonify({"error": "category_name is required"}), 400

        category = register_category(category_name, data.get('attributes') or {})
        from database import save_category_definition
        save_category_definition(category_name, data.get('attributes') or {}, data.get('owner', 'admin'))
        return jsonify({"status": "created" if category["created"] else "exists", "category": category}), 201
    except Exception as e:
        return jsonify({"error": f"Server Error: {str(e)}"}), 500


@app.route('/audit-log', methods=['GET'])
def get_audit_log():
    """Return the most recent audit trail rows for manual edits and deletions."""
    try:
        from database import get_recent_audit_log
        return jsonify(get_recent_audit_log(limit=50)), 200
    except Exception as e:
        return jsonify({"error": f"Server Error: {str(e)}"}), 500


@app.route('/analytics', methods=['GET'])
def get_analytics():
    """Return the minimal analytics summary for dashboard use."""
    try:
        from database import get_analytics_summary
        return jsonify(get_analytics_summary(request.args.get('start'), request.args.get('end'))), 200
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

        category_name = (data.get('category') or '').strip()
        if category_name:
            register_category(category_name)

        material = create_material_entry(
            common_code=data.get('common_code'),
            standard_description=data.get('standard_description', '').strip(),
            category=category_name,
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
        from database import get_records_for_common_code, update_material_entry

        from database import get_registry_materials
        current_material = next((item for item in get_registry_materials() if item['id'] == material_id), None)
        linked_records = get_records_for_common_code(current_material['common_code']) if current_material else []

        category_name = data.get('category')
        if category_name:
            register_category(category_name)

        material = update_material_entry(
            material_id,
            common_code=data.get('common_code'),
            standard_description=data.get('standard_description'),
            category=category_name,
            attributes=data.get('attributes'),
            changed_by=_current_username(),
        )
        reprocessed = []
        for record in linked_records:
            reprocessed.append(process_single_material(
                cpse_id=record.get('cpse_id'),
                material_code=record.get('material_code'),
                description=record.get('description') or material.get('standard_description'),
                specification=record.get('specification') or 'Not provided',
                unit_of_measure=record.get('unit_of_measure'),
                material_type=record.get('material_type'),
                procurement_date=record.get('procurement_date'),
                source_system_id=record.get('source_system_id', 'manual'),
                import_batch_id=record.get('import_batch_id'),
                source_record_id=record.get('source_record_id'),
                existing_record_id=record['id'],
                changed_by=_current_username(),
            ))
        return jsonify({"status": "updated", "material": material, "reprocessed_records": reprocessed}), 200
    except Exception as e:
        return jsonify({"error": f"Server Error: {str(e)}"}), 500


@app.route('/admin-materials/<int:material_id>', methods=['DELETE'])
def delete_admin_material(material_id):
    """Delete a registry material entry and all linked source records."""
    try:
        from database import delete_material_entry
        result = delete_material_entry(material_id, changed_by=_current_username())
        return jsonify({"status": "deleted", **result}), 200
    except Exception as e:
        return jsonify({"error": f"Server Error: {str(e)}"}), 500


@app.route('/admin-materials/<common_code>/retire', methods=['POST'])
def retire_admin_material(common_code):
    """Retire a common code while preserving its historical mappings."""
    try:
        data = request.get_json(silent=True) or {}
        replacement_code = (data.get('replacement_code') or '').strip()
        if not replacement_code:
            return jsonify({"error": "replacement_code required"}), 400
        from database import retire_common_code
        result = retire_common_code(common_code, replacement_code, _current_username())
        return jsonify(result), 200
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
            changed_by=_current_username(),
        )
        from matching import process_single_material
        reprocessed = process_single_material(
            cpse_id=record.get('cpse_id'),
            material_code=record.get('material_code'),
            description=record.get('description'),
            specification=record.get('specification') or 'Not provided',
            unit_of_measure=record.get('unit_of_measure'),
            material_type=record.get('material_type'),
            procurement_date=record.get('procurement_date'),
            source_system_id=record.get('source_system_id', 'manual'),
            import_batch_id=record.get('import_batch_id'),
            source_record_id=record.get('source_record_id'),
            existing_record_id=record_id,
            changed_by=_current_username(),
        )
        return jsonify({"status": "reprocessed", "record": reprocessed}), 200
    except ValueError as e:
        return jsonify({"error": str(e)}), 409
    except Exception as e:
        return jsonify({"error": f"Server Error: {str(e)}"}), 500


@app.route('/admin-records/<int:record_id>', methods=['DELETE'])
def delete_material_record_route(record_id):
    """Delete an individual material record."""
    try:
        from database import delete_material_record
        result = delete_material_record(record_id, changed_by=_current_username())
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
        
        from database import approve_pending_merge
        result = approve_pending_merge(
            common_code,
            reviewer=_current_username(),
            reason=data.get('reason', ''),
        )
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"error": f"Server Error: {str(e)}"}), 500


@app.route('/reject-merge', methods=['POST'])
def reject_merge():
    """Reject a pending merge and assign the record a replacement code."""
    try:
        data = request.get_json(silent=True) or {}
        record_id = data.get('record_id')
        
        if not record_id:
            return jsonify({"error": "record_id required"}), 400
        reason = (data.get('reason') or '').strip()
        if not reason:
            return jsonify({"error": "reason is required"}), 400
        
        from database import reject_pending_merge
        result = reject_pending_merge(
            record_id,
            reviewer=_current_username(),
            reason=reason,
        )
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"error": f"Server Error: {str(e)}"}), 500


# SAP MM integration note:
# This export endpoint would map to SAP MARA/MARC material master tables via the
# ERP-facing integration layer and is intended to be the canonical downstream API.
@app.route('/api/v1/materials/export', methods=['GET'])
def export_materials_api():
    """Expose a versioned, paginated ERP contract; adapters can consume this payload."""
    try:
        from database import create_integration_job, get_all_materials, update_integration_job
        records = get_all_materials()
        page = max(request.args.get('page', 1, type=int), 1)
        per_page = min(max(request.args.get('per_page', 100, type=int), 1), 500)
        start = (page - 1) * per_page
        job = create_integration_job(request.args.get('adapter', 'generic-erp'))
        payload = [
            {
                'material_id': row.get('id'),
                'common_code': row.get('common_code'),
                'cpse_source_code': row.get('cpse_id'),
                'description': row.get('description'),
                'specification': row.get('specification'),
                'category': row.get('category'),
                'unit_of_measure': row.get('unit_of_measure'),
                'plant': row.get('plant'),
                'purchasing_group': row.get('purchasing_group'),
                'valuation_class': row.get('valuation_class'),
                'classification': row.get('attribute_flags'),
                'status': row.get('status'),
            }
            for row in records[start:start + per_page]
        ]
        update_integration_job(job['job_id'], 'ready', acknowledgement='export-created')
        return jsonify({'api_version': 'v1', 'job': job, 'page': page, 'per_page': per_page, 'total': len(records), 'has_next': start + per_page < len(records), 'items': payload}), 200
    except Exception as e:
        return jsonify({"error": f"Server Error: {str(e)}"}), 500


@app.route('/analytics/report.csv', methods=['GET'])
def export_analytics_report():
    """Download the filtered analytics snapshot as a flat CSV report."""
    try:
        from database import get_analytics_summary
        summary = get_analytics_summary(request.args.get('start'), request.args.get('end'))
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['metric', 'value'])
        for key, value in summary.items():
            if isinstance(value, dict):
                for child_key, child_value in value.items():
                    writer.writerow([f'{key}.{child_key}', child_value])
            else:
                writer.writerow([key, value])
        return Response(output.getvalue(), mimetype='text/csv', headers={'Content-Disposition': 'attachment; filename=analytics-report.csv'})
    except Exception as error:
        return jsonify({'error': str(error)}), 500


@app.route('/health', methods=['GET'])
def health():
    """Basic liveness/readiness check for local and pilot deployments."""
    try:
        from database import get_connection
        conn = get_connection()
        conn.execute('SELECT 1')
        conn.close()
        return jsonify({'status': 'ok', 'database': 'ok'}), 200
    except Exception as error:
        return jsonify({'status': 'error', 'database': str(error)}), 503


@app.route('/api/v1/integration/jobs/<job_id>', methods=['GET'])
def integration_job_status(job_id):
    try:
        from database import get_integration_job
        return jsonify(get_integration_job(job_id)), 200
    except Exception as error:
        return jsonify({'error': str(error)}), 404


@app.route('/api/v1/integration/jobs/<job_id>/ack', methods=['POST'])
def acknowledge_integration_job(job_id):
    data = request.get_json(silent=True) or {}
    try:
        from database import update_integration_job
        return jsonify(update_integration_job(job_id, data.get('status', 'acknowledged'), error=data.get('error'), acknowledgement=data.get('acknowledgement', 'received'))), 200
    except Exception as error:
        return jsonify({'error': str(error)}), 404


@app.route('/upload-csv', methods=['POST'])
def upload_csv():
    """Phase 4, Item 11-12: Bulk CSV upload.
    Sequential processing: each row checked against previous results in batch.
    This step is treated as a legacy migration of CPSE master data into the unified registry."""
    try:
        import io
        import csv as csvmodule
        from uuid import uuid4
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
        import_batch_id = str(uuid4())
        source_system_id = request.form.get('source_system_id', 'csv-migration')
        
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
                    source_system_id=source_system_id,
                    import_batch_id=import_batch_id,
                    source_record_id=row.get('Source_Record_ID') or str(index),
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

        legacy_codes_migrated = sum(1 for r in results if r['status'] == 'success' and r.get('tolerance_score') is not None)
        new_common_codes_created = sum(1 for r in results if r['status'] == 'success' and r.get('tolerance_score') is None)
        
        return jsonify({
            "total_rows": len(results),
            "successful": sum(1 for r in results if r['status'] == 'success'),
            "errors": sum(1 for r in results if r['status'] == 'error'),
            "legacy_codes_migrated": legacy_codes_migrated,
            "new_common_codes_created": new_common_codes_created,
            "import_batch_id": import_batch_id,
            "source_system_id": source_system_id,
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
