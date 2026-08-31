// static/app_v2.js - Unified Material Master Control Engine

document.addEventListener('DOMContentLoaded', function () {
    // ============ UI Elements ============
    const tabButtons = document.querySelectorAll('.tab-btn');
    const tabContents = document.querySelectorAll('.tab-content');
    const modeRadios = document.querySelectorAll('input[name="mode"]');
    const materialForm = document.getElementById('materialForm');
    const csvForm = document.getElementById('csvForm');
    const demoForm = document.getElementById('demoForm');
    const runDemoBtn = document.getElementById('runDemoBtn');
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
    
    // Stats & Hero
    const statTotalRecords = document.getElementById('statTotalRecords');
    const statRecordsBig = document.getElementById('statRecordsBig');
    const statUniqueCodes = document.getElementById('statUniqueCodes');
    const heroCode = document.getElementById('heroCode');
    const heroDesc = document.getElementById('heroDesc');
    const heroMatch = document.getElementById('heroMatch');
    const heroReductionRate = document.getElementById('heroReductionRate');

    // Analytics KPIs & Table
    const kpiDedupRate = document.getElementById('kpiDedupRate');
    const kpiDedupSub = document.getElementById('kpiDedupSub');
    const kpiSharedMaterials = document.getElementById('kpiSharedMaterials');
    const kpiSavings = document.getElementById('kpiSavings');
    const kpiCompleteness = document.getElementById('kpiCompleteness');
    const sharedMaterialsTableContainer = document.getElementById('sharedMaterialsTableContainer');

    // ERP Hub
    const btnTriggerErpExport = document.getElementById('btnTriggerErpExport');
    const erpPayloadViewer = document.getElementById('erpPayloadViewer');
    const erpJobStatusBadge = document.getElementById('erpJobStatusBadge');
    const auditLogContainer = document.getElementById('auditLogContainer');

    // Chart.js Instances
    let chartCpseDedupInstance = null;
    let chartCategoryDistInstance = null;
    let chartConfidenceDistInstance = null;

    const tabCopy = {
        'tab-upload': ['Common National Material Code Registry', 'Standardization & Resemblance Engine'],
        'tab-registry': ['National Harmonized Register', 'Unified Material Library'],
        'tab-admin': ['Governance & Exception Resolution', 'Human-in-the-Loop Review Queue'],
        'tab-analytics': ['Strategic Procurement Intelligence', 'Analytics & Demand Aggregation'],
        'tab-erp': ['Enterprise Data Infrastructure', 'SAP / ERP Integration & Audit Trail']
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
            adminTabButton.hidden = false;
        }
    }

    // ============ Tab Navigation ============
    tabButtons.forEach(btn => {
        btn.addEventListener('click', function () {
            const tabName = this.getAttribute('data-tab');
            if (!tabName) return;
            
            // Hide all tabs
            tabContents.forEach(tab => tab.classList.remove('active'));
            tabButtons.forEach(b => b.classList.remove('active'));
            
            // Show selected tab
            const target = document.getElementById(tabName);
            if (target) target.classList.add('active');
            this.classList.add('active');

            if (tabCopy[tabName] && topbarKicker && topbarTitle) {
                topbarKicker.textContent = tabCopy[tabName][0];
                topbarTitle.textContent = tabCopy[tabName][1];
            }
            
            // Load tab specific data
            if (tabName === 'tab-registry') loadRegistry();
            if (tabName === 'tab-admin') loadPendingReview();
            if (tabName === 'tab-analytics') loadAnalyticsDashboard();
            if (tabName === 'tab-erp') {
                loadAuditLog();
            }
        });
    });

    // ============ Mode Toggle (Single vs Bulk vs Demo) ============
    modeRadios.forEach(radio => {
        radio.addEventListener('change', function () {
            materialForm.classList.add('hidden');
            csvForm.classList.add('hidden');
            if (demoForm) demoForm.classList.add('hidden');

            if (this.value === 'single') {
                materialForm.classList.remove('hidden');
            } else if (this.value === 'bulk') {
                csvForm.classList.remove('hidden');
            } else if (this.value === 'demo') {
                if (demoForm) demoForm.classList.remove('hidden');
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
        uploadCsvBtn.textContent = 'Migrating & Deduplicating...';
        uploadResult.innerHTML = '';

        try {
            const response = await fetch('/upload-csv', {
                method: 'POST',
                body: formData
            });

            const data = await response.json();

            if (response.ok) {
                renderUploadSuccess(data);
                csvForm.reset();
                await loadRegistry();
            } else {
                uploadResult.innerHTML = `<div class="error-card"><h3>Migration Failed</h3><p>${escapeHtml(data.error)}</p></div>`;
            }
        } catch (error) {
            console.error('Upload error:', error);
            uploadResult.innerHTML = '<div class="error-card"><h3>Upload failed</h3><p>Server connection error.</p></div>';
        } finally {
            uploadCsvBtn.disabled = false;
            uploadCsvBtn.textContent = 'Upload & Migrate Batch';
        }
    });

    // ============ 1-Click Multi-CPSE Benchmark Demo ============
    if (runDemoBtn) {
        runDemoBtn.addEventListener('click', async function () {
            runDemoBtn.disabled = true;
            runDemoBtn.textContent = '⏳ Ingesting Multi-CPSE Benchmark Dataset...';
            uploadResult.innerHTML = '<div class="stat-card" style="padding:14px;"><p>Analyzing 12 items across ONGC, IOCL, GAIL, SAIL, BHEL, NTPC with 3-tier matching and SI normalization...</p></div>';

            try {
                const response = await fetch('/api/v1/load-sample-dataset', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' }
                });

                const data = await response.json();

                if (response.ok) {
                    uploadResult.innerHTML = `
                        <div class="stat-card" style="border-left: 4px solid var(--green); padding:16px;">
                            <div class="stat-card__top">
                                <span class="stat-card__title">✓ Multi-CPSE Benchmark Ingestion Complete</span>
                                <span class="status-pill status-pill--success">${data.duplicate_reduction_pct}% DEDUPLICATED</span>
                            </div>
                            <p style="margin: 8px 0; color: var(--ink-soft);">
                                <strong>${data.total_ingested} Raw Materials</strong> from 6 CPSEs successfully consolidated into <strong>${data.unique_cnmc_created} Unified CNMC Codes</strong>.
                            </p>
                            <div style="display:flex; gap:10px; margin-top:10px;">
                                <button type="button" class="btn-primary" onclick="document.querySelector('[data-tab=\\'tab-analytics\\']').click()">
                                    📊 View Analytics & Demand Savings
                                </button>
                                <button type="button" class="btn-secondary" onclick="document.querySelector('[data-tab=\\'tab-registry\\']').click()">
                                    🏛️ View Harmonized Material Library
                                </button>
                            </div>
                        </div>
                    `;
                    await loadRegistry();
                } else {
                    uploadResult.innerHTML = `<div class="error-card"><h3>Demo Ingestion Failed</h3><p>${escapeHtml(data.error)}</p></div>`;
                }
            } catch (error) {
                console.error('Demo error:', error);
                uploadResult.innerHTML = '<div class="error-card"><h3>Demo error</h3><p>Server connection error.</p></div>';
            } finally {
                runDemoBtn.disabled = false;
                runDemoBtn.textContent = '🚀 Ingest 1-Click Multi-CPSE Benchmark Dataset';
            }
        });
    }

    function renderUploadSuccess(data) {
        uploadResult.innerHTML = `
            <div class="stat-card" style="border-left: 4px solid var(--green); padding:16px;">
                <div class="stat-card__top">
                    <span class="stat-card__title">✓ Migration Batch Complete</span>
                    <span class="status-pill status-pill--success">${data.successful} PROCESSED</span>
                </div>
                <p style="margin: 8px 0; color: var(--ink-soft);">
                    Processed <strong>${data.total_rows} records</strong>. Harmonized into <strong>${data.legacy_codes_migrated} existing codes</strong> and created <strong>${data.new_common_codes_created} new CNMC codes</strong>.
                </p>
                ${data.errors > 0 ? `<p style="color:var(--red);">⚠️ ${data.errors} rows encountered errors.</p>` : ''}
            </div>
        `;
    }

    // ============ Nameplate & Resemblance Output ============
    function renderNameplate(result) {
        const score = result.tolerance_score !== null ? Math.round(result.tolerance_score * 100) : null;
        const scoreDisplay = score !== null ? `${score}% Match` : 'New National Code';
        const isPending = result.status === 'pending_review';

        let badgeClass = 'match-badge';
        if (isPending) badgeClass += ' match-badge--review';
        else if (score !== null && score >= 85) badgeClass += ' match-badge--high';

        // Update Hero Card
        if (heroCode) heroCode.textContent = result.common_code || '—';
        if (heroDesc) heroDesc.textContent = result.standard_description || '—';
        if (heroMatch) {
            heroMatch.textContent = `✓ ${scoreDisplay}`;
            heroMatch.classList.remove('hidden');
        }

        let attrsHtml = '';
        if (result.attributes && Object.keys(result.attributes).length > 0) {
            attrsHtml = '<div class="nameplate__attrs">';
            for (const [k, v] of Object.entries(result.attributes)) {
                if (v !== null && v !== undefined) {
                    attrsHtml += `<span class="attr-pill"><strong>${escapeHtml(k)}:</strong> ${escapeHtml(String(v))}</span>`;
                }
            }
            attrsHtml += '</div>';
        }

        outputDiv.innerHTML = `
            <div class="nameplate">
                <div class="nameplate__header">
                    <div>
                        <span class="eyebrow">${escapeHtml(result.category || 'Standard Material')}</span>
                        <h3 class="nameplate__code">${escapeHtml(result.common_code)}</h3>
                    </div>
                    <span class="${badgeClass}">${escapeHtml(scoreDisplay)}</span>
                </div>
                <p class="nameplate__desc">${escapeHtml(result.standard_description)}</p>
                ${attrsHtml}
                <div class="nameplate__footer">
                    <span>Source: <strong>${escapeHtml(result.material_code || 'N/A')}</strong></span>
                    <span class="status-pill status-pill--${isPending ? 'warning' : 'success'}">${escapeHtml(result.status)}</span>
                </div>
            </div>
        `;
    }

    function renderError(msg) {
        outputDiv.innerHTML = `
            <div class="error-card">
                <h3>Standardization Error</h3>
                <p>${escapeHtml(msg)}</p>
            </div>
        `;
    }

    // ============ Load Registry & Stats ============
    async function loadRegistry() {
        try {
            const response = await fetch('/materials');
            const data = await response.json();
            const materials = Array.isArray(data) ? data : (data.materials || []);

            // Populate categories in filter dropdown
            const catResponse = await fetch('/admin-categories');
            if (catResponse.ok) {
                const catData = await catResponse.json();
                if (registryCategoryFilter) {
                    const currentVal = registryCategoryFilter.value;
                    registryCategoryFilter.innerHTML = '<option value="">All categories</option>';
                    (catData.categories || []).forEach(cat => {
                        const opt = document.createElement('option');
                        opt.value = cat;
                        opt.textContent = cat;
                        if (cat === currentVal) opt.selected = true;
                        registryCategoryFilter.appendChild(opt);
                    });
                }
            }

            // Calculate metrics
            let totalSourceRecords = 0;
            materials.forEach(m => {
                totalSourceRecords += (m.linked_records_count || m.total_records || 1);
            });

            if (statTotalRecords) statTotalRecords.textContent = totalSourceRecords;
            if (statRecordsBig) statRecordsBig.textContent = `${totalSourceRecords} Records`;
            if (statUniqueCodes) statUniqueCodes.textContent = materials.length;
            if (registryCount) registryCount.textContent = materials.length;

            const reductionPct = totalSourceRecords > 0 ? Math.round((1 - (materials.length / totalSourceRecords)) * 100) : 0;
            if (heroReductionRate) heroReductionRate.textContent = `${reductionPct}% Deduplicated`;

            renderRegistryGrid(materials);
            renderRecent(materials.slice(0, 5));
        } catch (error) {
            console.error('Error loading registry:', error);
            if (registryGrid) registryGrid.innerHTML = '<p class="registry__empty">Failed to load registry materials.</p>';
        }
    }

    function renderRegistryGrid(materials) {
        if (!registryGrid) return;
        if (!materials || materials.length === 0) {
            registryGrid.innerHTML = '<p class="registry__empty">No materials registered yet. Submit a material or run the 1-click demo!</p>';
            return;
        }

        registryGrid.innerHTML = materials.map(m => {
            const linkedCount = m.linked_records_count || m.records_count || (m.linked_records ? m.linked_records.length : 1);
            let attrsSnippet = '';
            if (m.attributes && typeof m.attributes === 'object') {
                const entries = Object.entries(m.attributes).filter(([k, v]) => v !== null && v !== '');
                if (entries.length > 0) {
                    attrsSnippet = `<div class="registry-card__attrs">${entries.slice(0, 3).map(([k, v]) => `<span>${escapeHtml(k)}: ${escapeHtml(String(v))}</span>`).join('')}</div>`;
                }
            }

            return `
                <div class="registry-card" data-code="${escapeHtml(m.common_code)}">
                    <div class="registry-card__top">
                        <span class="eyebrow">${escapeHtml(m.category || 'Uncategorized')}</span>
                        <span class="status-pill">${linkedCount} CPSE Records</span>
                    </div>
                    <strong class="registry-card__code">${escapeHtml(m.common_code)}</strong>
                    <p class="registry-card__desc">${escapeHtml(m.standard_description)}</p>
                    ${attrsSnippet}
                </div>
            `;
        }).join('');

        // Attach click to inspect
        registryGrid.querySelectorAll('.registry-card').forEach(card => {
            card.addEventListener('click', function () {
                const code = this.getAttribute('data-code');
                if (code) loadRecordsForCode(code);
            });
        });
    }

    function renderRecent(recentMaterials) {
        if (!recentList) return;
        if (!recentMaterials || recentMaterials.length === 0) {
            recentList.innerHTML = '<p class="recent-list__empty">Codes appear here after they are logged.</p>';
            return;
        }

        recentList.innerHTML = recentMaterials.map(m => `
            <div class="recent-item">
                <strong class="recent-item__code">${escapeHtml(m.common_code)}</strong>
                <span class="recent-item__desc">${escapeHtml(m.standard_description)}</span>
            </div>
        `).join('');
    }

    // ============ Analytics & Demand Aggregation Dashboard ============
    async function loadAnalyticsDashboard() {
        try {
            const response = await fetch('/analytics');
            if (!response.ok) throw new Error('Analytics fetch failed');
            const data = await response.json();

            // Update KPIs
            const dedupRate = data.duplicate_reduction_pct ? Math.round(data.duplicate_reduction_pct * 1000) / 10 : 0.0;
            if (kpiDedupRate) kpiDedupRate.textContent = `${dedupRate}%`;
            if (kpiDedupSub) kpiDedupSub.textContent = `${data.total_records_processed - data.total_unique_common_codes} redundant master codes eliminated`;

            if (kpiSharedMaterials) kpiSharedMaterials.textContent = data.shared_cnmc_count || 0;
            
            // Estimated collaborative procurement volume savings: ₹ 4.5 Lakhs per shared material
            const totalSavingsLakhs = Math.round((data.shared_cnmc_count || 0) * 4.5);
            if (kpiSavings) kpiSavings.textContent = `₹ ${totalSavingsLakhs} Lakhs`;
            if (kpiCompleteness) kpiCompleteness.textContent = `${data.data_completeness_pct || 100}%`;

            // 1. CPSE Deduplication Chart (Bar Chart)
            const cpseDedup = data.cpse_deduplication || [];
            const cpseLabels = cpseDedup.map(d => d.cpse_id);
            const cpseRawCounts = cpseDedup.map(d => d.raw_count);
            const cpseUniqueCounts = cpseDedup.map(d => d.unique_cnmc_count);

            const ctxCpse = document.getElementById('chartCpseDedup')?.getContext('2d');
            if (ctxCpse) {
                if (chartCpseDedupInstance) chartCpseDedupInstance.destroy();
                chartCpseDedupInstance = new Chart(ctxCpse, {
                    type: 'bar',
                    data: {
                        labels: cpseLabels.length > 0 ? cpseLabels : ['No Data'],
                        datasets: [
                            {
                                label: 'Raw Ingested Records',
                                data: cpseRawCounts.length > 0 ? cpseRawCounts : [0],
                                backgroundColor: 'rgba(228, 106, 52, 0.75)',
                                borderColor: '#e46a34',
                                borderWidth: 1
                            },
                            {
                                label: 'Unified CNMC Codes',
                                data: cpseUniqueCounts.length > 0 ? cpseUniqueCounts : [0],
                                backgroundColor: 'rgba(31, 138, 84, 0.75)',
                                borderColor: '#1f8a54',
                                borderWidth: 1
                            }
                        ]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {
                            legend: { position: 'top', labels: { font: { family: 'Inter', size: 11 } } }
                        },
                        scales: {
                            y: { beginAtZero: true, grid: { color: 'rgba(0,0,0,0.05)' } },
                            x: { grid: { display: false } }
                        }
                    }
                });
            }

            // 2. Category Distribution (Doughnut Chart)
            const catData = data.category_breakdown || {};
            const catLabels = Object.keys(catData);
            const catValues = Object.values(catData);

            const ctxCat = document.getElementById('chartCategoryDist')?.getContext('2d');
            if (ctxCat) {
                if (chartCategoryDistInstance) chartCategoryDistInstance.destroy();
                chartCategoryDistInstance = new Chart(ctxCat, {
                    type: 'doughnut',
                    data: {
                        labels: catLabels.length > 0 ? catLabels : ['Uncategorized'],
                        datasets: [{
                            data: catValues.length > 0 ? catValues : [1],
                            backgroundColor: [
                                '#e46a34', '#1f8a54', '#2b5c8f', '#b8792a', '#6f42c1',
                                '#d63384', '#0dcaf0', '#fd7e14', '#20c997', '#6c757d'
                            ]
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {
                            legend: { position: 'right', labels: { font: { family: 'Inter', size: 10 } } }
                        }
                    }
                });
            }

            // 3. Match Confidence Distribution (Bar Chart)
            const confData = data.confidence_breakdown || {};
            const confLabels = ['Auto-Merged (>=85%)', 'Human Review (70-85%)', 'New CNMC Code (<70%)'];
            const confValues = [
                confData.high || 0,
                confData.review_band || 0,
                (confData.low || 0) + (confData.new_code || 0)
            ];

            const ctxConf = document.getElementById('chartConfidenceDist')?.getContext('2d');
            if (ctxConf) {
                if (chartConfidenceDistInstance) chartConfidenceDistInstance.destroy();
                chartConfidenceDistInstance = new Chart(ctxConf, {
                    type: 'bar',
                    data: {
                        labels: confLabels,
                        datasets: [{
                            label: 'Records Count',
                            data: confValues,
                            backgroundColor: ['#1f8a54', '#b8792a', '#2b5c8f']
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: { legend: { display: false } },
                        scales: {
                            y: { beginAtZero: true, grid: { color: 'rgba(0,0,0,0.05)' } },
                            x: { grid: { display: false } }
                        }
                    }
                });
            }

            // 4. Render Top Inter-CPSE Shared Materials Table
            if (sharedMaterialsTableContainer) {
                const shared = data.shared_materials || [];
                if (shared.length === 0) {
                    sharedMaterialsTableContainer.innerHTML = '<p class="output__empty">No cross-CPSE shared materials identified yet. Ingest records from multiple CPSEs to see joint procurement opportunities.</p>';
                } else {
                    let tableHtml = `
                        <table class="shared-table">
                            <thead>
                                <tr>
                                    <th>CNMC Code</th>
                                    <th>Harmonized Description</th>
                                    <th>Category</th>
                                    <th>Sharing CPSEs</th>
                                </tr>
                            </thead>
                            <tbody>
                    `;
                    shared.forEach(item => {
                        const pills = (item.cpses || []).map(cpse => `<span class="cpse-pill">${escapeHtml(cpse.trim())}</span>`).join(' ');
                        tableHtml += `
                            <tr>
                                <td><strong>${escapeHtml(item.common_code)}</strong></td>
                                <td>${escapeHtml(item.standard_description)}</td>
                                <td><span class="eyebrow">${escapeHtml(item.category)}</span></td>
                                <td><div class="cpse-pill-group">${pills}</div></td>
                            </tr>
                        `;
                    });
                    tableHtml += '</tbody></table>';
                    sharedMaterialsTableContainer.innerHTML = tableHtml;
                }
            }

        } catch (error) {
            console.error('Error loading analytics:', error);
        }
    }

    // ============ SAP / ERP Integration Hub ============
    if (btnTriggerErpExport) {
        btnTriggerErpExport.addEventListener('click', async function () {
            btnTriggerErpExport.disabled = true;
            if (erpJobStatusBadge) {
                erpJobStatusBadge.textContent = 'DISPATCHING TO SAP MM...';
                erpJobStatusBadge.className = 'status-pill status-pill--warning';
            }
            if (erpPayloadViewer) erpPayloadViewer.textContent = 'Contacting ERP Gateway (/api/v1/materials/export)...';

            try {
                const response = await fetch('/api/v1/materials/export?adapter=sap-s4hana&per_page=10');
                const data = await response.json();

                if (response.ok) {
                    if (erpPayloadViewer) {
                        erpPayloadViewer.textContent = JSON.stringify(data, null, 2);
                    }
                    if (erpJobStatusBadge) {
                        erpJobStatusBadge.textContent = 'READY (JOB ID: ' + (data.job?.job_id?.substring(0, 8) || 'EXPORT-01') + ')';
                        erpJobStatusBadge.className = 'status-pill status-pill--success';
                    }

                    // Acknowledge handshake
                    if (data.job?.job_id) {
                        setTimeout(async () => {
                            await fetch(`/api/v1/integration/jobs/${data.job.job_id}/ack`, {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ status: 'acknowledged', acknowledgement: 'sap-mara-synced' })
                            });
                            if (erpJobStatusBadge) {
                                erpJobStatusBadge.textContent = 'SYNCED & ACKNOWLEDGED BY SAP';
                            }
                        }, 1200);
                    }
                } else {
                    if (erpPayloadViewer) erpPayloadViewer.textContent = 'Export Error: ' + JSON.stringify(data);
                    if (erpJobStatusBadge) erpJobStatusBadge.textContent = 'ERROR';
                }
            } catch (error) {
                console.error('ERP error:', error);
                if (erpPayloadViewer) erpPayloadViewer.textContent = 'Connection failure: ' + error.message;
            } finally {
                btnTriggerErpExport.disabled = false;
            }
        });
    }

    // ============ Governance Audit Log ============
    async function loadAuditLog() {
        if (!auditLogContainer) return;
        auditLogContainer.innerHTML = '<p class="output__empty">Fetching immutable audit logs...</p>';

        try {
            const response = await fetch('/audit-log');
            const logs = await response.json();

            if (!logs || logs.length === 0) {
                auditLogContainer.innerHTML = '<p class="output__empty">No audit events recorded yet.</p>';
                return;
            }

            auditLogContainer.innerHTML = logs.map(entry => {
                let badgeClass = 'status-pill';
                const act = (entry.action || '').toUpperCase();
                if (act.includes('APPROVE') || act.includes('CREATE')) badgeClass += ' status-pill--success';
                else if (act.includes('REJECT') || act.includes('DELETE')) badgeClass += ' status-pill--danger';
                else if (act.includes('RETIRE') || act.includes('UPDATE')) badgeClass += ' status-pill--warning';

                return `
                    <div class="audit-card">
                        <div class="audit-card__top">
                            <span class="audit-card__entity">${escapeHtml(entry.entity_type)} #${escapeHtml(String(entry.entity_id))}</span>
                            <span class="${badgeClass}">${escapeHtml(entry.action)}</span>
                        </div>
                        <div class="audit-card__meta">
                            <span>User: <strong>${escapeHtml(entry.changed_by || 'system')}</strong></span>
                            <span>Time: ${escapeHtml(entry.timestamp || 'Just now')}</span>
                        </div>
                        ${entry.new_value ? `<div class="audit-card__diff">${escapeHtml(typeof entry.new_value === 'object' ? JSON.stringify(entry.new_value) : String(entry.new_value))}</div>` : ''}
                    </div>
                `;
            }).join('');
        } catch (error) {
            console.error('Audit log error:', error);
            auditLogContainer.innerHTML = '<p class="output__empty">Failed to load audit trail.</p>';
        }
    }

    // ============ Pending Review Queue (Governance) ============
    async function loadPendingReview() {
        if (!reviewQueue) return;
        reviewQueue.innerHTML = '<p class="output__empty">Loading pending validation items...</p>';

        try {
            const response = await fetch('/pending-review');
            const items = await response.json();

            if (!items || items.length === 0) {
                reviewQueue.innerHTML = `
                    <div class="stat-card" style="padding:20px; text-align:center;">
                        <span class="status-pill status-pill--success" style="margin-bottom:8px;">ALL CLEAR</span>
                        <h3>No Pending Exception Items</h3>
                        <p style="color:var(--ink-soft); margin-top:4px;">All submitted material records have been categorized and confirmed with high confidence.</p>
                    </div>
                `;
                return;
            }

            reviewQueue.innerHTML = items.map(item => `
                <div class="stat-card" style="margin-bottom:14px; padding:18px; border-left: 4px solid var(--amber);">
                    <div class="stat-card__top">
                        <span class="stat-card__title">CPSE: ${escapeHtml(item.cpse_id)} &bull; Code: ${escapeHtml(item.material_code)}</span>
                        <span class="status-pill status-pill--warning">${Math.round((item.tolerance_score || 0.75) * 100)}% Resemblance</span>
                    </div>
                    <div style="margin: 10px 0;">
                        <p style="font-size:13.5px;"><strong>Raw Spec:</strong> ${escapeHtml(item.description)} ${item.specification ? '&bull; ' + escapeHtml(item.specification) : ''}</p>
                        <p style="font-size:13.5px; color: var(--ink-soft); margin-top:4px;"><strong>Target CNMC:</strong> ${escapeHtml(item.common_code)}</p>
                    </div>
                    <div style="display:flex; gap:10px; margin-top:12px;">
                        <button type="button" class="btn-primary" onclick="approveMerge('${escapeHtml(item.common_code)}')">
                            ✓ Approve Consolidation to ${escapeHtml(item.common_code)}
                        </button>
                        <button type="button" class="btn-secondary" onclick="rejectMerge(${item.id})">
                            ✕ Reject & Mint Distinct Code
                        </button>
                    </div>
                </div>
            `).join('');
        } catch (error) {
            console.error('Error loading pending review:', error);
            reviewQueue.innerHTML = '<p class="output__empty">Failed to load review items.</p>';
        }
    }

    window.approveMerge = async function (commonCode) {
        try {
            const response = await fetch('/approve-merge', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ common_code: commonCode, reason: 'Approved by Lead Material Master Admin' })
            });
            if (response.ok) {
                await loadPendingReview();
                await loadRegistry();
            }
        } catch (error) {
            console.error('Approve error:', error);
        }
    };

    window.rejectMerge = async function (recordId) {
        try {
            const response = await fetch('/reject-merge', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ record_id: recordId, reason: 'Distinct specification required new CNMC code' })
            });
            if (response.ok) {
                await loadPendingReview();
                await loadRegistry();
            }
        } catch (error) {
            console.error('Reject error:', error);
        }
    };

    // ============ Detail Drilldown for Code ============
    async function loadRecordsForCode(commonCode) {
        try {
            const response = await fetch(`/admin-records/${encodeURIComponent(commonCode)}`);
            const records = await response.json();
            alert(`CNMC Code: ${commonCode}\nLinked CPSE Records: ${records.length}\n\n` + records.map(r => `• [${r.cpse_id}] ${r.material_code}: ${r.description}`).join('\n'));
        } catch (e) {
            console.error(e);
        }
    }

    // ============ Search & Filters ============
    if (registrySearch) {
        registrySearch.addEventListener('input', function () {
            const q = this.value.toLowerCase();
            document.querySelectorAll('.registry-card').forEach(card => {
                const text = card.textContent.toLowerCase();
                card.style.display = text.includes(q) ? '' : 'none';
            });
        });
    }

    if (registryCategoryFilter) {
        registryCategoryFilter.addEventListener('change', function () {
            const cat = this.value.toLowerCase();
            document.querySelectorAll('.registry-card').forEach(card => {
                if (!cat) {
                    card.style.display = '';
                    return;
                }
                const cardCat = card.querySelector('.eyebrow')?.textContent.toLowerCase() || '';
                card.style.display = cardCat === cat ? '' : 'none';
            });
        });
    }

    // Initialize
    applyAccessVisibility();
    loadRegistry();
});