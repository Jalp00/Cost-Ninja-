"""Configuration loading, cost context building, and deterministic estimation."""

import json
import os
import re
from typing import Any

PRECISION_TIER_MAP = {
    "Basic": "simple",
    "Medium": "medium",
    "High": "high",
    "Maximum": "high",
    "Ultra-Precision": "high",
}

DEFAULTS = {
    "labor_rate_per_hour": 800.0,
    "volume_addition_percentage": 15.0,
    "overhead_percentage": 25.0,
    "profit_margin_percentage": 20.0,
    "supplier_markup_percentage": 25.0,
    "material_data": {},
    "machinability_modifiers": {
        "ALUMINUM": 1.0,
        "STEEL": 1.27,
        "STAINLESSSTEEL": 1.4,
        "TITANIUM": 1.6,
        "INCONEL": 1.8,
        "COPPER": 1.1,
        "PLASTIC": 0.9,
    },
    "rules": {},
    "radius_surcharge_rules": [],
    "extrusion_profiles": {},
    "quantity_discount": {
        "1": 0.0,
        "10": 5.0,
        "25": 10.0,
        "50": 15.0,
        "100": 20.0,
        "250": 25.0,
        "500": 30.0,
    },
    "lm_studio": {
        "base_url": "http://localhost:1234/v1",
        "api_key": "lm-studio",
        "text_model": "",
        "vision_model": "",
        "text_model_hint": "qwen3.5-9b",
        "vision_model_hint": "gemma-4-e4b",
    },
}


def normalize_quantity_discount(raw: Any) -> dict[str, float]:
    """Support both {threshold, percentage} and {qty: percent} formats."""
    if not isinstance(raw, dict):
        return dict(DEFAULTS["quantity_discount"])

    if "threshold" in raw and "percentage" in raw:
        threshold = int(raw["threshold"])
        percentage = float(raw["percentage"])
        normalized = {str(k): float(v) for k, v in DEFAULTS["quantity_discount"].items()}
        normalized[str(threshold)] = percentage
        return normalized

    result = {}
    for key, value in raw.items():
        try:
            result[str(int(key))] = float(value)
        except (ValueError, TypeError):
            continue
    return result or dict(DEFAULTS["quantity_discount"])


def load_configuration(config_path: str | None = None) -> dict:
    if config_path is None:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(script_dir, "config.json")

    config = json.loads(json.dumps(DEFAULTS))

    try:
        with open(config_path, encoding="utf-8") as f:
            loaded = json.load(f)
        print("INFO: Configuration loaded successfully from config.json")
        for key, value in loaded.items():
            if isinstance(value, dict) and key in config and key != "quantity_discount":
                config[key].update(value)
            else:
                config[key] = value
    except Exception as exc:
        print(f"ERROR loading config.json: {exc}. Using defaults.")

    config["quantity_discount"] = normalize_quantity_discount(config.get("quantity_discount"))

    if "overhead_percentage" not in config or config.get("overhead_percentage") is None:
        markup = float(config.get("supplier_markup_percentage", 25.0))
        config["overhead_percentage"] = markup
    if "profit_margin_percentage" not in config or config.get("profit_margin_percentage") is None:
        config["profit_margin_percentage"] = 20.0

    return config


def get_precision_tier(precision_level: str) -> str:
    return PRECISION_TIER_MAP.get(precision_level, "medium")


def get_quantity_discount_percent(config: dict, batch_qty: int) -> float:
    rules = config.get("quantity_discount", {})
    thresholds = []
    for key, value in rules.items():
        try:
            thresholds.append((int(key), float(value)))
        except (ValueError, TypeError):
            continue
    thresholds.sort(key=lambda x: x[0], reverse=True)
    for threshold, discount in thresholds:
        if batch_qty >= threshold:
            return discount
    return 0.0


