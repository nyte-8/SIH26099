# SIH26099 Documentation Index

## Overview

This workspace contains the **Unified Material Master Framework** for standardizing material descriptions across Central Public Sector Enterprises (CPSEs). The system uses AI-powered classification, attribute extraction, and human-in-the-loop review to create a unified national registry.

**Current Status:** Phases 1-6 Complete ✅ | Ready for Testing & Deployment

---

## Quick Navigation

### 👤 For Users (CPSEs) — New? Start Here! ⭐
Start here if you're using the system to upload and standardize materials.

**→ [BEGINNER_GUIDE.md](BEGINNER_GUIDE.md)** (5-10 min read) ⭐ START HERE
- Super simple, non-technical walkthrough
- Click-by-click instructions with examples
- Real-world scenario (Day 1-4 example)
- Common questions answered
- Visual quick reference cards
- Perfect if you've never used this before!

**→ [QUICK_START.md](QUICK_START.md)** (10-15 min read) — More Detailed Version
- Deeper dive into each tab
- CSV upload format specifications
- API reference for future integrations
- Read after BEGINNER_GUIDE for extra detail

---

### 👨‍💻 For Developers & Operators
Start here if you're implementing, testing, or deploying the system.

**→ [IMPLEMENTATION_SUMMARY.md](IMPLEMENTATION_SUMMARY.md)** (15-20 min read)
- Phase status overview (Items 1-19)
- Backend endpoints documentation
- Database schema
- Code generation examples
- Testing procedures
- Next priorities (Phases 7-9)

**→ [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md)** (20-30 min read)
- Pre-deployment checklist (all required tests)
- Step-by-step migration from old to new interface
- Real-world testing procedures
- Full end-to-end test scenario
- Production deployment timeline
- Performance monitoring

---

### 🧠 For Team Presentations (Nodal Round)
Start here if you're explaining the system design to the panel.

**→ [TECHNICAL_DEEP_DIVE.md](TECHNICAL_DEEP_DIVE.md)** (25-40 min read)
- "Why" behind each major component (Items 1-8)
- Component 1: Category Classifier
- Component 2: Attribute Schema
- Component 3: Attribute Extraction
- Component 4: Unit Normalization
- Component 5: Tiered Match Logic
- Component 6: Segmented Code Scheme
- Component 8: Three-Band Decision Logic
- Testing scenarios for each component
- Key takeaways + Q&A section

---

## File Structure

```
version2/
├── app.py                              Main Flask backend server
├── database.py                         SQLite3 database layer
├── matching.py                         Material processing pipeline
├── categories.py                       Category + attribute schemas
├── gemma_helper.py                     LLM integration (Gemma 7B)
├── units.py                            Unit normalization
├── main.py                             Batch processing entry point
├── static/
│   ├── index_v2.html                   NEW: Three-tab interface
│   ├── app_v2.js                       NEW: Three-tab JavaScript logic
│   ├── index.html                      OLD: Original interface (backup)
│   ├── app.js                          OLD: Original JavaScript (backup)
│   └── style.css                       Shared styling
├── dataset.csv                         Sample material data
├── material_master.db                  SQLite3 database
├── requirements.txt                    Python dependencies
├── README.md                           Original project README
│
├── DOCUMENTATION_INDEX.md              ← YOU ARE HERE
├── BEGINNER_GUIDE.md                   ⭐ START HERE if new
├── QUICK_START.md                      User guide (detailed version)
├── IMPLEMENTATION_SUMMARY.md           Phase status & technical details
├── TECHNICAL_DEEP_DIVE.md              Component explanations for presentations
└── DEPLOYMENT_GUIDE.md                 Testing & deployment procedures
```

---

## What Each File Does

### Core Backend

| File | Purpose |
|------|---------|
| **app.py** | Flask web server with REST API endpoints (/process, /materials, /records, /pending-review, /approve-merge, /reject-merge, /upload-csv) |
| **database.py** | SQLite3 storage layer; manages common_materials (standardized codes) and material_records (CPSE submissions) |
| **matching.py** | Material processing pipeline; orchestrates process_single_material() and bulk ingestion |
| **categories.py** | 18 fixed categories with per-category attribute schemas |
| **gemma_helper.py** | LLM integration (OpenAI-compatible API via LM Studio on localhost:1234); fallback to offline heuristics |
| **units.py** | Unit normalization across 8+ unit families (mm, bar, kv, pct, rpm, etc.) |
| **main.py** | Batch processing script for dataset.csv ingestion |

### Frontend (Dual Interface)

