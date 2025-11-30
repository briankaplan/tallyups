#!/usr/bin/env python3
"""
Gemini API Utility with Automatic Key Fallback
Provides a shared Gemini client that automatically switches API keys when quota is exceeded
"""
import os
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

# Load all available API keys
GEMINI_API_KEYS = [
    os.getenv('GEMINI_API_KEY'),
    os.getenv('GEMINI_API_KEY_2'),
    os.getenv('GEMINI_API_KEY_3')
]
GEMINI_API_KEYS = [k for k in GEMINI_API_KEYS if k]  # Filter out None values

_current_key_index = 0
_model = None

def _configure_with_key(index):
    """Configure Gemini with the API key at the given index"""
    global _model
    if index < len(GEMINI_API_KEYS):
        genai.configure(api_key=GEMINI_API_KEYS[index])
        # Use stable model - gemini-2.0-flash is faster and more reliable
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
    """Switch to the next API key. Returns True if successful, False if all keys exhausted"""
    global _current_key_index
    _current_key_index += 1
    if _current_key_index < len(GEMINI_API_KEYS):
        print(f"   🔄 Switching to Gemini API key #{_current_key_index + 1} of {len(GEMINI_API_KEYS)}")
        return _configure_with_key(_current_key_index)
    print("   ❌ All Gemini API keys exhausted!")
    return False

def reset_to_first_key():
    """Reset to the first API key"""
    global _current_key_index
    _current_key_index = 0
    _configure_with_key(0)

def generate_content_with_fallback(prompt, image=None, max_retries=3, retry_delay=30):
    """
    Generate content with automatic API key fallback on quota errors

    Args:
        prompt: The text prompt
        image: Optional PIL Image for vision tasks
        max_retries: Max retries per key before switching
        retry_delay: Seconds to wait before retrying on rate limit

    Returns:
        Generated content text or None on failure
    """
    import time
    global _current_key_index

    model = get_model()
    if not model:
        return None

    retries = 0
    keys_tried = 0

    while True:
        try:
            if image:
                response = model.generate_content([prompt, image])
            else:
                response = model.generate_content(prompt)
            return response.text

        except Exception as e:
            error_str = str(e).lower()

            # Check for quota/rate limit errors
            if 'quota' in error_str or 'rate' in error_str or '429' in error_str or 'resource' in error_str:
                # Extract retry delay from error if available
                import re
                delay_match = re.search(r'retry in (\d+)', error_str)
                actual_delay = int(delay_match.group(1)) + 2 if delay_match else retry_delay

                # Try waiting first before switching keys (rate limits reset quickly)
                if retries < 1:
                    print(f"   ⏳ Rate limited, waiting {actual_delay}s before retry...")
                    time.sleep(actual_delay)
                    retries += 1
                    continue

                # If still failing after wait, try next key
                print(f"   ⚠️  API quota exceeded on key #{_current_key_index + 1}")
                keys_tried += 1

                if keys_tried >= len(GEMINI_API_KEYS):
                    # All keys tried, wait and reset to first key
                    print(f"   🔄 All keys rate limited, waiting {actual_delay}s and retrying key #1...")
                    time.sleep(actual_delay)
                    reset_to_first_key()
                    model = get_model()
                    keys_tried = 0
                    retries = 0
                    continue

                if switch_to_next_key():
                    model = get_model()
                    retries = 0
                    continue
                else:
                    return None

            # Other errors - retry a few times
            retries += 1
            if retries >= max_retries:
                print(f"   ❌ Gemini error after {max_retries} retries: {e}")
                return None
            print(f"   ⚠️  Gemini error (retry {retries}/{max_retries}): {e}")

def analyze_receipt_image(image, prompt=None):
    """
    Analyze a receipt image using Gemini Vision

    Args:
        image: PIL Image object
        prompt: Optional custom prompt (uses default receipt analysis prompt if not provided)

    Returns:
        Dict with merchant, amount, date, description or None on failure
    """
    if prompt is None:
        prompt = """Analyze this receipt image and extract:
1. Merchant/store name
2. Total amount (just the number, e.g. 42.99)
3. Date (YYYY-MM-DD format if possible)
4. Brief description of purchase

Return as JSON: {"merchant": "...", "amount": 42.99, "date": "...", "description": "..."}
Only return the JSON, no other text."""

    result = generate_content_with_fallback(prompt, image)
    if result:
        try:
            import json
            # Clean up response - sometimes Gemini adds markdown code blocks
            result = result.strip()
            if result.startswith('```'):
                result = result.split('\n', 1)[1]
            if result.endswith('```'):
                result = result.rsplit('```', 1)[0]
            result = result.strip()
            return json.loads(result)
        except:
            pass
    return None

