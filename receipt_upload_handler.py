#!/usr/bin/env python3
"""
Receipt Upload Handler
Handles drag-and-drop file uploads in the receipt viewer
- Converts all formats (PDF, HEIC, PNG, JPG) to JPG
- Uses AI to extract merchant, date, amount
- Renames to merchant_date_amount.jpg format
- Saves to receipts folder
- Updates database
"""

import os
import re
import sqlite3
from pathlib import Path
from datetime import datetime
from PIL import Image
from pillow_heif import register_heif_opener
from pdf2image import convert_from_path
import google.generativeai as genai

# Register HEIC support
register_heif_opener()

DB_PATH = "receipts.db"
RECEIPTS_DIR = Path("receipts")
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', 'AIzaSyB7ck4xwzKdCR1e7o16fzLsY543WTMzD74')

genai.configure(api_key=GEMINI_API_KEY)

def sanitize_filename(text: str) -> str:
    """Convert text to safe filename"""
    text = text.lower()
    text = re.sub(r'[^a-z0-9\s]', '', text)
    text = re.sub(r'\s+', '_', text)
    return text[:50]  # Limit length

def convert_to_jpg(file_path: Path) -> Path:
    """Convert any image/PDF to JPG"""
    
    suffix = file_path.suffix.lower()
    
    # Already JPG
    if suffix in ['.jpg', '.jpeg']:
        return file_path
    
    # PDF conversion
    if suffix == '.pdf':
        images = convert_from_path(str(file_path), dpi=300, first_page=1, last_page=1)
        if images:
            jpg_path = file_path.with_suffix('.jpg')
            images[0].save(str(jpg_path), 'JPEG', quality=95, optimize=True)
            return jpg_path
    
    # HEIC, PNG, etc. - use PIL
    else:
        img = Image.open(file_path)
        if img.mode in ('RGBA', 'LA', 'P'):
            # Convert to RGB for JPEG
            background = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
            img = background
        
        jpg_path = file_path.with_suffix('.jpg')
        img.save(str(jpg_path), 'JPEG', quality=95, optimize=True)
        return jpg_path
    
    return file_path

def extract_receipt_data_with_ai(image_path: Path) -> dict:
    """Use Gemini AI to extract receipt info"""
    
    try:
        model = genai.GenerativeModel('gemini-2.0-flash-exp')
        img = Image.open(image_path)
        
        prompt = """Extract the following from this receipt image:
        1. Merchant/Store name
        2. Total amount (just the number, no currency symbol)
        3. Date (in YYYY-MM-DD format if possible)
        
        Return ONLY in this exact format:
        MERCHANT: [name]
        AMOUNT: [number]
        DATE: [YYYY-MM-DD]
        
        If you cannot find any of these, use:
        - MERCHANT: Unknown
        - AMOUNT: 0.00
        - DATE: [today's date]
        """
        
        response = model.generate_content([prompt, img])
        text = response.text.strip()
        
        # Parse response
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

def process_uploaded_receipt(file_path: Path, transaction_id: int = None) -> dict:
    """
    Process uploaded receipt file:
    1. Convert to JPG if needed
    2. Extract data with AI
    3. Rename to merchant_date_amount.jpg
    4. Update database
    
    Returns: dict with status and info
    """
    
    try:
        # Ensure receipts directory exists
        RECEIPTS_DIR.mkdir(exist_ok=True)
        
        # Convert to JPG
        print(f"Converting {file_path.name} to JPG...")
        jpg_path = convert_to_jpg(file_path)
        
        # Extract receipt data with AI
        print(f"Extracting receipt data with AI...")
        receipt_data = extract_receipt_data_with_ai(jpg_path)
        
        # Generate standard filename
        merchant_safe = sanitize_filename(receipt_data["merchant"])
        date_safe = receipt_data["date"].replace('-', '')
        amount_safe = str(receipt_data["amount"]).replace('.', '_')
        
        new_filename = f"{merchant_safe}_{date_safe}_{amount_safe}.jpg"
        new_path = RECEIPTS_DIR / new_filename
        
        # Rename/move file
        if jpg_path != new_path:
            jpg_path.rename(new_path)
        
        print(f"Saved as: {new_filename}")
        
        # Update database if transaction_id provided
        if transaction_id:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            
            cursor.execute("""
                UPDATE transactions SET
                    receipt_file = ?,
                    ai_receipt_merchant = ?,
                    ai_receipt_total = ?,
                    ai_receipt_date = ?,
                    review_status = 'needs_review',
                    updated_at = ?
                WHERE id = ?
            """, (
                str(new_path),
                receipt_data["merchant"],
                receipt_data["amount"],
                receipt_data["date"],
                datetime.now().isoformat(),
                transaction_id
            ))
            
            conn.commit()
            conn.close()
            print(f"Updated database for transaction ID {transaction_id}")
        
        # Delete original if it was converted
        if file_path != jpg_path and file_path.exists():
            file_path.unlink()
        
        return {
            "success": True,
            "filename": new_filename,
            "path": str(new_path),
            "merchant": receipt_data["merchant"],
            "amount": receipt_data["amount"],
            "date": receipt_data["date"],
            "transaction_id": transaction_id
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }

if __name__ == "__main__":
    # Test with a file
    import sys
    if len(sys.argv) > 1:
        test_file = Path(sys.argv[1])
        if test_file.exists():
            result = process_uploaded_receipt(test_file)
            print(f"\nResult: {result}")
        else:
            print(f"File not found: {test_file}")
