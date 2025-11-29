"""
Local OCR Extractor - 100% Local Version
Uses OpenCV preprocessing + Llama 3.2 Vision via Ollama
"""
import sys
from pathlib import Path
import cv2
import numpy as np
from typing import Dict, Optional
import base64
import json
import re
import requests
from datetime import datetime

from .config import OCRConfig
from .preprocess import ReceiptPreprocessor

# Ollama API endpoint
OLLAMA_API = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "llama3.2-vision:latest"


def _extract_with_llama_vision(image_path: str) -> Dict:
    """
    Extract receipt fields using Llama 3.2 Vision via Ollama

    Returns dict with: merchant, date, total, merchant_norm, confidence, success
    """
    try:
        # Read and encode image
        with open(image_path, 'rb') as f:
            image_data = base64.b64encode(f.read()).decode('utf-8')

        # Prompt for Llama Vision
        prompt = """Analyze this receipt image and extract the following information in JSON format:
{
  "merchant": "merchant name",
  "date": "YYYY-MM-DD",
  "total": 0.00
}

Only return the JSON, nothing else. If any field is unclear, use null."""

        # Call Ollama API
        payload = {
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "images": [image_data],
            "stream": False
        }

        response = requests.post(OLLAMA_API, json=payload, timeout=30)

        if response.status_code != 200:
            return {
                "success": False,
                "error": f"Ollama API returned {response.status_code}"
            }

        # Parse response
        response_data = response.json()
        llama_response = response_data.get("response", "")

        # Extract JSON from response
        # Llama might wrap JSON in markdown code blocks
        json_match = re.search(r'```json\s*(\{.*?\})\s*```', llama_response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            # Try to find raw JSON
            json_match = re.search(r'\{.*\}', llama_response, re.DOTALL)
            if json_match:
                json_str = json_match.group(0)
            else:
                return {
                    "success": False,
                    "error": "Could not find JSON in Llama response",
                    "raw_response": llama_response
                }

        # Parse JSON
        data = json.loads(json_str)

        # Normalize merchant name
        merchant = data.get("merchant", "")
        merchant_norm = merchant.lower().strip() if merchant else ""

        # Parse total
        total = data.get("total")
        if isinstance(total, str):
            # Remove currency symbols and parse
            total = float(re.sub(r'[^\d.]', '', total))
        elif total is None:
            total = 0.0
        else:
            total = float(total)

        # Validate date format
        date_str = data.get("date", "")
        try:
            if date_str and date_str.lower() != "null":
                datetime.strptime(date_str, "%Y-%m-%d")
            else:
                date_str = ""
        except:
            date_str = ""

        return {
            "success": True,
            "merchant": merchant,
            "date": date_str,
            "total": total,
            "merchant_norm": merchant_norm,
            "confidence": 0.85,  # Default confidence for Llama Vision
            "raw_response": llama_response,
            "parsed_json": data
        }

    except requests.exceptions.ConnectionError:
        return {
            "success": False,
            "error": "Cannot connect to Ollama. Is it running? Try: ollama serve"
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Llama Vision error: {str(e)}",
            "traceback": __import__('traceback').format_exc()
        }


def extract_receipt_fields_local(image_path: str, config: OCRConfig = None) -> Dict:
    """
    Extract receipt fields using OpenCV preprocessing + Vision AI

    Args:
        image_path: Path to receipt image
        config: OCR configuration (optional)

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
            "preprocessing_metadata": {...},
            "raw_vision_result": {...}
        }
    """
    if config is None:
        config = OCRConfig.simplified()

    image_path = Path(image_path)

    if not image_path.exists():
        return {
            "error": "File not found",
            "receipt_file": str(image_path.name)
        }

    result = {
        "receipt_file": str(image_path.name),
        "preprocessing_enabled": True,
        "local_vision_model": OLLAMA_MODEL
    }

    try:
        # Step 1: Preprocess image with OpenCV
        preprocessor = ReceiptPreprocessor(config)
        preprocessed_img, preprocess_meta = preprocessor.process(str(image_path))

        result["preprocessing_metadata"] = preprocess_meta

        # Save preprocessed image to temp file for Llama Vision
        import tempfile
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
            temp_path = tmp.name
            cv2.imwrite(temp_path, preprocessed_img)

        # Step 2: Call Llama 3.2 Vision via Ollama with preprocessed image
        vision_result = _extract_with_llama_vision(temp_path)

        if vision_result and vision_result.get("success"):
            # Map Llama Vision results to expected format
            result["Receipt Merchant"] = vision_result.get("merchant", "")
            result["Receipt Date"] = vision_result.get("date", "")
            result["Receipt Total"] = vision_result.get("total", 0.0)
            result["ai_receipt_merchant"] = vision_result.get("merchant", "")
            result["ai_receipt_date"] = vision_result.get("date", "")
            result["ai_receipt_total"] = vision_result.get("total", 0.0)
            result["merchant_normalized"] = vision_result.get("merchant_norm", "")
            result["confidence_score"] = vision_result.get("confidence", 0.0)
            result["raw_vision_result"] = vision_result
            result["success"] = True
        else:
            result["success"] = False
            result["error"] = vision_result.get("error", "Llama Vision returned no results")

        # Clean up temp file
        Path(temp_path).unlink(missing_ok=True)

    except Exception as e:
        result["success"] = False
        result["error"] = str(e)
        import traceback
        result["traceback"] = traceback.format_exc()

    return result


def batch_process_receipts(receipt_paths: list, config: OCRConfig = None) -> list:
    """
    Process multiple receipts in batch

    Args:
        receipt_paths: List of receipt file paths
        config: OCR configuration (optional)

    Returns:
        List of results
    """
    results = []

    for path in receipt_paths:
        print(f"Processing: {path}")
        result = extract_receipt_fields_local(path, config)
        results.append(result)

    return results


# Compatibility function for existing code
def process_receipt_for_row(receipt_path: str, transaction_row: Dict = None, config: OCRConfig = None) -> Dict:
    """
    Process receipt and return result compatible with existing system

    This function signature matches your existing codebase expectations
    """
    result = extract_receipt_fields_local(receipt_path, config)

    # Add transaction info if provided
    if transaction_row:
        result["transaction"] = transaction_row

    return result
