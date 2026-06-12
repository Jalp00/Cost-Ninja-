"""Enhanced quote comparison OCR and fuzzy matching."""

import re
from collections import Counter

import cv2
import numpy as np
import pytesseract
from PIL import Image

try:
    import jellyfish
    import Levenshtein
    from rapidfuzz import fuzz

    ENHANCED_MATCHING = True
except ImportError:
    ENHANCED_MATCHING = False


class QuoteComparisonFix:
    def setup_enhanced_ocr(self):
        try:
            pytesseract.image_to_string(Image.new("RGB", (50, 50), "white"))
            self.tesseract_available = True
        except Exception:
            self.tesseract_available = False

    def preprocess_pdf_image(self, image):
        if not hasattr(self, "tesseract_available"):
            self.setup_enhanced_ocr()
        if not self.tesseract_available:
            return [image]
        try:
            cv_img = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
            gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)
            _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            denoised = cv2.fastNlMeansDenoising(gray)
            return [Image.fromarray(binary), Image.fromarray(denoised)]
        except Exception:
            return [image]

    def extract_with_enhanced_ocr(self, images):
        all_items = []
        for img in images:
            for processed_img in self.preprocess_pdf_image(img):
                try:
                    text = pytesseract.image_to_string(
                        processed_img,
                        config="--psm 6 -c tessedit_char_whitelist=0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz.,$-",
                    )
                    all_items.extend(self.parse_ocr_text_to_items(text))
                except Exception:
                    continue
        return self.remove_duplicate_items(all_items)

    def parse_ocr_text_to_items(self, text):
        items = []
        patterns = [
            r"([A-Z0-9]{6,12})\s+(.{10,50}?)\s+(\d+\.?\d*)",
            r"([A-Z0-9]{6,12})\s+(.{10,50}?)\s+(\d{1,4})\s+(\d+\.?\d*)",
            r"\d+\s+([A-Z0-9]{6,12})\s+(.{10,50}?)\s+(\d+\.?\d*)",
        ]
        for line in text.split("\n"):
            line = line.strip()
            if len(line) < 10:
                continue
            for pattern in patterns:
                match = re.search(pattern, line)
                if not match:
                    continue
                try:
                    groups = match.groups()
                    if len(groups) == 3:
                        pn, desc, price = groups
                        qty = 1
                    elif len(groups) == 4:
                        pn, desc, qty, price = groups
                        qty = int(qty)
                    else:
                        continue
                    price = float(price)
                    if not (1 <= price <= 10000 and 1 <= qty <= 10000):
                        continue
                    items.append({
                        "part_number": pn.strip(),
                        "description": desc.strip(),
                        "quantity": qty,
                        "price": price,
                        "method": "Enhanced_OCR",
                    })
                    break
                except (ValueError, IndexError):
                    continue
        return items

    def remove_duplicate_items(self, items):
        unique = {}
        for item in items:
            pn = item["part_number"].upper().strip()
            if pn not in unique or item["price"] > unique[pn]["price"]:
                unique[pn] = item
        return list(unique.values())

    def advanced_fuzzy_match(self, quote_part, historical_parts):
        quote_part = quote_part.upper().strip()
        best_matches = []
        for hist_part in historical_parts:
            hist_part = hist_part.upper().strip()
            if quote_part == hist_part:
                return [(hist_part, 100.0, "EXACT")]
            scores = {}
            max_len = max(len(quote_part), len(hist_part))
            if max_len > 0:
                diff = sum(c1 != c2 for c1, c2 in zip(quote_part.ljust(max_len), hist_part.ljust(max_len)))
                scores["basic"] = (1 - diff / max_len) * 100
            quote_chars = Counter(quote_part)
            hist_chars = Counter(hist_part)
            common = sum((quote_chars & hist_chars).values())
            total = sum((quote_chars | hist_chars).values())
            scores["frequency"] = (common / total * 100) if total > 0 else 0
            position_score = weight_sum = 0
            for i in range(min(len(quote_part), len(hist_part))):
                weight = 1.0 / (i + 1)
                weight_sum += weight
                if quote_part[i] == hist_part[i]:
                    position_score += weight
            scores["position"] = (position_score / weight_sum * 100) if weight_sum > 0 else 0
            scores["length"] = (1 - abs(len(quote_part) - len(hist_part)) / max_len) * 100
            if ENHANCED_MATCHING:
                try:
                    scores["levenshtein"] = (1 - Levenshtein.distance(quote_part, hist_part) / max_len) * 100
                    scores["jaro_winkler"] = jellyfish.jaro_winkler_similarity(quote_part, hist_part) * 100
                    scores["rapidfuzz"] = fuzz.ratio(quote_part, hist_part)
                except Exception:
                    pass
            if ENHANCED_MATCHING and "levenshtein" in scores:
                weights = {
                    "basic": 0.15, "frequency": 0.15, "position": 0.2, "length": 0.1,
                    "levenshtein": 0.2, "jaro_winkler": 0.15, "rapidfuzz": 0.05,
                }
            else:
                weights = {"basic": 0.3, "frequency": 0.25, "position": 0.3, "length": 0.15}
            composite = sum(scores.get(k, 0) * v for k, v in weights.items())
            best_method = max(scores.items(), key=lambda x: x[1])
            best_matches.append((hist_part, composite, f"{best_method[0].upper()}_{best_method[1]:.1f}"))
        best_matches.sort(key=lambda x: x[1], reverse=True)
        return best_matches[:3]
