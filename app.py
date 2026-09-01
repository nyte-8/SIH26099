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


REQUIRED_IMPORT_HEADERS = {'CPSE_ID', 'Material_Code', 'Description'}


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
        'Unit_of_Measure': value('Unit_of_Measure') or None,
        'Material_Type': value('Material_Type') or None,
        'Procurement_Date': value('Procurement_Date') or None,
        'Source_Record_ID': value('Source_Record_ID') or None,
    }


def _validate_import_row(row, index, seen):
    errors = []
    for field in ('CPSE_ID', 'Material_Code', 'Description'):
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
    descriptions = [row['Description']]
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
                    description=payload['Description'], specification=payload.get('Specification', ''),
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

        required_fields = ['cpse_id', 'material_code', 'description']
        missing = [f for f in required_fields if not data.get(f)]
        if missing:
            return jsonify({"error": f"Missing required field(s): {', '.join(missing)}"}), 400

        result = process_single_material(
            cpse_id=data['cpse_id'],
            material_code=data['material_code'],
            description=data['description'],
            specification=data.get('specification', ''),  # Now optional
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


@app.route('/admin-categories/candidates', methods=['GET'])
def get_category_candidates():
    """Return candidate categories awaiting admin approval.
    
    These are categories that appeared in Uncategorized materials and met
    the observation threshold, but have NOT been auto-promoted (as of this fix).
    
    Admin must explicitly call /admin-categories/<name>/promote to activate.
    """
    try:
        from database import get_connection
        conn = get_connection()
        candidates = conn.execute(
            "SELECT category_name, observation_count, last_observed, promoted "
            "FROM category_candidates WHERE promoted = 0 "
            "ORDER BY observation_count DESC, last_observed DESC"
        ).fetchall()
        conn.close()
        
        return jsonify({
            'candidates': [
                {
                    'name': row['category_name'],
                    'observation_count': row['observation_count'],
                    'last_observed': row['last_observed'],
                    'status': 'pending_approval',
                }
                for row in candidates
            ]
        }), 200
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


@app.route('/admin-categories/<category_name>/promote', methods=['POST'])
def promote_category_candidate(category_name):
    """Explicitly approve a candidate category for promotion.
    
    Categories are no longer auto-promoted; this endpoint must be called
    to activate a candidate category (recorded via observe_category_candidate).
    
    Requires: reviewer or administrator role
    """
    try:
        from database import get_connection, save_category_definition, log_audit
        from categories import suggested_category_definition, register_category
        
        category_name = (category_name or '').strip()
        if not category_name:
            return jsonify({"error": "category_name is required"}), 400
        
        data = request.get_json(silent=True) or {}
        attributes = data.get('attributes')
        
        conn = get_connection()
        
        # Verify it's a candidate
        candidate = conn.execute(
            "SELECT observation_count, promoted FROM category_candidates WHERE category_name = ?",
            (category_name,)
        ).fetchone()
        
        if not candidate:
            conn.close()
            return jsonify({"error": f"'{category_name}' is not a candidate category"}), 404
        
        if candidate['promoted']:
            conn.close()
            return jsonify({"error": f"'{category_name}' has already been promoted"}), 409
        
        # Use provided attributes or auto-suggested ones
        if attributes is None:
            attributes = suggested_category_definition(category_name) or {}
        
        # Promote it
        register_category(category_name, attributes)
        save_category_definition(category_name, attributes, _current_username())
        
        # Mark as promoted
        conn.execute(
            "UPDATE category_candidates SET promoted = 1 WHERE category_name = ?",
            (category_name,)
        )
        
        # Log the approval
        log_audit(
            'category_candidate',
            0,
            'promoted',
            None,
            category_name,
            _current_username(),
            details={'observation_count': candidate['observation_count'], 'approved_by': _current_username()}
        )
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'status': 'promoted',
            'category_name': category_name,
            'attributes': attributes,
            'promoted_by': _current_username(),
            'observation_count': candidate['observation_count'],
        }), 200
    
    except Exception as e:
        import traceback
        print(traceback.format_exc())
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
# This export endpoint maps to SAP MARA/MARC material master tables via the
# ERP-facing integration layer and is the canonical downstream API.
# Supports multiple adapters (SAP, Oracle, generic HTTP, or simulated).
@app.route('/api/v1/materials/export', methods=['GET'])
def export_materials_api():
    """Expose a versioned, paginated ERP contract with adapter-based transmission.
    
    Query Parameters:
    - adapter: ERP adapter name (sap, oracle, http, demo) - default: demo
    - page: Page number for pagination - default: 1
    - per_page: Records per page - default: 100, max: 500
    - transmit: Whether to actually transmit to ERP - default: false (export only)
    
    Returns:
    - api_version, job, items (paginated materials), transmission status
    """
    try:
        from database import create_integration_job, get_all_materials, update_integration_job
        from erp_adapters import get_adapter, load_adapter_config
        
        records = get_all_materials()
        page = max(request.args.get('page', 1, type=int), 1)
        per_page = min(max(request.args.get('per_page', 100, type=int), 1), 500)
        start = (page - 1) * per_page
        should_transmit = request.args.get('transmit', 'false').lower() == 'true'
        adapter_name = request.args.get('adapter', 'demo')
        
        job = create_integration_job(adapter_name)
        
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
        
        transmission_status = None
        transmission_message = None
        
        # Attempt transmission if requested
        if should_transmit and payload:
            adapter_config = load_adapter_config(adapter_name)
            adapter = get_adapter(adapter_name, adapter_config)
            
            if adapter:
                try:
                    success, message = adapter.transmit(payload, job['job_id'])
                    transmission_status = 'success' if success else 'partial_failure'
                    transmission_message = message
                    update_integration_job(
                        job['job_id'],
                        'acknowledged' if success else 'error',
                        acknowledgement=message
                    )
                except Exception as e:
                    transmission_status = 'error'
                    transmission_message = str(e)
                    update_integration_job(job['job_id'], 'error', error=str(e))
            else:
                transmission_status = 'adapter_not_found'
                transmission_message = f"Adapter '{adapter_name}' not available"
                update_integration_job(job['job_id'], 'error', error=transmission_message)
        else:
            transmission_status = 'export_only'
            transmission_message = 'No transmission attempted (transmit=false)'
            update_integration_job(job['job_id'], 'ready', acknowledgement='export-created')
        
        return jsonify({
            'api_version': 'v1',
            'job': job,
            'page': page,
            'per_page': per_page,
            'total': len(records),
            'has_next': start + per_page < len(records),
            'transmission': {
                'adapter': adapter_name,
                'status': transmission_status,
                'message': transmission_message,
            },
            'items': payload
        }), 200
    except Exception as e:
        import traceback
        logger_error = traceback.format_exc()
        print(f"Export error: {logger_error}")
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


