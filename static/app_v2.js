// static/app_v2.js - Updated with three-tab interface and new features

document.addEventListener('DOMContentLoaded', function () {
    // ============ UI Elements ============
    const tabButtons = document.querySelectorAll('.tab-btn');
    const tabContents = document.querySelectorAll('.tab-content');
    const modeRadios = document.querySelectorAll('input[name="mode"]');
    const materialForm = document.getElementById('materialForm');
    const csvForm = document.getElementById('csvForm');
    const outputDiv = document.getElementById('output');
    const loadingDiv = document.getElementById('loading');
    const submitBtn = document.getElementById('submitBtn');
    const uploadCsvBtn = document.getElementById('uploadCsvBtn');
    const registryGrid = document.getElementById('registryGrid');
    const registryCount = document.getElementById('registryCount');
    const reviewQueue = document.getElementById('reviewQueue');
    const uploadResult = document.getElementById('uploadResult');
    const recentList = document.getElementById('recentList');
    const registrySearch = document.getElementById('registrySearch');
    const registryCategoryFilter = document.getElementById('registryCategoryFilter');
    const registrySort = document.getElementById('registrySort');
    const topbarTitle = document.getElementById('topbarTitle');
    const topbarKicker = document.getElementById('topbarKicker');
    const adminTabButton = document.querySelector('[data-tab="tab-admin"]');
    const statTotalRecords = document.getElementById('statTotalRecords');
    const statRecordsBig = document.getElementById('statRecordsBig');
    const statUniqueCodes = document.getElementById('statUniqueCodes');
    const heroCode = document.getElementById('heroCode');
    const heroDesc = document.getElementById('heroDesc');
    const heroMatch = document.getElementById('heroMatch');

    const tabCopy = {
        'tab-upload': ['Common National Material Code Registry', 'Log material record'],
        'tab-registry': ['National register', 'Standardized material codes'],
        'tab-admin': ['Governance & exception queue', 'Admin review']
    };

    // ============ Helper Functions ============
    function escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str ?? '';
        return div.innerHTML;
    }

    async function applyAccessVisibility() {
        if (!adminTabButton) return;
        try {
            const response = await fetch('/me');
            const user = await response.json();
            const canViewAdmin = !user.auth_enabled || (user.authenticated && user.role === 'administrator');
            adminTabButton.hidden = !canViewAdmin;
            if (!canViewAdmin && document.getElementById('tab-admin')?.classList.contains('active')) {
                document.querySelector('[data-tab="tab-upload"]')?.click();
            }
        } catch (error) {
            adminTabButton.hidden = true;
            console.error('Access visibility error:', error);
        }
    }

    // ============ Tab Navigation ============
    tabButtons.forEach(btn => {
        btn.addEventListener('click', function () {
            const tabName = this.getAttribute('data-tab');
            
            // Hide all tabs
            tabContents.forEach(tab => tab.classList.remove('active'));
            tabButtons.forEach(b => b.classList.remove('active'));
            
            // Show selected tab
            document.getElementById(tabName).classList.add('active');
            this.classList.add('active');

            if (tabCopy[tabName] && topbarKicker && topbarTitle) {
                topbarKicker.textContent = tabCopy[tabName][0];
                topbarTitle.textContent = tabCopy[tabName][1];
            }
            
            // Load data for registry and admin tabs
            if (tabName === 'tab-registry') loadRegistry();
            if (tabName === 'tab-admin') loadPendingReview();
        });
    });

    // ============ Mode Toggle (Single vs Bulk) ============
    modeRadios.forEach(radio => {
        radio.addEventListener('change', function () {
            if (this.value === 'single') {
                materialForm.classList.remove('hidden');
                csvForm.classList.add('hidden');
            } else {
                materialForm.classList.add('hidden');
                csvForm.classList.remove('hidden');
            }
        });
    });

    // ============ Single Entry Processing ============
    materialForm.addEventListener('submit', async function (event) {
        event.preventDefault();

        loadingDiv.classList.remove('hidden');
        outputDiv.innerHTML = '';
        submitBtn.disabled = true;

        const formData = {
            cpse_id: document.getElementById('cpse_id').value,
            material_code: document.getElementById('material_code').value,
            description: document.getElementById('description').value,
            specification: document.getElementById('specification').value
        };

        try {
            const response = await fetch('/process', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(formData)
            });

            const result = await response.json();

            if (response.ok) {
                renderNameplate(result);
                materialForm.reset();
                await loadRegistry();
            } else {
                renderError(result.error || 'An unknown error occurred during processing.');
            }
        } catch (error) {
            console.error('Fetch error:', error);
            renderError('Could not reach the server. Make sure app.py is running.');
        } finally {
            loadingDiv.classList.add('hidden');
            submitBtn.disabled = false;
        }
    });

    // ============ Bulk CSV Upload ============
    csvForm.addEventListener('submit', async function (event) {
        event.preventDefault();

        const fileInput = document.getElementById('csvFile');
        const file = fileInput.files[0];

        if (!file) {
            uploadResult.innerHTML = '<div class="error-card"><h3>No file selected</h3></div>';
            return;
        }

        const formData = new FormData();
        formData.append('file', file);

        uploadCsvBtn.disabled = true;
        uploadResult.innerHTML = '<p class="nameplate__confidence">Processing CSV…</p>';

        try {
            const response = await fetch('/upload-csv', {
                method: 'POST',
                body: formData
            });

            const result = await response.json();

            if (response.ok) {
                const successCount = result.successful;
                const errorCount = result.errors;
                uploadResult.innerHTML = `
                    <div class="bulk-summary">
                        <h3>Legacy migration results</h3>
                        <p>Total rows: ${result.total_rows}</p>
                        <p class="stat-ok">Successfully processed: ${successCount}</p>
                        <p class="stat-ok">Legacy codes migrated: ${result.legacy_codes_migrated ?? 0}</p>
                        <p class="stat-ok">New common codes created: ${result.new_common_codes_created ?? 0}</p>
                        ${errorCount > 0 ? `<p class="stat-bad">Errors: ${errorCount}</p>` : ''}
                        <details style="margin-top: 12px;">
                            <summary>View details</summary>
                            <pre style="font-size: 11px; overflow-x: auto;">${JSON.stringify(result.results, null, 2)}</pre>
                        </details>
                    </div>
                `;
                csvForm.reset();
                await loadRegistry();
            } else {
                uploadResult.innerHTML = `<div class="error-card"><h3>Upload Failed</h3><p>${escapeHtml(result.error)}</p></div>`;
            }
        } catch (error) {
            uploadResult.innerHTML = `<div class="error-card"><h3>Error</h3><p>${escapeHtml(error.message)}</p></div>`;
        } finally {
            uploadCsvBtn.disabled = false;
        }
    });

    // ============ Render Nameplate ============
    function renderNameplate(result) {
        const attrs = result.attributes || {};
        const attrChips = Object.entries(attrs)
            .filter(([, v]) => v !== null && v !== undefined && v !== '')
            .map(([k, v]) => `<span class="chip">${escapeHtml(k)}: ${escapeHtml(v)}</span>`)
            .join('');

        const hasMatch = result.tolerance_score != null;
        const matchPct = hasMatch ? Math.round(result.tolerance_score * 100) : null;

        const confidenceLine = hasMatch
            ? `<div class="nameplate__confidence">Matched existing code — ${matchPct}% similarity</div>`
            : `<div class="nameplate__confidence nameplate__confidence--new">New code minted — no matching material on file</div>`;

        const statusBadge = result.status === 'pending_review'
            ? '<span class="nameplate__status is-pending">Pending review</span>'
            : '<span class="nameplate__status">Confirmed</span>';

        const meter = hasMatch ? `
            <div class="match-meter">
                <div class="match-meter__row">
                    <span>Resemblance to matched code</span>
                    <span class="match-meter__pct">${matchPct}% RESEMBLANCE</span>
                </div>
                <div class="match-meter__track"><div class="match-meter__fill" style="width:${matchPct}%"></div></div>
            </div>
        ` : '';

        const candidateList = (result.candidates || [])
            .filter(c => c.common_code !== result.common_code)
            .slice(0, 3);

        const candidatesBlock = candidateList.length ? `
            <div class="candidates">
                <p class="candidates__label">Other resembling materials</p>
                ${candidateList.map(c => `
                    <div class="candidate-row">
                        <div class="candidate-row__main">
                            <strong>${escapeHtml(c.common_code)}</strong>
                            <span>${escapeHtml(c.standard_description || '')}</span>
                        </div>
                        <span class="candidate-row__score">${Math.round((c.score || 0) * 100)}%</span>
                    </div>
                `).join('')}
            </div>
        ` : '';

        outputDiv.innerHTML = `
            <div class="nameplate">
                <div class="nameplate__code">${escapeHtml(result.common_code)}</div>
                <div class="nameplate__desc">${escapeHtml(result.standard_description)}</div>
                <div class="nameplate__tags">
                    <span class="nameplate__category">${escapeHtml(result.category)}</span>
                    ${statusBadge}
                    <span class="nameplate__source">from ${escapeHtml(result.material_code)}</span>
                </div>
                ${attrChips ? `<div class="nameplate__attrs">${attrChips}</div>` : ''}
                ${meter}
            </div>
            ${confidenceLine}
            ${candidatesBlock}
        `;

        if (heroCode && heroDesc) {
            heroCode.textContent = result.common_code;
            heroDesc.textContent = result.standard_description || '';
            if (heroMatch) {
                if (hasMatch) {
                    heroMatch.textContent = `✓ ${matchPct}% match`;
                    heroMatch.classList.remove('hidden');
                } else {
                    heroMatch.classList.add('hidden');
                }
            }
        }
    }

    // ============ Render Error ============
    function renderError(message) {
        outputDiv.innerHTML = `
            <div class="error-card">
                <h3>Couldn't standardize that record</h3>
                <p>${escapeHtml(message)}</p>
            </div>
        `;
    }

    // ============ Load Registry (Tab 2) ============
    async function loadRegistry() {
        try {
            const [materialsRes, recordsRes] = await Promise.all([
                fetch(`/materials?sort=${encodeURIComponent(registrySort?.value || 'latest')}`),
                fetch('/records')
            ]);
            const materialsPayload = await materialsRes.json();
            const materials = Array.isArray(materialsPayload) ? materialsPayload : (materialsPayload.items || []);
            const records = await recordsRes.json();

            registryCount.textContent = materials.length;

            const totalSourceRecords = materials.reduce((sum, m) => sum + (Number(m.record_count) || 0), 0) || materials.length;
            if (statTotalRecords) statTotalRecords.textContent = materials.length;
            if (statRecordsBig) statRecordsBig.textContent = `${totalSourceRecords} Records`;
            if (statUniqueCodes) statUniqueCodes.textContent = materials.length;

            if (registryCategoryFilter) {
                const categories = [...new Set(materials.map(item => item.category).filter(Boolean))].sort();
                registryCategoryFilter.innerHTML = '<option value="">All categories</option>' + categories.map(category => `<option value="${escapeHtml(category)}">${escapeHtml(category)}</option>`).join('');
            }

            if (!materials.length) {
                registryGrid.innerHTML = '<p class="registry__empty">No materials processed yet.</p>';
                renderRecent([]);
                return;
            }

            registryGrid.innerHTML = materials.map(m => {
                const linked = records.filter(r => r.common_code === m.common_code);
                const linkedRows = linked.map(r => `
                    <div class="tag__record">
                        <div class="tag__record-header">
                            <span>${escapeHtml(r.cpse_id || '—')} · ${escapeHtml(r.material_code || '—')}</span>
                            <span style="font-size: 11px;">${r.tolerance_score != null ? Math.round(r.tolerance_score * 100) + '%' : 'origin'} | ${escapeHtml(r.status || 'confirmed')}</span>
                        </div>
                        <div class="tag__record-body">
                            <div><strong>Description:</strong> ${escapeHtml(r.description || '—')}</div>
                            <div><strong>Specification:</strong> ${escapeHtml(r.specification || '—')}</div>
                            <div>${escapeHtml(r.material_type || '—')} · ${escapeHtml(r.unit_of_measure || '—')} · ${escapeHtml(r.procurement_date || '—')}</div>
                        </div>
                    </div>
                `).join('');

                const pendingCount = m.pending_count || 0;
                const pendingBadge = pendingCount > 0 
                    ? `<span class="pending-badge">${pendingCount} pending</span>`
                    : '';

                return `
                    <details class="tag">
                        <summary>
                            <span class="tag__count">×${m.record_count}</span>
                            <span class="tag__code">${escapeHtml(m.common_code)}</span>
                            <span class="tag__category">${escapeHtml(m.category)}</span>
                            <span class="tag__desc">${escapeHtml(m.standard_description)}</span>
                            ${pendingBadge}
                        </summary>
                        <div class="tag__records">${linkedRows || '<div class="tag__record">No linked records.</div>'}</div>
                    </details>
                `;
            }).join('');

            renderRecent(materials);
            filterRegistry();
        } catch (error) {
            registryGrid.innerHTML = '<p class="registry__empty">Could not load the registry.</p>';
            console.error('Registry load error:', error);
        }
    }

    // ============ Load Admin Controls (Tab 3) ============
    async function loadPendingReview() {
        try {
            const [materialsRes, pendingRes, analyticsRes, auditRes, materialCodesRes] = await Promise.all([
                fetch('/admin-materials'),
                fetch('/pending-review'),
                fetch('/analytics'),
                fetch('/audit-log'),
                fetch('/material-codes')
            ]);
            const materials = materialsRes.ok ? await materialsRes.json() : [];
            const pending = pendingRes.ok ? await pendingRes.json() : [];
            const analytics = analyticsRes.ok ? await analyticsRes.json() : {};
            const auditEntries = auditRes.ok ? await auditRes.json() : [];
            const materialCodes = materialCodesRes.ok ? await materialCodesRes.json() : [];

            const analyticsCards = `
                <div class="analytics-panel">
                    <div class="analytics-card">
                        <span class="analytics-label">Processed records</span>
                        <strong>${Number(analytics.total_records_processed || 0)}</strong>
                    </div>
                    <div class="analytics-card">
                        <span class="analytics-label">Unique common codes</span>
                        <strong>${Number(analytics.total_unique_common_codes || 0)}</strong>
                    </div>
                    <div class="analytics-card">
                        <span class="analytics-label">Duplicate reduction</span>
                        <strong>${(Number(analytics.duplicate_reduction_pct || 0) * 100).toFixed(1)}%</strong>
                    </div>
                    <div class="analytics-card">
                        <span class="analytics-label">Data completeness</span>
                        <strong>${Number(analytics.data_completeness_pct || 0).toFixed(1)}%</strong>
                    </div>
                    <div class="analytics-card">
                        <span class="analytics-label">New-code rate</span>
                        <strong>${Number(analytics.new_code_rate_pct || 0).toFixed(1)}%</strong>
                    </div>
                </div>
                <div class="analytics-breakdown">
                    <h4>Category breakdown</h4>
                    ${Object.entries(analytics.category_breakdown || {}).length
                        ? Object.entries(analytics.category_breakdown).map(([category, count]) => `
                            <div class="analytics-row">
                                <span>${escapeHtml(category)}</span>
                                <strong>${count}</strong>
                            </div>
                        `).join('')
                        : '<p class="registry__empty">No category counts available yet.</p>'}
                </div>
                <div class="analytics-breakdown">
                    <h4>Review ageing</h4>
                    ${Object.entries(analytics.pending_review_ageing || {}).map(([age, count]) => `
                        <div class="analytics-row"><span>${escapeHtml(age.replaceAll('_', ' '))}</span><strong>${count}</strong></div>
                    `).join('') || '<p class="registry__empty">No pending review items.</p>'}
                </div>
            `;

            const auditRows = auditEntries.length
                ? auditEntries.slice(0, 8).map(entry => `
                    <tr>
                        <td>${escapeHtml(entry.entity_type || '—')}</td>
                        <td>${escapeHtml(String(entry.entity_id ?? '—'))}</td>
                        <td>${escapeHtml(entry.field || '—')}</td>
                        <td>${escapeHtml(String(entry.old_value ?? 'null'))}</td>
                        <td>${escapeHtml(String(entry.new_value ?? 'null'))}</td>
                        <td>${escapeHtml(entry.changed_by || 'system')}</td>
                    </tr>
                `).join('')
                : '<tr><td colspan="6">No audit entries yet.</td></tr>';

            const adminList = materials.map(item => `
                <div class="admin-item" data-id="${item.id}" data-code="${escapeHtml(item.common_code)}">
                    <div style="display: flex; gap: 12px; align-items: flex-start;">
                        <button class="admin-item__expand-btn" type="button" aria-label="Toggle records">▼</button>
                        <div class="admin-item__main" style="flex: 1;">
                            <div class="admin-item__code">${escapeHtml(item.common_code)}</div>
                            <div class="admin-item__desc">${escapeHtml(item.standard_description)}</div>
                            <div class="admin-item__meta">${escapeHtml(item.category)}</div>
                        </div>
                        <div class="admin-item__actions">
                            <div class="admin-item__confirm">
                                <button class="btn-icon btn-icon--confirm admin-confirm-delete" data-id="${item.id}" aria-label="Confirm delete">✓</button>
                                <button class="btn-icon btn-icon--cancel admin-cancel-delete" data-id="${item.id}" aria-label="Cancel delete">✕</button>
                            </div>
                            <button type="button" class="btn-small admin-edit-btn" data-id="${item.id}">Edit</button>
                            <button type="button" class="btn-small admin-delete-btn" data-id="${item.id}">Remove</button>
                        </div>
                    </div>
                    <div class="admin-item__records" data-code="${escapeHtml(item.common_code)}">
                        <p class="registry__empty">Loading records…</p>
                    </div>
                </div>
            `).join('');

            const materialCodeRows = materialCodes.length
                ? materialCodes.map(item => `
                    <tr>
                        <td><strong>${escapeHtml(item.material_code)}</strong></td>
                        <td>${escapeHtml(item.material_name)}</td>
                        <td>${Number(item.usage_count || 0)}</td>
                        <td>${item.is_common ? 'Common' : 'Observed once'}</td>
                    </tr>
                `).join('')
                : '<tr><td colspan="4">No material codes observed yet.</td></tr>';

            const pendingList = pending.length
                ? pending.map(item => `
                    <div class="pending-item">
                        <div class="pending-item__header">
                            <div>
                                <strong>${escapeHtml(item.material_code || 'Unknown')}</strong>
                                <br><small>${escapeHtml(item.cpse_id || '—')} · ${escapeHtml(item.material_code || '—')}</small>
                            </div>
                            <div class="pending-item__score">
                                ${Math.round((item.tolerance_score || 0) * 100)}% similar
                            </div>
                        </div>
                        <div class="pending-item__body">
                            <strong>Matched to:</strong> ${escapeHtml(item.common_code)}<br>
                            <strong>Source description:</strong> ${escapeHtml(item.description || '—')}<br>
                            <strong>Source specification:</strong> ${escapeHtml(item.specification || '—')}<br>
                            <strong>Universal description:</strong> ${escapeHtml(item.standard_description)}<br>
                            <strong>Category:</strong> ${escapeHtml(item.category)}<br>
                            ${item.attribute_flags ? '<strong>Attribute match:</strong> ' + escapeHtml(JSON.stringify(item.attribute_flags).substring(0, 80)) : ''}
                        </div>
                        <div class="pending-item__actions">
                            <button class="btn-small approve-btn" data-code="${escapeHtml(item.common_code)}">Approve Merge</button>
                            <button class="btn-small reject-btn" data-id="${item.id}">Request New Code</button>
                        </div>
                    </div>
                `).join('')
                : '<p class="registry__empty">No items pending review.</p>';

            reviewQueue.innerHTML = `
                <div class="admin-controls">
                    <button id="adminAddBtn" class="btn-stamp btn-stamp--small">Add new registry entry</button>
                </div>
                <div id="adminFormContainer" class="admin-form hidden"></div>

                <details class="admin-accordion" open>
                    <summary>Pending review</summary>
                    <div class="admin-review-list">${pendingList}</div>
                </details>

                <details class="admin-accordion" open>
                    <summary>Operational analytics</summary>
                    <div class="analytics-section">${analyticsCards}</div>
                </details>

                <details class="admin-accordion" open>
                    <summary>Registry entries</summary>
                    <div class="admin-list">${adminList || '<p class="registry__empty">No registry entries yet.</p>'}</div>
                </details>

                <details class="admin-accordion" open>
                    <summary>Recent audit trail</summary>
                    <div class="audit-table-wrap">
                        <table class="audit-table">
                            <thead>
                                <tr>
                                    <th>Entity</th>
                                    <th>ID</th>
                                    <th>Field</th>
                                    <th>Old value</th>
                                    <th>New value</th>
                                    <th>Changed by</th>
                                </tr>
                            </thead>
                            <tbody>${auditRows}</tbody>
                        </table>
                    </div>
                </details>

                <details class="admin-accordion">
                    <summary>Material code dictionary</summary>
                    <div class="audit-table-wrap">
                        <table class="audit-table">
                            <thead>
                                <tr><th>Code</th><th>Material</th><th>Uses</th><th>Status</th></tr>
                            </thead>
                            <tbody>${materialCodeRows}</tbody>
                        </table>
                    </div>
                </details>
            `;

            document.getElementById('adminAddBtn').addEventListener('click', () => renderAdminForm());

            document.querySelectorAll('.admin-item__expand-btn').forEach(btn => {
                btn.addEventListener('click', async (event) => {
                    event.stopPropagation();
                    const row = btn.closest('.admin-item');
                    const code = row.getAttribute('data-code');
                    const recordsContainer = row.querySelector('.admin-item__records');
                    
                    if (recordsContainer.classList.contains('visible')) {
                        recordsContainer.classList.remove('visible');
                        btn.textContent = '▼';
                    } else {
                        recordsContainer.classList.add('visible');
                        btn.textContent = '▲';
                        await loadRecordsForCode(code, recordsContainer);
                    }
                });
            });

            document.querySelectorAll('.admin-edit-btn').forEach(btn => {
                btn.addEventListener('click', async (event) => {
                    event.stopPropagation();
                    event.preventDefault();
                    const id = Number(btn.dataset.id);
                    const item = materials.find(m => Number(m.id) === id);
                    if (item) renderAdminForm(item);
                });
            });

            document.querySelectorAll('.admin-delete-btn').forEach(btn => {
                btn.addEventListener('click', (event) => {
                    event.stopPropagation();
                    event.preventDefault();
                    const row = btn.closest('.admin-item');
                    const confirmBox = row.querySelector('.admin-item__confirm');
                    if (confirmBox) {
                        confirmBox.classList.add('visible');
                    }
                });
            });

            document.querySelectorAll('.admin-cancel-delete').forEach(btn => {
                btn.addEventListener('click', (event) => {
                    event.stopPropagation();
                    event.preventDefault();
                    const row = btn.closest('.admin-item');
                    const confirmBox = row.querySelector('.admin-item__confirm');
                    if (confirmBox) {
                        confirmBox.classList.remove('visible');
                    }
                });
            });

            document.querySelectorAll('.admin-confirm-delete').forEach(btn => {
                btn.addEventListener('click', async (event) => {
                    event.stopPropagation();
                    event.preventDefault();
                    const id = Number(btn.dataset.id);
                    await deleteMaterial(id);
                });
            });

            document.querySelectorAll('.approve-btn').forEach(btn => {
                btn.addEventListener('click', async function (event) {
                    event.stopPropagation();
                    event.preventDefault();
                    const code = this.getAttribute('data-code');
                    await approveMerge(code);
                });
            });

            document.querySelectorAll('.reject-btn').forEach(btn => {
                btn.addEventListener('click', async function (event) {
                    event.stopPropagation();
                    event.preventDefault();
                    const id = this.getAttribute('data-id');
                    await rejectMerge(id);
                });
            });
        } catch (error) {
            reviewQueue.innerHTML = '<p class="error-card">Could not load admin controls.</p>';
            console.error('Pending review load error:', error);
        }
    }

    function renderAdminForm(material = null) {
        const container = document.getElementById('adminFormContainer');
        const categoryFormContainer = document.getElementById('adminCategoryFormContainer');
        if (categoryFormContainer) {
            categoryFormContainer.classList.add('hidden');
            categoryFormContainer.innerHTML = '';
        }
        if (!container) return;

        const isEdit = !!material;
        container.classList.remove('hidden');
        container.innerHTML = `
            <form id="adminEditorForm" class="admin-editor">
                <div class="field">
                    <label for="adminCode">Common code</label>
                    <input id="adminCode" name="common_code" value="${escapeHtml(material?.common_code || '')}" placeholder="CNMC-0009">
                </div>
                <div class="field">
                    <label for="adminDescription">Standard description</label>
                    <textarea id="adminDescription" name="standard_description" rows="2">${escapeHtml(material?.standard_description || '')}</textarea>
                </div>
                <div class="field">
                    <label for="adminCategory">Category</label>
                    <input id="adminCategory" name="category" value="${escapeHtml(material?.category || '')}" placeholder="Pipe or Circuits">
                </div>
                ${isEdit ? '<p class="file-well__hint">Linked records will be re-checked against the updated description.</p>' : '<p class="file-well__hint">Need a new class? Add a category first or type a fresh name here.</p>'}
                <div class="admin-editor__actions">
                    <button type="submit" class="btn-stamp btn-stamp--small">${isEdit ? 'Save changes' : 'Add entry'}</button>
                    <button type="button" class="btn-small admin-cancel-btn">Cancel</button>
                </div>
            </form>
        `;
        container.scrollIntoView({ behavior: 'smooth', block: 'start' });
        document.getElementById('adminCode')?.focus();

        document.getElementById('adminEditorForm').addEventListener('submit', async function (event) {
            event.preventDefault();
            const payload = {
                common_code: document.getElementById('adminCode').value.trim(),
                standard_description: document.getElementById('adminDescription').value.trim(),
                category: document.getElementById('adminCategory').value.trim()
            };

            if (!payload.standard_description || !payload.category) {
                alert('Description and category are required.');
                return;
            }

            if (isEdit) {
                await updateMaterial(material.id, payload);
            } else {
                await createMaterial(payload);
            }
        });

        document.querySelector('.admin-cancel-btn').addEventListener('click', () => {
            container.classList.add('hidden');
            container.innerHTML = '';
        });
    }

    function renderCategoryForm() {
        const container = document.getElementById('adminCategoryFormContainer');
        const materialContainer = document.getElementById('adminFormContainer');
        if (materialContainer) {
            materialContainer.classList.add('hidden');
            materialContainer.innerHTML = '';
        }

        if (!container) return;
        container.classList.remove('hidden');
        container.innerHTML = `
            <form id="adminCategoryEditorForm" class="admin-editor">
                <div class="field">
                    <label for="adminCategoryName">New category</label>
                    <input id="adminCategoryName" name="category_name" placeholder="Circuits">
                </div>
                <div class="admin-editor__actions">
                    <button type="submit" class="btn-stamp btn-stamp--small">Save category</button>
                    <button type="button" class="btn-small admin-category-cancel-btn">Cancel</button>
                </div>
            </form>
        `;

        document.getElementById('adminCategoryEditorForm').addEventListener('submit', async function (event) {
            event.preventDefault();
            const categoryName = document.getElementById('adminCategoryName').value.trim();
            if (!categoryName) {
                alert('Category name is required.');
                return;
            }
            await createCategory({ category_name: categoryName });
        });

        document.querySelector('.admin-category-cancel-btn').addEventListener('click', () => {
            container.classList.add('hidden');
            container.innerHTML = '';
        });
    }

    async function createCategory(payload) {
        try {
            const response = await fetch('/admin-categories', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const result = await response.json();
            if (!response.ok) throw new Error(result.error || 'Create category failed');
            const categoryContainer = document.getElementById('adminCategoryFormContainer');
            if (categoryContainer) {
                categoryContainer.classList.add('hidden');
                categoryContainer.innerHTML = '';
            }
            alert(`Category saved: ${payload.category_name}`);
            await loadPendingReview();
        } catch (error) {
            console.error('Create category error:', error);
            alert(error.message || 'Unable to add category');
        }
    }

    async function createMaterial(payload) {
        try {
            const response = await fetch('/admin-materials', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const result = await response.json();
            if (!response.ok) throw new Error(result.error || 'Create failed');
            document.getElementById('adminFormContainer').classList.add('hidden');
            document.getElementById('adminFormContainer').innerHTML = '';
            await loadPendingReview();
            await loadRegistry();
        } catch (error) {
            console.error('Create material error:', error);
            alert(error.message || 'Unable to create item');
        }
    }

    async function updateMaterial(id, payload) {
        try {
            const response = await fetch(`/admin-materials/${id}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const result = await response.json();
            if (!response.ok) throw new Error(result.error || 'Update failed');
            document.getElementById('adminFormContainer').classList.add('hidden');
            document.getElementById('adminFormContainer').innerHTML = '';
            await loadPendingReview();
            await loadRegistry();
        } catch (error) {
            console.error('Update material error:', error);
            alert(error.message || 'Unable to update item');
        }
    }

    async function deleteMaterial(id) {
        try {
            const response = await fetch(`/admin-materials/${id}`, { method: 'DELETE' });
            const result = await response.json();
            if (!response.ok) throw new Error(result.error || 'Delete failed');
            await loadPendingReview();
            await loadRegistry();
        } catch (error) {
            console.error('Delete material error:', error);
            alert(error.message || 'Unable to remove item');
        }
    }

    // ============ Load Records for a Common Code ============
    async function loadRecordsForCode(commonCode, container) {
        try {
            const response = await fetch(`/admin-records/${encodeURIComponent(commonCode)}`);
            const records = response.ok ? await response.json() : [];

            if (!records.length) {
                container.innerHTML = '<p class="registry__empty">No individual records.</p>';
                return;
            }

            const recordsList = records.map(record => `
                <div class="record-item" data-record-id="${record.id}">
                    <div class="record-item__header">
                        <div class="record-item__info">
                            <div><strong>${escapeHtml(record.cpse_id || '—')}</strong> · ${escapeHtml(record.material_code || '—')}</div>
                            <small>${escapeHtml(record.description || '')}</small>
                            <small style="display: block;">${escapeHtml(record.specification || '')}</small>
                            <small style="display: block;">${escapeHtml(record.material_type || '—')} · ${escapeHtml(record.unit_of_measure || '—')} · ${escapeHtml(record.procurement_date || '—')}</small>
                            <small style="display: block; margin-top: 2px;">Status: ${escapeHtml(record.status || 'confirmed')}</small>
                        </div>
                        <div class="record-item__actions">
                            <div class="record-item__confirm">
                                <button class="btn-icon btn-icon--confirm record-confirm-delete" data-record-id="${record.id}" aria-label="Confirm delete">✓</button>
                                <button class="btn-icon btn-icon--cancel record-cancel-delete" data-record-id="${record.id}" aria-label="Cancel delete">✕</button>
                            </div>
                            <button class="btn-record-edit" data-record-id="${record.id}">Edit</button>
                            <button class="btn-record-delete" data-record-id="${record.id}">Delete</button>
                        </div>
                    </div>
                </div>
            `).join('');

            container.innerHTML = `<div style="padding: 8px 0;">${recordsList}</div>`;

            // Set up event listeners for record buttons
            container.querySelectorAll('.btn-record-edit').forEach(btn => {
                btn.addEventListener('click', async (event) => {
                    event.stopPropagation();
                    event.preventDefault();
                    const recordId = Number(btn.dataset.recordId);
                    const record = records.find(r => r.id === recordId);
                    if (record) {
                        renderRecordEditForm(recordId, record, commonCode);
                    }
                });
            });

            container.querySelectorAll('.btn-record-delete').forEach(btn => {
                btn.addEventListener('click', (event) => {
                    event.stopPropagation();
                    event.preventDefault();
                    const recordContainer = btn.closest('.record-item');
                    const confirmBox = recordContainer.querySelector('.record-item__confirm');
                    if (confirmBox) {
                        confirmBox.classList.add('visible');
                    }
                });
            });

            container.querySelectorAll('.record-cancel-delete').forEach(btn => {
                btn.addEventListener('click', (event) => {
                    event.stopPropagation();
                    event.preventDefault();
                    const recordContainer = btn.closest('.record-item');
                    const confirmBox = recordContainer.querySelector('.record-item__confirm');
                    if (confirmBox) {
                        confirmBox.classList.remove('visible');
                    }
                });
            });

            container.querySelectorAll('.record-confirm-delete').forEach(btn => {
                btn.addEventListener('click', async (event) => {
                    event.stopPropagation();
                    event.preventDefault();
                    const recordId = Number(btn.dataset.recordId);
                    await deleteMaterialRecord(recordId, commonCode);
                });
            });
        } catch (error) {
            container.innerHTML = `<p class="error-card">Error loading records: ${escapeHtml(error.message)}</p>`;
            console.error('Load records error:', error);
        }
    }

    // ============ Render Record Edit Form ============
    function renderRecordEditForm(recordId, record, commonCode) {
        // Create a modal-like form for editing
        const formHtml = `
            <div class="modal-backdrop" id="recordEditModal">
                <div class="modal-card">
                    <h3>Edit record</h3>
                    <form id="recordEditForm" class="modal-form">
                        <div class="field">
                            <label for="editCpseId">CPSE ID</label>
                            <input type="text" id="editCpseId" value="${escapeHtml(record.cpse_id || '')}">
                        </div>
                        <div class="field">
                            <label for="editMaterialCode">Material code</label>
                            <input type="text" id="editMaterialCode" value="${escapeHtml(record.material_code || '')}">
                        </div>
                        <div class="field">
                            <label for="editDescription">Description</label>
                            <textarea id="editDescription" rows="3">${escapeHtml(record.description || '')}</textarea>
                        </div>
                        <div class="field">
                            <label for="editSpecification">Specification</label>
                            <textarea id="editSpecification" rows="2">${escapeHtml(record.specification || '')}</textarea>
                        </div>
                        <div class="modal-actions">
                            <button type="submit" class="btn-stamp" style="flex: 1; margin: 0; align-self: auto;">Save &amp; reprocess</button>
                            <button type="button" id="cancelRecordEdit" class="btn-small" style="flex: 1;">Cancel</button>
                        </div>
                    </form>
                </div>
            </div>
        `;
        
        // Append to body
        const modal = document.createElement('div');
        modal.innerHTML = formHtml;
        document.body.appendChild(modal);
        
        // Handle form submission
        document.getElementById('recordEditForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            const payload = {
                cpse_id: document.getElementById('editCpseId').value.trim(),
                material_code: document.getElementById('editMaterialCode').value.trim(),
                description: document.getElementById('editDescription').value.trim(),
                specification: document.getElementById('editSpecification').value.trim()
            };
            
            if (!payload.description) {
                alert('Description is required');
                return;
            }
            
            await updateMaterialRecord(recordId, payload, commonCode);
            modal.remove();
        });
        
        // Handle cancel
        document.getElementById('cancelRecordEdit').addEventListener('click', () => {
            modal.remove();
        });
    }

    // ============ Update Material Record ============
    async function updateMaterialRecord(recordId, payload, commonCode) {
        try {
            const response = await fetch(`/admin-records/${recordId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const result = await response.json();
            if (!response.ok) throw new Error(result.error || 'Update failed');
            
            await loadPendingReview();
            await loadRegistry();
        } catch (error) {
            console.error('Update record error:', error);
            alert(error.message || 'Unable to update record');
        }
    }

    // ============ Delete Material Record ============
    async function deleteMaterialRecord(recordId, commonCode) {
        try {
            const response = await fetch(`/admin-records/${recordId}`, { method: 'DELETE' });
            const result = await response.json();
            if (!response.ok) throw new Error(result.error || 'Delete failed');
            
            // Reload records for the common code
            const adminItem = document.querySelector(`.admin-item[data-code="${escapeHtml(commonCode)}"]`);
            if (adminItem) {
                const recordsContainer = adminItem.querySelector('.admin-item__records');
                await loadRecordsForCode(commonCode, recordsContainer);
            }
            await loadRegistry();
        } catch (error) {
            console.error('Delete record error:', error);
            alert(error.message || 'Unable to delete record');
        }
    }

    // ============ Approve Merge ============
    async function approveMerge(commonCode) {
        try {
            const reason = window.prompt('Approval reason (optional):', '') ?? '';
            const response = await fetch('/approve-merge', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ common_code: commonCode, reason })
            });

            if (response.ok) {
                const result = await response.json();
                alert(result.message || `Approved merge for ${commonCode}`);
                await loadPendingReview();
                await loadRegistry();
            } else {
                alert('Failed to approve merge');
            }
        } catch (error) {
            console.error('Approve error:', error);
            alert('Error approving merge');
        }
    }

    // ============ Reject Merge ============
    async function rejectMerge(recordId) {
        try {
            const reason = window.prompt('Why should this receive a new code?', '') ?? '';
            if (!reason.trim()) return;
            const response = await fetch('/reject-merge', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ record_id: recordId, reason })
            });

            if (response.ok) {
                alert('Rejection flagged for reprocessing');
                await loadPendingReview();
            } else {
                alert('Failed to reject merge');
            }
        } catch (error) {
            console.error('Reject error:', error);
            alert('Error rejecting merge');
        }
    }

    function renderRecent(materials) {
        if (!recentList) return;
        const slice = [...(materials || [])]
            .sort((a, b) => {
                const dateDiff = new Date(b.created_at || 0) - new Date(a.created_at || 0);
                return dateDiff || String(b.common_code || '').localeCompare(String(a.common_code || ''));
            })
            .slice(0, 4);
        if (!slice.length) {
            recentList.innerHTML = '<p class="recent-list__empty">Codes appear here after they are logged.</p>';
            return;
        }
        recentList.innerHTML = slice.map(m => `
            <div class="recent-item">
                <div>
                    <span class="recent-item__code">${escapeHtml(m.common_code)}</span>
                    <span class="recent-item__desc">${escapeHtml(m.standard_description || '')}</span>
                </div>
                <span class="recent-item__cat">${escapeHtml(m.category || '')}</span>
            </div>
        `).join('');
    }

    function filterRegistry() {
        if (!registryGrid) return;
        const q = (registrySearch?.value || '').trim().toLowerCase();
        const category = registryCategoryFilter?.value || '';
        registryGrid.querySelectorAll('.tag').forEach(row => {
            const hay = row.textContent.toLowerCase();
            const rowCategory = row.querySelector('.tag__category')?.textContent || '';
            row.style.display = (!q || hay.includes(q)) && (!category || rowCategory === category) ? '' : 'none';
        });
    }

    if (registrySearch) {
        registrySearch.addEventListener('input', filterRegistry);
    }
    if (registryCategoryFilter) {
        registryCategoryFilter.addEventListener('change', filterRegistry);
    }
    if (registrySort) {
        registrySort.addEventListener('change', loadRegistry);
    }

    applyAccessVisibility();

    // Load registry on page load
    loadRegistry();
});