#!/usr/bin/env python3
"""
Llama 3.2 Vision Receipt Extractor
100% FREE, runs locally via Ollama
Matches Mindee-quality extraction

Requirements:
- Ollama installed with llama3.2-vision model
- pip install ollama pdf2image pillow
"""

import ollama
from pdf2image import convert_from_path
from PIL import Image
import base64
import io
import json
import re
from typing import Optional, Dict, Any, List
from pathlib import Path


class LlamaVisionReceiptExtractor:
    """Extract receipt data using Llama 3.2 Vision (free, local)"""

    EXTRACTION_PROMPT = """Read this receipt image carefully and extract ALL information:

1. Supplier/Merchant name (the business name at the top)
2. Full address (street, city, state, zip, country)
3. Phone number (if present)
4. Invoice/Receipt number
5. Date paid (format as YYYY-MM-DD)
6. Time (if present)
7. Total amount paid (final amount including everything)
8. Subtotal (before tax/tip)
9. Tax amount (if any, or state "none")
10. Tip/gratuity amount (if any, or state "none")
11. Each line item with: description, quantity, unit price, total price
12. Payment method (card type and last 4 digits if shown)
13. Currency (USD, EUR, etc.)

Be precise with numbers. List each field on its own line."""

    def __init__(self, model: str = "llama3.2-vision"):
        self.model = model

    def _image_to_base64(self, image: Image.Image) -> str:
        """Convert PIL Image to base64 string"""
        buffer = io.BytesIO()
        image.save(buffer, format='PNG')
        return base64.b64encode(buffer.getvalue()).decode()

    def _load_image(self, image_path: str) -> Image.Image:
        """Load image from file path (supports PDF, PNG, JPG, etc.)"""
        path = Path(image_path)

        if path.suffix.lower() == '.pdf':
            images = convert_from_path(str(path))
            return images[0].convert("RGB")
        else:
            return Image.open(path).convert("RGB")

    def _extract_raw(self, image: Image.Image) -> str:
        """Get raw extraction text from Llama Vision"""
        img_base64 = self._image_to_base64(image)

        response = ollama.chat(
            model=self.model,
            messages=[{
                'role': 'user',
                'content': self.EXTRACTION_PROMPT,
                'images': [img_base64]
            }],
            options={'temperature': 0}
        )

        return response['message']['content']

    def _parse_extraction(self, text: str) -> Dict[str, Any]:
        """Parse the raw extraction text into structured JSON"""
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
            "raw_text": text
        }

        lines = text.split('\n')

        # Parse line items section separately
        in_line_items = False
        current_item = {}

        for i, line in enumerate(lines):
            line_lower = line.lower()

            # Clean the line value (remove markdown formatting)
            def extract_value(line):
                # Match patterns like "**Name**: Value" or "Name: Value"
                match = re.search(r'\*?\*?[^:]+\*?\*?:\s*\*?\*?(.+?)(?:\*?\*?)?$', line)
                if match:
                    return match.group(1).strip().strip('*').strip()
                return None

            # Supplier name - match "Supplier/Merchant Name": CLEAR
            if any(x in line_lower for x in ['supplier', 'merchant']) and 'name' in line_lower:
                val = extract_value(line)
                if val and val not in ['Not present', 'None', 'N/A']:
                    result['supplier_name'] = val

            # Address
            elif 'address' in line_lower and 'full' in line_lower:
                val = extract_value(line)
                if val and len(val) > 10:
                    result['supplier_address'] = val

            # Phone
            elif 'phone' in line_lower:
                val = extract_value(line)
                if val and val not in ['Not present', 'None', 'N/A']:
                    result['supplier_phone'] = val

            # Receipt/Invoice number
            elif ('receipt' in line_lower or 'invoice' in line_lower) and 'number' in line_lower:
                val = extract_value(line)
                if val and val not in ['Not present', 'None', 'N/A']:
                    result['receipt_number'] = val

            # Date - handle various formats
            elif 'date' in line_lower and 'paid' in line_lower:
                val = extract_value(line)
                if val:
                    # Try YYYY-MM-DD format first
                    match = re.search(r'(\d{4}-\d{2}-\d{2})', val)
                    if match:
                        result['date'] = match.group(1)
                    else:
                        # Try to parse "October 21, 2025" format
                        result['date'] = self._parse_date(val)

            # Time
            elif 'time' in line_lower and 'not present' not in line_lower:
                val = extract_value(line)
                if val and val not in ['Not present', 'None', 'N/A']:
                    result['time'] = val

            # Total amount
            elif 'total' in line_lower and ('amount' in line_lower or 'paid' in line_lower):
                val = extract_value(line)
                if val:
                    match = re.search(r'\$?([\d,]+\.?\d*)', val)
                    if match:
                        try:
                            result['total_amount'] = float(match.group(1).replace(',', ''))
                        except:
                            pass

            # Subtotal
            elif 'subtotal' in line_lower:
                val = extract_value(line)
                if val:
                    match = re.search(r'\$?([\d,]+\.?\d*)', val)
                    if match:
                        try:
                            result['subtotal'] = float(match.group(1).replace(',', ''))
                        except:
                            pass

            # Tax
            elif 'tax' in line_lower and 'amount' in line_lower:
                val = extract_value(line)
                if val:
                    if 'none' in val.lower() or 'not applicable' in val.lower() or 'n/a' in val.lower():
                        result['tax_amount'] = 0.0
                    else:
                        match = re.search(r'\$?([\d,]+\.?\d+)', val)
                        if match:
                            try:
                                result['tax_amount'] = float(match.group(1).replace(',', ''))
                            except:
                                pass

            # Tip
            elif 'tip' in line_lower or 'gratuity' in line_lower:
                val = extract_value(line)
                if val:
                    if 'none' in val.lower() or 'not applicable' in val.lower() or 'n/a' in val.lower():
                        result['tip_amount'] = 0.0
                    else:
                        match = re.search(r'\$?([\d,]+\.?\d+)', val)
                        if match:
                            try:
                                result['tip_amount'] = float(match.group(1).replace(',', ''))
                            except:
                                pass

            # Payment method
            elif 'payment' in line_lower and 'method' in line_lower:
                val = extract_value(line)
                if val and val not in ['Not present', 'None', 'N/A']:
                    result['payment_method'] = val

            # Currency
            elif 'currency' in line_lower:
                val = extract_value(line)
                if val:
                    # Extract just the currency code
                    match = re.search(r'([A-Z]{3})', val)
                    if match:
                        result['currency'] = match.group(1)

            # Line items section
            elif 'line items' in line_lower:
                in_line_items = True
                continue

            # Parse line items (indented descriptions with prices)
            elif in_line_items:
                # Check for description line "- **Description**: CLEAR Plus"
                if '**description**' in line_lower or ('description' in line_lower and ':' in line):
                    if current_item.get('description'):
                        # Save previous item
                        result['line_items'].append(current_item)
                    current_item = {'description': '', 'quantity': 1, 'unit_price': 0.0, 'total_price': 0.0}
                    val = extract_value(line)
                    if val:
                        current_item['description'] = val

                elif '**quantity**' in line_lower or ('quantity' in line_lower and ':' in line):
                    val = extract_value(line)
                    if val:
                        match = re.search(r'(\d+)', val)
                        if match:
                            current_item['quantity'] = int(match.group(1))

                elif '**unit price**' in line_lower or ('unit price' in line_lower and ':' in line):
                    val = extract_value(line)
                    if val:
                        match = re.search(r'\$?([\d,]+\.?\d*)', val)
                        if match:
                            current_item['unit_price'] = float(match.group(1).replace(',', ''))

                elif '**total price**' in line_lower or ('total price' in line_lower and ':' in line):
                    val = extract_value(line)
                    if val:
                        match = re.search(r'\$?([\d,]+\.?\d*)', val)
                        if match:
                            current_item['total_price'] = float(match.group(1).replace(',', ''))

        # Don't forget the last item
        if current_item.get('description'):
            result['line_items'].append(current_item)

        return result

    def _parse_date(self, date_str: str) -> Optional[str]:
        """Parse date string to YYYY-MM-DD format"""
        import datetime

        # Month name mapping
        months = {
            'january': 1, 'february': 2, 'march': 3, 'april': 4,
            'may': 5, 'june': 6, 'july': 7, 'august': 8,
            'september': 9, 'october': 10, 'november': 11, 'december': 12
        }

        date_str = date_str.lower().strip()

        # Try "Month DD, YYYY" format
        for month_name, month_num in months.items():
            if month_name in date_str:
                match = re.search(rf'{month_name}\s+(\d{{1,2}}),?\s+(\d{{4}})', date_str)
                if match:
                    day = int(match.group(1))
                    year = int(match.group(2))
                    return f"{year:04d}-{month_num:02d}-{day:02d}"

        return None

    def _parse_line_item(self, line: str) -> Optional[Dict[str, Any]]:
        """Parse a single line item"""
        # Pattern: "* **Name**: qty unit, $price, $total" or similar

        # Try to extract description
        desc_match = re.search(r'\*?\*?([A-Za-z][A-Za-z\s]+?)(?:\*?\*?)?[:\s]*\d', line)
        if not desc_match:
            desc_match = re.search(r'\*?\*?([A-Za-z][A-Za-z\s]+)', line)

        if not desc_match:
            return None

        description = desc_match.group(1).strip().strip('*').strip(':').strip()

        # Extract prices (usually 2-3 numbers: qty, unit price, total)
        prices = re.findall(r'\$?([\d,]+\.?\d*)', line)
        prices = [float(p.replace(',', '')) for p in prices if p]

        item = {
            "description": description,
            "quantity": 1,
            "unit_price": 0.0,
            "total_price": 0.0
        }

        if len(prices) >= 3:
            item['quantity'] = int(prices[0]) if prices[0] < 100 else 1
            item['unit_price'] = prices[1]
            item['total_price'] = prices[2]
        elif len(prices) == 2:
            item['unit_price'] = prices[0]
            item['total_price'] = prices[1]
        elif len(prices) == 1:
            item['unit_price'] = prices[0]
            item['total_price'] = prices[0]

        return item

    def extract(self, image_path: str) -> Dict[str, Any]:
        """
        Extract receipt data from image file

        Args:
            image_path: Path to image or PDF file

        Returns:
            Dictionary with Mindee-compatible schema
        """
        image = self._load_image(image_path)
        raw_text = self._extract_raw(image)
        return self._parse_extraction(raw_text)

    def extract_from_image(self, image: Image.Image) -> Dict[str, Any]:
        """Extract from PIL Image object"""
        raw_text = self._extract_raw(image)
        return self._parse_extraction(raw_text)


def main():
    """Test the extractor"""
    import sys

    if len(sys.argv) < 2:
        print("Usage: python llama_vision_extractor.py <image_path>")
        print("\nExample:")
        print("  python llama_vision_extractor.py receipt.pdf")
        print("  python llama_vision_extractor.py receipt.jpg")
        sys.exit(1)

    image_path = sys.argv[1]

    print(f"Extracting from: {image_path}")
    print("=" * 60)

    extractor = LlamaVisionReceiptExtractor()
    result = extractor.extract(image_path)

    # Print results
    print("\nEXTRACTED DATA:")
    print("=" * 60)

    # Remove raw_text for cleaner output
    display_result = {k: v for k, v in result.items() if k != 'raw_text'}
    print(json.dumps(display_result, indent=2))

    print("\n" + "=" * 60)
    print("RAW EXTRACTION TEXT:")
    print("=" * 60)
    print(result.get('raw_text', ''))


if __name__ == "__main__":
    main()