def build_cost_context(config: dict, batch_qty: int, precision_level: str) -> str:
    tier = get_precision_tier(precision_level)
    rules = config.get("rules", {})
    setup_hours = rules.get("setup_time_hours", {})
    surcharges = rules.get("surcharges_percent", {})

    ultra_note = ""
    if precision_level == "Ultra-Precision":
        ultra_note = (
            "\nUltra-Precision: apply tight_tolerance and finish_n6_or_better surcharges "
            "from rules.surcharges_percent."
        )

    return f"""--- Predefined Data for This Analysis (metric units) ---
Hourly Labor Rate (Default fallback): ₹{config.get('labor_rate_per_hour', 800.0):.2f}/hour
Volume Addition for Raw Material: {config.get('volume_addition_percentage', 15.0):.1f}%
Overhead: {config.get('overhead_percentage', 25.0):.1f}% | Profit Margin: {config.get('profit_margin_percentage', 20.0):.1f}%
Batch Quantity: {batch_qty}
Precision Level: {precision_level} (rule tier: {tier}){ultra_note}

Setup Time Hours (tier={tier}): {setup_hours.get(tier, setup_hours.get('medium', 4.0))} h
Drilling Times (min): {rules.get('drilling_time_min', {})}
Threading Times (min): {rules.get('threading_time_min', {})}
Milling Times (min): {rules.get('milling_time_min', {})}
Turning Times (min): {rules.get('turning_time_min', {})}
Non-cutting Times (min): {rules.get('non_cutting_times_min', {})}
Surcharges (%): {surcharges}
Radius Surcharge Rules: {config.get('radius_surcharge_rules', [])}
Extrusion Profiles: {config.get('extrusion_profiles', {})}

Hourly Rates by Process (INR):
{json.dumps(config.get('hourly_rates', []), indent=2)}

Material Data (price_per_kg, density_g_cm3):
{json.dumps(config.get('material_data', {}), indent=2)}

Machinability Modifiers:
{json.dumps(config.get('machinability_modifiers', {}), indent=2)}

Quantity Discount Rules (% off base cost):
{json.dumps(config.get('quantity_discount', {}), indent=2)}
--- End Predefined Data ---

CRITICAL INSTRUCTIONS:
1. Setup and Machining Cost: Both use the SAME hourly rate based on the chosen process (do NOT use a different rate for setup).
2. Weight Calculation Formula (Use this exact math):
   - Step 1: Base Volume (cm³) = (Length_mm × Width_mm × Height_mm) / 1000
   - Step 2: Total Volume (cm³) = Base Volume + Volume Addition for Raw Material (e.g., +15%)
   - Step 3: Weight (kg) = (Total Volume (cm³) × Density (g/cm³)) / 1000
   - Step 4: Material Cost = Weight (kg) × price_per_kg
3. Labor Breakdown Table: You MUST format your labor breakdown as a Markdown table exactly like this:
| Process Name | Setup Time (min) | Machining Time (min) | Total Time (min) | Hourly Rate (₹/hr) | Total Cost (₹) |
|---|---|---|---|---|---|
| ... | ... | ... | ... | ... | ... |

Analyze the drawing and provide detailed cost estimation using the rules above.
At the end include a line: FINAL PER-UNIT ESTIMATED COST: ₹[amount]
Also include a JSON block on its own line:
{{"part_name":"","part_number":"","material":"","final_cost_per_unit":0.0}}
"""


def _material_key(material: str, config: dict) -> str | None:
    if not material:
        return None
    upper = material.upper().replace(" ", "")
    # Direct name match
    for key in config.get("material_data", {}):
        if key.upper().replace(" ", "") in upper or upper in key.upper().replace(" ", ""):
            return key
    # Search equivalent material aliases
    for key, data in config.get("material_data", {}).items():
        for equiv in data.get("equivalents", []):
            if equiv.upper().replace(" ", "") in upper or upper in equiv.upper().replace(" ", ""):
                return key
    # Fallback to machinability family
    for family in config.get("machinability_modifiers", {}):
        if family in upper:
            return family
    return None