| File | Purpose |
|------|---------|
| **index_v2.html** | NEW: Three-tab interface (Upload / Registry / Admin Review) |
| **app_v2.js** | NEW: Tab switching, form handling, AJAX interactions |
| **index.html** | BACKUP: Original single-page interface |
| **app.js** | BACKUP: Original JavaScript |
| **style.css** | Shared CSS for both interfaces |

### Database

| File | Purpose |
|------|---------|
| **material_master.db** | SQLite3 database with common_materials and material_records tables |
| **dataset.csv** | Sample CSV for testing bulk upload workflow |

### Documentation (This Folder)

| File | Purpose |
|------|---------|
| **DOCUMENTATION_INDEX.md** | Navigation guide for all docs (you are here) |
| **QUICK_START.md** | User guide: how to use the three-tab interface |
| **IMPLEMENTATION_SUMMARY.md** | Technical summary: phase status, endpoints, schema, testing |
| **TECHNICAL_DEEP_DIVE.md** | Component deep-dives: "why" for each slice (for presentations) |
| **DEPLOYMENT_GUIDE.md** | Deployment steps: migration, testing, rollout timeline |

---

## Quick Status Dashboard

### Completed ✅

- **Phase 1 (Items 1-5):** Core matching logic
  - Category classifier (LLM + fallback heuristics)
  - Per-category attribute schemas
  - Attribute extraction
  - Unit normalization
  - Tiered match logic (Tier 1: category, Tier 2: attributes, Tier 3: text similarity)

- **Phase 2 (Item 6):** Segmented code scheme
  - Format: CATEGORY-MATERIAL-DIMENSION-SERIAL
  - Example: `PP-SS-050-0001` (Pipe, Stainless Steel, 50mm, serial 1)

- **Phase 3 (Items 8-10):** Human-in-the-loop review
  - Three-band decision logic (High ≥85%, Mid 70-85%, Low <70%)
  - Status field (confirmed / pending_review / rejected_needs_new_code)
  - Review queue with approve/reject workflow

- **Phase 4 (Items 11-12):** Bulk CSV ingestion
  - `/upload-csv` endpoint with sequential row processing
  - Detailed per-row results (status, code, tolerance score)

- **Phase 5 (Items 13-14):** Traceability
  - Source entry storage (one record per CPSE submission)
  - Backend queries for registry summaries and pending reviews

- **Phase 6 (Items 15-21):** Three-tab frontend
  - Tab 1: Single entry + bulk CSV upload
  - Tab 2: Registry browser with expandable source entries
  - Tab 3: Admin review queue with approve/reject buttons

### Pending ⏳

- **Phase 3 (Item 10):** Second AI pass for mid-band items (not yet implemented)
- **Phase 7-9 (Stretch):** Extras and polish
  - Multilingual support (stub)
  - REST API documentation for ERP
  - Metrics dashboard
  - Admin edit capabilities

---

## Key Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/` | GET | Serve index.html (or index_v2.html after migration) |
| `/process` | POST | Single material standardization |
| `/materials` | GET | Unique codes summary with record counts |
| `/records` | GET | All source records from all CPSEs |
| `/pending-review` | GET | All mid-band items (70-85% confidence) |
| `/approve-merge` | POST | Confirm mid-band merge, set status="confirmed" |
| `/reject-merge` | POST | Reject merge, flag for new code |
| `/upload-csv` | POST | Bulk CSV processing with per-row results |

---

## Database Schema

### common_materials (Standardized Registry)
- id, common_code (UNIQUE), standard_description, category, attributes (JSON), created_at

### material_records (CPSE Submissions)
- id, common_code (FK), cpse_id, material_code, description, specification, unit_of_measure, material_type, procurement_date, status, tolerance_score, attribute_flags (JSON), created_at

---

## Getting Started (5 minutes)

### 1. Read BEGINNER_GUIDE.md (5-10 min) ⭐ START HERE
```
This is the easiest way to learn the system!
Simple language, step-by-step instructions, no jargon.
```

### 2. Check Prerequisites
```bash
cd c:\Users\shree\Downloads\version2
python --version  # Should be 3.13+
pip list | grep -E "(flask|pandas)"
```

### 3. Start the Server
```bash
python app.py
```

### 4. Open Browser
```
http://127.0.0.1:5000
```

### 5. Try It Out
- **Tab 1:** Upload a test material using BEGINNER_GUIDE
- **Tab 2:** See it in the registry
- **Tab 3:** (If mid-band) Approve or reject

---

## Testing Workflow

### Option A: Quick Test (5 min)
1. Read [QUICK_START.md](QUICK_START.md) (user guide)
2. Start Flask server
3. Upload a test material via Tab 1
4. Verify it appears in Tab 2