SAMPLE_CPSE_DATASET = [
    {
        "CPSE_ID": "ONGC",
        "Material_Code": "ONGC-PIP-101",
        "Description": "SS 304 Seamless Pipe 2 inch Sch 40, Stainless Steel 304, 2 inch (50.8mm) diameter, Schedule 40, length 6000mm",
        "Unit_of_Measure": "MTR",
        "Material_Type": "Piping",
        "Procurement_Date": "2024-01-15"
    },
    {
        "CPSE_ID": "IOCL",
        "Material_Code": "IOCL-P-992",
        "Description": "Pipe Stainless Steel 50mm Dia Sch40, SS304 grade seamless piping, nominal diameter 50mm, wall schedule 40, 6m length",
        "Unit_of_Measure": "M",
        "Material_Type": "Pipes & Tubes",
        "Procurement_Date": "2024-02-20"
    },
    {
        "CPSE_ID": "GAIL",
        "Material_Code": "GAIL-MAT-440",
        "Description": "PIPE, SS, 50 MM NOMINAL BORE, SCH 40, Stainless steel pipe 50mm NB sch 40 length 6000mm for gas processing unit",
        "Unit_of_Measure": "NOS",
        "Material_Type": "Piping Materials",
        "Procurement_Date": "2024-03-10"
    },
    {
        "CPSE_ID": "ONGC",
        "Material_Code": "ONGC-VAL-502",
        "Description": "Ball Valve 2 inch 150# Flanged SS316, Full bore ball valve, size 50mm (2 inch), rating Class 150 (20 bar), SS316 body",
        "Unit_of_Measure": "NOS",
        "Material_Type": "Valves",
        "Procurement_Date": "2024-01-18"
    },
    {
        "CPSE_ID": "IOCL",
        "Material_Code": "IOCL-VLV-331",
        "Description": "SS316 Ball Valve Size 50mm PN20 Flanged, Stainless steel 316 flanged ball valve, 50mm nominal size, 20 bar pressure rating",
        "Unit_of_Measure": "EA",
        "Material_Type": "Valves & Fittings",
        "Procurement_Date": "2024-02-25"
    },
    {
        "CPSE_ID": "BHEL",
        "Material_Code": "BHEL-FST-801",
        "Description": "Hex Bolt M12 x 50mm Grade 8.8 High Tensile, M12 hex head bolt, 50mm length, 12mm size, high tensile grade 8.8 carbon steel with nut",
        "Unit_of_Measure": "SET",
        "Material_Type": "Fasteners",
        "Procurement_Date": "2024-01-22"
    },
    {
        "CPSE_ID": "NTPC",
        "Material_Code": "NTPC-BOLT-104",
        "Description": "Bolt Hexagonal 12mm x 50mm Gr 8.8 Carbon Steel, Hex bolt 12mm dia, length 50mm, Grade 8.8 CS zinc plated for turbine casing",
        "Unit_of_Measure": "NOS",
        "Material_Type": "Hardware",
        "Procurement_Date": "2024-02-14"
    },
    {
        "CPSE_ID": "SAIL",
        "Material_Code": "SAIL-CBL-603",
        "Description": "XLPE Power Cable 3 Core 2.5 sqmm 1.1kV Copper, 3C x 2.5 sq mm copper conductor, XLPE insulated, PVC sheathed armored cable 1100V",
        "Unit_of_Measure": "MTR",
        "Material_Type": "Electrical",
        "Procurement_Date": "2024-03-01"
    },
    {
        "CPSE_ID": "BHEL",
        "Material_Code": "BHEL-EL-209",
        "Description": "Copper Cable 3C x 2.5mm2 1.1kV Armoured, 3 core copper electrical power cable, cross section 2.5 sqmm, voltage rating 1.1 kV",
        "Unit_of_Measure": "M",
        "Material_Type": "Cables & Wiring",
        "Procurement_Date": "2024-03-12"
    },
    {
        "CPSE_ID": "NTPC",
        "Material_Code": "NTPC-PMP-701",
        "Description": "Centrifugal Water Pump 50 m3/hr Head 40m, End suction centrifugal pump, flow rate 50 m3/h, head 40m, Cast Iron casing, 7.5kW motor",
        "Unit_of_Measure": "SET",
        "Material_Type": "Pumps & Turbines",
        "Procurement_Date": "2024-02-28"
    },
    {
        "CPSE_ID": "SAIL",
        "Material_Code": "SAIL-PLT-110",
        "Description": "Mild Steel Plate 10mm x 1500mm x 3000mm IS 2062, Structural mild steel plate, thickness 10mm, width 1500mm, length 3000mm, Grade E250",
        "Unit_of_Measure": "TON",
        "Material_Type": "Plates & Sheets",
        "Procurement_Date": "2024-01-30"
    },
    {
        "CPSE_ID": "GAIL",
        "Material_Code": "GAIL-GSK-905",
        "Description": "Spiral Wound Gasket 50mm NB Class 150 SS316 / Graphite, Metallic spiral wound gasket with inner ring, size 50mm, 150# rating, 316SS graphite filler",
        "Unit_of_Measure": "NOS",
        "Material_Type": "Gaskets",
        "Procurement_Date": "2024-03-15"
    }
]


