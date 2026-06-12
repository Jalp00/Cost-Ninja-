"""LM Studio OpenAI-compatible client with auto model detection and retries."""

from __future__ import annotations

import base64
import time
from io import BytesIO
from typing import Callable

import pytesseract
import requests
from openai import OpenAI
from PIL import Image

VISION_KEYWORDS = [
    "qwen3.5", "qwen-3.5", "qwen3_5",
    "gemma-4-e4b", "gemma4-e4b", "gemma-4-e2b", "gemma4-e2b",
    "vl", "vision", "multimodal", "-mm", "_mm",
    "llava", "moondream", "minicpm-v", "minicpm_v", "pixtral",
    "qwen2-vl", "qwen-vl", "internvl", "cogvlm",
]

RESOURCE_ERROR_FRAGMENTS = (
    "insufficient system resources",
    "model loading was stopped",
    "would likely overload your system",
    "guardrails",
    "out of memory",
    "cuda error",
)


class LMStudioClient:
    def __init__(self, lm_config: dict):
        self.base_url = str(lm_config.get("base_url", "http://localhost:1234/v1")).strip()
        self.api_key = str(lm_config.get("api_key", "lm-studio")).strip()
        self.text_model_override = str(lm_config.get("text_model", "")).strip()
        self.vision_model_override = str(lm_config.get("vision_model", "")).strip()
        self.text_hint = str(lm_config.get("text_model_hint", "qwen3.5-9b")).strip().lower()
        self.vision_hint = str(lm_config.get("vision_model_hint", "gemma-4-e4b")).strip().lower()
        self.default_max_tokens = int(lm_config.get("max_tokens", 20480))
        self.default_system_prompt = ""

        # Required model — will be auto-loaded if not already present
        self.required_model = str(lm_config.get("required_model", "qwen3.5-2b")).strip()
        self.required_model_confirmed = False
        self.model_load_message = ""

        self.client: OpenAI | None = None
        self.available = False
        self.active_text_model = ""
        self.active_vision_model = ""
        self.loaded_models: list[str] = []

        self._connect()

    def _api_base(self) -> str:
        return self.base_url.rstrip("/")

    @staticmethod
    def _model_matches(model_id: str, keywords: list[str]) -> bool:
        name = model_id.lower()
        return any(keyword in name for keyword in keywords)

    @staticmethod
    def is_vision_capable_model(model_id: str) -> bool:
        if not model_id:
            return False
        lower = model_id.lower()
        if "gemma-4" in lower or "gemma4" in lower:
            if any(tag in lower for tag in ("e4b", "e2b")):
                return True
        return any(kw in lower for kw in VISION_KEYWORDS)

    def fetch_models(self) -> list[str]:
        try:
            response = requests.get(f"{self._api_base()}/models", timeout=5)
            if response.status_code != 200:
                return []
            models = []
            for item in response.json().get("data", []):
                model_id = item.get("id") or item.get("name")
                if model_id:
                    models.append(model_id)
            return models
        except Exception:
            return []

    def check_running(self) -> bool:
        try:
            return requests.get(f"{self._api_base()}/models", timeout=5).status_code == 200
        except Exception:
            return False

    def _pick_by_hint(self, models: list[str], hint: str, family: str | None = None) -> str:
        for model_id in models:
            lower = model_id.lower()
            if hint and hint not in lower:
                continue
            if family and family not in lower:
                continue
            return model_id
        return ""

    def _pick_gemma(self, models: list[str]) -> str:
        picked = self._pick_by_hint(models, self.vision_hint, "gemma")
        if picked:
            return picked
        for groups in (
            ["gemma-4-e4b", "gemma4-e4b"],
            ["gemma-4-e2b", "gemma4-e2b"],
            ["gemma-4", "gemma4"],
            ["gemma"],
        ):
            for model_id in models:
                if self._model_matches(model_id, groups):
                    return model_id
        return ""

    def _pick_qwen(self, models: list[str]) -> str:
        picked = self._pick_by_hint(models, self.text_hint, "qwen")
        if picked:
            return picked
        for groups in (
            ["qwen3.5-9b", "qwen-3.5-9b", "qwen3_5-9b"],
            ["qwen3.5", "qwen-3.5"],
            ["qwen3", "qwen-3"],
            ["qwen2.5", "qwen-2.5"],
            ["qwen"],
        ):
            for model_id in models:
                if self._model_matches(model_id, groups):
                    return model_id
        return ""

    def _pick_any_vision(self, models: list[str]) -> str:
        for model_id in models:
            if self.is_vision_capable_model(model_id):
                return model_id
        return self._pick_gemma(models)

    def resolve_models(self, models: list[str] | None = None) -> None:
        if models is None:
            models = self.fetch_models()
        self.loaded_models = models

        if self.text_model_override and self.vision_model_override:
            self.active_text_model = self.text_model_override
            self.active_vision_model = self.vision_model_override
        elif self.text_model_override or self.vision_model_override:
            single = self.text_model_override or self.vision_model_override
            self.active_text_model = self.active_vision_model = single
        elif len(models) == 1:
            self.active_text_model = self.active_vision_model = models[0]
        else:
            gemma = [m for m in models if "gemma" in m.lower()]
            qwen = [m for m in models if "qwen" in m.lower()]
            vision_candidates = [m for m in models if self.is_vision_capable_model(m)]

            if gemma and qwen:
                self.active_text_model = self._pick_qwen(models) or qwen[0]
                self.active_vision_model = self._pick_gemma(models) or gemma[0]
            elif vision_candidates:
                self.active_vision_model = vision_candidates[0]
                text_candidates = [m for m in models if m not in vision_candidates] or models
                self.active_text_model = self._pick_qwen(text_candidates) or text_candidates[0]
            else:
                self.active_text_model = self._pick_qwen(models) or (models[0] if models else "local-model")
                self.active_vision_model = self.active_text_model

    def _find_required_model(self) -> str | None:
        """Check if the required model is already loaded (fuzzy match)."""
        if not self.required_model:
            return None
        target = self.required_model.lower().replace(" ", "-").replace("_", "-")
        for model_id in self.loaded_models:
            model_lower = model_id.lower().replace("_", "-")
            # Check if target keywords are all present in the model id
            target_parts = target.split("-")
            if all(part in model_lower for part in target_parts):
                return model_id
        return None

    def _api_base_root(self) -> str:
        """Get the root API base URL (without /v1) for LM Studio native endpoints."""
        base = self.base_url.rstrip("/")
        if base.endswith("/v1"):
            return base[:-3]
        return base

    def load_model_via_api(self, model_identifier: str) -> bool:
        """Load a model via LM Studio API with correct context length."""
        root = self._api_base_root()
        load_url = f"{root}/api/v1/models/load"
        payload = {
            "model": model_identifier,
            "context_length": self.default_max_tokens,
        }
        try:
            print(f"INFO: Loading model '{model_identifier}' with context_length={self.default_max_tokens}...")
            resp = requests.post(load_url, json=payload, timeout=120)
            if resp.status_code == 200:
                print(f"INFO: Model '{model_identifier}' loaded successfully (context={self.default_max_tokens}).")
                return True
            else:
                print(f"WARN: Model load returned status {resp.status_code}: {resp.text[:200]}")
                return False
        except Exception as exc:
            print(f"WARN: Could not load model via API: {exc}")
            return False

    def unload_model_via_api(self, model_identifier: str) -> bool:
        """Unload a model via LM Studio API."""
        root = self._api_base_root()
        unload_url = f"{root}/api/v1/models/unload"
        try:
            print(f"INFO: Unloading model '{model_identifier}'...")
            resp = requests.post(unload_url, json={"model": model_identifier}, timeout=30)
            if resp.status_code == 200:
                print(f"INFO: Model '{model_identifier}' unloaded.")
                return True
            else:
                print(f"WARN: Unload returned status {resp.status_code}: {resp.text[:200]}")
                return False
        except Exception as exc:
            print(f"WARN: Could not unload model: {exc}")
            return False

    def ensure_required_model(self) -> None:
        """Ensure the required model is loaded with correct context_length.
        Forces single-model mode: the required model handles BOTH text and images.
        Always reloads the model to guarantee context_length and settings are correct."""
        if not self.required_model or not self.available:
            return

        # Step 1: Check if model is already loaded
        found = self._find_required_model()

        if found:
            # Model exists but may have wrong context_length — unload and reload
            print(f"INFO: Model '{found}' found. Reloading with context_length={self.default_max_tokens}...")
            self.model_load_message = f"⏳ Reloading {found} with context={self.default_max_tokens}..."
            self.unload_model_via_api(found)
            time.sleep(2)

        # Step 2: Load (or reload) the model with correct settings
        self.model_load_message = f"⏳ Loading {self.required_model} (context={self.default_max_tokens})..."
        model_to_load = found if found else self.required_model
        success = self.load_model_via_api(model_to_load)

        if success:
            time.sleep(2)
            self.loaded_models = self.fetch_models()
            found = self._find_required_model()
            if found:
                self.required_model_confirmed = True
                self.model_load_message = f"✓ {found} loaded (context={self.default_max_tokens})"
                self.active_text_model = found
                self.active_vision_model = found
                print(f"INFO: Model locked: {found} | context={self.default_max_tokens} | text+vision")
                return

        # Load failed — try with just the required_model name
        if not found:
            success = self.load_model_via_api(self.required_model)
            if success:
                time.sleep(2)
                self.loaded_models = self.fetch_models()
                found = self._find_required_model()
                if found:
                    self.required_model_confirmed = True
                    self.model_load_message = f"✓ {found} loaded (context={self.default_max_tokens})"
                    self.active_text_model = found
                    self.active_vision_model = found
                    print(f"INFO: Model locked: {found} | context={self.default_max_tokens} | text+vision")
                    return

        self.required_model_confirmed = False
        self.model_load_message = (
            f"✗ Could not load '{self.required_model}'. "
            "Please load it manually in LM Studio."
        )
        print(f"WARN: {self.model_load_message}")

    def _connect(self) -> None:
        try:
            self.client = OpenAI(base_url=self.base_url, api_key=self.api_key)
            if self.check_running():
                self.available = True
                self.resolve_models()
                self.ensure_required_model()
            else:
                self.available = False
                self.required_model_confirmed = False
                self.model_load_message = "LM Studio not connected"
        except Exception as exc:
            print(f"ERROR: Could not configure LM Studio client: {exc}")
            self.available = False
            self.required_model_confirmed = False
            self.model_load_message = f"Connection error: {exc}"

    def refresh(self) -> dict:
        """Re-check server and model list."""
        self._connect()
        return self.status_dict()

    def status_dict(self) -> dict:
        mode = "Vision"
        if self.active_text_model == self.active_vision_model:
            mode = "Vision" if self.is_vision_capable_model(self.active_text_model) else "OCR+Text"
        elif self.is_vision_capable_model(self.active_vision_model):
            mode = "Dual (Vision+Text)"
        else:
            mode = "OCR+Text"
        return {
            "connected": self.available,
            "text_model": self.active_text_model,
            "vision_model": self.active_vision_model,
            "mode": mode,
            "models": self.loaded_models,
            "base_url": self.base_url,
            "required_model_confirmed": self.required_model_confirmed,
            "model_load_message": self.model_load_message,
        }

    def model_for_request(self, has_images: bool) -> str:
        if self.active_text_model == self.active_vision_model:
            return self.active_text_model
        if has_images and self.is_vision_capable_model(self.active_vision_model):
            return self.active_vision_model
        return self.active_text_model

    @staticmethod
    def optimize_image(pil_image: Image.Image, max_width: int = 2048) -> Image.Image:
        """Resize large images while preserving detail for engineering drawings."""
        w, h = pil_image.size
        if w <= max_width:
            return pil_image.convert("RGB")
        ratio = max_width / w
        new_size = (max_width, int(h * ratio))
        return pil_image.convert("RGB").resize(new_size, Image.Resampling.LANCZOS)

    @staticmethod
    def pil_to_base64_url(pil_image: Image.Image, fmt: str = "PNG", quality: int = 95) -> str:
        """Encode image as lossless PNG (default) to preserve fine text and lines."""
        buffer = BytesIO()
        if fmt.upper() == "JPEG":
            pil_image.save(buffer, format="JPEG", quality=quality, optimize=True)
            mime = "image/jpeg"
        else:
            pil_image.save(buffer, format="PNG", optimize=True)
            mime = "image/png"
        encoded = base64.b64encode(buffer.getvalue()).decode("utf-8")
        return f"data:{mime};base64,{encoded}"

    import re

    def clean_engineering_ocr(self, text: str) -> str:
        """Fix common OCR misreads specific to engineering drawings."""
        # Fix 12.5O -> 12.50
        text = re.sub(r'(\d+\.\d*)[Oo]', r'\g<1>0', text)
        # Fix M6xl.0 -> M6x1.0
        text = re.sub(r'([Mm]\d+x)[lL](\.\d+)', r'\g<1>1\g<2>', text)
        # Fix standalone 'O' near numbers that should be '0'
        text = re.sub(r'\bO\b(?=\s*\d)', '0', text)
        text = re.sub(r'(?<=\d\s)\bO\b', '0', text)
        # Fix common symbols often misread
        text = text.replace("R.", "R").replace("0.", "Ø")
        return text

    def multi_pass_ocr(self, images: list[Image.Image]) -> str:
        """Run multiple passes of Tesseract to catch scattered annotations and tables."""
        parts = []
        for index, image in enumerate(images, start=1):
            try:
                # Pass 1: Standard block (good for paragraphs/notes)
                text_p1 = pytesseract.image_to_string(image, config="--psm 6 --oem 3")
                # Pass 2: Column based (good for BOM tables)
                text_p2 = pytesseract.image_to_string(image, config="--psm 4 --oem 3")
                # Pass 3: Sparse text (good for scattered dimensions around the drawing)
                text_p3 = pytesseract.image_to_string(image, config="--psm 11 --oem 3")
                
                # Combine and clean
                combined = f"--- Pass 1 (Standard) ---\n{text_p1}\n\n--- Pass 2 (Tables) ---\n{text_p2}\n\n--- Pass 3 (Sparse) ---\n{text_p3}"
                cleaned = self.clean_engineering_ocr(combined)
                parts.append(f"--- Page {index} (Multi-Pass OCR) ---\n{cleaned.strip()}")
            except Exception as exc:
                parts.append(f"--- Page {index}: OCR unavailable ({exc}) ---")
        return "\n\n".join(parts)

    def build_user_content(self, text: str, images: list[Image.Image] | None = None, pdf_native_text: str = "", extra_images: list[Image.Image] | None = None):
        all_images = (images or []) + (extra_images or [])
        if not all_images:
            return text + (f"\n\n--- PDF Native Text ---\n{pdf_native_text}" if pdf_native_text else "")
            
        model = self.model_for_request(True)

        # Always run OCR to supplement vision — catches small text the model may miss
        ocr_text = self.multi_pass_ocr(images or [])

        native_text_section = ""
        if pdf_native_text:
            native_text_section = (
                "\n\n--- PDF NATIVE TEXT (100% ACCURATE) ---\n"
                "This text was extracted directly from the PDF file. It is the MOST reliable source of truth "
                "for dimensions, tolerances, part numbers, and notes. Always prefer this over OCR or Image Vision if there is a conflict.\n"
                f"{pdf_native_text}"
            )

        if self.is_vision_capable_model(model):
            # Hybrid mode: send images AND Native Text AND OCR text for maximum accuracy
            supplemented_text = (
                f"{text}{native_text_section}\n\n"
                "--- OCR-Extracted Text (Use this to verify text you see in the image) ---\n"
                f"{ocr_text}"
            )
            optimized = [self.optimize_image(img) for img in all_images]
            content = [{"type": "text", "text": supplemented_text}]
            for image in optimized:
                content.append({
                    "type": "image_url",
                    "image_url": {"url": self.pil_to_base64_url(image)},
                })
            return content

        # Text-only fallback
        return (
            f"{text}{native_text_section}\n\n"
            "--- Document text (OCR — text-only model, no image input) ---\n"
            f"{ocr_text}"
        )

    @staticmethod
    def _looks_like_resource_error(exc: Exception) -> bool:
        msg = str(exc).lower()
        return any(fragment in msg for fragment in RESOURCE_ERROR_FRAGMENTS)

    def chat_completion(
        self,
        system_prompt: str = "",
        user_text: str = "",
        images: list[Image.Image] | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        on_token: Callable[[str], None] | None = None,
        pdf_native_text: str = "",
        extra_images: list[Image.Image] | None = None,
    ) -> str:
        if not self.available or not self.client:
            raise RuntimeError("LM Studio is not running. Load a model and start the local server.")

        # Use the stored system prompt if none is provided
        effective_prompt = system_prompt or self.default_system_prompt
        # Use the configured max_tokens if not explicitly overridden
        effective_max_tokens = max_tokens if max_tokens is not None else self.default_max_tokens

        messages = [
            {"role": "system", "content": effective_prompt},
            {"role": "user", "content": self.build_user_content(user_text, images, pdf_native_text, extra_images)},
        ]
        model = self.model_for_request(bool(images) or bool(extra_images))

        for attempt in range(3):
            try:
                if on_token:
                    chunks = []
                    stream = self.client.chat.completions.create(
                        model=model,
                        messages=messages,
                        temperature=temperature,
                        max_tokens=effective_max_tokens,
                        stream=True,
                    )
                    for chunk in stream:
                        delta = chunk.choices[0].delta.content or ""
                        if delta:
                            chunks.append(delta)
                            on_token(delta)
                    return "".join(chunks)

                response = self.client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=effective_max_tokens,
                )
                return response.choices[0].message.content or ""

            except Exception as exc:
                if self._looks_like_resource_error(exc) and (images or extra_images):
                    messages = [
                        {"role": "system", "content": effective_prompt},
                        {"role": "user", "content": self.build_user_content(user_text, None, pdf_native_text, None)},
                    ]
                    model = self.active_text_model or model
                    continue
                if attempt < 2:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                raise

        raise RuntimeError("LM Studio request failed after retries.")

    def test_chat(self) -> str:
        return self.chat_completion(
            "You are a helpful assistant.",
            "Reply in one short sentence: what is 2+2?",
            max_tokens=80,
        )
