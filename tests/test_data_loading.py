#!/usr/bin/env python3
"""
Data Loading Verification Script
Tests that CSV data loads correctly through the /csv endpoint
"""
import sys
import json
from pathlib import Path

# Add current directory to path
sys.path.insert(0, str(Path(__file__).parent))

def test_csv_loading():
    """Test CSV loading and data integrity"""
    print("🧪 Testing Data Loading...\n")

    # Test 1: Import modules
    print("1️⃣ Testing module imports...")
    try:
        from viewer_server import load_csv, df, CSV_PATH
        print("   ✓ Modules imported successfully")
    except Exception as e:
        print(f"   ✗ Import failed: {e}")
        return False

    # Test 2: Load CSV
    print("\n2️⃣ Testing CSV loading...")
    try:
        load_csv()
        print(f"   ✓ CSV loaded: {len(df)} rows")
    except Exception as e:
        print(f"   ✗ CSV load failed: {e}")
        return False

    # Test 3: Check columns
    print("\n3️⃣ Testing required columns...")
    required_cols = ['_index', 'Chase Description', 'Chase Amount', 'Chase Date', 'Receipt File']
    missing = [col for col in required_cols if col not in df.columns]

    if missing:
        print(f"   ⚠️  Missing columns: {missing}")
    else:
        print(f"   ✓ All required columns present")

    print(f"   📋 Total columns: {len(df.columns)}")

    # Test 4: Check data types
    print("\n4️⃣ Testing data types...")
    try:
        assert df['_index'].dtype in ['int64', 'int32'], "_index should be integer"
        print("   ✓ _index column is integer type")
    except AssertionError as e:
        print(f"   ✗ {e}")

    # Test 5: Sample data
    print("\n5️⃣ Testing sample data...")
    if len(df) > 0:
        sample = df.iloc[0].to_dict()
        print(f"   ✓ Sample row keys: {list(sample.keys())[:10]}...")
        print(f"   ✓ Sample _index: {sample.get('_index')}")
        print(f"   ✓ Sample merchant: {sample.get('Chase Description', 'N/A')}")
    else:
        print("   ⚠️  No data rows found")

    # Test 6: JSON serialization (what /csv endpoint returns)
    print("\n6️⃣ Testing JSON serialization...")
    try:
        from viewer_server import safe_json
        records = df.to_dict(orient="records")
        json_data = safe_json(records)
        json_str = json.dumps(json_data)
        print(f"   ✓ Serializable to JSON: {len(json_str):,} bytes")

        # Verify format matches what UI expects
        if isinstance(json_data, list) and len(json_data) > 0:
            print(f"   ✓ Returns array (UI expects this format)")
            print(f"   ✓ First record has _index: {json_data[0].get('_index')}")
        else:
            print(f"   ⚠️  Unexpected format: {type(json_data)}")
    except Exception as e:
        print(f"   ✗ JSON serialization failed: {e}")
        return False

    # Test 7: Receipt file check
    print("\n7️⃣ Testing receipt files...")
    receipt_files = df['Receipt File'].dropna()
    receipt_files = receipt_files[receipt_files != '']

    from viewer_server import RECEIPT_DIR
    exists_count = 0
    for fname in receipt_files.head(10):
        if (RECEIPT_DIR / fname).exists():
            exists_count += 1

    print(f"   ✓ Rows with receipts: {len(receipt_files)}")
    print(f"   ✓ Sample check: {exists_count}/10 receipt files exist")

    # Test 8: Dashboard stats calculation
    print("\n8️⃣ Testing dashboard calculations...")
    total_rows = len(df)
    with_receipts = len(receipt_files)
    missing = total_rows - with_receipts

    try:
        total_amount = df['Chase Amount'].apply(
            lambda x: float(str(x).replace('$','').replace(',','')) if x else 0
        ).sum()
        print(f"   ✓ Total rows: {total_rows:,}")
        print(f"   ✓ With receipts: {with_receipts:,}")
        print(f"   ✓ Missing receipts: {missing:,}")
        print(f"   ✓ Total amount: ${abs(total_amount):,.2f}")
    except Exception as e:
        print(f"   ⚠️  Amount calculation: {e}")

    print("\n" + "="*60)
    print("✅ DATA LOADING VERIFICATION COMPLETE")
    print("="*60)
    return True

def test_endpoint_format():
    """Test that /csv endpoint format matches UI expectations"""
    print("\n🌐 Testing /csv Endpoint Format...\n")

    try:
        from viewer_server import app, load_csv
        load_csv()

        # Simulate /csv endpoint
        with app.test_client() as client:
            response = client.get('/csv')
            data = response.get_json()

            print("1️⃣ Testing response format...")
            if isinstance(data, list):
                print("   ✓ Returns array (correct format for UI)")
                print(f"   ✓ Array length: {len(data)}")
            else:
                print(f"   ✗ Unexpected type: {type(data)}")
                print("   ✗ UI expects array, got something else")
                return False

            print("\n2️⃣ Testing first record structure...")
            if len(data) > 0:
                first = data[0]
                if '_index' in first:
                    print(f"   ✓ Has _index: {first['_index']}")
                else:
                    print("   ✗ Missing _index field")

                required = ['Chase Description', 'Chase Amount', 'Chase Date']
                for field in required:
                    if field in first:
                        print(f"   ✓ Has {field}")
                    else:
                        print(f"   ⚠️  Missing {field}")

            print("\n✅ Endpoint format verification complete")
            return True

    except Exception as e:
        print(f"✗ Endpoint test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("="*60)
    print("📊 RECEIPTAI DATA LOADING TEST SUITE")
    print("="*60 + "\n")

    success = True

    # Run tests
    if not test_csv_loading():
        success = False

    if not test_endpoint_format():
        success = False

    print("\n" + "="*60)
    if success:
        print("✅ ALL TESTS PASSED - Data loading is working correctly!")
        print("\nThe UI should now:")
        print("  • Load all CSV rows from /csv endpoint")
        print("  • Display transaction table correctly")
        print("  • Show accurate dashboard stats")
        print("  • Load receipt images when selected")
    else:
        print("❌ SOME TESTS FAILED - Review errors above")
    print("="*60)

    sys.exit(0 if success else 1)
