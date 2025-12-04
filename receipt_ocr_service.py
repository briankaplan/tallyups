#!/usr/bin/env python3
"""
Unified Receipt OCR Service
- Primary: Gemini 2.0 Flash (FREE with your API keys)
- Fallback: Local Llama 3.2 Vision (Ollama)
- Output: Mindee-compatible schema

Integrates with:
- /mobile-upload endpoint
- Receipt verification pipeline
- Transaction matching system
"""

import os
import io
import json
import base64
import re
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime

from PIL import Image
from pdf2image import convert_from_path

# Import existing utilities
try:
    from gemini_utils import generate_content_with_fallback, get_model
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False
    print("⚠️  Gemini utils not available")

try:
    import ollama
    OLLAMA_AVAILABLE = True
except ImportError:
    OLLAMA_AVAILABLE = False


class ReceiptOCRService:
    """
    Production-ready receipt OCR with Mindee-quality extraction.

    Usage:
        service = ReceiptOCRService()
        result = service.extract("/path/to/receipt.pdf")

        # Result schema:
        {
            "supplier_name": "CLEAR",
            "supplier_address": "85 10th Avenue...",
            "supplier_phone": None,
            "receipt_number": "7994BFE1-0001",
            "date": "2025-10-21",
            "time": None,
            "total_amount": 334.00,
            "subtotal": 334.00,
            "tax_amount": 0.0,
            "tip_amount": 0.0,
            "line_items": [...],
            "payment_method": "Visa - 6771",
            "currency": "USD",
            "confidence": 0.95,
            "ocr_method": "gemini"
        }
    """

    # Detailed extraction prompt (same quality as Llama Vision)
    EXTRACTION_PROMPT = """You are a precise receipt OCR system. Extract ALL information from this receipt image.

Return ONLY a valid JSON object with these exact fields (use null for missing values):
{
    "supplier_name": "business/merchant name",
    "supplier_address": "full address including city, state, zip",
    "supplier_phone": "phone number or null",
    "receipt_number": "invoice/receipt/order number",
    "date": "YYYY-MM-DD format",
    "time": "HH:MM format or null",
    "total_amount": 0.00,
    "subtotal": 0.00,
    "tax_amount": 0.00,
    "tip_amount": 0.00,
    "line_items": [
        {"description": "item name", "quantity": 1, "unit_price": 0.00, "total_price": 0.00}
    ],
    "payment_method": "card type and last 4 digits",
    "currency": "USD"
}

IMPORTANT:
- Extract the EXACT merchant/business name (not address or other text)
- Use numeric values for amounts (no $ signs)
- Date must be YYYY-MM-DD format
- Include ALL line items with their prices
- Return ONLY valid JSON, no markdown, no explanation"""

    def __init__(self, prefer_local: bool = False):
        """
        Initialize OCR service.

        Args:
            prefer_local: If True, prefer Ollama over Gemini (for testing)
        """
        self.prefer_local = prefer_local
        self._validate_services()

    def _validate_services(self):
        """Check which services are available"""
        self.gemini_ready = GEMINI_AVAILABLE
        self.ollama_ready = OLLAMA_AVAILABLE

        if self.ollama_ready:
            try:
                # Check if llama3.2-vision is available
                models = ollama.list()
                model_names = [m.get('name', '') for m in models.get('models', [])]
                self.ollama_ready = any('llama3.2-vision' in n or 'llava' in n for n in model_names)
            except:
                self.ollama_ready = False

    def _load_image(self, image_path: str) -> Image.Image:
        """Load image from file path (supports PDF, PNG, JPG, HEIC, etc.)"""
        path = Path(image_path)

        if path.suffix.lower() == '.pdf':
            images = convert_from_path(str(path))
            return images[0].convert("RGB")
        else:
            return Image.open(path).convert("RGB")

    def _image_to_base64(self, image: Image.Image) -> str:
        """Convert PIL Image to base64 string"""
        buffer = io.BytesIO()
        image.save(buffer, format='PNG')
        return base64.b64encode(buffer.getvalue()).decode()

    def _extract_with_gemini(self, image: Image.Image) -> Optional[Dict[str, Any]]:
        """Extract using Gemini Vision API"""
        if not self.gemini_ready:
            return None

        try:
            result = generate_content_with_fallback(self.EXTRACTION_PROMPT, image)
            if result:
                return self._parse_json_response(result, "gemini")
        except Exception as e:
            print(f"⚠️  Gemini extraction error: {e}")

        return None

    def _extract_with_ollama(self, image: Image.Image) -> Optional[Dict[str, Any]]:
        """Extract using local Ollama Llama Vision"""
        if not self.ollama_ready:
            return None

        try:
            img_base64 = self._image_to_base64(image)

            response = ollama.chat(
                model='llama3.2-vision',
                messages=[{
                    'role': 'user',
                    'content': self.EXTRACTION_PROMPT,
                    'images': [img_base64]
                }],
                options={'temperature': 0}
            )

            result = response['message']['content']
            return self._parse_json_response(result, "ollama")

        except Exception as e:
            print(f"⚠️  Ollama extraction error: {e}")

        return None

    def _parse_json_response(self, response: str, method: str) -> Optional[Dict[str, Any]]:
        """Parse JSON from model response"""
        try:
            # Clean up response
            response = response.strip()

            # Remove markdown code blocks
            if '```json' in response:
                response = response.split('```json')[1].split('```')[0]
            elif '```' in response:
                response = response.split('```')[1].split('```')[0]

            # Find JSON object
            start = response.find('{')
            end = response.rfind('}') + 1

            if start >= 0 and end > start:
                json_str = response[start:end]
                data = json.loads(json_str)

                # Add metadata
                data['ocr_method'] = method
                data['confidence'] = self._calculate_confidence(data)

                # Normalize data
                return self._normalize_result(data)

        except json.JSONDecodeError as e:
            print(f"⚠️  JSON parse error: {e}")
            # Try to extract key fields from free-form text
            return self._parse_freeform_response(response, method)

        return None

    def _parse_freeform_response(self, text: str, method: str) -> Optional[Dict[str, Any]]:
        """Parse free-form text response when JSON fails"""
        result = {
            "supplier_name": None,
            "supplier_address": None,
            "supplier_phone": None,
            "receipt_number": None,
            "date": None,
            "time": None,
            "total_amount": None,
            "subtotal": None,
            "tax_amount": None,
            "tip_amount": None,
            "line_items": [],
            "payment_method": None,
            "currency": "USD",
            "ocr_method": method,
            "confidence": 0.5
        }

        lines = text.split('\n')

        for line in lines:
            line_lower = line.lower()

            # Extract values using patterns
            if 'supplier' in line_lower or 'merchant' in line_lower:
                match = re.search(r'[:\s]+([A-Z][^\n*]+)', line)
                if match:
                    result['supplier_name'] = match.group(1).strip().strip('*')

            if 'total' in line_lower and ('amount' in line_lower or 'paid' in line_lower):
                match = re.search(r'\$?([\d,]+\.?\d*)', line)
                if match:
                    try:
                        result['total_amount'] = float(match.group(1).replace(',', ''))
                    except:
                        pass

            if 'date' in line_lower:
                match = re.search(r'(\d{4}-\d{2}-\d{2})', line)
                if match:
                    result['date'] = match.group(1)
                else:
                    # Try month name format
                    result['date'] = self._parse_date_string(line)

        return result if result['supplier_name'] or result['total_amount'] else None

    def _parse_date_string(self, text: str) -> Optional[str]:
        """Parse various date formats to YYYY-MM-DD"""
        months = {
            'january': 1, 'february': 2, 'march': 3, 'april': 4,
            'may': 5, 'june': 6, 'july': 7, 'august': 8,
            'september': 9, 'october': 10, 'november': 11, 'december': 12
        }

        text_lower = text.lower()

        for month_name, month_num in months.items():
            if month_name in text_lower:
                match = re.search(rf'{month_name}\s+(\d{{1,2}}),?\s+(\d{{4}})', text_lower)
                if match:
                    day = int(match.group(1))
                    year = int(match.group(2))
                    return f"{year:04d}-{month_num:02d}-{day:02d}"

        return None

    def _normalize_result(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize and clean extracted data"""

        # Ensure numeric fields are floats
        for field in ['total_amount', 'subtotal', 'tax_amount', 'tip_amount']:
            if data.get(field):
                try:
                    val = data[field]
                    if isinstance(val, str):
                        val = val.replace('$', '').replace(',', '')
                    data[field] = float(val)
                except:
                    data[field] = None

        # Normalize line items
        if data.get('line_items'):
            normalized_items = []
            for item in data['line_items']:
                if isinstance(item, dict) and item.get('description'):
                    normalized_item = {
                        'description': str(item.get('description', '')),
                        'quantity': int(item.get('quantity', 1) or 1),
                        'unit_price': float(item.get('unit_price', 0) or 0),
                        'total_price': float(item.get('total_price', 0) or 0)
                    }
                    normalized_items.append(normalized_item)
            data['line_items'] = normalized_items

        # Clean string fields
        for field in ['supplier_name', 'supplier_address', 'receipt_number', 'payment_method']:
            if data.get(field):
                data[field] = str(data[field]).strip().strip('*').strip()

        return data

    def _calculate_confidence(self, data: Dict[str, Any]) -> float:
        """Calculate confidence score based on extracted fields"""
        required_fields = ['supplier_name', 'date', 'total_amount']
        optional_fields = ['supplier_address', 'receipt_number', 'subtotal', 'line_items', 'payment_method']

        score = 0.0

        # Required fields (60% of score)
        for field in required_fields:
            if data.get(field):
                score += 0.2

        # Optional fields (40% of score)
        for field in optional_fields:
            if data.get(field):
                if field == 'line_items' and len(data.get('line_items', [])) > 0:
                    score += 0.08
                elif data.get(field):
                    score += 0.08

        return min(1.0, score)

    def extract(self, image_path: str) -> Dict[str, Any]:
        """
        Extract receipt data from image file.

        Args:
            image_path: Path to image or PDF file

        Returns:
            Dictionary with Mindee-compatible schema
        """
        # Load image
        image = self._load_image(image_path)

        return self.extract_from_image(image)

    def extract_from_image(self, image: Image.Image) -> Dict[str, Any]:
        """
        Extract receipt data from PIL Image.

        Args:
            image: PIL Image object

        Returns:
            Dictionary with Mindee-compatible schema
        """
        result = None

        # Try extraction methods in order
        if self.prefer_local and self.ollama_ready:
            result = self._extract_with_ollama(image)
            if not result and self.gemini_ready:
                result = self._extract_with_gemini(image)
        else:
            if self.gemini_ready:
                result = self._extract_with_gemini(image)
            if not result and self.ollama_ready:
                result = self._extract_with_ollama(image)

        # Return empty result if extraction failed
        if not result:
            return {
                "supplier_name": None,
                "supplier_address": None,
                "supplier_phone": None,
                "receipt_number": None,
                "date": None,
                "time": None,
                "total_amount": None,
                "subtotal": None,
                "tax_amount": None,
                "tip_amount": None,
                "line_items": [],
                "payment_method": None,
                "currency": "USD",
                "ocr_method": "failed",
                "confidence": 0.0
            }

        return result

    def verify_receipt(self, image_path: str, expected: Dict[str, Any]) -> Dict[str, Any]:
        """
        Verify receipt matches expected transaction data.

        Args:
            image_path: Path to receipt image
            expected: Dict with expected values {merchant, amount, date}

        Returns:
            Dict with match status and details
        """
        extracted = self.extract(image_path)

        verification = {
            "extracted": extracted,
            "expected": expected,
            "matches": {},
            "overall_match": False,
            "confidence": 0.0
        }

        # Check merchant match (fuzzy)
        if extracted.get('supplier_name') and expected.get('merchant'):
            ext_merchant = extracted['supplier_name'].lower().strip()
            exp_merchant = expected['merchant'].lower().strip()

            # Simple fuzzy match
            merchant_match = (
                ext_merchant in exp_merchant or
                exp_merchant in ext_merchant or
                self._fuzzy_match(ext_merchant, exp_merchant) > 0.7
            )
            verification['matches']['merchant'] = merchant_match

        # Check amount match (within tolerance)
        if extracted.get('total_amount') and expected.get('amount'):
            amount_diff = abs(extracted['total_amount'] - expected['amount'])
            amount_match = amount_diff < 0.02  # Within 2 cents
            verification['matches']['amount'] = amount_match

        # Check date match (within 3 days)
        if extracted.get('date') and expected.get('date'):
            try:
                ext_date = datetime.strptime(extracted['date'], '%Y-%m-%d')
                exp_date = datetime.strptime(expected['date'], '%Y-%m-%d')
                date_diff = abs((ext_date - exp_date).days)
                date_match = date_diff <= 3
                verification['matches']['date'] = date_match
            except:
                verification['matches']['date'] = False

        # Calculate overall match
        matches = verification['matches']
        if matches.get('amount', False):  # Amount is most important
            if matches.get('merchant', False) or matches.get('date', False):
                verification['overall_match'] = True
                verification['confidence'] = 0.95
            else:
                verification['confidence'] = 0.7

        return verification

    def _fuzzy_match(self, str1: str, str2: str) -> float:
        """Simple fuzzy string match ratio"""
        if not str1 or not str2:
            return 0.0

        # Normalize
        str1 = re.sub(r'[^a-z0-9]', '', str1.lower())
        str2 = re.sub(r'[^a-z0-9]', '', str2.lower())

        if not str1 or not str2:
            return 0.0

        # Check containment
        if str1 in str2 or str2 in str1:
            return 0.9

        # Simple character overlap ratio
        common = set(str1) & set(str2)
        return len(common) / max(len(set(str1)), len(set(str2)))


# Convenience functions for integration
_service = None

def get_ocr_service() -> ReceiptOCRService:
    """Get singleton OCR service instance"""
    global _service
    if _service is None:
        _service = ReceiptOCRService()
    return _service

def extract_receipt(image_path: str) -> Dict[str, Any]:
    """Extract receipt data from image file"""
    return get_ocr_service().extract(image_path)

def extract_receipt_from_image(image: Image.Image) -> Dict[str, Any]:
    """Extract receipt data from PIL Image"""
    return get_ocr_service().extract_from_image(image)

def verify_receipt(image_path: str, merchant: str = None, amount: float = None, date: str = None) -> Dict[str, Any]:
    """Verify receipt matches expected transaction"""
    expected = {
        'merchant': merchant,
        'amount': amount,
        'date': date
    }
    return get_ocr_service().verify_receipt(image_path, expected)


if __name__ == '__main__':
    import sys

    if len(sys.argv) < 2:
        print("Usage: python receipt_ocr_service.py <image_path> [expected_amount]")
        print("\nExamples:")
        print("  python receipt_ocr_service.py receipt.pdf")
        print("  python receipt_ocr_service.py receipt.jpg 334.00")
        sys.exit(1)

    image_path = sys.argv[1]
    expected_amount = float(sys.argv[2]) if len(sys.argv) > 2 else None

    service = ReceiptOCRService()

    print(f"🔍 Extracting from: {image_path}")
    print(f"   Gemini: {'✅ Ready' if service.gemini_ready else '❌ Not available'}")
    print(f"   Ollama: {'✅ Ready' if service.ollama_ready else '❌ Not available'}")
    print("=" * 60)

    result = service.extract(image_path)

    print("\n📋 EXTRACTED DATA:")
    print("=" * 60)

    # Pretty print key fields
    print(f"   Merchant:    {result.get('supplier_name')}")
    print(f"   Address:     {result.get('supplier_address')}")
    print(f"   Date:        {result.get('date')}")
    print(f"   Total:       ${result.get('total_amount')}")
    print(f"   Subtotal:    ${result.get('subtotal')}")
    print(f"   Tax:         ${result.get('tax_amount')}")
    print(f"   Tip:         ${result.get('tip_amount')}")
    print(f"   Payment:     {result.get('payment_method')}")
    print(f"   Receipt #:   {result.get('receipt_number')}")
    print(f"   Method:      {result.get('ocr_method')}")
    print(f"   Confidence:  {result.get('confidence', 0)*100:.0f}%")

    if result.get('line_items'):
        print(f"\n   Line Items:")
        for item in result['line_items']:
            print(f"     - {item['description']}: ${item['total_price']}")

    # Verify if expected amount provided
    if expected_amount:
        print("\n" + "=" * 60)
        print("🔍 VERIFICATION:")
        verification = service.verify_receipt(image_path, {'amount': expected_amount})
        print(f"   Expected Amount: ${expected_amount}")
        print(f"   Extracted Amount: ${result.get('total_amount')}")
        print(f"   Match: {'✅ YES' if verification['matches'].get('amount') else '❌ NO'}")

    print("\n" + "=" * 60)
    print("📄 FULL JSON:")
    print(json.dumps({k: v for k, v in result.items() if k != 'raw_text'}, indent=2))
