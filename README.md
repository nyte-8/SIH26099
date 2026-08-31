# Hackathon Project: AI-powered Unified Material Master Framework

## 🎯 Project Goal

To develop an **AI-powered National Unified Material Master Framework** using NLP/ML to analyze material data across multiple CPSEs, identify duplicates, standardize descriptions, and generate Common National Material Codes. The ultimate goal is to achieve 'One Nation – One Material Code' while maintaining traceability.

## 🛠️ System Architecture

This project is structured around a Python-based backend that orchestrates the AI processing and database persistence, connected to a simple web frontend for user interaction.

**Core Components:**
1.  **Data Source (`dataset.csv`):** Raw material data from various CPSEs (Person D).
2.  **AI Engine (`gemma_helper.py`):** The core module that interfaces with the local Gemma model to perform semantic matching and standardization (Person E).
3.  **Database Layer (`database.py`):** SQLite database for persisting standardized material master data (Person B).
4.  **Orchestrator (`main.py`):** The script that controls the entire workflow: loads data, calls the AI, and saves results.
5.  **Matching Logic (`matching.py`):** The script responsible for reading CSV, calling the AI, and handling persistence (Person A).
6.  **Frontend (`static/` folder):** A simple web interface for users to input material data and trigger the process (Person C).

## ⚙️ Setup Instructions

### Prerequisites
*   Python 3.x installed.
*   (Optional but recommended) [LM Studio](https://lmstudio.ai) with a model loaded and its local server started (Developer tab > "Start Server", default `http://localhost:1234`). If LM Studio isn't running, the app still works — it falls back to a deterministic offline standardization heuristic instead of a real AI call.

### Setup Steps
1.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```
2.  **Run the web app** (this starts the Flask server, initializes the DB automatically, and serves the frontend):
    ```bash
    python app.py
    ```
    Then open **http://127.0.0.1:5000** in your browser.
3.  **(Alternative) Batch mode:** to process `dataset.csv` in one shot from the command line instead of using the web form:
    ```bash
    python main.py
    ```
    *Note: the first run of either creates `material_master.db`.*

If your LM Studio server runs on a different host/port, or you want to pin a specific model name, set env vars before running:
```bash
set LM_STUDIO_HOST=http://localhost:1234
set LM_STUDIO_MODEL=your-model-name
```

## 🧑‍💻 Team Roles & Workflow

| Role | File(s) | Responsibility |
| :--- | :--- | :--- |
| **Person D** | `dataset.csv` | Providing the raw material data. |
| **Person E** | `gemma_helper.py` | Defining and executing the core AI prompt/logic for matching and standardization. |
| **Person B** | `database.py`, `main.py` | Handling database persistence and orchestrating the full pipeline. |
| **Person A** | `matching.py` | Implementing the data processing logic that links AI output to DB storage. |
| **Person C** | `static/index.html`, `.css`, `.js` | Building the user interface for data input and result display. |
| **Person F** | `README.md` | Documenting the entire project structure and workflow. |

## 💡 Integration Layer / Pitch Note

The ERP-facing export endpoint is the integration layer for downstream systems: `/api/v1/materials/export`.
This is the API contract used to hand off harmonized material data to ERP or SAP-style downstream processes.

## 💡 Next Steps (Hackathon Focus)

1.  **Refine Prompts:** Iterate on the prompt within `gemma_helper.py` to ensure reliable, standardized output from the model for all material types.
2.  **Error Handling:** Strengthen error handling in `matching.py` and `main.py` to manage potential AI failures gracefully.
3.  **Integration Testing:** Focus on ensuring that the data saved in the database is logically consistent with the AI's output.