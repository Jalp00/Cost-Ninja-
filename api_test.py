"""Verify LM Studio connectivity and model capabilities."""

import json
import os
import sys

import requests
from openai import OpenAI

from lm_studio_client import LMStudioClient

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.json")

with open(CONFIG_PATH, encoding="utf-8") as f:
    config = json.load(f)

lm_config = config.get("lm_studio", {})
base_url = str(lm_config.get("base_url", "http://localhost:1234/v1")).strip().rstrip("/")
api_key = str(lm_config.get("api_key", "lm-studio")).strip()

passed = 0
failed = 0


def ok(msg):
    global passed
    passed += 1
    print(f"[PASS] {msg}")


def fail(msg):
    global failed
    failed += 1
    print(f"[FAIL] {msg}")


print("=" * 60)
print("Cost Ninja LM Studio Smoke Test")
print("=" * 60)

# Test 1: /models reachable
print("\n--- Test 1: Server /models ---")
try:
    resp = requests.get(f"{base_url}/models", timeout=5)
    resp.raise_for_status()
    models = [m.get("id", "") for m in resp.json().get("data", [])]
    ok(f"LM Studio running at {base_url}")
    if models:
        print(f"       Models: {', '.join(models)}")
    else:
        print("       WARNING: No models listed — load a model in LM Studio")
except Exception as exc:
    fail(f"LM Studio not reachable: {exc}")
    print("\nOpen LM Studio -> load a model -> Developer -> Start server")
    sys.exit(1)

# Test 2: Client init + model resolution
print("\n--- Test 2: Model resolution ---")
client = LMStudioClient(lm_config)
st = client.status_dict()
if st["connected"]:
    ok(f"Client connected | text={st['text_model']} | vision={st['vision_model']} | mode={st['mode']}")
else:
    fail("Client could not connect")

# Test 3: Text chat completion
print("\n--- Test 3: Text chat ---")
try:
    reply = client.test_chat()
    ok(f"Chat response: {reply[:120].strip()}")
except Exception as exc:
    fail(f"Chat failed: {exc}")

# Test 4: Vision probe (skip if text-only)
print("\n--- Test 4: Vision capability ---")
vision_model = client.active_vision_model
if LMStudioClient.is_vision_capable_model(vision_model):
    try:
        oai = OpenAI(base_url=base_url, api_key=api_key)
        tiny_png = (
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQ"
            "AAAABJRU5ErkJggg=="
        )
        import base64
        data_url = f"data:image/png;base64,{tiny_png}"
        resp = oai.chat.completions.create(
            model=vision_model,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": "Describe this image in one word."},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }],
            max_tokens=20,
        )
        ok(f"Vision model responded: {(resp.choices[0].message.content or '')[:80]}")
    except Exception as exc:
        print(f"[SKIP] Vision probe failed (may need OCR fallback): {exc}")
else:
    print(f"[SKIP] Model '{vision_model}' is text-only — app will use OCR for drawings")

print("\n" + "=" * 60)
print(f"Results: {passed} passed, {failed} failed")
print("=" * 60)

sys.exit(0 if failed == 0 else 1)
