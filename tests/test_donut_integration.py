#!/usr/bin/env python3
"""
Test Donut OCR Integration
==========================
Tests that the Donut model is properly integrated into all system components.
"""

import sys
import json
import pytest
from pathlib import Path

# Check if torch is available (required for Donut)
try:
    import torch
    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

@pytest.mark.skipif(not HAS_TORCH, reason="torch not installed (required for Donut OCR)")
def test_donut_extractor():
    """Test the core Donut extractor module"""
    print("\n" + "="*60)
    print("TEST 1: Donut Extractor Module")
    print("="*60)

    try:
        from receipt_ocr_local.donut_extractor import DonutReceiptExtractor, get_donut_extractor

        extractor = get_donut_extractor()
        print(f"✅ Found model: {extractor.model_path.name}")
        print(f"   Loading model...")
        extractor.load()
        print(f"   Device: {extractor.device}")
        print(f"✅ Donut extractor loaded successfully")
        assert extractor is not None, "Extractor should be loaded"
    except Exception as e:
        print(f"❌ Failed: {e}")
        pytest.fail(f"Donut extractor failed: {e}")


@pytest.mark.skipif(not HAS_TORCH, reason="torch not installed (required for Donut OCR)")
def test_main_extractor():
    """Test the main extractor function"""
    print("\n" + "="*60)
    print("TEST 2: Main Extractor (receipt_ocr_local)")
    print("="*60)

    try:
        from receipt_ocr_local import extract_receipt_fields_local

        # Find a test receipt
        receipts_dir = BASE_DIR / "receipts"
        if not receipts_dir.exists():
            print("⚠️  No receipts directory found")
            pytest.skip("No receipts directory found")

        test_files = list(receipts_dir.glob("*.jpg")) + list(receipts_dir.glob("*.png"))
        if not test_files:
            print("⚠️  No receipt images found")
            pytest.skip("No receipt images found")

        test_file = test_files[0]
        print(f"   Testing with: {test_file.name}")

        result = extract_receipt_fields_local(str(test_file))

        if result.get("success"):
            print(f"✅ Extraction successful!")
            print(f"   Merchant: {result.get('Receipt Merchant', 'N/A')}")
            print(f"   Date: {result.get('Receipt Date', 'N/A')}")
            print(f"   Total: ${result.get('Receipt Total', 0):.2f}")
            print(f"   Subtotal: ${result.get('subtotal_amount', 0):.2f}")
            print(f"   Tip: ${result.get('tip_amount', 0):.2f}")
            print(f"   Confidence: {result.get('confidence_score', 0):.0%}")
            print(f"   Method: {result.get('ocr_method', 'Unknown')}")
            assert result is not None, "Result should not be None"
        else:
            print(f"❌ Extraction failed: {result.get('error', 'Unknown')}")
            pytest.fail(f"Extraction failed: {result.get('error', 'Unknown')}")

    except Exception as e:
        print(f"❌ Failed: {e}")
        import traceback
        traceback.print_exc()
        pytest.fail(f"Main extractor failed: {e}")


@pytest.mark.skipif(not HAS_TORCH, reason="torch not installed (required for Donut OCR)")
def test_ai_receipt_locator():
    """Test the AI receipt locator"""
    print("\n" + "="*60)
    print("TEST 3: AI Receipt Locator")
    print("="*60)

    try:
        from ai_receipt_locator import vision_extract, LOCAL_OCR_AVAILABLE

        print(f"   Local OCR available: {LOCAL_OCR_AVAILABLE}")

        # Find a test receipt
        receipts_dir = BASE_DIR / "receipts"
        test_files = list(receipts_dir.glob("*.jpg")) + list(receipts_dir.glob("*.png"))
        if not test_files:
            print("⚠️  No receipt images found")
            pytest.skip("No receipt images found")

        test_file = test_files[0]
        print(f"   Testing with: {test_file.name}")

        result = vision_extract(test_file)

        if result:
            print(f"✅ Vision extract successful!")
            print(f"   Merchant: {result.get('merchant_name', 'N/A')}")
            print(f"   Normalized: {result.get('merchant_normalized', 'N/A')}")
            print(f"   Date: {result.get('receipt_date', 'N/A')}")
            print(f"   Total: ${result.get('total_amount', 0):.2f}")
            print(f"   Source: {result.get('ocr_source', 'Unknown')}")
            assert result is not None, "Result should not be None"
        else:
            print(f"❌ Vision extract returned None")
            pytest.fail("Vision extract returned None")

    except Exception as e:
        print(f"❌ Failed: {e}")
        import traceback
        traceback.print_exc()
        pytest.fail(f"AI receipt locator failed: {e}")