@app.route('/api/v1/sample-dataset', methods=['GET'])
def get_sample_dataset():
    """Returns benchmark multi-CPSE messy dataset for instant evaluation demo."""
    return jsonify({
        "status": "success",
        "count": len(SAMPLE_CPSE_DATASET),
        "dataset": SAMPLE_CPSE_DATASET
    }), 200


@app.route('/api/v1/load-sample-dataset', methods=['POST'])
def load_sample_dataset():
    """Ingests the multi-CPSE benchmark dataset and returns detailed deduplication metrics."""
    try:
        from matching import process_single_material
        from uuid import uuid4
        batch_id = f"demo-batch-{uuid4().hex[:8]}"
        results = []

        for idx, row in enumerate(SAMPLE_CPSE_DATASET, start=1):
            res = process_single_material(
                cpse_id=row['CPSE_ID'],
                material_code=row['Material_Code'],
                description=row['Description'],
                specification='',
                unit_of_measure=row.get('Unit_of_Measure'),
                material_type=row.get('Material_Type'),
                procurement_date=row.get('Procurement_Date'),
                source_system_id=f"ERP_{row['CPSE_ID']}",
                import_batch_id=batch_id,
                source_record_id=str(idx),
                changed_by="demo_loader"
            )
            results.append({
                "row": idx,
                "cpse_id": row['CPSE_ID'],
                "material_code": row['Material_Code'],
                "common_code": res.get('common_code'),
                "category": res.get('category'),
                "status": res.get('status'),
                "tolerance_score": res.get('tolerance_score'),
                "standard_description": res.get('standard_description'),
            })

        unique_codes = len(set(r['common_code'] for r in results if r.get('common_code')))
        total_rows = len(results)
        reduction_pct = round((1 - (unique_codes / total_rows)) * 100, 1) if total_rows else 0.0

        return jsonify({
            "status": "success",
            "batch_id": batch_id,
            "total_ingested": total_rows,
            "unique_cnmc_created": unique_codes,
            "duplicate_reduction_pct": reduction_pct,
            "results": results
        }), 200
    except Exception as e:
        return jsonify({"error": f"Failed to load sample dataset: {str(e)}"}), 500


@app.route('/')
def index():
    """Serves the frontend."""
    return send_from_directory('static', 'index.html')


if __name__ == '__main__':
    print("Starting Flask server on http://127.0.0.1:5000")
    app.run(debug=True, port=5000)

