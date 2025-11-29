#!/usr/bin/env python3
"""
Multi-Engine Receipt OCR Extractor
===================================
Combines CORD (Donut) with Tesseract fallback for robust extraction.
Falls back to Tesseract when CORD output is garbled.
"""

import re
import logging
from pathlib import Path
from typing import Optional
import pytesseract
from PIL import Image, ImageEnhance, ImageFilter

from donut_extractor import (
    DonutReceiptExtractor,
    get_donut_extractor,
    MERCHANT_DB,
    logger
)

# Import validation (for optional post-extraction validation)
try:
    from validation import validate_extraction
    VALIDATION_AVAILABLE = True
except ImportError:
    VALIDATION_AVAILABLE = False

# Try to import EasyOCR for handwriting support
try:
    import easyocr
    EASYOCR_AVAILABLE = True
except ImportError:
    EASYOCR_AVAILABLE = False
    logger.warning("EasyOCR not available - handwriting recognition limited")

# Tesseract config for receipts
TESSERACT_CONFIG = '--oem 3 --psm 6 -l eng'


class MultiEngineExtractor:
    """
    Multi-engine receipt extractor with intelligent fallback.

    Strategy:
    1. Try CORD (Donut) first - good for structured receipts
    2. Detect garbled output (repetition, low confidence)
    3. Fall back to Tesseract with preprocessing
    4. Return best result based on confidence
    """

    def __init__(self):
        self.donut = get_donut_extractor()
        self._tesseract_available = self._check_tesseract()
        self._easyocr_reader = None  # Lazy load for EasyOCR

    def _get_easyocr_reader(self):
        """Get or create EasyOCR reader (lazy loading)"""
        if not EASYOCR_AVAILABLE:
            return None
        if self._easyocr_reader is None:
            logger.info("Loading EasyOCR reader (supports handwriting)...")
            self._easyocr_reader = easyocr.Reader(['en'], gpu=False)
        return self._easyocr_reader

    def _check_tesseract(self) -> bool:
        """Check if Tesseract is available"""
        try:
            pytesseract.get_tesseract_version()
            return True
        except Exception:
            logger.warning("Tesseract not available - using CORD only")
            return False

    def extract(self, image_path: str | Path) -> dict:
        """
        Extract receipt fields using multi-engine approach.

        Args:
            image_path: Path to receipt image

        Returns:
            dict with standardized receipt fields
        """
        image_path = Path(image_path)

        # Try CORD first
        cord_result = self.donut.extract(image_path)

        # Check if CORD output is garbled
        if self._is_garbled(cord_result):
            logger.info(f"CORD output garbled for {image_path.name}, trying Tesseract")

            if self._tesseract_available:
                tess_result = self._extract_with_tesseract(image_path)

                # When CORD is garbled, prefer Tesseract if it got reasonable results
                # Don't trust CORD's confidence score when output is garbled
                tess_conf = tess_result['confidence_score']
                tess_total = tess_result.get('Receipt Total', 0)
                tess_merchant = tess_result.get('Receipt Merchant', '')

                # Use Tesseract if it extracted meaningful data
                if tess_conf >= 0.5 or (tess_merchant and len(tess_merchant) > 3 and 0 < tess_total < 1000):
                    logger.info(f"Using Tesseract result (merchant={tess_merchant}, total={tess_total})")
                    tess_result['engines_used'] = ['CORD (garbled)', 'Tesseract']
                    return tess_result
                else:
                    logger.info(f"Tesseract also failed, keeping CORD result")

        return cord_result

    def _is_garbled(self, result: dict) -> bool:
        """
        Detect if CORD output is garbled.

        Signs of garbled output:
        - High repetition in raw text
        - Merchant looks like a date/time
        - Total is unreasonably high
        - Very low confidence
        """
        raw = result.get('raw_output', '')
        merchant = result.get('Receipt Merchant', '')
        total = result.get('Receipt Total', 0)
        confidence = result.get('confidence_score', 0)

        # Check for text repetition (garbled CORD often repeats)
        if raw:
            words = raw.split()
            if len(words) > 10:
                unique_ratio = len(set(words)) / len(words)
                if unique_ratio < 0.3:  # Less than 30% unique words
                    logger.debug(f"High repetition detected: {unique_ratio:.2f}")
                    return True

        # Check if merchant looks like date/time
        if merchant and re.match(r'^\d{1,2}/\d{1,2}/\d{2,4}', merchant):
            logger.debug("Merchant looks like date")
            return True

        # Check for unreasonable total
        if total > 5000:
            logger.debug(f"Total unreasonably high: {total}")
            return True

        # Check extraction issues
        issues = result.get('extraction_issues', [])
        if 'total_high_value' in issues or 'merchant_missing' in issues:
            return True

        return False

    def _auto_rotate_image(self, image: Image.Image) -> Image.Image:
        """
        Auto-detect and fix image rotation using Tesseract OSD.
        """
        try:
            # Use Tesseract's orientation detection
            osd = pytesseract.image_to_osd(image)
            rotation = int(re.search(r'Rotate: (\d+)', osd).group(1))

            if rotation != 0:
                logger.info(f"Auto-rotating image by {rotation} degrees")
                # Tesseract reports rotation needed to fix, so we rotate by that amount
                image = image.rotate(-rotation, expand=True)
        except Exception as e:
            logger.debug(f"OSD detection failed: {e}, trying manual rotation check")
            # Fallback: try each rotation and pick best
            best_conf = 0
            best_rotation = 0
            for angle in [0, 90, 180, 270]:
                rotated = image.rotate(-angle, expand=True) if angle != 0 else image
                try:
                    # Quick OCR to check confidence
                    data = pytesseract.image_to_data(rotated, output_type=pytesseract.Output.DICT)
                    confs = [int(c) for c in data['conf'] if int(c) > 0]
                    avg_conf = sum(confs) / len(confs) if confs else 0
                    if avg_conf > best_conf:
                        best_conf = avg_conf
                        best_rotation = angle
                except:
                    pass

            if best_rotation != 0:
                logger.info(f"Manual rotation detection: rotating by {best_rotation} degrees")
                image = image.rotate(-best_rotation, expand=True)

        return image

    def _extract_with_tesseract(self, image_path: Path) -> dict:
        """
        Extract receipt fields using Tesseract OCR.

        Includes image preprocessing for better results.
        """
        try:
            # Load and preprocess image
            image = Image.open(image_path).convert('L')  # Grayscale

            # Auto-rotate if needed
            image = self._auto_rotate_image(image)

            # Enhance contrast
            enhancer = ImageEnhance.Contrast(image)
            image = enhancer.enhance(2.0)

            # Sharpen
            image = image.filter(ImageFilter.SHARPEN)

            # OCR
            text = pytesseract.image_to_string(image, config=TESSERACT_CONFIG)

            # Extract fields using same heuristics as CORD
            merchant = self._extract_merchant_tess(text)
            date_str = self._extract_date_tess(text)
            total = self._extract_total_tess(text)

            # Normalize merchant
            merchant_normalized = self.donut._normalize_merchant(merchant)

            # Calculate confidence
            confidence = self._calculate_confidence(merchant, date_str, total)

            # Log result
            logger.info(f"Tesseract extraction: merchant={merchant}, date={date_str}, total={total}")

            return {
                "receipt_file": str(image_path),
                "Receipt Merchant": merchant,
                "Receipt Date": date_str,
                "Receipt Total": total,
                "ai_receipt_merchant": merchant,
                "ai_receipt_date": date_str,
                "ai_receipt_total": total,
                "merchant_normalized": merchant_normalized,
                "subtotal_amount": 0.0,
                "tip_amount": 0.0,
                "confidence_score": confidence,
                "success": confidence > 0.3,
                "ocr_method": "Tesseract",
                "engines_used": ["Tesseract"],
                "raw_output": text,
                "extraction_issues": [],
            }

        except Exception as e:
            logger.error(f"Tesseract extraction failed: {e}")
            return self.donut._empty_result(str(image_path), error=str(e))

    def _extract_merchant_tess(self, text: str) -> str:
        """Extract merchant from Tesseract output"""
        lines = [l.strip() for l in text.split('\n') if l.strip()]

        # Known merchant patterns
        for pattern in [
            r"(Wendy's|McDonald's|Starbucks|Target|Walmart|Costco|Amazon)",
            r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+(?:House|Inn|Hotel|Club|Bar|Grill))',
        ]:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1)

        # Look for all-caps store name in first few lines
        for line in lines[:5]:
            # Skip common non-merchant lines
            if any(skip in line.upper() for skip in ['RECEIPT', 'ORDER', 'WELCOME', 'THANK']):
                continue
            # Check if mostly uppercase and reasonable length
            if line.isupper() and 3 < len(line) < 40:
                return line

        # Return first reasonable line
        for line in lines[:3]:
            if len(line) > 3 and not re.match(r'^[\d\s\-/:.]+$', line):
                return line

        return ""

    def _extract_date_tess(self, text: str) -> str:
        """Extract date from Tesseract output"""
        patterns = [
            r'(\d{1,2}/\d{1,2}/\d{2,4})',
            r'(\d{4}-\d{2}-\d{2})',
            r'((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s*\d{4})',
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return self.donut._parse_date(match.group(1))

        return ""

    def _extract_total_tess(self, text: str) -> float:
        """Extract total from Tesseract output"""
        lines = text.split('\n')

        # Look for TOTAL line
        for line in reversed(lines):  # Start from bottom
            upper = line.upper()
            if 'TOTAL' in upper and 'SUBTOTAL' not in upper:
                # Extract amount from this line
                match = re.search(r'\$?\s*([\d,]+\.\d{2})', line)
                if match:
                    try:
                        return float(match.group(1).replace(',', ''))
                    except:
                        pass

        # Look for DUE, AMOUNT patterns
        for pattern in [r'(?:DUE|AMOUNT|CHARGE)[:\s]+\$?\s*([\d,]+\.\d{2})']:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    return float(match.group(1).replace(',', ''))
                except:
                    pass

        # Fallback: find amounts and pick reasonable max
        amounts = re.findall(r'\$?\s*([\d,]+\.\d{2})', text)
        if amounts:
            values = []
            for a in amounts:
                try:
                    v = float(a.replace(',', ''))
                    if 0.01 <= v <= 1000:  # Reasonable range
                        values.append(v)
                except:
                    pass
            if values:
                return max(values)

        return 0.0

    def _calculate_confidence(self, merchant: str, date: str, total: float) -> float:
        """Calculate confidence score"""
        score = 0.0

        if merchant and len(merchant) > 3:
            score += 0.5
        if date:
            score += 0.3
        if 0 < total < 1000:
            score += 0.2

        return min(score, 1.0)

    def _extract_handwritten_tip(self, image_path: Path) -> dict:
        """
        Extract handwritten tip and total from receipt using EasyOCR.

        Focuses on the bottom third of the receipt where tips are usually written.
        EasyOCR handles handwriting better than Tesseract.

        Returns:
            dict with tip, total, and confidence
        """
        reader = self._get_easyocr_reader()
        if reader is None:
            return {"tip": 0.0, "total": 0.0, "confidence": 0.0}

        try:
            # Load image and crop to bottom third (where tip/signature usually is)
            image = Image.open(image_path)
            width, height = image.size

            # Crop bottom 40% of receipt for tip area
            bottom_region = image.crop((0, int(height * 0.6), width, height))

            # Convert to RGB if needed
            if bottom_region.mode != 'RGB':
                bottom_region = bottom_region.convert('RGB')

            # Run EasyOCR on bottom region
            import numpy as np
            img_array = np.array(bottom_region)
            results = reader.readtext(img_array)

            tip = 0.0
            total = 0.0

            # Look for tip and total patterns in EasyOCR results
            for bbox, text, conf in results:
                upper_text = text.upper()

                # Look for TIP line
                if 'TIP' in upper_text or 'GRATUITY' in upper_text:
                    # Extract amount from this or next detection
                    amounts = re.findall(r'\$?\s*([\d,]+\.?\d*)', text)
                    for amt in amounts:
                        try:
                            val = float(amt.replace(',', ''))
                            if 0 < val < 500:  # Reasonable tip range
                                tip = val
                                logger.info(f"Found handwritten tip: ${tip:.2f}")
                                break
                        except:
                            pass

                # Look for TOTAL line
                if 'TOTAL' in upper_text and 'SUB' not in upper_text:
                    amounts = re.findall(r'\$?\s*([\d,]+\.?\d*)', text)
                    for amt in amounts:
                        try:
                            val = float(amt.replace(',', ''))
                            if 0 < val < 10000:  # Reasonable total range
                                total = val
                                logger.info(f"Found handwritten total: ${total:.2f}")
                                break
                        except:
                            pass

                # Also look for standalone amounts (handwritten numbers)
                if not tip or not total:
                    amounts = re.findall(r'^\s*\$?\s*([\d,]+\.\d{2})\s*$', text)
                    for amt in amounts:
                        try:
                            val = float(amt.replace(',', ''))
                            if 0 < val < 100 and not tip:
                                tip = val
                            elif val > tip and not total:
                                total = val
                        except:
                            pass

            # Calculate confidence
            confidence = 0.0
            if tip > 0:
                confidence += 0.5
            if total > 0:
                confidence += 0.5

            return {
                "tip": tip,
                "total": total,
                "confidence": confidence
            }

        except Exception as e:
            logger.error(f"EasyOCR handwriting extraction failed: {e}")
            return {"tip": 0.0, "total": 0.0, "confidence": 0.0}

    def extract_with_handwriting(self, image_path: str | Path) -> dict:
        """
        Enhanced extraction that specifically handles handwritten tips.

        Strategy:
        1. Run normal multi-engine extraction
        2. If tip is 0 or confidence is low, try EasyOCR on bottom region
        3. Merge results
        """
        image_path = Path(image_path)

        # Get base extraction
        result = self.extract(image_path)

        # If we already have a tip, return as-is
        if result.get('tip_amount', 0) > 0:
            return result

        # Try EasyOCR for handwritten tip
        if EASYOCR_AVAILABLE:
            hw_result = self._extract_handwritten_tip(image_path)

            # Update result with handwritten findings
            if hw_result['tip'] > 0:
                result['tip_amount'] = hw_result['tip']
                result['handwritten_tip'] = True
                logger.info(f"Added handwritten tip: ${hw_result['tip']:.2f}")

            # Update total if EasyOCR found a better one
            if hw_result['total'] > 0 and result.get('Receipt Total', 0) == 0:
                result['Receipt Total'] = hw_result['total']
                result['ai_receipt_total'] = hw_result['total']
                result['handwritten_total'] = True

        return result


# Singleton instance
_multi_engine = None

def get_multi_engine_extractor() -> MultiEngineExtractor:
    """Get or create singleton multi-engine extractor"""
    global _multi_engine
    if _multi_engine is None:
        _multi_engine = MultiEngineExtractor()
    return _multi_engine


def extract_receipt(image_path: str | Path, validate: bool = False) -> dict:
    """
    Extract receipt fields using multi-engine approach.

    This is the main entry point - use this for best results.

    Args:
        image_path: Path to receipt image
        validate: Run post-extraction validation

    Returns:
        dict with standardized receipt fields
    """
    extractor = get_multi_engine_extractor()
    result = extractor.extract(image_path)

    if validate and VALIDATION_AVAILABLE:
        result = validate_extraction(result)

    return result


def extract_receipt_with_handwriting(image_path: str | Path, validate: bool = False) -> dict:
    """
    Extract receipt fields with handwriting support for tips.

    Use this for restaurant receipts with handwritten tips.

    Args:
        image_path: Path to receipt image
        validate: Run post-extraction validation

    Returns:
        dict with standardized receipt fields including handwritten tip
    """
    extractor = get_multi_engine_extractor()
    result = extractor.extract_with_handwriting(image_path)

    if validate and VALIDATION_AVAILABLE:
        result = validate_extraction(result)

    return result


# CLI
if __name__ == "__main__":
    import sys
    import json

    if len(sys.argv) > 1:
        result = extract_receipt(sys.argv[1])
        print(json.dumps(result, indent=2))
    else:
        print("Usage: python multi_engine_extractor.py <image_path>")
        print("\nMulti-engine receipt OCR with CORD + Tesseract fallback")
