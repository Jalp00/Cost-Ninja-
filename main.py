"""Cost Ninja - AI Quote Pilot V3 (local LM Studio)."""

import json
import os
import queue
import re
import sys
import threading
import traceback
from datetime import datetime

import customtkinter as ctk
import fitz
import pandas as pd
import pytesseract
from PIL import Image, ImageEnhance, ImageFilter
from tkinter import filedialog, messagebox

from config_helpers import (
    build_cost_context,
    estimate_cost_deterministic,
    extract_cost_info_from_response,
    extract_part_info_from_response,
    get_precision_tier,
    get_quantity_discount_percent,
    load_configuration,
)
from lm_studio_client import LMStudioClient
from quote_comparison import ENHANCED_MATCHING, QuoteComparisonFix
from ui_widgets import (
    IMAGE_DISPLAY_MAX_HEIGHT,
    IMAGE_DISPLAY_MAX_WIDTH,
    THEME_COLORS,
    NvidiaButton,
    NvidiaEntry,
    NvidiaFrame,
    NvidiaLabel,
    NvidiaTextbox,
)

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

LOCAL_SYSTEM_PROMPT = """
You are an expert AI assistant specializing in mechanical engineering drawing analysis and manufacturing cost estimation.

CRITICAL READING INSTRUCTIONS:
1. TITLE BLOCK: Read the title block FIRST. Extract part name, part number, drawing number, material specification, surface finish, and revision.
2. DIMENSIONS: Read EVERY dimension annotation carefully. Pay close attention to small text. Use the OCR text provided to cross-check any numbers you are unsure about.
3. TOLERANCES: Look for geometric dimensioning & tolerancing (GD&T) symbols, plus/minus tolerances, and general tolerance notes.
4. HOLES & THREADS: Count ALL holes. Identify thread callouts (e.g., M6x1.0, 1/4-20 UNC). Differentiate between through-holes and blind holes.
5. SURFACE FINISH: Look for surface roughness symbols (Ra values, N-grades like N7, N6) on any surface.
6. NOTES & SPECIFICATIONS: Read ALL notes on the drawing — they often contain critical info about heat treatment, plating, anodizing, or special processes.
7. CROSS-SECTIONS & DETAIL VIEWS: If multiple views are shown, use them to understand the 3D geometry of the part.

Show ALL calculations step-by-step with drilling time, setup time, material weight, and cost formulas.
Use the predefined rules and material data provided in the user message.

Output sections:
* TITLE BLOCK INFORMATION (part name, number, material, revision, date)
* OVERALL DIMENSIONS (length x width x height in mm, raw stock size needed)
* FEATURE INVENTORY (list every hole, thread, pocket, slot, chamfer, fillet with dimensions)
* KEY MANUFACTURING PROCESSES (turning, milling, drilling, threading, finishing)
* TOLERANCE & SURFACE FINISH ANALYSIS (identify tight tolerances and fine finishes)
* DETAILED TIME ESTIMATION (Per Unit) — itemize each operation
* DETAILED COST CALCULATION (Per Unit) — material + labor + surcharges
* FINAL PER-UNIT ESTIMATED COST: ₹[amount]
* Notes and Limitations

Also include a JSON block on its own line:
{"part_name":"","part_number":"","material":"","final_cost_per_unit":0.0}
"""

QUOTE_LLM_PROMPT = """
Extract ALL items from this supplier quote table with EXACT quantities and prices.
Format each item as:
Part: [PART_NUMBER] | Qty: [ACTUAL_QUANTITY] | Price: [UNIT_PRICE] | Desc: [DESCRIPTION]
"""


