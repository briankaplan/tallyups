#!/usr/bin/env python3
"""
Drag & Drop Receipt Uploader
- Accepts ALL file types (PDF, HEIC, PNG, JPG, etc.)
- Converts everything to JPG
- Uses AI to extract merchant, date, amount
- Renames to merchant_date_amount.jpg
- Saves to receipts folder
- Updates database
"""

import os
import re
import sqlite3
from pathlib import Path
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory
from werkzeug.utils import secure_filename
from PIL import Image
from pillow_heif import register_heif_opener
from pdf2image import convert_from_path
import google.generativeai as genai

# Register HEIC support
register_heif_opener()

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 20 * 1024 * 1024  # 20MB max (receipts shouldn't be larger)

DB_PATH = "receipts.db"
RECEIPTS_DIR = Path("receipts")
UPLOAD_DIR = Path("uploads_temp")

# Security: Allowed file types
ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.heic', '.pdf', '.tiff', '.webp'}
ALLOWED_MAGIC_BYTES = {
    b'\xff\xd8\xff': 'jpeg',
    b'\x89PNG': 'png',
    b'GIF87a': 'gif',
    b'GIF89a': 'gif',
    b'%PDF': 'pdf',
    b'II*\x00': 'tiff',  # Little-endian TIFF
    b'MM\x00*': 'tiff',  # Big-endian TIFF
    b'RIFF': 'webp',  # WebP (check after RIFF header)
}

def validate_file(file) -> tuple:
    """Validate uploaded file type by extension and magic bytes. Returns (is_valid, error_message)."""
    if not file.filename:
        return False, "No filename provided"

    # Check extension
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return False, f"File type '{ext}' not allowed. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"

    # Check magic bytes (file content type)
    file.seek(0)
    header = file.read(16)
    file.seek(0)

    if not header:
        return False, "Empty file"

    # HEIC files have 'ftyp' signature at offset 4
    if len(header) >= 12 and header[4:8] == b'ftyp':
        heic_types = [b'heic', b'heix', b'hevc', b'hevx', b'mif1']
        if header[8:12] in heic_types:
            return True, None

    # Check common magic bytes
    for magic, file_type in ALLOWED_MAGIC_BYTES.items():
        if header.startswith(magic):
            return True, None

    # For WebP, check 'WEBP' at offset 8
    if header[:4] == b'RIFF' and len(header) >= 12 and header[8:12] == b'WEBP':
        return True, None

    return False, "File content does not match allowed file types"

GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', 'AIzaSyB7ck4xwzKdCR1e7o16fzLsY543WTMzD74')
genai.configure(api_key=GEMINI_API_KEY)

# Ensure directories exist
RECEIPTS_DIR.mkdir(exist_ok=True)
UPLOAD_DIR.mkdir(exist_ok=True)

def sanitize_filename(text: str) -> str:
    """Convert text to safe filename"""
    text = text.lower()
    text = re.sub(r'[^a-z0-9\s]', '', text)
    text = re.sub(r'\s+', '_', text)
    return text[:40]

def convert_to_jpg(file_path: Path) -> Path:
    """Convert any file to JPG"""
    suffix = file_path.suffix.lower()
    
    # Already JPG
    if suffix in ['.jpg', '.jpeg']:
        return file_path
    
    # PDF conversion
    if suffix == '.pdf':
        print(f"Converting PDF to JPG: {file_path.name}")
        images = convert_from_path(str(file_path), dpi=300, first_page=1, last_page=1)
        if images:
            jpg_path = file_path.with_suffix('.jpg')
            images[0].save(str(jpg_path), 'JPEG', quality=95, optimize=True)
            file_path.unlink()  # Delete PDF
            return jpg_path
    
    # HEIC, PNG, etc.
    else:
        print(f"Converting {suffix} to JPG: {file_path.name}")
        img = Image.open(file_path)
        if img.mode in ('RGBA', 'LA', 'P'):
            background = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
            img = background
        
        jpg_path = file_path.with_suffix('.jpg')
        img.save(str(jpg_path), 'JPEG', quality=95, optimize=True)
        if file_path != jpg_path:
            file_path.unlink()  # Delete original
        return jpg_path
    
    return file_path

