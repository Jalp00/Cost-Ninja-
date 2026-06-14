# Cost Ninja V3 - On-Premise AI Quote Pilot

Cost Ninja V3 is an advanced, fully air-gapped AI assistant that specializes in analyzing mechanical engineering drawings and performing intelligent quote comparisons. Built specifically for strict regulatory environments (AS9100 RevD), it utilizes local Large Language Models (LLMs) via LM Studio to guarantee 100% data sovereignty.

✨ Features

🎯 Drawing Analysis
* **Local AI-Powered Analysis:** Advanced technical drawing interpretation running entirely on-premise without cloud APIs.
* **Deterministic Cost Estimation:** A hard-coded rules engine that calculates precise material costs, labor, and manufacturing setups to eliminate AI hallucinations.
* **Multi-format Support:** Ingests PDF and image files (PNG, JPG, JPEG) using multi-pass OCR fallbacks.
* **Live Prompt Editor:** Real-time customization of AI analysis parameters.
* **Precision Levels:** Multiple analysis depth options from Basic to Ultra-Precision.

💰 Enhanced Quote Comparison
* **Advanced OCR:** Enhanced text extraction with OpenCV preprocessing to capture scattered PDF data.
* **Fuzzy Matching:** Utilizes RapidFuzz, Jellyfish, and Levenshtein algorithms for highly intelligent part number matching.
* **Historical Data Analysis:** Compares supplier quotes directly against internal historical pricing (Excel/ERP exports).
* **Savings Identification:** Automated cost-saving opportunity detection.
* **Professional Reports:** Generates negotiation emails and detailed Excel analysis reports.

🎨 Modern Interface
* **NVIDIA-Inspired Design:** Futuristic dark theme built on CustomTkinter with distinct accent colors.
* **Asynchronous Processing:** Threaded architecture ensures the UI remains responsive during heavy local AI inference.
* **Real-time Feedback:** Live status updates and LLM streaming progress indicators.

🚀 Quick Start

**Prerequisites**
* Python 3.10 or higher
* **LM Studio** installed locally with at least one Vision/Text model loaded (e.g., Qwen-VL, LLaVA, or Gemma).
* Dedicated GPU (e.g., NVIDIA RTX 3050 Ti or higher recommended).
* (Optional) Tesseract OCR installed on the host machine for enhanced quote extraction.

**Installation**
 1. Clone the repository
    git clone https://github.com/Jalp00/Cost-Ninja-V3.git
    cd Cost-Ninja-V3


2.Create a virtual environment
Bash
python -m venv venv
# Windows
venv\Scripts\activate

3.Install dependencies
Bash
pip install -r requirements.txt

4.Run the application

Bash
# Ensure LM Studio is running its local server on port 1234
python main.py


📖 Usage Guide

Drawing Analysis

Load Drawing: Click "Load Drawing" to select a technical PDF or image.

Set Parameters: Adjust batch quantity, select precision level, and add live prompt overrides if needed.

Analyze: Click "⚡ Analyze & Estimate" to start local AI analysis.

Review Results: View the deterministic cost breakdown alongside the AI's geometric feature extraction.

Export: Export the final calculations to TXT or Excel.

Quote Comparison

Open Tool: Click "Quote Comparison" in the header.

Load Data: Import the supplier quote PDF and your historical orders Excel file.

Run Analysis: Click "Advanced Analysis" to initiate fuzzy matching.

Review Savings: Examine identified cost-saving opportunities and review confidence scores.

Generate Email: Copy the auto-generated negotiation email to send to suppliers.

🔧 Configuration

The application uses config.json for all operational customization:

 JSON
{
  "labor_rate_per_hour": 800.0,
  "overhead_percentage": 25.0,
  "profit_margin_percentage": 20.0,
  "material_data": {
    "AL 6061": { "price_per_kg": 400.0, "density_g_cm3": 2.7, "equivalents": ["AL6061"] }
  },
  "quantity_discount": {
    "100": 15.0
  },
  "lm_studio": {
    "base_url": "http://localhost:1234/v1"
  }
}
Key Configuration Options:

Labor rates: Customize hourly manufacturing costs per machine process.

Material database: Extensive material pricing, density data, and equivalent aliases.

Machinability modifiers: Multipliers adjusting time based on material hardness (e.g., Inconel vs. Aluminum).

LM Studio Connection: Point the application to your specific local server port.

🛠 Enhanced Features Setup

For optimal quote comparison performance, ensure Tesseract is installed on the host OS:

Bash
# Windows: Download from [https://github.com/UB-Mannheim/tesseract/wiki](https://github.com/UB-Mannheim/tesseract/wiki)
# Add Tesseract to your System PATH variables.
🏗 Project Structure

Plaintext
Cost-Ninja-V3/
├── main.py                # Main GUI application & async orchestrator
├── config_helpers.py      # Deterministic math & configuration loading
├── lm_studio_client.py    # Local AI bridge & vision preprocessing
├── quote_comparison.py    # OCR and fuzzy matching engine
├── ui_widgets.py          # CustomTkinter theme and styling definitions
├── api_test.py            # Diagnostic script for LM Studio connectivity
├── config.json            # Core operational database
├── requirements.txt       # Python dependencies
└── README.md              # This file
📝 License
Proprietary Internal Software. All rights reserved.

🙏 Acknowledgments

LM Studio: Providing the local OpenAI-compatible inference server for air-gapped security.

CustomTkinter: Modern Python GUI framework.

PyMuPDF (fitz): Robust PDF processing and rasterization.

OpenCV & Tesseract: Enhanced OCR functionality for scattered technical annotations.

RapidFuzz & Jellyfish: Industry-leading string matching algorithms.
