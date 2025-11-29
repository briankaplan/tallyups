#!/usr/bin/env python3
"""
Merchant Intelligence Processing Script
Normalizes merchants, detects subscriptions, categorizes, and generates descriptions

Now uses MySQL database via db_mysql.py for all storage.
"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import MySQL database
try:
    from db_mysql import get_mysql_db
    _db = get_mysql_db()
    USE_MYSQL = _db.use_mysql if _db else False
except ImportError:
    USE_MYSQL = False
    _db = None

# =============================================================================
# DATABASE LOOKUPS
# =============================================================================

def load_merchant_db():
    """Load merchant knowledge from MySQL database"""
    if USE_MYSQL and _db:
        return _db.get_all_merchants()
    return {}


def search_contacts(query):
    """Search contacts by name for note generation"""
    if not query or len(query) < 2:
        return []

    if USE_MYSQL and _db:
        return _db.search_contacts(query, limit=5)
    return []


def extract_and_match_contacts(notes):
    """Extract names from notes and match to CRM contacts"""
    if not notes:
        return []

    matched_contacts = []

    # Common patterns for names in notes
    # Pattern 1: "with FirstName LastName"
    # Pattern 2: "FirstName LastName -"
    # Pattern 3: "FirstName LastName,"

    # Extract potential names (capitalized words)
    name_pattern = r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b'
    potential_names = re.findall(name_pattern, notes)

    # Filter out common words that aren't names
    skip_words = {
        'Down', 'Home', 'Music', 'City', 'Rodeo', 'Los', 'Angeles',
        'Nashville', 'Meeting', 'Dinner', 'Lunch', 'Breakfast', 'Coffee',
        'Flight', 'Hotel', 'Trip', 'Uber', 'Business', 'Personal',
        'January', 'February', 'March', 'April', 'May', 'June',
        'July', 'August', 'September', 'October', 'November', 'December',
        'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'
    }

    for name in potential_names:
        if name in skip_words or name.split()[0] in skip_words:
            continue

        # Search in contacts database
        matches = search_contacts(name.split()[0])  # Search by first name
        for match in matches:
            # Check if full name appears in notes
            if match['name'].lower() in notes.lower():
                matched_contacts.append(match)
                break
            # Check if first name matches closely
            elif name.lower() in match['name'].lower():
                matched_contacts.append(match)
                break

    # Remove duplicates
    seen = set()
    unique_contacts = []
    for c in matched_contacts:
        if c['name'] not in seen:
            seen.add(c['name'])
            unique_contacts.append(c)

    return unique_contacts[:3]  # Max 3 contacts


# Load merchant database at module load
MERCHANT_DB = load_merchant_db()

# =============================================================================
# MERCHANT KNOWLEDGE BASE
# =============================================================================

SUBSCRIPTION_PATTERNS = {
    "APPLE.COM/BILL": {
        "merchant": "Apple",
        "category": "Software & Subscriptions",
        "subscription": True,
        "plans": {
            (19.94, 19.96): "Apple One Family",
            (10.99, 11.00): "Apple Music",
            (2.99, 3.00): "iCloud 200GB",
            (0.99, 1.00): "iCloud 50GB",
        }
    },
    "CLAUDE.AI SUBSCRIPTION": {
        "merchant": "Claude AI (Anthropic)",
        "category": "Software & Subscriptions",
        "subscription": True,
        "plan": "Claude Pro"
    },
    "SPOTIFY USA": {
        "merchant": "Spotify",
        "category": "Software & Subscriptions",
        "subscription": True,
        "plan": "Spotify Premium"
    },
    "MIDJOURNEY INC.": {
        "merchant": "Midjourney",
        "category": "Software & Subscriptions",
        "subscription": True,
        "plan": "Midjourney Subscription"
    },
    "CURSOR AI POWERED IDE": {
        "merchant": "Cursor",
        "category": "Software & Subscriptions",
        "subscription": True,
        "plan": "Cursor Pro"
    },
    "CURSOR USAGE": {
        "merchant": "Cursor",
        "category": "Software & Subscriptions",
        "subscription": True,
        "plan": "Cursor Usage"
    },
    "CLOUDFLARE": {
        "merchant": "Cloudflare",
        "category": "Software & Subscriptions",
        "subscription": True,
        "plan": "Cloudflare Services"
    },
    "EXPENSIFY INC.": {
        "merchant": "Expensify",
        "category": "Software & Subscriptions",
        "subscription": True,
        "plan": "Expensify"
    },
    "CALENDARBRIDGE": {
        "merchant": "CalendarBridge",
        "category": "Software & Subscriptions",
        "subscription": True,
        "plan": "CalendarBridge Sync"
    },
    "HIVE CO": {
        "merchant": "Hive",
        "category": "Software & Subscriptions",
        "subscription": True,
        "plan": "Hive Project Management"
    },
    "SOURCEGRAPH INC": {
        "merchant": "Sourcegraph",
        "category": "Software & Subscriptions",
        "subscription": True,
        "plan": "Sourcegraph"
    },
    "COWBOY CHANNEL PLUS": {
        "merchant": "Cowboy Channel Plus",
        "category": "Software & Subscriptions",
        "subscription": True,
        "plan": "Cowboy Channel Plus"
    },
    "ANTHROPIC": {
        "merchant": "Anthropic",
        "category": "Software & Subscriptions",
        "subscription": True,
        "plan": "Anthropic API"
    },
    "EASYFAQ.IO": {
        "merchant": "EasyFAQ",
        "category": "Software & Subscriptions",
        "subscription": True,
        "plan": "EasyFAQ"
    },
    "HUGGINGFACE": {
        "merchant": "Hugging Face",
        "category": "Software & Subscriptions",
        "subscription": True,
        "plan": "Hugging Face"
    },
    "CHARTMETRIC": {
        "merchant": "Chartmetric",
        "category": "Software & Subscriptions",
        "subscription": True,
        "plan": "Chartmetric Analytics"
    },
    "AMAZON PRIME": {
        "merchant": "Amazon Prime",
        "category": "Software & Subscriptions",
        "subscription": True,
        "plan": "Amazon Prime"
    },
    "IM-ADA.AI": {
        "merchant": "Ada AI",
        "category": "Software & Subscriptions",
        "subscription": True,
        "plan": "Ada AI"
    },
    "EVERY STUDIO": {
        "merchant": "Every Studio",
        "category": "Software & Subscriptions",
        "subscription": True,
        "plan": "Every Studio"
    },
    "YOUTUBE TV": {
        "merchant": "YouTube TV",
        "category": "Software & Subscriptions",
        "subscription": True,
        "plan": "YouTube TV"
    },
    "OPENAI": {
        "merchant": "OpenAI",
        "category": "Software & Subscriptions",
        "subscription": True,
        "plan": "ChatGPT Plus"
    },
}

MERCHANT_NORMALIZATIONS = {
    # Soho House
    "SH NASHVILLE": "Soho House Nashville",
    "SOHO HOUSE": "Soho House",

    # Transportation
    "UBER *TRIP": "Uber",
    "UBER TRIP": "Uber",
    "LYFT": "Lyft",

    # Parking
    "METROPOLIS PARKING": "Metropolis Parking",
    "PMC - PAID PARKING": "PMC Parking",
    "PARK HAPPY LLC": "Park Happy",

    # DoorDash patterns
    "DD DOORDASH": "DoorDash",

    # Airlines
    "SOUTHWES": "Southwest Airlines",
    "SOUTHWEST": "Southwest Airlines",
    "DELTA": "Delta Airlines",
    "AMERICAN": "American Airlines",
    "UNITED": "United Airlines",

    # Hotels
    "MARRIOTT": "Marriott",
    "HILTON": "Hilton",
    "HYATT": "Hyatt",
    "PEPPERMILL": "Peppermill Resort & Casino",

    # Restaurants
    "CORNER PUB": "Corner Pub",
    "12 SOUTH TAPROOM": "12 South Taproom & Grill",
    "FLORA - BAMA": "Flora-Bama Lounge",
    "THE WHARF F&AMP;B": "The Wharf Orange Beach",
    "HILLSTONE": "Hillstone",
    "CHEESECAKE FACTORY": "The Cheesecake Factory",

    # Retail
    "AMAZON PRIME": "Amazon Prime",
    "AMAZON MKTPLACE": "Amazon",
    "AMZN MKTP": "Amazon",
    "AMAZON": "Amazon",
    "TARGET": "Target",
    "WALMART": "Walmart",
    "COSTCO": "Costco",
    "NORDSTROM": "Nordstrom",

    # Apple
    "APPLE.COM/US": "Apple Store Online",

    # Banking
    "PURCHASE INTEREST CHARGE": "Chase Interest Charge",
    "PAYMENT THANK YOU": "Chase Payment",
}

CATEGORY_RULES = {
    # By merchant type
    "parking": "Auto & Parking",
    "uber": "Travel",
    "lyft": "Travel",
    "airlines": "Travel",
    "hotel": "Travel",
    "restaurant": "Meals & Entertainment",
    "soho house": "Meals & Entertainment",
    "amazon": "Office Supplies",
    "target": "Office Supplies",
    "nordstrom": "Shopping",
    "doordash": "Meals & Entertainment",
}

# =============================================================================
# MERCHANT INTELLIGENCE FUNCTIONS
# =============================================================================

def normalize_merchant(chase_description: str, amount: float = 0) -> dict:
    """Normalize merchant name and detect patterns"""
    desc_upper = chase_description.upper().strip()

    result = {
        "merchant": chase_description,
        "category": None,
        "is_subscription": False,
        "subscription_name": None,
        "confidence": 0.7
    }

    # Check merchant database first (highest priority)
    if desc_upper in MERCHANT_DB:
        db_merchant = MERCHANT_DB[desc_upper]
        result["merchant"] = db_merchant['normalized']
        result["category"] = db_merchant['category']
        result["is_subscription"] = db_merchant['is_subscription']
        result["confidence"] = 0.95

        if db_merchant['is_subscription']:
            result["subscription_name"] = f"{db_merchant['normalized']} Subscription"

        # Still check subscription patterns for plan names
        for pattern, info in SUBSCRIPTION_PATTERNS.items():
            if pattern in desc_upper and "plans" in info:
                for amount_range, plan_name in info["plans"].items():
                    if amount_range[0] <= amount <= amount_range[1]:
                        result["subscription_name"] = plan_name
                        result["confidence"] = 0.98
                        break

        return result

    # Check subscription patterns
    for pattern, info in SUBSCRIPTION_PATTERNS.items():
        if pattern in desc_upper:
            result["merchant"] = info["merchant"]
            result["category"] = info["category"]
            result["is_subscription"] = info.get("subscription", False)
            result["confidence"] = 0.98

            # Determine subscription plan
            if "plans" in info:
                for amount_range, plan_name in info["plans"].items():
                    if amount_range[0] <= amount <= amount_range[1]:
                        result["subscription_name"] = plan_name
                        break
                if not result["subscription_name"]:
                    result["subscription_name"] = f"{info['merchant']} Subscription"
            else:
                result["subscription_name"] = info.get("plan", f"{info['merchant']} Subscription")

            return result

    # Check merchant normalizations
    for pattern, normalized in MERCHANT_NORMALIZATIONS.items():
        if pattern in desc_upper:
            result["merchant"] = normalized
            result["confidence"] = 0.95

            # Assign categories based on merchant type
            normalized_lower = normalized.lower()
            if "parking" in normalized_lower:
                result["category"] = "Auto & Parking"
            elif "uber" in normalized_lower or "lyft" in normalized_lower:
                result["category"] = "Travel"
            elif "airlines" in normalized_lower or "southwest" in normalized_lower:
                result["category"] = "Travel"
            elif any(h in normalized_lower for h in ["marriott", "hilton", "hyatt", "peppermill", "hotel"]):
                result["category"] = "Travel"
            elif "soho house" in normalized_lower:
                result["category"] = "Meals & Entertainment"
            elif any(r in normalized_lower for r in ["pub", "taproom", "grill", "wharf", "flora-bama", "hillstone", "cheesecake"]):
                result["category"] = "Meals & Entertainment"
            elif "doordash" in normalized_lower:
                result["category"] = "Meals & Entertainment"
            elif "amazon" in normalized_lower or "target" in normalized_lower:
                result["category"] = "Office Supplies"
            elif "nordstrom" in normalized_lower:
                result["category"] = "Shopping"
            elif "apple" in normalized_lower:
                result["category"] = "Office Supplies"
            elif "interest charge" in normalized_lower or "payment" in normalized_lower:
                result["category"] = "Fees & Charges"

            return result

    # Handle DoorDash with sub-merchant
    if "DD DOORDASH" in desc_upper or "DOORDASH" in desc_upper:
        sub_merchant = desc_upper.replace("DD DOORDASH", "").replace("DOORDASH", "").strip()
        if sub_merchant:
            result["merchant"] = f"DoorDash ({sub_merchant.title()})"
        else:
            result["merchant"] = "DoorDash"
        result["category"] = "Meals & Entertainment"
        result["confidence"] = 0.92
        return result

    # Default: clean up the merchant name with smart normalization
    cleaned = chase_description.upper().strip()

    # Strip POS prefixes (Toast, Square, PayPal, etc.)
    pos_prefixes = [
        "TST* ", "TST*", "SQ *", "SQ*", "PAYPAL *", "PAYPAL*",
        "SP * ", "SP *", "STRIPE* ", "STRIPE*", "GUST* ", "GUST*",
        "POS ", "DEBIT CARD PURCHASE - ", "CHECK CARD PURCHASE - "
    ]
    for prefix in pos_prefixes:
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):].strip()
            break

    # Strip location/terminal suffixes
    location_patterns = [
        r'\s*-\s*AIRP.*$',           # - AIRP, - AIRPORT
        r'\s*-\s*[A-Z]{2,3}\s*$',    # - TN, - CA, etc.
        r'\s+NASHVILLE\s+TN.*$',
        r'\s+[A-Z]{2}\s+\d{5}.*$',   # State + ZIP
        r'\s+#\d+.*$',               # Store numbers
        r'\s+\d{10,}$',              # Long numbers (transaction IDs)
        r'\s+[A-Z]{2}$',             # Two-letter state codes at end
    ]

    for pattern in location_patterns:
        cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)

    # Clean up special characters
    cleaned = cleaned.replace("&AMP;", "&").strip()
    cleaned = re.sub(r'\s+', ' ', cleaned)  # Multiple spaces to single

    # Title case the result
    if cleaned:
        result["merchant"] = cleaned.title()
        # Detect category from common restaurant/meal indicators
        lower = cleaned.lower()
        if any(word in lower for word in ['cafe', 'restaurant', 'pizzeria', 'grill', 'kitchen', 'bar', 'pub', 'diner', 'bistro', 'taco', 'burger', 'sushi', 'thai', 'italian', 'mexican']):
            result["category"] = "Meals & Entertainment"
            result["confidence"] = 0.75
        elif any(word in lower for word in ['parking', 'garage']):
            result["category"] = "Auto & Parking"
            result["confidence"] = 0.75
        elif any(word in lower for word in ['hotel', 'inn', 'suites', 'resort']):
            result["category"] = "Travel"
            result["confidence"] = 0.75
        else:
            result["confidence"] = 0.6
    else:
        result["merchant"] = chase_description.replace("&AMP;", "&").strip()
        result["confidence"] = 0.6

    return result


def generate_description(
    merchant: str,
    amount: float,
    date: str,
    business_type: str,
    notes: str = None,
    is_subscription: bool = False,
    subscription_name: str = None,
    category: str = None,
    matched_contacts: list = None
) -> str:
    """Generate human-readable description"""

    # Parse date for month name
    try:
        dt = datetime.strptime(date, "%Y-%m-%d")
        month_name = dt.strftime("%B")
    except:
        month_name = ""

    # Subscription description
    if is_subscription and subscription_name:
        if business_type == "Personal":
            return f"{month_name} {subscription_name} subscription."
        else:
            return f"{month_name} {subscription_name} subscription for {business_type} operations."

    # Use matched contacts from CRM, or extract from notes as fallback
    contacts = matched_contacts or []
    if not contacts and notes:
        # Fallback: extract from existing notes
        name_patterns = [
            r"with\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
            r"([A-Z][a-z]+\s+[A-Z][a-z]+)(?:\s*[-,])",
        ]
        for pattern in name_patterns:
            matches = re.findall(pattern, notes)
            contacts.extend(matches)
        contacts = list(set(contacts))[:3]

    merchant_lower = merchant.lower()

    # Parking
    if "parking" in merchant_lower:
        if business_type == "Personal":
            return f"Parking at {merchant}."
        else:
            return f"Parking for {business_type} business."

    # Uber/Lyft
    if "uber" in merchant_lower or "lyft" in merchant_lower:
        if notes and any(word in notes.lower() for word in ["trip", "la", "los angeles", "travel"]):
            return f"{merchant} ride during business travel for {business_type}."
        elif contacts:
            return f"{merchant} ride with {', '.join(contacts[:2])} for {business_type}."
        else:
            return f"{merchant} ride for {business_type} business."

    # Airlines
    if "airlines" in merchant_lower or "southwest" in merchant_lower:
        if notes:
            # Extract route from notes
            route_match = re.search(r"([\w\s]+)\s+(?:to|flight)\s+([\w\s]+)", notes, re.I)
            if route_match:
                return f"Flight from {route_match.group(1).strip()} to {route_match.group(2).strip()} for {business_type} business."
        return f"{merchant} flight for {business_type} business travel."

    # Hotels
    if any(h in merchant_lower for h in ["marriott", "hilton", "hyatt", "peppermill", "hotel", "resort"]):
        if notes:
            return f"Hotel stay at {merchant} for {business_type} business. {notes.split('.')[0]}."
        return f"Hotel stay at {merchant} for {business_type} business travel."

    # Soho House
    if "soho house" in merchant_lower:
        if contacts:
            return f"Meeting at {merchant} with {', '.join(contacts[:2])} for {business_type}."
        elif notes and "lunch" in notes.lower():
            return f"Lunch meeting at {merchant} for {business_type}."
        elif notes and "dinner" in notes.lower():
            return f"Dinner meeting at {merchant} for {business_type}."
        else:
            return f"Business meeting at {merchant} for {business_type}."

    # Restaurants
    if category == "Meals & Entertainment" or any(r in merchant_lower for r in ["pub", "grill", "taproom", "wharf", "flora", "restaurant"]):
        if contacts:
            return f"Business meal at {merchant} with {', '.join(contacts[:2])} for {business_type}."
        elif notes:
            return f"Business meal at {merchant} for {business_type}. {notes.split('.')[0]}."
        else:
            meal_type = "Lunch" if amount < 40 else "Dinner"
            return f"{meal_type} at {merchant} for {business_type}."

    # DoorDash
    if "doordash" in merchant_lower:
        if notes and "travel" in notes.lower():
            return f"{merchant} delivery during business travel for {business_type}."
        elif notes and any(word in notes.lower() for word in ["lunch", "meeting"]):
            return f"{merchant} delivery for working lunch - {business_type}."
        else:
            return f"{merchant} delivery for {business_type}."

    # Office supplies
    if category == "Office Supplies" or any(s in merchant_lower for s in ["amazon", "target", "staples"]):
        if business_type == "Personal":
            return f"Purchase from {merchant}."
        else:
            return f"Office supplies from {merchant} for {business_type}."

    # Fees
    if "interest" in merchant_lower or "fee" in merchant_lower:
        return f"Credit card {merchant.lower()}."

    # Payment
    if "payment" in merchant_lower:
        return f"Credit card payment - thank you."

    # Default
    if notes and len(notes) > 10:
        return notes.split('.')[0] + "."
    elif business_type == "Personal":
        return f"Personal expense at {merchant}."
    else:
        return f"Business expense at {merchant} for {business_type}."


def process_transaction(row: dict, receipt_path: str = None) -> dict:
    """
    Process a single transaction through Merchant Intelligence.

    If receipt_path is provided and valid, runs Donut OCR to get accurate
    merchant/item data from the actual receipt image.
    """
    chase_desc = row.get("chase_description", "") or ""
    amount = row.get("chase_amount", 0) or 0
    date = row.get("chase_date", "") or ""
    business_type = row.get("business_type", "") or "Business"
    notes = row.get("notes", "") or ""
    chase_category = row.get("chase_category", "") or ""

    # Start with pattern-based normalization
    mi = normalize_merchant(chase_desc, amount)

    ocr_merchant = None
    ocr_items = None
    ocr_confidence = 0.0

    # If receipt provided, run Donut OCR for accurate data
    if receipt_path:
        try:
            from pathlib import Path
            receipt_file = Path(receipt_path)

            if receipt_file.exists() and receipt_file.suffix.lower() in ['.jpg', '.jpeg', '.png', '.pdf']:
                # Import Donut extractor
                import sys
                sys.path.insert(0, str(Path(__file__).parent.parent))
                from receipt_ocr_local import extract_receipt_fields_local

                print(f"   🔍 Running Donut OCR on receipt: {receipt_file.name}")
                ocr_result = extract_receipt_fields_local(str(receipt_file))

                if ocr_result and ocr_result.get("success"):
                    ocr_merchant = ocr_result.get("ai_receipt_merchant") or ocr_result.get("Receipt Merchant", "")
                    ocr_total = ocr_result.get("ai_receipt_total") or ocr_result.get("Receipt Total", 0)
                    ocr_date = ocr_result.get("ai_receipt_date") or ocr_result.get("Receipt Date", "")
                    ocr_confidence = ocr_result.get("confidence_score", 0.0)

                    # Get items if available (for subscriptions like Apple)
                    raw_json = ocr_result.get("raw_json", "")
                    if raw_json:
                        try:
                            import json
                            raw_data = json.loads(raw_json)
                            ocr_items = raw_data.get("items", [])
                        except:
                            pass

                    # Use OCR merchant if confidence is high enough
                    if ocr_merchant and ocr_confidence >= 0.6:
                        # Override pattern-based with actual receipt data
                        mi["merchant"] = ocr_merchant.strip()
                        mi["confidence"] = max(mi["confidence"], ocr_confidence)
                        print(f"   ✅ Donut found: {ocr_merchant} (conf: {ocr_confidence:.0%})")

                        # For Apple receipts, extract actual app name
                        if "apple" in chase_desc.lower() and ocr_items:
                            app_names = [item.get("name", "") for item in ocr_items if item.get("name")]
                            if app_names:
                                mi["merchant"] = f"Apple ({', '.join(app_names[:2])})"
                                mi["subscription_name"] = app_names[0]
                                mi["is_subscription"] = True
                                print(f"   📱 Apple subscription: {app_names[0]}")
                    else:
                        print(f"   ⚠️ Donut low confidence ({ocr_confidence:.0%}), using pattern match")
                else:
                    print(f"   ⚠️ Donut OCR failed: {ocr_result.get('error', 'Unknown')}")
        except Exception as e:
            print(f"   ⚠️ OCR error: {e}")

    # Use existing category if MI didn't determine one
    if not mi["category"]:
        if chase_category:
            mi["category"] = chase_category
        elif business_type == "Personal":
            mi["category"] = "Personal"
        else:
            mi["category"] = "Business Expenses"

    # Match contacts from notes using CRM database
    matched_contacts = extract_and_match_contacts(notes)
    contact_names = [c['name'] for c in matched_contacts]

    # Generate description with matched contacts
    description = generate_description(
        merchant=mi["merchant"],
        amount=amount,
        date=date,
        business_type=business_type,
        notes=notes,
        is_subscription=mi["is_subscription"],
        subscription_name=mi["subscription_name"],
        category=mi["category"],
        matched_contacts=contact_names
    )

    return {
        "mi_merchant": mi["merchant"],
        "mi_category": mi["category"],
        "mi_description": description,
        "mi_confidence": mi["confidence"],
        "mi_is_subscription": 1 if mi["is_subscription"] else 0,
        "mi_subscription_name": mi["subscription_name"],
        "mi_processed_at": datetime.now().isoformat()
    }


def process_all_transactions(smart_skip: bool = True, use_receipts: bool = True):
    """
    Process all transactions in the MySQL database.

    Args:
        smart_skip: If True, skip rows with mi_confidence >= 0.85
        use_receipts: If True, use Donut OCR on matched receipts
    """
    from pathlib import Path

    if not USE_MYSQL or not _db:
        print("❌ MySQL not available")
        return 0

    conn = _db.get_connection()
    cursor = conn.cursor()

    # Get all transactions with receipt paths
    if smart_skip:
        # Only get rows that need processing
        cursor.execute("""
            SELECT id, chase_description, chase_amount, chase_date,
                   chase_category, business_type, notes, receipt_file,
                   mi_confidence
            FROM transactions
            WHERE mi_confidence IS NULL
               OR mi_confidence < 0.85
               OR mi_merchant IS NULL
               OR mi_merchant = ''
        """)
    else:
        cursor.execute("""
            SELECT id, chase_description, chase_amount, chase_date,
                   chase_category, business_type, notes, receipt_file,
                   mi_confidence
            FROM transactions
        """)

    rows = cursor.fetchall()
    total = len(rows)
    processed = 0
    skipped = 0
    ocr_used = 0

    print(f"🧠 Merchant Intelligence Batch Processing (MySQL)")
    print(f"   Found {total} transactions to process")
    print(f"   Smart skip: {smart_skip}, Use receipts: {use_receipts}")
    print()

    for row in rows:
        row_dict = dict(row) if hasattr(row, 'keys') else {
            'id': row[0], 'chase_description': row[1], 'chase_amount': row[2],
            'chase_date': row[3], 'chase_category': row[4], 'business_type': row[5],
            'notes': row[6], 'receipt_file': row[7], 'mi_confidence': row[8]
        }

        # Get receipt path if using receipts
        receipt_path = None
        if use_receipts:
            rp = row_dict.get("receipt_file", "")
            if rp:
                # Handle relative paths
                if not rp.startswith("/"):
                    rp = str(Path(__file__).parent.parent / "receipts" / rp)
                if Path(rp).exists():
                    receipt_path = rp
                    ocr_used += 1

        print(f"[{processed+1}/{total}] {row_dict.get('chase_description', '')[:40]}...")
        mi_result = process_transaction(row_dict, receipt_path)

        # Update the transaction
        cursor.execute("""
            UPDATE transactions SET
                mi_merchant = %s,
                mi_category = %s,
                mi_description = %s,
                mi_confidence = %s,
                mi_is_subscription = %s,
                mi_subscription_name = %s,
                mi_processed_at = %s
            WHERE id = %s
        """, (
            mi_result["mi_merchant"],
            mi_result["mi_category"],
            mi_result["mi_description"],
            mi_result["mi_confidence"],
            mi_result["mi_is_subscription"],
            mi_result["mi_subscription_name"],
            mi_result["mi_processed_at"],
            row_dict["id"]
        ))

        processed += 1
        if processed % 50 == 0:
            print(f"\n  ✓ Processed {processed}/{total}")
            conn.commit()

    conn.commit()
    conn.close()

    print(f"\n✅ Completed!")
    print(f"   Processed: {processed}")
    print(f"   Receipts OCR'd: {ocr_used}")
    if smart_skip:
        # Count how many were skipped
        conn2 = _db.get_connection()
        cursor2 = conn2.cursor()
        cursor2.execute("SELECT COUNT(*) as cnt FROM transactions WHERE mi_confidence >= 0.85")
        result = cursor2.fetchone()
        skipped = result['cnt'] if hasattr(result, 'keys') else result[0]
        conn2.close()
        print(f"   Smart-skipped: {skipped} (confidence >= 85%)")

    return processed


def process_single_with_ocr(transaction_id: int) -> dict:
    """
    Process a single transaction with Donut OCR.
    Used by the 'A' hotkey for individual processing.
    """
    from pathlib import Path

    if not USE_MYSQL or not _db:
        return {"error": "MySQL not available"}

    conn = _db.get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, chase_description, chase_amount, chase_date,
               chase_category, business_type, notes, receipt_file
        FROM transactions
        WHERE id = %s
    """, (transaction_id,))

    row = cursor.fetchone()
    if not row:
        conn.close()
        return {"error": f"Transaction {transaction_id} not found"}

    row_dict = dict(row) if hasattr(row, 'keys') else {
        'id': row[0], 'chase_description': row[1], 'chase_amount': row[2],
        'chase_date': row[3], 'chase_category': row[4], 'business_type': row[5],
        'notes': row[6], 'receipt_file': row[7]
    }

    # Get receipt path
    receipt_path = None
    rp = row_dict.get("receipt_file", "")
    if rp:
        if not rp.startswith("/"):
            rp = str(Path(__file__).parent.parent / "receipts" / rp)
        if Path(rp).exists():
            receipt_path = rp

    print(f"🔄 Processing transaction {transaction_id}: {row_dict.get('chase_description', '')[:40]}")
    if receipt_path:
        print(f"   📄 Receipt: {Path(receipt_path).name}")

    # Process with OCR
    mi_result = process_transaction(row_dict, receipt_path)

    # Update the transaction
    cursor.execute("""
        UPDATE transactions SET
            mi_merchant = %s,
            mi_category = %s,
            mi_description = %s,
            mi_confidence = %s,
            mi_is_subscription = %s,
            mi_subscription_name = %s,
            mi_processed_at = %s
        WHERE id = %s
    """, (
        mi_result["mi_merchant"],
        mi_result["mi_category"],
        mi_result["mi_description"],
        mi_result["mi_confidence"],
        mi_result["mi_is_subscription"],
        mi_result["mi_subscription_name"],
        mi_result["mi_processed_at"],
        transaction_id
    ))

    conn.commit()
    conn.close()

    print(f"   ✅ Done: {mi_result['mi_merchant']} ({mi_result['mi_confidence']:.0%})")

    return {
        "id": transaction_id,
        "success": True,
        "used_ocr": receipt_path is not None,
        **mi_result
    }


if __name__ == "__main__":
    process_all_transactions()
