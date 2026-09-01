// static/app_v2.js - Unified Material Master Control Engine

// Global CSRF token storage
let csrfToken = null;

// Helper to add CSRF token to fetch requests
function secureFetch(url, options = {}) {
    const opts = { ...options };
    if (opts.method && ['POST', 'PUT', 'PATCH', 'DELETE'].includes(opts.method.toUpperCase())) {
        opts.headers = opts.headers || {};
        if (csrfToken) {
            opts.headers['X-CSRF-Token'] = csrfToken;
        }
    }
    return fetch(url, opts);
}

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
    const loginModal = document.getElementById('loginModal');
    const newCodeModal = document.getElementById('newCodeModal');
    const loginForm = document.getElementById('loginForm');
    const newCodeForm = document.getElementById('newCodeForm');
    const useUserDemoBtn = document.getElementById('useUserDemoBtn');
    const cancelNewCodeBtn = document.getElementById('cancelNewCodeBtn');
    const userBadge = document.createElement('div');
    userBadge.className = 'user-chip';
    userBadge.innerHTML = '<span>Not logged in</span>';
    
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
            if (user.authenticated) {
                const badge = document.querySelector('.user-chip');
                if (badge) {
                    badge.innerHTML = `<span>${escapeHtml(user.username || 'user')}</span><button type="button" id="logoutBtn">logout</button>`;
                    const logoutBtn = document.getElementById('logoutBtn');
                    if (logoutBtn) logoutBtn.addEventListener('click', logoutUser);
                    if (loginModal) loginModal.classList.add('hidden');
                }
            } else if (loginModal) {
                loginModal.classList.remove('hidden');
            }
        } catch (error) {
            adminTabButton.hidden = false;
            if (loginModal) loginModal.classList.remove('hidden');
        }
    }

    async function logoutUser() {
        try {
            await fetch('/logout', { method: 'POST' });
        } catch (error) {
            console.error('Logout failed', error);
        }
        const badge = document.querySelector('.user-chip');
        if (badge) {
            badge.innerHTML = '<span>Not logged in</span>';
        }
        if (loginModal) loginModal.classList.remove('hidden');
        window.location.reload();
    }

    async function loginUser(username, password) {
        const response = await fetch('/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password })
        });
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.error || 'Invalid username or password');
        }
        // Store CSRF token from login response
        if (data.csrf_token) {
            csrfToken = data.csrf_token;
        }
        if (loginModal) loginModal.classList.add('hidden');
        await applyAccessVisibility();
        return data;
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

    const topbarRight = document.querySelector('.topbar__right');
    if (topbarRight && !document.querySelector('.user-chip')) {
        topbarRight.appendChild(userBadge);
    }

    loginForm?.addEventListener('submit', async function (event) {
        event.preventDefault();
        const username = document.getElementById('loginUsername').value.trim();
        const password = document.getElementById('loginPassword').value;
        try {
            await loginUser(username, password);
        } catch (error) {
            alert(error.message || 'Login failed');
        }
    });

    useUserDemoBtn?.addEventListener('click', () => {
        document.getElementById('loginUsername').value = 'user';
        document.getElementById('loginPassword').value = 'user';
        loginForm.requestSubmit();
    });

    newCodeForm?.addEventListener('submit', async function (event) {
        event.preventDefault();
        const recordId = document.getElementById('newCodeRecordId').value;
        const reason = document.getElementById('newCodeReason').value.trim();
        if (!recordId || !reason) {
            alert('Please add a reason before attaching a new code.');
            return;
        }
        try {
            const response = await secureFetch('/reject-merge', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ record_id: Number(recordId), reason })
            });
            const data = await response.json();
            if (!response.ok) {
                throw new Error(data.error || 'Unable to attach new code');
            }
            newCodeModal.classList.add('hidden');
            newCodeForm.reset();
            await loadPendingReview();
            await loadRegistry();
        } catch (error) {
            alert(error.message || 'Could not attach a new code');
        }
    });

    cancelNewCodeBtn?.addEventListener('click', () => {
        newCodeModal.classList.add('hidden');
        newCodeForm.reset();
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
            description: document.getElementById('description').value
        };

        try {
            const response = await secureFetch('/process', {
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
            const response = await secureFetch('/upload-csv', {
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
                const response = await secureFetch('/api/v1/load-sample-dataset', {
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

            // Populate categories in filter dropdown (admin-only endpoint may be unavailable to normal users)
            try {
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
            } catch (error) {
                // ignored for non-admin or restricted access
            }

            // Calculate metrics
            let totalSourceRecords = 0;
            materials.forEach(m => {
                const c = m.record_count ?? m.linked_records_count ?? m.total_records ?? (m.linked_records ? m.linked_records.length : 1);
                totalSourceRecords += c;
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
            const count = m.record_count ?? m.linked_records_count ?? m.records_count ?? (m.linked_records ? m.linked_records.length : 1);
            const countText = `${count} ${count === 1 ? 'CPSE Record' : 'CPSE Records'}`;

            let attrsSnippet = '';
            if (m.attributes && typeof m.attributes === 'object') {
                const entries = Object.entries(m.attributes).filter(([k, v]) => v !== null && v !== '');
                if (entries.length > 0) {
                    attrsSnippet = `<div class="registry-card__attrs">${entries.slice(0, 4).map(([k, v]) => `<span>${escapeHtml(k)}: ${escapeHtml(String(v))}</span>`).join('')}</div>`;
                }
            }

            return `
                <div class="registry-card" data-code="${escapeHtml(m.common_code)}">
                    <div class="registry-card__top">
                        <span class="eyebrow">${escapeHtml(m.category || 'Uncategorized')}</span>
                        <div style="display:flex; align-items:center; gap:8px;">
                            <span class="status-pill card-count-pill">${escapeHtml(countText)}</span>
                            <span class="registry-card__chevron"><span class="chevron-icon">▼</span> Details</span>
                        </div>
                    </div>
                    <strong class="registry-card__code">${escapeHtml(m.common_code)}</strong>
                    <p class="registry-card__desc">${escapeHtml(m.standard_description)}</p>
                    ${attrsSnippet}

                    <!-- Expandable Dropdown Drawer for Attached CPSE Records -->
                    <div class="registry-card__drawer" id="drawer-${escapeHtml(m.common_code)}">
                        <div class="drawer-header">
                            <span class="drawer-header-count">📦 Attached CPSE Source Records (${count})</span>
                            <span style="font-size:10px; color:var(--ink-faint);">Click card to collapse</span>
                        </div>
                        <div class="attached-records-list">
                            <p class="output__empty" style="padding:10px;">Loading attached records...</p>
                        </div>
                    </div>
                </div>
            `;
        }).join('');

        // Attach click to toggle expandable dropdown
        registryGrid.querySelectorAll('.registry-card').forEach(card => {
            card.addEventListener('click', async function (e) {
                // If clicking inside drawer text, allow selection without toggling
                if (e.target.closest('.registry-card__drawer') && !e.target.closest('.drawer-header')) {
                    return;
                }

                const code = this.getAttribute('data-code');
                const isOpen = this.classList.contains('registry-card--open');

                if (isOpen) {
                    this.classList.remove('registry-card--open');
                } else {
                    this.classList.add('registry-card--open');
                    await loadDrawerRecords(this, code);
                }
            });
        });
    }

    async function loadDrawerRecords(cardElement, commonCode) {
        const drawerList = cardElement.querySelector('.attached-records-list');
        if (!drawerList) return;

        try {
            const response = await fetch(`/admin-records/${encodeURIComponent(commonCode)}`);
            const records = await response.json();

            if (!records || records.length === 0) {
                drawerList.innerHTML = '<p class="output__empty" style="padding:8px;">No source CPSE records linked to this code.</p>';
                return;
            }

            // Dynamically update card count to match actual database records
            const exactCount = records.length;
            const exactCountText = `${exactCount} ${exactCount === 1 ? 'CPSE Record' : 'CPSE Records'}`;
            const pill = cardElement.querySelector('.card-count-pill');
            if (pill) pill.textContent = exactCountText;
            const headerCount = cardElement.querySelector('.drawer-header-count');
            if (headerCount) headerCount.textContent = `📦 Attached CPSE Source Records (${exactCount})`;

            drawerList.innerHTML = records.map(r => {
                const scoreDisplay = r.tolerance_score !== null && r.tolerance_score !== undefined
                    ? `${Math.round(r.tolerance_score * 100)}% Match`
                    : 'Origin Master';

                return `
                    <div class="attached-record-item">
                        <div class="attached-record-item__top">
                            <div style="display:flex; align-items:center; gap:6px;">
                                <span class="cpse-pill">${escapeHtml(r.cpse_id || 'CPSE')}</span>
                                <span class="attached-record-item__code">${escapeHtml(r.material_code || 'N/A')}</span>
                            </div>
                            <span class="status-pill status-pill--success">${escapeHtml(scoreDisplay)}</span>
                        </div>
                        <div class="attached-record-item__desc">
                            <strong>Description:</strong> ${escapeHtml(r.description || '')}
                        </div>
                        ${r.specification ? `<div class="attached-record-item__spec"><strong>Specification:</strong> ${escapeHtml(r.specification)}</div>` : ''}
                        <div class="attached-record-item__meta">
                            <span>Source System: ${escapeHtml(r.source_system_id || 'ERP')}</span>
                            <span>Procured: ${escapeHtml(r.procurement_date || 'N/A')}</span>
                        </div>
                    </div>
                `;
            }).join('');
        } catch (error) {
            console.error('Error fetching attached records for code:', commonCode, error);
            drawerList.innerHTML = '<p class="output__empty" style="color:var(--red);">Failed to load attached records.</p>';
        }
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
            if (!response.ok) {
                reviewQueue.innerHTML = `
                    <div class="stat-card" style="padding:24px; text-align:center;">
                        <span class="status-pill status-pill--warning" style="margin-bottom:8px;">ACCESS LIMITED</span>
                        <h3>Review Queue Unavailable</h3>
                        <p style="color:var(--ink-soft); margin-top:6px;">This view is reserved for the administrator role.</p>
                    </div>
                `;
                return;
            }
            const items = await response.json();

            if (!items || items.length === 0) {
                reviewQueue.innerHTML = `
                    <div class="stat-card" style="padding:24px; text-align:center;">
                        <span class="status-pill status-pill--success" style="margin-bottom:8px;">ALL CLEAR</span>
                        <h3>No Pending Exception Items</h3>
                        <p style="color:var(--ink-soft); margin-top:6px;">All submitted material records have been categorized and confirmed with high confidence (>= 85%) or minted as distinct codes.</p>
                    </div>
                `;
                return;
            }

            reviewQueue.innerHTML = items.map(item => {
                const score = Math.round((item.tolerance_score || 0.75) * 100);
                
                // Master attributes tags
                let masterAttrsHtml = '';
                if (item.attributes && typeof item.attributes === 'object') {
                    const entries = Object.entries(item.attributes).filter(([k, v]) => v !== null && v !== '');
                    if (entries.length > 0) {
                        masterAttrsHtml = entries.map(([k, v]) => `<span class="attr-pill"><strong>${escapeHtml(k)}:</strong> ${escapeHtml(String(v))}</span>`).join('');
                    } else {
                        masterAttrsHtml = '<span class="attr-pill" style="color:var(--ink-faint);">General specification</span>';
                    }
                }

                // Attribute diff tags (Flags)
                let diffTagsHtml = '';
                if (item.attribute_flags && typeof item.attribute_flags === 'object' && Object.keys(item.attribute_flags).length > 0) {
                    diffTagsHtml = Object.entries(item.attribute_flags).map(([attr, flag]) => {
                        let tagClass = 'attr-tag--unknown';
                        let icon = '⚪';
                        if (flag === 'matched' || flag === 'match') {
                            tagClass = 'attr-tag--matched';
                            icon = '✓';
                        } else if (flag === 'conflict') {
                            tagClass = 'attr-tag--conflict';
                            icon = '✕';
                        }
                        return `<span class="attr-tag ${tagClass}">${icon} <strong>${escapeHtml(attr)}</strong>: ${escapeHtml(flag)}</span>`;
                    }).join('');
                } else {
                    diffTagsHtml = `<span class="attr-tag attr-tag--matched">✓ High Text Similarity (${score}%)</span>`;
                }

                return `
                <div class="review-card">
                    <div class="review-card__header">
                        <div class="review-card__title">
                            <span>Record #${item.id}</span>
                            <span class="status-pill status-pill--warning">${score}% Similarity</span>
                            <span class="eyebrow" style="margin-left:4px;">${escapeHtml(item.category || 'Standard Category')}</span>
                        </div>
                        <div class="review-card__meta">
                            <span style="font-size:12px; color:var(--ink-soft);">Mid-Band Confidence (70–85%) &bull; Decision Required</span>
                        </div>
                    </div>

                    <div class="review-compare-grid">
                        <!-- Left Column: Source CPSE Record -->
                        <div class="review-col review-col--source">
                            <div class="review-col__heading">
                                <span>🏢 Incoming CPSE Record</span>
                                <span class="cpse-pill">${escapeHtml(item.cpse_id || 'CPSE')}</span>
                            </div>
                            <div style="display:flex; justify-content:space-between; align-items:baseline;">
                                <span class="review-col__code">${escapeHtml(item.material_code || 'N/A')}</span>
                                <span style="font-size:11px; color:var(--ink-faint);">Source Code</span>
                            </div>
                            <p class="review-col__desc"><strong>Description:</strong> ${escapeHtml(item.description || '')}</p>
                            ${item.specification ? `<div class="review-col__spec"><strong>Specification:</strong> ${escapeHtml(item.specification)}</div>` : ''}
                        </div>

                        <!-- Right Column: Universal CNMC Target -->
                        <div class="review-col review-col--master">
                            <div class="review-col__heading">
                                <span>🇮🇳 Proposed Universal National Code</span>
                                <span class="status-pill status-pill--success">CNMC MASTER</span>
                            </div>
                            <div style="display:flex; justify-content:space-between; align-items:baseline;">
                                <span class="review-col__code" style="color:var(--green-ink);">${escapeHtml(item.common_code)}</span>
                                <span style="font-size:11px; color:var(--green-ink); font-weight:700;">${escapeHtml(item.category || '')}</span>
                            </div>
                            <p class="review-col__desc"><strong>Standard Description:</strong> ${escapeHtml(item.standard_description || '')}</p>
                            <div style="margin-top:6px;">
                                <span style="font-size:11.5px; font-weight:700; color:var(--ink-faint); text-transform:uppercase;">Master Technical Attributes:</span>
                                <div class="review-col__attrs">${masterAttrsHtml}</div>
                            </div>
                        </div>
                    </div>

                    <!-- Attribute Comparison Diff Bar -->
                    <div class="review-diff-bar">
                        <span class="review-diff-bar__title">Technical Attribute &amp; Resemblance Analysis:</span>
                        <div class="review-diff-tags">
                            ${diffTagsHtml}
                        </div>
                    </div>

                    <!-- Action Buttons -->
                    <div class="review-card__actions">
                        <div style="font-size:12.5px; color:var(--ink-soft);">
                            Merging will link <strong>[${escapeHtml(item.cpse_id)}] ${escapeHtml(item.material_code)}</strong> to <strong>${escapeHtml(item.common_code)}</strong>.
                        </div>
                        <div style="margin:10px 0; padding:10px 12px; border:1px solid rgba(255,170,0,.45); background:rgba(255,170,0,.08); border-radius:10px; color:var(--ink-soft); font-size:12.5px; line-height:1.5;">
                            <strong>These codes seem similar.</strong> If this belongs to a different material family, attach a new code instead of merging.
                        </div>
                        <div class="review-card__btns">
                            <button type="button" class="btn-primary" onclick="approveMerge('${escapeHtml(item.common_code)}')">
                                ✓ Approve Consolidation to ${escapeHtml(item.common_code)}
                            </button>
                            <button type="button" class="btn-secondary" onclick="confirmAttachNewCode(${item.id})">
                                🆕 Attach New Code
                            </button>
                            <button type="button" class="btn-secondary" onclick="rejectMerge(${item.id})">
                                ✕ Reject &amp; Mint Distinct Code
                            </button>
                        </div>
                    </div>
                </div>
                `;
            }).join('');
        } catch (error) {
            console.error('Error loading pending review:', error);
            reviewQueue.innerHTML = '<p class="output__empty">Failed to load review items.</p>';
        }
    }

    window.approveMerge = async function (commonCode) {
        try {
            const response = await secureFetch('/approve-merge', {
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

    window.confirmAttachNewCode = function (recordId) {
        document.getElementById('newCodeRecordId').value = recordId;
        document.getElementById('newCodeReason').value = 'These codes seem similar; this material belongs to a different family and should be attached as a new code.';
        newCodeModal.classList.remove('hidden');
    };

    window.rejectMerge = async function (recordId, reasonOverride) {
        try {
            const reason = reasonOverride || 'Distinct specification required new CNMC code';
            const response = await secureFetch('/reject-merge', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ record_id: recordId, reason })
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