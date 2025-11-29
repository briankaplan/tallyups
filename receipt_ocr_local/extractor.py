"""
Receipt OCR Extractor - Donut Primary with Ensemble Fallback
============================================================
Uses trained Donut model (97-98% accuracy) as primary extractor.
Falls back to ensemble OCR (PaddleOCR + EasyOCR + Tesseract) if needed.
"""

import sys
from pathlib import Path
from typing import Dict
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import Donut extractor (primary)
from .donut_extractor import extract_with_donut, get_donut_extractor
from .validation import validate_extraction, batch_validate, ValidationConfig

# Import ensemble OCR (fallback)
try:
    from scripts.ocr.ultimate_free_ocr import UltimateFreeOCR
    ENSEMBLE_AVAILABLE = True
except ImportError:
    try:
        # Fallback: add scripts/ocr to path
        import sys
        from pathlib import Path
        scripts_path = str(Path(__file__).parent.parent / "scripts" / "ocr")
        if scripts_path not in sys.path:
            sys.path.insert(0, scripts_path)
        from ultimate_free_ocr import UltimateFreeOCR
        ENSEMBLE_AVAILABLE = True
    except ImportError:
        ENSEMBLE_AVAILABLE = False

# Global instances
_ocr_instance = None
_use_donut = True  # Primary method

def get_ocr():
    """Get or create global ensemble OCR instance"""
    global _ocr_instance
    if _ocr_instance is None and ENSEMBLE_AVAILABLE:
        _ocr_instance = UltimateFreeOCR()
    return _ocr_instance


def extract_receipt_fields_local(image_path: str, config=None) -> Dict:
    """
    Extract receipt fields using Donut (primary) or ensemble OCR (fallback)

    Args:
        image_path: Path to receipt image
        config: OCR configuration dict with optional keys:
            - use_donut: bool (default True) - Use Donut model
            - fallback_to_ensemble: bool (default True) - Fall back to ensemble
            - validate: bool (default False) - Run post-extraction validation

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
            "subtotal_amount": 12.00,
            "tip_amount": 3.50,
            "confidence_score": 0.95,
            "success": True,
            "ocr_method": "Donut",
            "engines_used": ["Donut"]
        }
    """
    image_path = Path(image_path)
    config = config or {}

    if not image_path.exists():
        return {
            "error": "File not found",
            "receipt_file": str(image_path.name),
            "success": False
        }

    use_donut = config.get('use_donut', _use_donut)
    fallback_to_ensemble = config.get('fallback_to_ensemble', True)
    run_validation = config.get('validate', False)

    result = None

    def _maybe_validate(res):
        """Apply validation if enabled"""
        if run_validation and res.get('success'):
            return validate_extraction(res)
        return res

    # Try Donut first (primary method)
    if use_donut:
        try:
            result = extract_with_donut(image_path)

            # Check if extraction was successful
            if result.get('success') and result.get('confidence_score', 0) >= 0.5:
                return _maybe_validate(result)

            # Donut failed or low confidence - try fallback
            if fallback_to_ensemble and ENSEMBLE_AVAILABLE:
                print(f"Donut confidence {result.get('confidence_score', 0):.2f} < 0.5, trying ensemble...")
                ensemble_result = _extract_with_ensemble(image_path)

                # Use ensemble if it's better
                if ensemble_result.get('confidence_score', 0) > result.get('confidence_score', 0):
                    ensemble_result['donut_tried'] = True
                    return _maybe_validate(ensemble_result)

            return _maybe_validate(result)

        except Exception as e:
            print(f"Donut extraction failed: {e}")
            if fallback_to_ensemble and ENSEMBLE_AVAILABLE:
                return _maybe_validate(_extract_with_ensemble(image_path))
            else:
                return {
                    "error": str(e),
                    "receipt_file": str(image_path.name),
                    "success": False,
                    "ocr_method": "Donut"
                }

    # Use ensemble directly if Donut disabled
    if ENSEMBLE_AVAILABLE:
        return _maybe_validate(_extract_with_ensemble(image_path))

    return {
        "error": "No OCR method available",
        "receipt_file": str(image_path.name),
        "success": False
    }


def _extract_with_ensemble(image_path: Path) -> Dict:
    """Extract using ensemble OCR (PaddleOCR + EasyOCR + Tesseract)"""

    result = {
        "receipt_file": str(image_path.name),
        "preprocessing_enabled": True,
        "ocr_method": "UltimateFreeOCR"
    }

    try:
        ocr = get_ocr()
        if ocr is None:
            return {
                "error": "Ensemble OCR not available",
                "receipt_file": str(image_path.name),
                "success": False
            }

        ocr_result = ocr.process_receipt(str(image_path))

        if ocr_result['confidence'] > 0:
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
            result["subtotal_amount"] = 0.0
            result["tip_amount"] = 0.0
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
    Process receipt and return result compatible with existing system.
    Optionally includes transaction context for better matching.
    """
    result = extract_receipt_fields_local(receipt_path, config)

    if transaction_row:
        result["transaction"] = transaction_row

    return result


def batch_process_receipts(receipt_paths: list, config=None) -> list:
    """
    Process multiple receipts in batch.

    Args:
        receipt_paths: List of receipt file paths
        config: OCR configuration

    Returns:
        List of results
    """
    results = []

    # Pre-load Donut model for efficiency
    if config is None or config.get('use_donut', True):
        try:
            extractor = get_donut_extractor()
            extractor.load()
        except Exception as e:
            print(f"Warning: Could not pre-load Donut: {e}")

    for i, path in enumerate(receipt_paths):
        print(f"Processing [{i+1}/{len(receipt_paths)}]: {path}")
        result = extract_receipt_fields_local(path, config)
        results.append(result)

    return results


def set_primary_method(use_donut: bool = True):
    """Set the primary OCR method"""
    global _use_donut
    _use_donut = use_donut
    print(f"Primary OCR method: {'Donut' if use_donut else 'Ensemble'}")


# Convenience exports
__all__ = [
    'extract_receipt_fields_local',
    'process_receipt_for_row',
    'batch_process_receipts',
    'set_primary_method',
    'extract_with_donut',
    'validate_extraction',
    'batch_validate',
    'ValidationConfig',
]