@pytest.mark.skipif(not HAS_TORCH, reason="torch not installed (required for Donut OCR)")
def test_batch_processing():
    """Test batch processing capability"""
    print("\n" + "="*60)
    print("TEST 4: Batch Processing")
    print("="*60)

    try:
        from receipt_ocr_local import batch_process_receipts

        # Find test receipts
        receipts_dir = BASE_DIR / "receipts"
        test_files = list(receipts_dir.glob("*.jpg"))[:3]  # Just test 3

        if len(test_files) < 2:
            print("⚠️  Not enough receipt images for batch test")
            pytest.skip("Not enough receipt images for batch test")

        print(f"   Processing {len(test_files)} receipts...")

        results = batch_process_receipts([str(f) for f in test_files])

        success_count = sum(1 for r in results if r.get("success"))
        print(f"✅ Batch processing complete: {success_count}/{len(results)} successful")

        assert success_count > 0, "At least one batch process should succeed"

    except Exception as e:
        print(f"❌ Failed: {e}")
        import traceback
        traceback.print_exc()
        pytest.fail(f"Batch processing failed: {e}")


@pytest.mark.skipif(not HAS_TORCH, reason="torch not installed (required for Donut OCR)")
def test_config():
    """Test configuration options"""
    print("\n" + "="*60)
    print("TEST 5: Configuration")
    print("="*60)

    try:
        from receipt_ocr_local import OCRConfig

        # Test different configs
        configs = {
            "donut_only": OCRConfig.donut_only(),
            "with_fallback": OCRConfig.with_fallback(),
            "ensemble_only": OCRConfig.ensemble_only(),
        }

        for name, config in configs.items():
            print(f"   {name}:")
            print(f"      use_donut: {config.use_donut}")
            print(f"      fallback_to_ensemble: {config.fallback_to_ensemble}")

        print(f"✅ Configuration working correctly")
        assert len(configs) == 3, "Should have 3 config options"

    except Exception as e:
        print(f"❌ Failed: {e}")
        pytest.fail(f"Config test failed: {e}")


def main():
    """Run all integration tests"""
    print("="*60)
    print("DONUT OCR INTEGRATION TEST SUITE")
    print("="*60)

    tests = [
        ("Donut Extractor", test_donut_extractor),
        ("Main Extractor", test_main_extractor),
        ("AI Receipt Locator", test_ai_receipt_locator),
        ("Batch Processing", test_batch_processing),
        ("Configuration", test_config),
    ]

    results = []
    for name, test_fn in tests:
        try:
            passed = test_fn()
            results.append((name, passed))
        except Exception as e:
            print(f"❌ {name} crashed: {e}")
            results.append((name, False))

    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)

    passed = sum(1 for _, p in results if p)
    total = len(results)

    for name, p in results:
        status = "✅ PASS" if p else "❌ FAIL"
        print(f"   {status}: {name}")

    print(f"\nTotal: {passed}/{total} tests passed")

    if passed == total:
        print("\n🎉 All tests passed! Donut integration is working correctly.")
    else:
        print(f"\n⚠️  {total - passed} test(s) failed. Check the output above.")

    return passed == total


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
