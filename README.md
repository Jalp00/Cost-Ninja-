# Cost Ninja - AI Quote Pilot V3

## Executive Summary
Cost Ninja V3 is a proprietary, on-premise project control and estimation tool designed specifically for manufacturing operations. Built to operate in highly regulated environments requiring strict data sovereignty, the system processes technical engineering drawings to generate accurate manufacturing cost estimates. It operates entirely off-grid utilizing local hardware, ensuring zero data leakage of proprietary intellectual property.

## Core Capabilities
* **AI-Powered Drawing Analysis:** Extracts Title Block data, tolerances, surface finishes, and feature inventories directly from PDF or image-based engineering drawings.
* **Deterministic Cost Grounding:** Cross-verifies AI extractions against a hard-coded, rule-based estimation engine to calculate precise labor, material, and setup costs.
* **Automated Quote Comparison:** Ingests supplier quote PDFs, utilizes OCR and fuzzy-matching, and compares quoted prices against historical purchase order data to identify savings opportunities.
* **Air-Gapped Execution:** Integrates directly with LM Studio to run vision and text Large Language Models (LLMs) locally.

## System Architecture & Modules
* `main.py`: The application entry point and asynchronous GUI orchestrator.
* `lm_studio_client.py`: The integration layer for local LLM processing. Features auto-model detection and multi-pass OCR fallbacks.
* `config_helpers.py`: The deterministic calculation engine. Handles routing, raw material volume math, and complexity tiering.
* `quote_comparison.py`: Procurement analysis module utilizing Levenshtein distance and Jaro-Winkler algorithms to match unstructured quote data to internal ERP/Excel history.
* `config.json`: The central database for machine capacities, hourly labor rates, material densities, and markup percentages.

## Hardware & Deployment Requirements
Optimized for local workstation hardware with dedicated VRAM (e.g., NVIDIA RTX 3050 Ti or higher) to ensure complete local processing. 

### Installation
1. Ensure Python 3.10+ is installed.
2. Clone the repository to the local workstation.
3. Initialize the virtual environment and install dependencies:
   ```powershell
   python -m venv venv
   .\venv\Scripts\activate
   pip install -r requirements.txt
   
4.Configure LM Studio: Load the required models, navigate to the Developer tab, and start the local server.
5.Launch the application: python main.py
