"""
Ultimate Free OCR Extractor - Integrated Version
Replaces Llama Vision with ensemble OCR (PaddleOCR + EasyOCR + Tesseract)
Compatible with existing receipt processing pipeline
"""

import sys
from pathlib import Path
from typing import Dict
sys.path.insert(0, str(Path(__file__).parent.parent))

from ultimate_free_ocr import UltimateFreeOCR

# Global OCR instance (initialized once)
_ocr_instance = None

def get_ocr():
    """Get or create global OCR instance"""
    global _ocr_instance
    if _ocr_instance is None:
        _ocr_instance = UltimateFreeOCR()
    return _ocr_instance

def extract_receipt_fields_local(image_path: str, config=None) -> Dict:
    """
    Extract receipt fields using Ultimate Free OCR

    Compatible with existing system - same signature as receipt_ocr_local.extractor

    Args:
        image_path: Path to receipt image
        config: OCR configuration (ignored - uses ensemble defaults)

    Returns:
        {
            "receipt_file": "receipt.jpg",
            "Receipt Merchant": "Starbucks",
            "Receipt Date": "2024-01-15",
            "Receipt Total": 15.50,
            "ai_receipt_merchant": "Starbucks",
            "ai_receipt_date": "2024-01-15",
            "ai_receipt_total": 15.50,
            "merchant_normalized": "starbucks",
            "confidence_score": 0.92,
            "success": True,
            "preprocessing_enabled": True,
            "ocr_method": "UltimateFreeOCR",
            "engines_used": ["PaddleOCR", "EasyOCR", "Tesseract"]
        }
    """
    image_path = Path(image_path)

    if not image_path.exists():
        return {
            "error": "File not found",
            "receipt_file": str(image_path.name),
            "success": False
        }

    result = {
        "receipt_file": str(image_path.name),
        "preprocessing_enabled": True,
        "ocr_method": "UltimateFreeOCR"
    }

    try:
        # Get OCR instance
        ocr = get_ocr()

        # Process with ensemble OCR
        ocr_result = ocr.process_receipt(str(image_path))

        if ocr_result['confidence'] > 0:
            # Map to expected format
            merchant = ocr_result.get('merchant', '')
            date = ocr_result.get('date', '')
            total = ocr_result.get('total', 0.0)

            result["Receipt Merchant"] = merchant
            result["Receipt Date"] = date
            result["Receipt Total"] = total
            result["ai_receipt_merchant"] = merchant
            result["ai_receipt_date"] = date
            result["ai_receipt_total"] = total
            result["merchant_normalized"] = merchant.lower().strip() if merchant else ""
            result["confidence_score"] = ocr_result['confidence']
            result["engines_used"] = ocr_result['engines_used']
            result["raw_ocr_text"] = ocr_result.get('raw_text', '')[:500]
            result["success"] = True
        else:
            result["success"] = False
            result["error"] = "Low confidence OCR result"
            result["confidence_score"] = ocr_result['confidence']

    except Exception as e:
        result["success"] = False
        result["error"] = str(e)
        import traceback
        result["traceback"] = traceback.format_exc()

    return result


def process_receipt_for_row(receipt_path: str, transaction_row: Dict = None, config=None) -> Dict:
    """
    Process receipt and return result compatible with existing system

    This function signature matches your existing codebase expectations
    """
    result = extract_receipt_fields_local(receipt_path, config)

    # Add transaction info if provided
    if transaction_row:
        result["transaction"] = transaction_row

    return result


def batch_process_receipts(receipt_paths: list, config=None) -> list:
    """
    Process multiple receipts in batch

    Args:
        receipt_paths: List of receipt file paths
        config: OCR configuration (ignored)

    Returns:
        List of results
    """
    results = []

    for path in receipt_paths:
        print(f"Processing: {path}")
        result = extract_receipt_fields_local(path, config)
        results.append(result)

    return results