def analyze_email_content(subject, body, from_email):
    """
    Analyze email content to extract receipt information

    Args:
        subject: Email subject
        body: Email body text
        from_email: Sender email address

    Returns:
        Tuple of (merchant, amount, description, is_subscription) or (None, None, None, False) on failure
    """
    prompt = f"""Analyze this email and extract receipt information:

Subject: {subject}
From: {from_email}
Body: {body[:2000]}

Extract:
1. Merchant/company name
2. Total amount charged (number only, e.g. 19.99)
3. Brief description of what was purchased
4. Is this a subscription? (true/false)

Return as JSON: {{"merchant": "...", "amount": 19.99, "description": "...", "is_subscription": false}}
Only return the JSON, no other text."""

    result = generate_content_with_fallback(prompt)
    if result:
        try:
            import json
            result = result.strip()
            if result.startswith('```'):
                result = result.split('\n', 1)[1]
            if result.endswith('```'):
                result = result.rsplit('```', 1)[0]
            result = result.strip()
            data = json.loads(result)
            return (
                data.get('merchant'),
                data.get('amount'),
                data.get('description'),
                data.get('is_subscription', False)
            )
        except:
            pass
    return (None, None, None, False)


def extract_receipt_from_html_email(html_content: str, subject: str = "", sender: str = ""):
    """
    Extract receipt data from raw HTML email content using Gemini.
    Works without browser - suitable for Railway deployment.

    Args:
        html_content: Raw HTML email content
        subject: Email subject for context
        sender: Sender email for context

    Returns:
        Dict with merchant, amount, date, description or None on failure
    """
    import re
    from html.parser import HTMLParser

    # Strip HTML tags to get plain text
    class HTMLTextExtractor(HTMLParser):
        def __init__(self):
            super().__init__()
            self.text_parts = []
            self.skip_data = False

        def handle_starttag(self, tag, attrs):
            if tag in ['script', 'style', 'head']:
                self.skip_data = True

        def handle_endtag(self, tag):
            if tag in ['script', 'style', 'head']:
                self.skip_data = False
            if tag in ['p', 'div', 'tr', 'br', 'li']:
                self.text_parts.append('\n')

        def handle_data(self, data):
            if not self.skip_data:
                self.text_parts.append(data)

    try:
        parser = HTMLTextExtractor()
        parser.feed(html_content)
        plain_text = ' '.join(parser.text_parts)
        # Clean up whitespace
        plain_text = re.sub(r'\s+', ' ', plain_text).strip()
    except:
        # Fallback: crude HTML strip
        plain_text = re.sub(r'<[^>]+>', ' ', html_content)
        plain_text = re.sub(r'\s+', ' ', plain_text).strip()

    # Limit text length for API
    plain_text = plain_text[:4000]

    prompt = f"""Extract receipt/invoice information from this email:

Subject: {subject}
From: {sender}

Email Content:
{plain_text}

Extract the following (be precise with numbers):
1. merchant_name: The business/company name
2. merchant_normalized: Simplified merchant name (e.g., "Soho House Nashville" → "soho house")
3. receipt_date: Transaction date in YYYY-MM-DD format (or empty string if not found)
4. subtotal_amount: Subtotal before tax/tip (number only, 0 if not shown)
5. tip_amount: Tip amount (number only, 0 if not shown)
6. total_amount: FINAL total charged (number only)

Return ONLY valid JSON:
{{"merchant_name": "...", "merchant_normalized": "...", "receipt_date": "YYYY-MM-DD", "subtotal_amount": 0.0, "tip_amount": 0.0, "total_amount": 123.45}}"""

    result = generate_content_with_fallback(prompt)
    if result:
        try:
            import json
            result = result.strip()
            if result.startswith('```'):
                result = result.split('\n', 1)[1]
            if result.endswith('```'):
                result = result.rsplit('```', 1)[0]
            result = result.strip()
            data = json.loads(result)

            # Validate we got meaningful data
            if data.get('merchant_name') and data.get('total_amount'):
                return {
                    'merchant_name': data.get('merchant_name', ''),
                    'merchant_normalized': data.get('merchant_normalized', ''),
                    'receipt_date': data.get('receipt_date', ''),
                    'subtotal_amount': float(data.get('subtotal_amount', 0) or 0),
                    'tip_amount': float(data.get('tip_amount', 0) or 0),
                    'total_amount': float(data.get('total_amount', 0) or 0),
                    'ocr_source': 'gemini_html_extraction',
                }
        except Exception as e:
            print(f"   ⚠️ Gemini HTML extraction parse error: {e}")
    return None

# Initialize on import
_configure_with_key(0)

if __name__ == '__main__':
    # Test the utility
    print(f"Loaded {len(GEMINI_API_KEYS)} Gemini API keys")
    print(f"Current key index: {_current_key_index}")

    # Test a simple generation
    result = generate_content_with_fallback("Say 'Hello, API key fallback works!'")
    print(f"Test result: {result}")