def extract_with_ai(image_path: Path) -> dict:
    """Extract merchant, date, amount using Gemini"""
    try:
        model = genai.GenerativeModel('gemini-2.0-flash-exp')
        img = Image.open(image_path)
        
        prompt = """Extract from this receipt:
1. Merchant/Store name
2. Total amount (number only, no $)
3. Date (YYYY-MM-DD format)

Return ONLY in this format:
MERCHANT: [name]
AMOUNT: [number]
DATE: [YYYY-MM-DD]

If cannot find, use Unknown for merchant, 0.00 for amount, today for date."""
        
        response = model.generate_content([prompt, img])
        text = response.text.strip()
        
        result = {
            "merchant": "Unknown",
            "amount": 0.0,
            "date": datetime.now().strftime('%Y-%m-%d')
        }
        
        for line in text.split('\n'):
            line = line.strip()
            if line.startswith('MERCHANT:'):
                result["merchant"] = line.replace('MERCHANT:', '').strip()
            elif line.startswith('AMOUNT:'):
                amount_str = line.replace('AMOUNT:', '').strip()
                match = re.search(r'[\d.]+', amount_str)
                if match:
                    result["amount"] = float(match.group())
            elif line.startswith('DATE:'):
                result["date"] = line.replace('DATE:', '').strip()
        
        return result
    except Exception as e:
        print(f"AI extraction error: {e}")
        return {
            "merchant": "Unknown",
            "amount": 0.0,
            "date": datetime.now().strftime('%Y-%m-%d')
        }

@app.route('/')
def index():
    """Serve the drag-and-drop UI"""
    return send_from_directory('.', 'receipt_uploader_ui.html')

@app.route('/upload', methods=['POST'])
def upload_receipt():
    """Handle file upload with full conversion and renaming"""
    if 'file' not in request.files:
        return jsonify({'error': 'No file'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No filename'}), 400

    # Security: Validate file type
    is_valid, error_msg = validate_file(file)
    if not is_valid:
        return jsonify({'error': error_msg}), 400

    try:
        # Save uploaded file temporarily
        filename = secure_filename(file.filename)
        if not filename:
            return jsonify({'error': 'Invalid filename'}), 400
        temp_path = UPLOAD_DIR / filename
        file.save(temp_path)
        
        # Step 1: Convert to JPG
        print(f"\n📤 Processing: {filename}")
        jpg_path = convert_to_jpg(temp_path)
        print(f"✅ Converted to JPG")
        
        # Step 2: Extract data with AI
        print(f"🤖 Extracting data with AI...")
        data = extract_with_ai(jpg_path)
        print(f"   Merchant: {data['merchant']}")
        print(f"   Amount: ${data['amount']}")
        print(f"   Date: {data['date']}")
        
        # Step 3: Rename to standard format
        merchant_safe = sanitize_filename(data['merchant'])
        date_safe = data['date'].replace('-', '')
        amount_safe = str(data['amount']).replace('.', '_')
        
        final_filename = f"{merchant_safe}_{date_safe}_{amount_safe}.jpg"
        final_path = RECEIPTS_DIR / final_filename
        
        # Handle duplicate names
        counter = 1
        while final_path.exists():
            final_filename = f"{merchant_safe}_{date_safe}_{amount_safe}_{counter}.jpg"
            final_path = RECEIPTS_DIR / final_filename
            counter += 1
        
        # Move to final location
        jpg_path.rename(final_path)
        print(f"💾 Saved as: {final_filename}")
        
        # Step 4: Update database
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Insert as new receipt (you could also match to existing transaction)
        cursor.execute("""
            INSERT INTO transactions (
                chase_description,
                chase_amount,
                chase_date,
                receipt_file,
                ai_receipt_merchant,
                ai_receipt_total,
                ai_receipt_date,
                review_status,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'needs_review', ?, ?)
        """, (
            data['merchant'],
            data['amount'],
            data['date'],
            str(final_path),
            data['merchant'],
            data['amount'],
            data['date'],
            datetime.now().isoformat(),
            datetime.now().isoformat()
        ))
        
        conn.commit()
        transaction_id = cursor.lastrowid
        conn.close()
        
        print(f"✅ Added to database (ID: {transaction_id})")
        
        return jsonify({
            'success': True,
            'filename': final_filename,
            'merchant': data['merchant'],
            'amount': data['amount'],
            'date': data['date'],
            'id': transaction_id
        })
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    print("=" * 80)
    print("DRAG & DROP RECEIPT UPLOADER")
    print("=" * 80)
    print()
    print("✅ Accepts: PDF, HEIC, PNG, JPG, and more")
    print("✅ Converts all to JPG")
    print("✅ Renames to: merchant_date_amount.jpg")
    print("✅ Updates database automatically")
    print()
    print("Open: http://localhost:5051")
    print("=" * 80)
    print()
    app.run(host='0.0.0.0', port=5051, debug=True)