def estimate_cost_deterministic(config: dict, features: dict) -> dict:
    """Lightweight rule-based estimate to ground LLM output."""
    rules = config.get("rules", {})
    tier = features.get("complexity_tier", "medium")
    labor_rate = float(config.get("labor_rate_per_hour", 800.0))
    batch_qty = max(int(features.get("batch_qty", 1)), 1)

    setup_h = float(rules.get("setup_time_hours", {}).get(tier, 4.0))
    setup_min_per_unit = (setup_h * 60.0) / batch_qty

    drill = rules.get("drilling_time_min", {})
    thread = rules.get("threading_time_min", {})
    mill = rules.get("milling_time_min", {})
    turn = rules.get("turning_time_min", {})

    small_holes = int(features.get("small_holes", 0))
    large_holes = int(features.get("large_holes", 0))
    small_threads = int(features.get("small_threads", 0))
    large_threads = int(features.get("large_threads", 0))

    material_name = features.get("material", "ALUMINUM")
    mat_key = _material_key(material_name, config)
    mach_mod = 1.0
    for family, mod in config.get("machinability_modifiers", {}).items():
        if family in material_name.upper().replace(" ", ""):
            mach_mod = float(mod)
            break

    drill_min = (
        small_holes * float(drill.get("small_hole", 0.5))
        + large_holes * float(drill.get("large_hole", 1.0))
    ) * mach_mod
    thread_min = (
        small_threads * float(thread.get("small_thread", 1.0))
        + large_threads * float(thread.get("large_thread", 1.5))
    )
    mill_min = float(mill.get(tier, 45.0)) * mach_mod
    turn_min = float(turn.get(tier, 30.0)) * mach_mod

    total_min = setup_min_per_unit + drill_min + thread_min + mill_min + turn_min
    labor_cost = (total_min / 60.0) * labor_rate

    length = float(features.get("length_mm", 50))
    width = float(features.get("width_mm", 50))
    height = float(features.get("height_mm", 20))
    volume_cm3 = (length * width * height) / 1000.0
    volume_cm3 *= 1.0 + float(config.get("volume_addition_percentage", 15.0)) / 100.0

    mat_data = config.get("material_data", {}).get(mat_key or "ALUMINUM", {})
    density = float(mat_data.get("density_g_cm3", 2.8))
    price_kg = float(mat_data.get("price_per_kg", 8.0))
    weight_kg = (volume_cm3 * density) / 1000.0
    material_cost = weight_kg * price_kg

    base = labor_cost + material_cost
    surcharge_pct = 0.0
    if features.get("tight_tolerance"):
        surcharge_pct += float(rules.get("surcharges_percent", {}).get("tight_tolerance", 25.0))
    if features.get("finish_n6"):
        surcharge_pct += float(rules.get("surcharges_percent", {}).get("finish_n6_or_better", 20.0))
    elif features.get("finish_n7"):
        surcharge_pct += float(rules.get("surcharges_percent", {}).get("finish_n7", 13.0))

    min_radius = features.get("min_radius_mm")
    if min_radius is not None:
        for rule in config.get("radius_surcharge_rules", []):
            if float(min_radius) <= float(rule.get("if_smaller_or_equal_to_mm", 0)):
                surcharge_pct += float(rule.get("add_percent", 0))
                break

    total = base * (1.0 + surcharge_pct / 100.0)
    return {
        "labor_cost": round(labor_cost, 2),
        "material_cost": round(material_cost, 2),
        "weight_kg": round(weight_kg, 4),
        "total_minutes": round(total_min, 2),
        "surcharge_percent": surcharge_pct,
        "estimated_cost_per_unit": round(total, 2),
    }


def extract_structured_json(response_text: str) -> dict | None:
    """Parse trailing JSON block from LLM response."""
    patterns = [
        r'\{[^{}]*"part_name"[^{}]*"final_cost_per_unit"[^{}]*\}',
        r'\{[^{}]*"final_cost_per_unit"[^{}]*\}',
    ]
    for pattern in patterns:
        matches = re.findall(pattern, response_text, re.DOTALL | re.IGNORECASE)
        for match in reversed(matches):
            try:
                data = json.loads(match)
                if isinstance(data, dict):
                    return data
            except json.JSONDecodeError:
                continue
    return None


def extract_part_info_from_response(response_text: str) -> dict:
    structured = extract_structured_json(response_text)
    part_info = {"name": "N/A", "number": "N/A", "material": "N/A"}
    if structured:
        part_info["name"] = structured.get("part_name") or part_info["name"]
        part_info["number"] = structured.get("part_number") or part_info["number"]
        part_info["material"] = structured.get("material") or part_info["material"]

    for line in response_text.split("\n"):
        line = line.strip()
        if part_info["name"] == "N/A" and ("Part Name:" in line or "Part:" in line):
            part_info["name"] = line.split(":")[-1].strip().replace("*", "") or part_info["name"]
        elif part_info["number"] == "N/A" and ("Part Number:" in line or "Drawing Number:" in line):
            part_info["number"] = line.split(":")[-1].strip().replace("*", "") or part_info["number"]
        elif part_info["material"] == "N/A" and "Material:" in line:
            part_info["material"] = line.split(":")[-1].strip().replace("*", "") or part_info["material"]
    return part_info


def extract_cost_info_from_response(response_text: str) -> dict:
    cost_info = {"base_cost": 0.0, "extracted": False}
    structured = extract_structured_json(response_text)
    if structured and structured.get("final_cost_per_unit") is not None:
        try:
            cost_info["base_cost"] = float(structured["final_cost_per_unit"])
            cost_info["extracted"] = True
            return cost_info
        except (TypeError, ValueError):
            pass

    for line in response_text.split("\n"):
        if "FINAL PER-UNIT ESTIMATED COST:" in line:
            match = re.search(r"(?:₹|Rs\.?|INR|\$)(\d+\.?\d*)", line)
            if match:
                cost_info["base_cost"] = float(match.group(1))
                cost_info["extracted"] = True
                return cost_info
        if any(c in line for c in ("₹", "Rs", "INR", "$")) and ("cost" in line.lower() or "price" in line.lower()):
            match = re.search(r"(?:₹|Rs\.?|INR|\$)(\d+\.?\d*)", line)
            if match and cost_info["base_cost"] == 0.0:
                cost_info["base_cost"] = float(match.group(1))
                cost_info["extracted"] = True
    if cost_info["base_cost"] == 0.0:
        cost_info["base_cost"] = 50.0
        cost_info["extracted"] = False
    return cost_info
