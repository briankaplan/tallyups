#!/usr/bin/env python3
"""
Test PDF Upload to Viewer Server

Simulates uploading a PDF receipt via the /upload_receipt endpoint
to verify PDF→JPG conversion works correctly.
"""

import requests
from pathlib import Path

# Find a test PDF
test_pdfs = list(Path('/Users/briankaplan/Desktop/Task').rglob('*.pdf'))

if not test_pdfs:
    print("❌ No PDF files found to test with")
    exit(1)

test_pdf = test_pdfs[0]
print(f"📄 Testing with: {test_pdf.name}")
print(f"   Size: {test_pdf.stat().st_size / 1024:.1f} KB")
print()

# Prepare upload
url = 'http://localhost:5050/upload_receipt'

# Use a test transaction index (you can change this)
test_idx = 0

with open(test_pdf, 'rb') as f:
    files = {'file': (test_pdf.name, f, 'application/pdf')}
    data = {'_index': str(test_idx)}

    print(f"🚀 Uploading to: {url}")
    print(f"   For transaction index: {test_idx}")
    print()

    try:
        response = requests.post(url, files=files, data=data)

        print(f"📡 Response Status: {response.status_code}")
        print(f"📦 Response Body:")
        print(response.text)
        print()

        if response.status_code == 200:
            result = response.json()
            if result.get('success'):
                print("✅ SUCCESS!")
                print(f"   Receipt: {result.get('receipt')}")

                # Check if it was converted to JPG
                receipt_name = result.get('receipt', '')
                if receipt_name.endswith('.jpg'):
                    print("✅ PDF was converted to JPG!")
                elif receipt_name.endswith('.pdf'):
                    print("⚠️  PDF was NOT converted (still .pdf)")
                else:
                    print(f"❓ Unknown format: {receipt_name}")
            else:
                print(f"❌ Upload failed: {result.get('error')}")
        else:
            print(f"❌ HTTP Error: {response.status_code}")

    except requests.exceptions.ConnectionError:
        print("❌ Could not connect to server")
        print("   Make sure viewer_server.py is running on port 5050")
    except Exception as e:
        print(f"❌ Error: {e}")
