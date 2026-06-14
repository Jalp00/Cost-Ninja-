# Cost Ninja - AI Quote Pilot V3

Local-first manufacturing quote assistant powered by **LM Studio**. Analyzes engineering drawings for cost estimates and compares supplier quotes against historical data.

## Requirements

- Python 3.10+
- [LM Studio](https://lmstudio.ai/) with any loaded model (Gemma, Qwen, LLaVA, etc.)
- Optional: [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki) for text-only models

## Setup (Windows)

```powershell
cd "C:\Users\your name\Desktop\your file"
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
```

### LM Studio

1. Open LM Studio and load **any** GGUF model
2. Go to **Developer** tab → **Start server** (default port `1234`)
3. The app auto-detects loaded models; optional hints in `config.json` → `lm_studio`

### Smoke test

```powershell
python api_test.py
```

### Run the app

```powershell
python main.py
```

Or use the legacy entry point: `python maiin.py`

## Features

- **Drawing analysis** — load PDF/image, stream AI cost estimate from local LLM
- **Quote comparison** — OCR + fuzzy match supplier quotes vs Excel history
- **Status bar** — LM Studio connection, active model, OCR mode
- **Settings** — test connection, change base URL
- **Export** — TXT or structured JSON reports

## Configuration

Edit [config.json](config.json):

- `labor_rate_per_hour`, material prices, machining rules
- `lm_studio.base_url` — default `http://localhost:1234/v1`
- `lm_studio.text_model` / `vision_model` — leave empty for auto-detect

## Project structure

| File | Purpose |
|------|---------|
| `main.py` | Application entry point |
| `lm_studio_client.py` | LM Studio API client |
| `config_helpers.py` | Config loading and cost logic |
| `quote_comparison.py` | OCR and fuzzy matching |
| `ui_widgets.py` | CustomTkinter theme widgets |
| `api_test.py` | LM Studio connectivity test |
