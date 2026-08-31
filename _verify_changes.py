import os
import json

os.remove('material_master.db') if os.path.exists('material_master.db') else None

import database
from gemma_helper import _extract_attributes_offline


database.setup_database()
print('audit_helper', database.log_audit('material_record', 1, 'description', 'old', 'new'))
print('summary_before', database.get_analytics_summary())

conn = database.get_connection()
cur = conn.cursor()
cur.execute(
    'INSERT INTO common_materials (common_code, standard_description, category, attributes) VALUES (?, ?, ?, ?)',
    ('CNMC-0001', 'SS Pipe', 'Pipe', json.dumps({'diameter_mm': 50, 'length_mm': 2000})),
)
cur.execute(
    'INSERT INTO material_records (common_code, cpse_id, material_code, description, specification, status, tolerance_score, attribute_flags) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
    ('CNMC-0001', 'CPSE-1', 'M1', 'SS Pipe 50mm', 'schedule 40', 'confirmed', 0.9, '{}'),
)
conn.commit()
conn.close()

print('analytics_after_insert', database.get_analytics_summary())
print('offline_fix', _extract_attributes_offline({
    'diameter_mm': {'type': 'numeric', 'unit': 'mm'},
    'length_mm': {'type': 'numeric', 'unit': 'mm'},
    'schedule': {'type': 'string'}
}, 'SS Pipe 50mm length 2000mm'))

print('update_entry', database.update_material_entry(1, standard_description='SS Pipe 300mm', category='Pipe', attributes={'diameter_mm': 300, 'length_mm': 2000}))
print('update_record', database.update_material_record(1, description='Updated description'))
print('delete_record', database.delete_material_record(1))
print('delete_entry', database.delete_material_entry(1))
print('summary_after_delete', database.get_analytics_summary())

from app import app
client = app.test_client()
print('audit_route_status', client.get('/audit-log').status_code)
print('audit_route_preview', client.get('/audit-log').get_json()[:2])
print('analytics_route_status', client.get('/analytics').status_code)
print('analytics_route_payload', client.get('/analytics').get_json())
