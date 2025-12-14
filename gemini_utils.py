#!/usr/bin/env python3
"""
AI API Utility - OpenAI Primary, Gemini Fallback
Provides shared AI clients with automatic fallback between providers
"""
import os
from dotenv import load_dotenv

load_dotenv()

# =============================================================================
# OpenAI (PRIMARY)
# =============================================================================
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
_openai_client = None

def get_openai_client():
    """Get or create OpenAI client"""
    global _openai_client
    if _openai_client is None and OPENAI_API_KEY:
        try:
            from openai import OpenAI
            _openai_client = OpenAI(api_key=OPENAI_API_KEY)
        except ImportError:
            print("⚠️ OpenAI package not installed")
    return _openai_client

def generate_with_openai(prompt, max_tokens=1000):
    """Generate content using OpenAI GPT-4o-mini"""
    client = get_openai_client()
    if not client:
        return None
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=0.3
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"   ❌ OpenAI error: {e}")
        return None

def analyze_image_with_openai(image, prompt):
    """Analyze image using OpenAI GPT-4o vision"""
    import base64
    from io import BytesIO

    client = get_openai_client()
    if not client:
        return None

    try:
        # Convert PIL image to base64
        buffered = BytesIO()
        image.save(buffered, format="JPEG")
        image_base64 = base64.b64encode(buffered.getvalue()).decode('utf-8')

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}}
                ]
            }],
            max_tokens=1000,
            temperature=0.3
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"   ❌ OpenAI vision error: {e}")
        return None

# =============================================================================
# Gemini (FALLBACK)
# =============================================================================
import google.generativeai as genai

GEMINI_API_KEYS = [
    os.getenv('GEMINI_API_KEY'),
    os.getenv('GEMINI_API_KEY_2'),
    os.getenv('GEMINI_API_KEY_3')
]
GEMINI_API_KEYS = [k for k in GEMINI_API_KEYS if k]

_current_key_index = 0
_model = None

def _configure_with_key(index):
    """Configure Gemini with the API key at the given index"""
    global _model
    if index < len(GEMINI_API_KEYS):
        genai.configure(api_key=GEMINI_API_KEYS[index])
        _model = genai.GenerativeModel('gemini-2.0-flash')
        return True
    return False

def get_model():
    """Get the current Gemini model"""
    global _model, _current_key_index
    if _model is None:
        _configure_with_key(_current_key_index)
    return _model

def switch_to_next_key():
    """Switch to the next Gemini API key"""
    global _current_key_index
    _current_key_index += 1
    if _current_key_index < len(GEMINI_API_KEYS):
        print(f"   🔄 Switching to Gemini API key #{_current_key_index + 1} of {len(GEMINI_API_KEYS)}")
        return _configure_with_key(_current_key_index)
    return False

def reset_to_first_key():
    """Reset to the first API key"""
    global _current_key_index
    _current_key_index = 0
    _configure_with_key(0)

def generate_with_gemini(prompt, image=None, max_retries=2):
    """Generate content using Gemini (used as fallback) with proper exponential backoff"""
    import time
    import random

    model = get_model()
    if not model:
        return None

    for attempt in range(max_retries):
        try:
            if image:
                response = model.generate_content([prompt, image])
            else:
                response = model.generate_content(prompt)
            return response.text
        except Exception as e:
            error_str = str(e).lower()
            is_rate_limit = any(term in error_str for term in ['quota', 'rate', '429', 'resource'])

            if is_rate_limit:
                # Exponential backoff BEFORE switching keys
                delay = min(2 ** attempt, 30) * (0.5 + random.random())
                print(f"   ⚠️ Gemini rate limited, waiting {delay:.1f}s before retry...")
                time.sleep(delay)

                if switch_to_next_key():
                    model = get_model()
                    continue
                else:
                    # All keys exhausted - longer backoff before giving up
                    exhausted_delay = 60 + random.uniform(0, 60)
                    print(f"   ❌ All Gemini keys exhausted, backing off {exhausted_delay:.0f}s")
                    time.sleep(exhausted_delay)
                    reset_to_first_key()
                    return None

            if attempt < max_retries - 1:
                # Exponential backoff for non-rate-limit errors
                delay = min(2 ** attempt, 30) * (0.5 + random.random())
                print(f"   ⚠️ Gemini error, retrying in {delay:.1f}s...")
                time.sleep(delay)
                continue

            print(f"   ❌ Gemini error: {e}")
            return None

    return None

# =============================================================================
# MAIN INTERFACE - OpenAI First, Gemini Fallback
# =============================================================================

def generate_content_with_fallback(prompt, image=None, max_retries=3, **kwargs):
    """
    Generate content - tries OpenAI first, falls back to Gemini.

    Args:
        prompt: The text prompt
        image: Optional PIL Image for vision tasks
        max_retries: Max retries (default 3)

    Returns:
        Generated content text or None on failure
    """
    # Try OpenAI first (primary)
    if image:
        result = analyze_image_with_openai(image, prompt)
    else:
        result = generate_with_openai(prompt)

    if result:
        return result

    # Fall back to Gemini
    print("   🔄 OpenAI failed, trying Gemini fallback...")
    result = generate_with_gemini(prompt, image, max_retries)

    if result:
        print("   ✅ Gemini fallback successful")
        return result

    print("   ❌ All AI providers failed")
    return None


def analyze_receipt_image(image, prompt=None):
    """
    Analyze a receipt image using AI vision (OpenAI primary, Gemini fallback)

    Args:
        image: PIL Image object
        prompt: Optional custom prompt

    Returns:
        Dict with merchant, amount, date, description or None on failure
    """
    import json

    if prompt is None:
        prompt = """Analyze this receipt image and extract:
1. Merchant/store name
2. Total amount (just the number, e.g. 42.99)
3. Date (YYYY-MM-DD format if possible)
4. Brief description of purchase

Return ONLY valid JSON:
{"merchant": "...", "amount": 42.99, "date": "2024-01-15", "description": "..."}"""

    response_text = generate_content_with_fallback(prompt, image)

    if not response_text:
        return None

    try:
        response_text = response_text.strip()
        response_text = response_text.replace('```json', '').replace('```', '').strip()
        return json.loads(response_text)
    except json.JSONDecodeError as e:
        print(f"   ⚠️ Could not parse AI response as JSON: {e}")
        return {"raw_response": response_text}


# Legacy compatibility - these functions now use OpenAI by default
def calculate_backoff_delay(attempt: int, base_delay: float = 1.0, max_delay: float = 60.0, jitter: bool = True) -> float:
    """Calculate exponential backoff delay (kept for compatibility)"""
    import random
    delay = min(base_delay * (2 ** attempt), max_delay)
    if jitter:
        delay = delay * (0.5 + random.random())
    return delay