### Option B: Full Deployment Test (2-3 hours)
1. Read [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md) (all 10 steps)
2. Run all checklist items
3. Execute end-to-end scenario
4. Verify metrics

### Option C: Learn the Design (1-2 hours)
1. Read [TECHNICAL_DEEP_DIVE.md](TECHNICAL_DEEP_DIVE.md)
2. Review each component's "why"
3. Prepare presentation talking points
4. Run Q&A scenarios

---

## Common Questions

**Q: What's the difference between the old and new interface?**
A: Old (index.html) = single upload form. New (index_v2.html) = three tabs: Upload, Registry, Admin Review. See [QUICK_START.md](QUICK_START.md).

**Q: How are materials matched?**
A: Three-tier logic: (1) Category must match, (2) Attributes must not conflict, (3) Text similarity determines final decision. See [TECHNICAL_DEEP_DIVE.md](TECHNICAL_DEEP_DIVE.md).

**Q: What's the three-band logic?**
A: High confidence (≥85%) = auto-confirm. Mid-band (70-85%) = human review needed. Low (<70%) = create new code. See [IMPLEMENTATION_SUMMARY.md](IMPLEMENTATION_SUMMARY.md).

**Q: How do I deploy this?**
A: Follow [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md) steps 1-10 for full testing and rollout.

**Q: What if LM Studio is offline?**
A: System falls back to keyword matching and offline heuristics. No downtime. See [TECHNICAL_DEEP_DIVE.md](TECHNICAL_DEEP_DIVE.md).

---

## Need Help?

- **Using the system?** → [QUICK_START.md](QUICK_START.md)
- **Deploying or testing?** → [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md)
- **Preparing a presentation?** → [TECHNICAL_DEEP_DIVE.md](TECHNICAL_DEEP_DIVE.md)
- **Understanding architecture?** → [IMPLEMENTATION_SUMMARY.md](IMPLEMENTATION_SUMMARY.md)

---

## Roadmap Alignment

This implementation covers:
- ✅ Phase 1: Core Matching Logic (5 items)
- ✅ Phase 2: Code Scheme (1 item)
- ✅ Phase 3: Human-in-the-Loop (3 items; 2 of 3 complete)
- ✅ Phase 4: Bulk Ingestion (2 items)
- ✅ Phase 5: Traceability (2 items)
- ✅ Phase 6: Frontend Redesign (7 items)
- ⏳ Phase 7-9: Polish & Extras (Stretch goals)

**Current Score: 18/19 core items complete (95%)**

---

## Next Steps (Recommended Priority)

1. **Read QUICK_START.md** (10 min) — Understand user workflow
2. **Run DEPLOYMENT_GUIDE.md Steps 1-5** (30 min) — Verify setup
3. **Execute full end-to-end test** (1 hour) — Validate logic
4. **Read TECHNICAL_DEEP_DIVE.md** (1 hour) — Prepare presentation
5. **Deploy to production** — Follow DEPLOYMENT_GUIDE.md Steps 6-10

---

**Documentation Version:** 2.0  
**Last Updated:** 2026-08-30  
**Maintained By:** Development Team  
**Deployment Status:** Ready for Testing

---

### Quick Links (Copy-Paste)

```
START HERE:        BEGINNER_GUIDE.md ⭐
User Guide:        QUICK_START.md
Implementation:    IMPLEMENTATION_SUMMARY.md
Deployment:        DEPLOYMENT_GUIDE.md
Technical:         TECHNICAL_DEEP_DIVE.md
Navigation:        DOCUMENTATION_INDEX.md (this file)
```

---

## Document Sizes & Reading Times

| Document | Size | Read Time | Audience |
|----------|------|-----------|----------|
| BEGINNER_GUIDE.md | ~8 KB | 5-10 min | New users, anyone learning the system ⭐ |
| QUICK_START.md | ~6 KB | 10-15 min | Users, anyone trying the system |
| IMPLEMENTATION_SUMMARY.md | ~12 KB | 15-20 min | Developers, architects |
| DEPLOYMENT_GUIDE.md | ~15 KB | 20-30 min | DevOps, QA testers |
| TECHNICAL_DEEP_DIVE.md | ~16 KB | 25-40 min | Team for presentations, technical reviewers |
| DOCUMENTATION_INDEX.md | ~8 KB | 5-10 min | Navigation & overview |

**Total:** ~65 KB of documentation, ~85-125 min total reading  
**Recommended:** Start with BEGINNER_GUIDE, then read others as needed

---

**Thank you for using SIH26099 Material Master Framework! 🚀**