class App(ctk.CTk):
    def __init__(self, config, lm_client: LMStudioClient):
        super().__init__()
        self.config = config
        self.lm_client = lm_client
        self.local_llm_available = lm_client.available
        self.last_analysis_result = None
        self.tesseract_ok = self._check_tesseract()

        # Load system prompt and token limit into the client so they're always ready
        self.lm_client.default_system_prompt = LOCAL_SYSTEM_PROMPT
        self.lm_client.default_max_tokens = 20480

        self.title("Cost Ninja — AI Quote Pilot V3")
        self.geometry("1600x1020")
        ctk.set_appearance_mode("dark")
        self.configure(fg_color=THEME_COLORS["bg_dark"])

        self.image_paths_for_analysis = []
        self.loaded_pil_images_for_chat = []
        self.analysis_queue = queue.Queue()
        self.displayed_ctk_image = None
        self.quote_images = []
        self.historical_orders_df = None
        self.quote_fixer = QuoteComparisonFix()
        self._streaming = False

        self.setup_ui()
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.update_status_bar()
        self.update_output_textbox(
            "Welcome to Cost Ninja — AI Quote Personal Assistant\n\n"
            "Load a technical drawing (PDF, PNG, JPG) to begin cost analysis.\n"
            "Connect to LM Studio for AI-powered estimation.",
            clear_first=True,
        )

    def _check_tesseract(self):
        try:
            pytesseract.image_to_string(Image.new("RGB", (50, 50), "white"))
            return True
        except Exception:
            return False

    def setup_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # ── Header Bar ──────────────────────────────────────────────────
        self.header_frame = NvidiaFrame(self, style="header")
        self.header_frame.grid(row=0, column=0, padx=0, pady=0, sticky="ew")

        NvidiaLabel(
            self.header_frame,
            text="Cost Ninja — AI Quote Personal Assistant",
            style="title",
        ).pack(side="left", padx=24, pady=14)

        # Status indicators — right side
        self.connection_label = NvidiaLabel(self.header_frame, text="● Checking...", style="accent")
        self.connection_label.pack(side="right", padx=12)

        self.model_label = NvidiaLabel(self.header_frame, text="Model: —", style="primary")
        self.model_label.pack(side="right", padx=8)

        NvidiaButton(
            self.header_frame, text="Settings", style="secondary",
            command=self.open_settings_panel, width=90, height=34,
        ).pack(side="right", padx=4, pady=8)

        NvidiaButton(
            self.header_frame, text="Refresh LM", style="secondary",
            command=self.refresh_lm_studio_action, width=100, height=34,
        ).pack(side="right", padx=4, pady=8)

        NvidiaButton(
            self.header_frame, text="Load Drawing", style="primary",
            command=self.select_drawing_file_action, width=150, height=38,
        ).pack(side="right", padx=8, pady=8)

        NvidiaButton(
            self.header_frame, text="Quote Comparison", style="accent",
            command=self.open_quote_comparison_window, width=170, height=38,
        ).pack(side="right", padx=4, pady=8)

        self.selected_file_label = NvidiaLabel(self.header_frame, text="No drawing loaded")
        self.selected_file_label.pack(side="right", padx=12)

        # ── Accent line under header ────────────────────────────────────
        accent_line = ctk.CTkFrame(self, height=2, fg_color=THEME_COLORS["primary"])
        accent_line.grid(row=0, column=0, sticky="sew", padx=0)

        # ── Main Content Container ───────────────────────────────────────
        self.main_container = ctk.CTkFrame(self, fg_color="transparent")
        self.main_container.grid(row=1, column=0, padx=12, pady=(8, 4), sticky="nsew")
        self.main_container.grid_rowconfigure(0, weight=1)
        self.main_container.grid_rowconfigure(1, weight=1)
        self.main_container.grid_columnconfigure(0, weight=2)
        self.main_container.grid_columnconfigure(1, weight=1)

        # ── Drawing Viewer Panel ────────────────────────────────────────
        self.drawing_panel = NvidiaFrame(self.main_container)
        self.drawing_panel.grid(row=0, column=0, padx=4, pady=4, sticky="nsew")
        self.drawing_panel.grid_rowconfigure(1, weight=1)
        self.drawing_panel.grid_columnconfigure(0, weight=1)
        NvidiaLabel(self.drawing_panel, text="▸ TECHNICAL DRAWING VIEWER", style="section").grid(
            row=0, column=0, sticky="w", padx=16, pady=(12, 4),
        )
        self.image_display_label = ctk.CTkLabel(
            self.drawing_panel, text="Load a drawing to begin",
            text_color=THEME_COLORS["text_muted"],
            fg_color="transparent",
            font=("Segoe UI", 13),
        )
        self.image_display_label.grid(row=1, column=0, sticky="nsew")

        # ── Analysis Output Panel ───────────────────────────────────────
        self.output_panel = NvidiaFrame(self.main_container)
        self.output_panel.grid(row=1, column=0, padx=4, pady=4, sticky="nsew")
        self.output_panel.grid_rowconfigure(1, weight=1)
        self.output_panel.grid_columnconfigure(0, weight=1)
        hdr = ctk.CTkFrame(self.output_panel, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 6))
        hdr.grid_columnconfigure(0, weight=1)
        NvidiaLabel(hdr, text="▸ ANALYSIS OUTPUT", style="section").grid(row=0, column=0, sticky="w")
        self.mini_copy_button = NvidiaButton(
            hdr, text="Copy", style="secondary", command=self.copy_output_to_clipboard_action, width=65, height=28,
        )
        self.mini_copy_button.grid(row=0, column=1, sticky="e")
        self.output_textbox = NvidiaTextbox(self.output_panel, wrap="word", state="disabled", font=("Consolas", 12))
        self.output_textbox.grid(row=1, column=0, padx=16, pady=(0, 12), sticky="nsew")

        # ── Control Panel (Right Sidebar) ──────────────────────────────
        self.control_panel = NvidiaFrame(self.main_container)
        self.control_panel.grid(row=0, column=1, rowspan=2, padx=4, pady=4, sticky="nsew")
        self.control_panel.grid_rowconfigure(3, weight=1)
        self.control_panel.grid_columnconfigure(0, weight=1)
        NvidiaLabel(self.control_panel, text="▸ ANALYSIS CONTROL CENTER", style="section").grid(
            row=0, column=0, sticky="w", padx=16, pady=(14, 10),
        )

        params = NvidiaFrame(self.control_panel)
        params.grid(row=1, column=0, padx=12, pady=(0, 8), sticky="ew")
        NvidiaLabel(params, text="Batch Quantity", style="accent").pack(anchor="w", padx=16, pady=(14, 4))
        self.batch_quantity_entry = NvidiaEntry(params, height=36)
        self.batch_quantity_entry.pack(fill="x", padx=16, pady=(0, 10))
        self.batch_quantity_entry.insert(0, "1")
        NvidiaLabel(params, text="Precision Level", style="accent").pack(anchor="w", padx=16, pady=(4, 4))
        self.precision_var = ctk.StringVar(value="Maximum")
        ctk.CTkOptionMenu(
            params, values=["Basic", "Medium", "High", "Maximum", "Ultra-Precision"],
            variable=self.precision_var, height=36,
            fg_color=THEME_COLORS["bg_dark"],
            button_color=THEME_COLORS["primary"],
            button_hover_color=THEME_COLORS["primary_hover"],
            text_color=THEME_COLORS["text_primary"],
            font=("Segoe UI", 12),
            dropdown_fg_color=THEME_COLORS["bg_medium"],
            dropdown_hover_color=THEME_COLORS["surface"],
            dropdown_text_color=THEME_COLORS["text_primary"],
            corner_radius=8,
        ).pack(fill="x", padx=16, pady=(0, 14))

        NvidiaLabel(self.control_panel, text="▸ LIVE PROMPT EDITOR", style="section").grid(
            row=2, column=0, sticky="w", padx=16, pady=(8, 4),
        )
        self.prompt_override_textbox = NvidiaTextbox(self.control_panel, wrap="word", height=150, font=("Consolas", 11))
        self.prompt_override_textbox.grid(row=3, column=0, padx=12, pady=(0, 10), sticky="nsew")
        self.prompt_override_textbox.insert("0.0", "# Optional overrides, e.g. material or tolerance notes\n")

        actions = ctk.CTkFrame(self.control_panel, fg_color="transparent")
        actions.grid(row=4, column=0, sticky="ew", padx=12, pady=(0, 14))
        actions.grid_columnconfigure(0, weight=1)
        actions.grid_columnconfigure(1, weight=1)
        actions.grid_columnconfigure(2, weight=1)
        self.analyze_button = NvidiaButton(
            actions, text="⚡ Analyze & Estimate", style="primary",
            command=self.analyze_drawing_action, state="disabled", height=48,
        )
        self.analyze_button.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 10))
        NvidiaButton(actions, text="Copy Full", style="accent", command=self.copy_output_to_clipboard_action, height=34).grid(
            row=1, column=0, sticky="ew", padx=(0, 4),
        )
        NvidiaButton(actions, text="Export TXT/JSON", style="secondary", command=self.export_report_action, height=34).grid(
            row=1, column=1, sticky="ew", padx=(4, 4),
        )
        NvidiaButton(actions, text="Export Excel", style="success", command=self.export_excel_action, height=34).grid(
            row=1, column=2, sticky="ew", padx=(4, 0),
        )

        # ── Status Bar ──────────────────────────────────────────────────
        status_accent = ctk.CTkFrame(self, height=1, fg_color=THEME_COLORS["border_default"])
        status_accent.grid(row=2, column=0, sticky="ew", padx=0)
        self.status_bar = NvidiaFrame(self, style="status")
        self.status_bar.grid(row=3, column=0, padx=0, pady=0, sticky="ew")
        self.status_label = NvidiaLabel(self.status_bar, text="Status", style="primary")
        self.status_label.pack(side="left", padx=16, pady=8)

    def update_status_bar(self):
        st = self.lm_client.status_dict()
        connected = st["connected"]
        model = st["text_model"] or "none"
        mode = st["mode"]
        tess = "OK" if self.tesseract_ok else "Missing"
        tokens = self.lm_client.default_max_tokens
        prompt_loaded = "✓" if self.lm_client.default_system_prompt else "✗"
        model_ok = "✓" if self.lm_client.required_model_confirmed else "✗"
        dot_char = "●" if connected else "○"
        dot_label = "Connected" if connected else "Disconnected"
        self.connection_label.configure(
            text=f"{dot_char} LM Studio: {dot_label}",
            text_color=THEME_COLORS["success"] if connected else THEME_COLORS["error"],
        )
        self.model_label.configure(text=f"Model: {model[:40]}  {model_ok}")
        self.status_label.configure(
            text=(
                f"{dot_char} LM Studio: {dot_label}  ·  Model: {model} {model_ok}  ·  "
                f"Mode: {mode}  ·  Tokens: {tokens:,}  ·  Prompt: {prompt_loaded}  ·  Tesseract: {tess}"
            )
        )
        self.local_llm_available = connected

    def refresh_lm_studio_action(self):
        self.lm_client.refresh()
        self.update_status_bar()
        st = self.lm_client.status_dict()
        model_status = st.get("model_load_message", "N/A")
        messagebox.showinfo(
            "LM Studio",
            f"Connected: {st['connected']}\n"
            f"Text model: {st['text_model']}\n"
            f"Vision model: {st['vision_model']}\n"
            f"Mode: {st['mode']}\n"
            f"Tokens: {self.lm_client.default_max_tokens:,}\n"
            f"System Prompt: {'Loaded' if self.lm_client.default_system_prompt else 'Not Loaded'}\n"
            f"\nModel Status: {model_status}",
        )

    def open_settings_panel(self):
        win = ctk.CTkToplevel(self)
        win.title("Settings — LM Studio")
        win.geometry("560x480")
        win.configure(fg_color=THEME_COLORS["bg_dark"])
        win.transient(self)
        win.grab_set()
        frame = NvidiaFrame(win)
        frame.pack(fill="both", expand=True, padx=16, pady=16)
        NvidiaLabel(frame, text="▸ LM Studio Configuration", style="section").pack(anchor="w", padx=20, pady=(16, 16))
        NvidiaLabel(frame, text="Base URL", style="accent").pack(anchor="w", padx=20)
        url_entry = NvidiaEntry(frame, width=440, height=36)
        url_entry.pack(padx=20, pady=(4, 16), fill="x")
        url_entry.insert(0, self.lm_client.base_url)

        # ── Status Info Section ──────────────────────────────────────────
        info_frame = ctk.CTkFrame(frame, fg_color=THEME_COLORS["bg_dark"], corner_radius=10)
        info_frame.pack(fill="x", padx=20, pady=(0, 12))

        tokens = self.lm_client.default_max_tokens
        prompt_loaded = "Loaded ✓" if self.lm_client.default_system_prompt else "Not Loaded ✗"
        prompt_len = len(self.lm_client.default_system_prompt) if self.lm_client.default_system_prompt else 0

        NvidiaLabel(info_frame, text="▸ Active Configuration", style="section").pack(anchor="w", padx=12, pady=(10, 6))
        NvidiaLabel(
            info_frame,
            text=f"  Max Tokens:       {tokens:,}",
            style="primary",
        ).pack(anchor="w", padx=12, pady=2)
        NvidiaLabel(
            info_frame,
            text=f"  System Prompt:    {prompt_loaded}  ({prompt_len} chars)",
            style="primary",
        ).pack(anchor="w", padx=12, pady=2)
        NvidiaLabel(
            info_frame,
            text=f"  Image Encoding:   PNG (Lossless)",
            style="primary",
        ).pack(anchor="w", padx=12, pady=2)
        NvidiaLabel(
            info_frame,
            text=f"  Vision+OCR Mode:  Hybrid (Image + OCR text)",
            style="primary",
        ).pack(anchor="w", padx=12, pady=(2, 10))

        def test_connection():
            self.lm_client.base_url = url_entry.get().strip()
            self.lm_client._connect()
            self.update_status_bar()
            try:
                reply = self.lm_client.test_chat()
                messagebox.showinfo("Test OK", f"Model replied:\n{reply[:200]}")
            except Exception as exc:
                messagebox.showerror("Test Failed", str(exc))

        def save_url():
            self.lm_client.base_url = url_entry.get().strip()
            self.config.setdefault("lm_studio", {})["base_url"] = self.lm_client.base_url
            self.lm_client.refresh()
            self.update_status_bar()
            win.destroy()

        btn_row = ctk.CTkFrame(frame, fg_color="transparent")
        btn_row.pack(pady=16)
        NvidiaButton(btn_row, text="Test Connection", style="accent", command=test_connection, width=150, height=38).pack(side="left", padx=8)
        NvidiaButton(btn_row, text="Save & Close", style="primary", command=save_url, width=130, height=38).pack(side="left", padx=8)

    def append_stream_token(self, token):
        if not self._streaming:
            return
        self.output_textbox.configure(state="normal")
        self.output_textbox.insert("end", token)
        self.output_textbox.see("end")
        self.output_textbox.configure(state="disabled")

    def enable_stream_output(self):
        self._streaming = True
        self.output_textbox.configure(state="normal")
        self.output_textbox.delete("1.0", "end")
        self.output_textbox.configure(state="disabled")

    def analyze_drawing_action(self):
        if not self.image_paths_for_analysis:
            self.update_output_textbox("ERROR: No drawing loaded.", clear_first=True)
            return
        if not self.local_llm_available:
            self.update_output_textbox(
                "ERROR: LM Studio is not available.\n"
                "Open LM Studio, load any model, Developer -> Start server.\n"
                f"Default URL: {self.lm_client.base_url}",
                clear_first=True,
            )
            return
        self.analyze_button.configure(state="disabled", text="⏳ Analyzing...")
        try:
            batch_quantity = max(1, int(self.batch_quantity_entry.get()))
        except ValueError:
            batch_quantity = 1
        prompt_overrides = self.prompt_override_textbox.get("0.0", "end-1c").strip()
        precision_level = self.precision_var.get()
        
        names = ", ".join(os.path.basename(p) for p in self.image_paths_for_analysis)
        self.enable_stream_output()
        self.update_output_textbox(
            f"INITIATING ANALYSIS\n{'='*50}\nFiles: {names}\nPrecision: {precision_level}\nQty: {batch_quantity}\n"
            f"Step 1/4: Connecting to LM Studio...\nStep 2/4: Sending drawing...\nStep 3/4: Generating (streaming)...\n",
            clear_first=True,
        )
        # Pass the raw images to the thread to keep the UI buttery smooth
        raw_images = list(self.loaded_pil_images_for_chat)
        threading.Thread(
            target=self.run_analysis_in_thread,
            args=(raw_images, prompt_overrides, batch_quantity, precision_level, getattr(self, 'pdf_native_text', "")),
            daemon=True,
        ).start()
        self.after(100, self.check_analysis_result)

    def run_analysis_in_thread(self, raw_images, prompt_overrides, batch_qty, precision_level, pdf_native_text=""):
        try:
            # 1. Do the heavy image preprocessing here in the background thread
            processed = [self.preprocess_image_for_analysis(img) for img in raw_images]
            
            # Auto-crop title block from the first page (bottom right corner)
            extra_images = []
            if processed:
                first_img = processed[0]
                w, h = first_img.size
                crop_w, crop_h = int(w * 0.35), int(h * 0.25)
                title_block = first_img.crop((w - crop_w, h - crop_h, w, h))
                extra_images.append(title_block)

            # 2. Build cost context
            cost_context = build_cost_context(self.config, batch_qty, precision_level)
            user_text = cost_context
            if prompt_overrides:
                user_text += f"\n--- User Supplementary Information ---\n{prompt_overrides}"

            tokens = []

            def on_token(t):
                tokens.append(t)
                self.after(0, lambda tok=t: self.append_stream_token(tok))

            # 3. Call the LM
            ai_response = self.lm_client.chat_completion(
                LOCAL_SYSTEM_PROMPT, user_text, processed,
                temperature=0.0, max_tokens=20480, on_token=on_token,
                pdf_native_text=pdf_native_text, extra_images=extra_images
            )
            self._streaming = False
            if "Error:" in ai_response or not ai_response.strip():
                self.analysis_queue.put({"error": ai_response or "Empty response from LM Studio"})
                return
            result = self.create_enhanced_report(ai_response, batch_qty, prompt_overrides, precision_level)
            self.analysis_queue.put(result)
        except Exception:
            self._streaming = False
            self.analysis_queue.put({"error": traceback.format_exc()})

    def create_enhanced_report(self, ai_response_text, batch_qty, live_overrides, precision_level):
        part_info = extract_part_info_from_response(ai_response_text)
        cost_info = extract_cost_info_from_response(ai_response_text)
        base_cost = cost_info.get("base_cost", 0.0)
        ai_extracted = cost_info.get("extracted", False)

        tier = get_precision_tier(precision_level)
        det = estimate_cost_deterministic(self.config, {
            "batch_qty": batch_qty,
            "complexity_tier": tier,
            "material": part_info.get("material", "ALUMINUM"),
            "tight_tolerance": precision_level in ("High", "Maximum", "Ultra-Precision"),
            "finish_n7": precision_level == "Maximum",
            "finish_n6": precision_level == "Ultra-Precision",
        })

        if not ai_extracted:
            base_cost = det.get("estimated_cost_per_unit", 50.0)

        discount_percent = get_quantity_discount_percent(self.config, batch_qty)
        overhead_percent = float(self.config.get("overhead_percentage", 25.0))
        profit_percent = float(self.config.get("profit_margin_percentage", 20.0))

        if discount_percent > 0:
            discount_amount = base_cost * (discount_percent / 100)
            cost_after_discount = base_cost - discount_amount
        else:
            discount_amount = 0.0
            cost_after_discount = base_cost

        cost_with_overhead = cost_after_discount * (1 + overhead_percent / 100)
        final_selling_price = cost_with_overhead * (1 + profit_percent / 100)

        name_val = part_info.get("name", "N/A")
        number_val = part_info.get("number", "N/A")
        material_val = part_info.get("material", "N/A")

        def is_uncertain(val):
            return not val or val.strip().upper() in ("N/A", "UNKNOWN", "NONE", "NOT FOUND", "", "N / A")

        uncertainties = []
        if is_uncertain(name_val):
            uncertainties.append("Part Name")
        if is_uncertain(number_val):
            uncertainties.append("Part Number")
        if is_uncertain(material_val):
            uncertainties.append("Material")
        if not ai_extracted:
            uncertainties.append("Estimated Cost")

        report = f"""COST NINJA V3 - COMPREHENSIVE ANALYSIS REPORT
{'='*70}
Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
Batch Quantity: {batch_qty} | Precision: {precision_level}
Model: {self.lm_client.active_text_model} | Mode: {self.lm_client.status_dict()['mode']}
"""
        if uncertainties:
            report += f"\n[!] WARNING: UNCERTAIN/MISSING EXTRACTION\n"
            report += f"The following fields could not be confidently extracted and use fallbacks:\n"
            for u in uncertainties:
                report += f"  - {u}\n"
            report += f"Please verify drawing details manually.\n"

        report += f"""
ORIGINAL AI ANALYSIS
------------------------------
{ai_response_text}

{'='*70}
ENHANCED BUSINESS ANALYSIS
Part: {part_info.get('name', 'N/A')} | Number: {part_info.get('number', 'N/A')}
Material: {part_info.get('material', 'N/A')}
"""
        if ai_extracted:
            report += f"AI Base Cost per Unit: ₹{base_cost:.2f}\n"
        else:
            report += f"AI Base Cost per Unit: [FAILURE] (Could not extract cost from AI response. Falling back to Rule-Based Estimate: ₹{base_cost:.2f})\n"

        report += f"""
DETERMINISTIC RULE-BASED CHECK (tier={tier})
Labor: ₹{det['labor_cost']:.2f} | Material: ₹{det['material_cost']:.2f}
Weight: {det['weight_kg']:.4f} kg | Minutes: {det['total_minutes']:.1f}
Rule Estimate: ₹{det['estimated_cost_per_unit']:.2f}
"""
        if discount_percent > 0:
            report += f"Quantity Discount ({discount_percent}%): -₹{discount_amount:.2f}\nCost after Discount: ₹{cost_after_discount:.2f}\n"
        report += f"""
+ Overhead ({overhead_percent}%): ₹{cost_with_overhead:.2f}
+ Profit ({profit_percent}%): ₹{final_selling_price:.2f}

RECOMMENDED SELLING PRICE: ₹{final_selling_price:.2f}
Total for {batch_qty} units: ₹{final_selling_price * batch_qty:.2f}
{'='*70}
"""

        result = {
            "report_text": report,
            "cost_per_unit": cost_after_discount,
            "recommended_selling_price": final_selling_price,
            "total_cost": final_selling_price * batch_qty,
            "batch_quantity": batch_qty,
            "part_info": part_info,
            "deterministic_estimate": det,
            "model_used": self.lm_client.active_text_model,
            "timestamp": datetime.now().isoformat(),
            "live_overrides_applied": bool(live_overrides),
            "ai_cost_extracted": ai_extracted,
        }
        return result

    def check_analysis_result(self):
        try:
            result = self.analysis_queue.get_nowait()
            self._streaming = False
            if "error" in result:
                self.update_output_textbox(f"ANALYSIS ERROR\n{'='*50}\n{result['error']}", clear_first=True)
                self.selected_file_label.configure(text="Analysis failed", text_color=THEME_COLORS["error"])
            else:
                self.last_analysis_result = result
                self.update_output_textbox(result.get("report_text", ""), clear_first=True)
                if not result.get("ai_cost_extracted", True):
                    self.selected_file_label.configure(text="Completed (AI Cost Extraction Failed)", text_color=THEME_COLORS["warning"])
                else:
                    self.selected_file_label.configure(text="Analysis completed", text_color=THEME_COLORS["text_secondary"])
            self.analyze_button.configure(state="normal", text="⚡ Analyze & Estimate")
        except queue.Empty:
            self.after(100, self.check_analysis_result)

    def _animate_loading(self, label, text_prefix, flag_name):
        if not getattr(self, flag_name, False):
            return
        frames = ["|", "/", "-", "\\"]
        idx = getattr(self, f"{flag_name}_idx", 0)
        label.configure(text=f"{text_prefix} {frames[idx]}")
        setattr(self, f"{flag_name}_idx", (idx + 1) % 4)
        self.after(100, lambda: self._animate_loading(label, text_prefix, flag_name))

    def select_drawing_file_action(self):
        filepath = filedialog.askopenfilename(
            title="Select Technical Drawing",
            filetypes=[
                ("All Supported", "*.pdf *.png *.jpg *.jpeg"),
                ("PDF Files", "*.pdf"),
                ("Image Files", "*.png *.jpg *.jpeg"),
                ("All files", "*.*"),
            ],
        )
        if not filepath:
            return
        
        self.is_loading_drawing = True
        self.is_loading_drawing_idx = 0
        self.analyze_button.configure(state="disabled")
        self._animate_loading(self.selected_file_label, "Loading drawing...", "is_loading_drawing")
        
        threading.Thread(target=self._async_load_drawing, args=(filepath,), daemon=True).start()

    def _async_load_drawing(self, filepath):
        try:
            image_paths_for_analysis = []
            loaded_pil_images_for_chat = []
            pdf_native_text = ""
            filename = os.path.basename(filepath)
            
            if filepath.lower().endswith(".pdf"):
                doc = fitz.open(filepath)
                text_parts = []
                for i, page in enumerate(doc):
                    if i >= 5:
                        break
                    page_text = page.get_text()
                    if page_text.strip():
                        text_parts.append(f"--- Page {i+1} ---\n{page_text.strip()}")
                    pix = page.get_pixmap(dpi=400)
                    loaded_pil_images_for_chat.append(
                        Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                    )
                pdf_native_text = "\n\n".join(text_parts)
                image_paths_for_analysis.append(filepath)
                final_label = f"{filename} ({len(doc)} pages)"
                doc.close()
            else:
                loaded_pil_images_for_chat.append(Image.open(filepath))
                image_paths_for_analysis.append(filepath)
                final_label = filename
            
            self.after(0, self._finalize_drawing_load, True, loaded_pil_images_for_chat, image_paths_for_analysis, pdf_native_text, final_label, filename)
        except Exception as exc:
            self.after(0, self._finalize_drawing_load, False, str(exc), None, None, None, None)

    def _finalize_drawing_load(self, success, arg1, image_paths, pdf_text, label_text, filename):
        self.is_loading_drawing = False
        if success:
            self.loaded_pil_images_for_chat = arg1
            self.image_paths_for_analysis = image_paths
            self.pdf_native_text = pdf_text
            self.selected_file_label.configure(text=label_text, text_color=THEME_COLORS["text_secondary"])
            self.display_image(self.loaded_pil_images_for_chat[0])
            self.analyze_button.configure(state="normal")
            self.update_output_textbox(
                f"Drawing loaded: {filename}\nImages: {len(self.loaded_pil_images_for_chat)}\nReady for analysis.",
                clear_first=True,
            )
        else:
            messagebox.showerror("Load Error", arg1)
            self.selected_file_label.configure(text="No drawing loaded", text_color=THEME_COLORS["text_secondary"])

    def display_image(self, pil_image):
        try:
            w, h = pil_image.size
            ratio = min(IMAGE_DISPLAY_MAX_WIDTH / w, IMAGE_DISPLAY_MAX_HEIGHT / h)
            nw, nh = int(w * ratio), int(h * ratio)
            resized = pil_image.resize((nw, nh), Image.Resampling.LANCZOS)
            self.displayed_ctk_image = ctk.CTkImage(light_image=resized, dark_image=resized, size=(nw, nh))
            self.image_display_label.configure(image=self.displayed_ctk_image, text="")
        except Exception as exc:
            self.image_display_label.configure(image=None, text=f"Display error: {exc}")

    def preprocess_image_for_analysis(self, pil_image):
        try:
            # Enhanced preprocessing for better OCR and Vision model reading
            img = pil_image.filter(ImageFilter.UnsharpMask(radius=2, percent=200, threshold=3))
            img = ImageEnhance.Contrast(img).enhance(1.5)
            img = ImageEnhance.Sharpness(img).enhance(2.0)
            return img
        except Exception:
            return pil_image

    def update_output_textbox(self, text, clear_first=False):
        self.output_textbox.configure(state="normal")
        if clear_first:
            self.output_textbox.delete("1.0", "end")
        self.output_textbox.insert("end", text + "\n")
        self.output_textbox.see("end")
        self.output_textbox.configure(state="disabled")

    def copy_output_to_clipboard_action(self):
        content = self.output_textbox.get("1.0", "end-1c")
        self.clipboard_clear()
        self.clipboard_append(content)

    def export_report_action(self):
        if not self.last_analysis_result:
            messagebox.showwarning("Warning", "No analysis result to export.")
            return
        
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = filedialog.asksaveasfilename(
            defaultextension=".txt",
            initialfile=f"quote_report_{ts}.txt",
            title="Save Report",
            filetypes=[("Text files", "*.txt")]
        )
        if not filepath:
            return
            
        # Enforce .txt extension
        if not filepath.lower().endswith(".txt"):
            filepath += ".txt"
            
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(self.last_analysis_result.get("report_text", ""))
            messagebox.showinfo("Success", f"Report saved to:\n{filepath}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save file:\n{str(e)}")

    def export_excel_action(self):
        if not self.last_analysis_result:
            messagebox.showwarning("Warning", "No analysis result to export.")
            return

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            initialfile=f"quote_report_{ts}.xlsx",
            title="Save Excel Report",
            filetypes=[("Excel files", "*.xlsx"), ("All files", "*.*")]
        )
        if not filepath:
            return
            
        try:
            part_info = self.last_analysis_result.get("part_info", {})
            det = self.last_analysis_result.get("deterministic_estimate", {})
            
            summary_data = {
                "Part Name": [part_info.get("name", "N/A")],
                "Part Number": [part_info.get("number", "N/A")],
                "Material": [part_info.get("material", "N/A")],
                "Batch Quantity": [self.last_analysis_result.get("batch_quantity", 1)],
                "AI Base Cost (INR)": [self.last_analysis_result.get("cost_per_unit", 0.0)],
                "Recommended Selling Price (INR)": [self.last_analysis_result.get("recommended_selling_price", 0.0)],
                "Total Batch Cost (INR)": [self.last_analysis_result.get("total_cost", 0.0)],
            }
            
            deterministic_data = {
                "Metric": [
                    "Labor Cost (INR)", 
                    "Material Cost (INR)", 
                    "Weight (kg)", 
                    "Total Minutes", 
                    "Surcharge Percentage", 
                    "Rule Base Cost (INR)"
                ],
                "Value": [
                    det.get("labor_cost", 0.0),
                    det.get("material_cost", 0.0),
                    det.get("weight_kg", 0.0),
                    det.get("total_minutes", 0.0),
                    det.get("surcharge_percent", 0.0),
                    det.get("estimated_cost_per_unit", 0.0)
                ]
            }

            df_summary = pd.DataFrame(summary_data)
            df_det = pd.DataFrame(deterministic_data)

            with pd.ExcelWriter(filepath, engine='openpyxl') as writer:
                df_summary.to_excel(writer, sheet_name="Summary", index=False)
                df_det.to_excel(writer, sheet_name="Rule Breakdown", index=False)
                
            messagebox.showinfo("Success", f"Excel Report saved to:\n{filepath}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save Excel file:\n{str(e)}")

    def open_quote_comparison_window(self):
        self.quote_window = ctk.CTkToplevel(self)
        self.quote_window.title("Quote Comparison — Cost Ninja")
        self.quote_window.geometry("1200x820")
        self.quote_window.configure(fg_color=THEME_COLORS["bg_dark"])
        self.quote_window.transient(self)
        self.quote_window.grab_set()
        main_frame = NvidiaFrame(self.quote_window)
        main_frame.pack(fill="both", expand=True, padx=16, pady=16)
        NvidiaLabel(main_frame, text="▸ Enhanced Quote Comparison", style="title").pack(anchor="w", padx=20, pady=(16, 16))
        # Accent divider
        ctk.CTkFrame(main_frame, height=1, fg_color=THEME_COLORS["border_default"]).pack(fill="x", padx=20, pady=(0, 12))
        btn_row = ctk.CTkFrame(main_frame, fg_color="transparent")
        btn_row.pack(fill="x", padx=20, pady=(0, 14))
        for text, style, cmd in [
            ("Load Supplier Quote", "primary", self.load_supplier_quote),
            ("Load Historical Data", "accent", self.load_historical_orders),
            ("Advanced Analysis", "success", self.analyze_quote_comparison),
            ("Re-test Extraction", "warning", self.retest_quote_extraction),
        ]:
            NvidiaButton(btn_row, text=text, style=style, command=cmd, height=42, width=200).pack(side="left", padx=6)
        st = self.lm_client.status_dict()
        dot = "●" if st['connected'] else "○"
        self.quote_status_label = NvidiaLabel(
            main_frame,
            text=f"{dot} LM Studio: {'Connected' if st['connected'] else 'Offline'}  ·  Mode: {st['mode']}  ·  OCR: {'OK' if self.tesseract_ok else 'Limited'}",
            style="accent",
        )
        self.quote_status_label.pack(anchor="w", padx=20, pady=6)
        self.quote_results_textbox = NvidiaTextbox(main_frame, wrap="word", font=("Consolas", 11), height=420)
        self.quote_results_textbox.pack(fill="both", expand=True, padx=20, pady=(0, 12))
        NvidiaButton(main_frame, text="Copy Negotiation Email", style="warning", command=self.copy_negotiation_email, height=40, width=240).pack(pady=(0, 14))

    def load_supplier_quote(self):
        filepath = filedialog.askopenfilename(title="Select Quote PDF", filetypes=[("PDF", "*.pdf"), ("All", "*.*")])
        if not filepath:
            return
        
        self.is_loading_quote = True
        self.is_loading_quote_idx = 0
        self.quote_status_label.configure(text_color=THEME_COLORS["text_primary"])
        # We need the app to animate on `self.quote_status_label`.
        self._animate_loading(self.quote_status_label, "Loading quote...", "is_loading_quote")
        
        threading.Thread(target=self._async_load_quote, args=(filepath,), daemon=True).start()

    def _async_load_quote(self, filepath):
        try:
            quote_images = []
            doc = fitz.open(filepath)
            for page in doc:
                pix = page.get_pixmap(dpi=400)
                quote_images.append(Image.frombytes("RGB", [pix.width, pix.height], pix.samples))
            doc.close()
            self.after(0, self._finalize_quote_load, True, quote_images, filepath, None)
        except Exception as exc:
            self.after(0, self._finalize_quote_load, False, None, None, str(exc))

    def _finalize_quote_load(self, success, images, filepath, error_msg):
        self.is_loading_quote = False
        if success:
            self.quote_pdf_path = filepath
            self.quote_images = images
            self.quote_status_label.configure(text=f"Quote loaded: {os.path.basename(filepath)} ({len(self.quote_images)} pages)")
            self.quote_results_textbox.delete("0.0", "end")
            self.quote_results_textbox.insert("0.0", f"Loaded {len(self.quote_images)} pages. Ready.\n")
        else:
            messagebox.showerror("Error", error_msg)
            self.quote_status_label.configure(text="Failed to load quote")

    def load_historical_orders(self):
        filepath = filedialog.askopenfilename(filetypes=[("Excel", "*.xlsx *.xls"), ("All", "*.*")])
        if not filepath:
            return
        try:
            df = pd.read_excel(filepath)
            mapping = {}
            for col in df.columns:
                cl = col.lower().strip()
                if any(t in cl for t in ("part number", "part_number", "pn", "item")):
                    mapping[col] = "Part Number"
                elif any(t in cl for t in ("price", "unit price", "cost")):
                    mapping[col] = "Price"
                elif any(t in cl for t in ("quantity", "qty")):
                    mapping[col] = "Quantity"
                elif any(t in cl for t in ("description", "desc")):
                    mapping[col] = "Description"
            df.rename(columns=mapping, inplace=True)
            if "Part Number" not in df.columns or "Price" not in df.columns:
                messagebox.showerror("Error", "Excel must have Part Number and Price columns.")
                return
            df["Part Number"] = df["Part Number"].astype(str).str.strip().str.upper().str.replace(r"[^A-Z0-9]", "", regex=True)
            df["Price"] = pd.to_numeric(df["Price"], errors="coerce")
            df = df.dropna(subset=["Part Number", "Price"])
            df = df[(df["Price"] > 0) & (df["Price"] < 100000) & (df["Part Number"].str.len() >= 6)]
            self.historical_orders_df = df
            self.quote_status_label.configure(text=f"Historical data: {len(df)} records")
            self.quote_results_textbox.insert("end", f"\nLoaded {len(df)} valid records.\n")
        except Exception as exc:
            messagebox.showerror("Error", str(exc))

    def retest_quote_extraction(self):
        if not self.quote_images:
            messagebox.showwarning("No Quote", "Load a supplier quote first.")
            return
        self.quote_results_textbox.delete("0.0", "end")
        self.quote_results_textbox.insert("0.0", "Re-testing extraction...\n")
        threading.Thread(target=self._retest_extraction_thread, daemon=True).start()

    def _retest_extraction_thread(self):
        items = self.extract_quote_data_enhanced(force_llm=True)
        msg = f"Extracted {len(items)} items.\n"
        for item in items[:15]:
            msg += f"  {item['part_number']} qty={item.get('quantity',1)} ₹{item['price']:.2f}\n"
        self.after(0, lambda: self.quote_results_textbox.insert("end", msg))

    def analyze_quote_comparison(self):
        if not hasattr(self, "quote_pdf_path"):
            messagebox.showwarning("No Quote", "Load a supplier quote first.")
            return
        if self.historical_orders_df is None:
            messagebox.showwarning("No Data", "Load historical orders first.")
            return
        self.quote_results_textbox.delete("0.0", "end")
        self.quote_results_textbox.insert("0.0", "Starting quote analysis...\n")
        threading.Thread(target=self.run_enhanced_quote_analysis, daemon=True).start()

    def run_enhanced_quote_analysis(self):
        try:
            items = self.extract_quote_data_enhanced()
            if not items:
                self.after(0, lambda: self.quote_results_textbox.insert("end", "No items extracted.\n"))
                return
            results = self.compare_with_historical(items)
            report = self.generate_comparison_report(results)
            email = self.generate_negotiation_email(results)
            self.after(0, lambda: self._show_quote_results(report, email))
        except Exception:
            self.after(0, lambda: self.quote_results_textbox.insert("end", traceback.format_exc()))

    def extract_quote_data_enhanced(self, force_llm=False):
        if not force_llm and self.quote_images:
            ocr_items = self.quote_fixer.extract_with_enhanced_ocr(self.quote_images)
            if ocr_items and len(ocr_items) > 10:
                return ocr_items
        return self.extract_with_local_llm(self.quote_images)

    def extract_with_local_llm(self, images):
        if not self.local_llm_available:
            return []
        try:
            text = self.lm_client.chat_completion(
                QUOTE_LLM_PROMPT,
                "Extract all quote items with correct quantities.",
                images, temperature=0.0, max_tokens=20480,
            )
            return self.parse_llm_response(text)
        except Exception as exc:
            print(f"Quote LLM error: {exc}")
            return []

    def parse_llm_response(self, response_text):
        items = []
        for line in response_text.split("\n"):
            if "Part:" not in line:
                continue
            match = re.search(
                r"Part:\s*([A-Z0-9]+).*?Qty:\s*(\d+).*?Price:\s*(\d+\.?\d*).*?Desc:\s*(.+?)(?:\||$)",
                line,
            )
            if not match:
                continue
            try:
                pn, qty, price, desc = match.group(1), int(match.group(2)), float(match.group(3)), match.group(4).strip()
                if 6 <= len(pn) <= 12 and 1 <= qty <= 10000 and 1 <= price <= 10000:
                    items.append({
                        "part_number": pn, "quantity": qty, "price": price,
                        "description": desc, "total": price * qty,
                        "confidence": 85.0, "method": "Local_LLM",
                    })
            except (ValueError, IndexError):
                continue
        return items

    def compare_with_historical(self, quote_items):
        results = []
        hist = {str(r["Part Number"]).upper(): r["Price"] for _, r in self.historical_orders_df.iterrows()}
        parts = list(hist.keys())
        for item in quote_items:
            pn = item["part_number"].upper()
            matches = self.quote_fixer.advanced_fuzzy_match(pn, parts)
            if not matches or matches[0][1] < 70:
                continue
            best_pn, sim, method = matches[0]
            hist_price = float(hist[best_pn])
            quote_price = float(item["price"])
            qty = int(item.get("quantity", 1))
            if hist_price < quote_price:
                savings = (quote_price - hist_price) * qty
                results.append({
                    "part_number": pn, "matched_historical_part": best_pn,
                    "similarity_score": sim, "match_method": method, "quantity": qty,
                    "quote_price": quote_price, "historical_price": hist_price,
                    "total_savings": savings, "savings_percent": (quote_price - hist_price) / quote_price * 100,
                    "is_high_confidence": sim >= 85, "description": item.get("description", ""),
                })
        results.sort(key=lambda x: x["total_savings"], reverse=True)
        return results

    def generate_comparison_report(self, results):
        if not results:
            return "No savings opportunities found."
        total = sum(r["total_savings"] for r in results)
        hc = [r for r in results if r["is_high_confidence"]]
        lc = [r for r in results if not r["is_high_confidence"]]
        
        report = f"QUOTE ANALYSIS\n{'='*60}\nTotal savings: ₹{total:,.2f}\nItems: {len(results)} | High confidence: {len(hc)}\n\n"
        
        report += "HIGH CONFIDENCE MATCHES\n" + "-"*30 + "\n"
        if hc:
            for i, r in enumerate(hc[:15], 1):
                report += f"{i}. {r['part_number']} -> {r['matched_historical_part']} ({r['similarity_score']:.0f}%)\n"
                report += f"   Qty {r['quantity']} | Quote ₹{r['quote_price']:.2f} | Hist ₹{r['historical_price']:.2f} | Save ₹{r['total_savings']:,.2f}\n"
        else:
            report += "No high confidence matches found.\n"
            
        if lc:
            report += "\nUNCERTAIN MATCHES (LOW CONFIDENCE - VERIFY MANUALLY)\n" + "-"*40 + "\n"
            for i, r in enumerate(lc[:15], 1):
                report += f"{i}. [UNCERTAIN] {r['part_number']} -> {r['matched_historical_part']} ({r['similarity_score']:.0f}%)\n"
                report += f"   Qty {r['quantity']} | Quote ₹{r['quote_price']:.2f} | Hist ₹{r['historical_price']:.2f} | Save ₹{r['total_savings']:,.2f}\n"
                
        return report

    def generate_negotiation_email(self, results):
        hc = [r for r in results if r["is_high_confidence"]]
        if not hc:
            return "No negotiation email — no high-confidence matches."
        total = sum(r["total_savings"] for r in hc)
        email = f"Subject: Cost Review - ₹{total:,.0f} Savings Opportunity\n\nDear Supplier,\n\nWe identified ₹{total:,.0f} in optimization opportunities:\n\n"
        for i, r in enumerate(hc[:10], 1):
            email += f"{i}. Part {r['part_number']} (Qty {r['quantity']}): Your ₹{r['quote_price']:.2f} vs target ₹{r['historical_price']:.2f}\n"
        email += "\nBest regards,\n[Your Name]\n"
        return email

    def _show_quote_results(self, report, email):
        self.quote_results_textbox.delete("0.0", "end")
        self.quote_results_textbox.insert("0.0", report + "\n" + "=" * 60 + "\n\nNEGOTIATION EMAIL:\n\n" + email)
        self.negotiation_email = email
        self.quote_status_label.configure(text="Analysis complete")

    def copy_negotiation_email(self):
        if hasattr(self, "negotiation_email"):
            self.clipboard_clear()
            self.clipboard_append(self.negotiation_email)
            messagebox.showinfo("Copied", "Email copied to clipboard.")
        else:
            messagebox.showwarning("No Email", "Run analysis first.")

    def on_closing(self):
        self.destroy()


def main():
    ctk.set_appearance_mode("dark")
    print("Starting Cost Ninja - AI Quote Pilot V3")
    print("Powered by local LM Studio")
    if ENHANCED_MATCHING:
        print("Enhanced fuzzy matching: available")
    else:
        print("Optional: pip install jellyfish python-Levenshtein rapidfuzz")

    app_config = load_configuration()
    lm_client = LMStudioClient(app_config.get("lm_studio", {}))
    if not lm_client.available:
        print("WARNING: LM Studio not reachable. Start server in LM Studio Developer tab.")

    app = App(config=app_config, lm_client=lm_client)
    app.mainloop()


if __name__ == "__main__":
    main()
