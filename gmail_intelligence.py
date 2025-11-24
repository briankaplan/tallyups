#!/usr/bin/env python3
"""
Gmail Intelligence Layer
========================

Learns over time:
1. Which email accounts have receipts for which merchants
2. Which senders typically send receipts
3. Merchant name variations (Cambria = Choice Hotels)
4. What file types are actually receipts (skip business docs)

Prevents wasting AI tokens on:
- PDFs (convert or skip)
- Business documents
- Contracts/invoices
- Wrong email accounts
"""

import json
from pathlib import Path
from typing import Dict, List, Optional, Set
from datetime import datetime
from collections import defaultdict

BASE_DIR = Path(__file__).resolve().parent
INTELLIGENCE_FILE = BASE_DIR / "gmail_intelligence.json"

# =============================================================================
# MERCHANT INTELLIGENCE
# =============================================================================

# Known merchant variations
MERCHANT_ALIASES = {
    "cambria": ["choice hotels", "cambria hotel", "cambria nashville"],
    "soho house": ["sh nashville", "shnashville", "soho house nashville"],
    "anthropic": ["claude", "anthropic ai"],
    "uber": ["uber eats", "uber"],
    "doordash": ["doordash", "door dash"],
    "amazon": ["amazon.com", "amzn mktp", "amazon mktpl"],
    "apple": ["apple.com", "apple store", "app store"],
    "google": ["google storage", "google workspace", "gsuite", "google cloud"],
}

# Merchant type detection (helps build better queries)
MERCHANT_TYPES = {
    "hotel": ["hotel", "inn", "lodge", "resort", "marriott", "hilton", "hyatt", "cambria", "hampton"],
    "restaurant": ["restaurant", "cafe", "grill", "bar", "kitchen", "bistro", "diner"],
    "rideshare": ["uber", "lyft", "curb"],
    "grocery": ["kroger", "whole foods", "trader joe", "publix", "walmart"],
    "subscription": ["netflix", "spotify", "apple", "google", "microsoft", "adobe"],
}

# Sender patterns that typically have receipts
RECEIPT_SENDERS = [
    "noreply",
    "receipts",
    "orders",
    "confirmation",
    "booking",
    "reservations",
    "no-reply",
    "donotreply",
]

# Senders to SKIP (never receipts, waste tokens)
SKIP_SENDERS = [
    "linkedin",
    "facebook",
    "twitter",
    "github",
    "calendar",
    "drive-shares",
    "docs.google.com",
    "calendar-notification",
]

# =============================================================================
# LEARNING DATABASE
# =============================================================================

class GmailIntelligence:
    """
    Learns from successful matches:
    - Which account has receipts for which merchants
    - Which email senders send receipts
    - Which file patterns are actually receipts
    """

    def __init__(self):
        self.data = {
            "merchant_to_account": defaultdict(list),  # "cambria" → ["brian_personal"]
            "account_success_rate": defaultdict(lambda: {"found": 0, "searched": 0}),
            "sender_patterns": defaultdict(int),  # "noreply@choicehotels.com" → 5
            "last_updated": None,
        }
        self.load()

    def load(self):
        """Load learned intelligence"""
        if INTELLIGENCE_FILE.exists():
            try:
                with open(INTELLIGENCE_FILE) as f:
                    loaded = json.load(f)
                    self.data["merchant_to_account"] = defaultdict(list, loaded.get("merchant_to_account", {}))
                    self.data["account_success_rate"] = defaultdict(
                        lambda: {"found": 0, "searched": 0},
                        loaded.get("account_success_rate", {})
                    )
                    self.data["sender_patterns"] = defaultdict(int, loaded.get("sender_patterns", {}))
                    self.data["last_updated"] = loaded.get("last_updated")
                print(f"📚 Loaded Gmail intelligence: {len(self.data['merchant_to_account'])} merchants known")
            except Exception as e:
                print(f"⚠️  Could not load intelligence: {e}")

    def save(self):
        """Save learned intelligence"""
        self.data["last_updated"] = datetime.now().isoformat()
        with open(INTELLIGENCE_FILE, "w") as f:
            json.dump(
                {
                    "merchant_to_account": dict(self.data["merchant_to_account"]),
                    "account_success_rate": dict(self.data["account_success_rate"]),
                    "sender_patterns": dict(self.data["sender_patterns"]),
                    "last_updated": self.data["last_updated"],
                },
                f,
                indent=2
            )
        print(f"💾 Saved Gmail intelligence")

    def learn_success(self, merchant: str, account: str, sender: str):
        """Record a successful match"""
        merchant_norm = merchant.lower().strip()

        # Learn merchant → account mapping
        if account not in self.data["merchant_to_account"][merchant_norm]:
            self.data["merchant_to_account"][merchant_norm].append(account)

        # Update account success rate
        self.data["account_success_rate"][account]["found"] += 1

        # Learn sender pattern
        if sender:
            sender_lower = sender.lower()
            self.data["sender_patterns"][sender_lower] += 1

        self.save()

    def record_search(self, account: str):
        """Record that we searched this account"""
        self.data["account_success_rate"][account]["searched"] += 1

    def get_priority_accounts(self, merchant: str) -> List[str]:
        """Get which accounts to search first for this merchant"""
        merchant_norm = merchant.lower().strip()

        # Check direct match
        if merchant_norm in self.data["merchant_to_account"]:
            return self.data["merchant_to_account"][merchant_norm]

        # Check aliases
        for base_merchant, aliases in MERCHANT_ALIASES.items():
            if any(alias in merchant_norm for alias in aliases):
                if base_merchant in self.data["merchant_to_account"]:
                    return self.data["merchant_to_account"][base_merchant]

        # Return accounts sorted by success rate
        accounts = ["brian_personal", "brian_mcr", "brian_downhome"]
        return sorted(
            accounts,
            key=lambda a: self.data["account_success_rate"][a]["found"],
            reverse=True
        )

    def should_skip_sender(self, sender: str) -> bool:
        """Check if this sender never has receipts"""
        if not sender:
            return False
        sender_lower = sender.lower()
        return any(skip in sender_lower for skip in SKIP_SENDERS)

    def is_receipt_sender(self, sender: str) -> bool:
        """Check if this sender typically has receipts"""
        if not sender:
            return False
        sender_lower = sender.lower()

        # Known good sender
        if any(pattern in sender_lower for pattern in RECEIPT_SENDERS):
            return True

        # Learned sender
        if sender_lower in self.data["sender_patterns"]:
            return self.data["sender_patterns"][sender_lower] >= 2  # Seen 2+ times

        return False

# =============================================================================
# SMART QUERY BUILDER
# =============================================================================

def build_smart_query(merchant: str, amount: float, date_after: str, date_before: str) -> str:
    """
    Build intelligent Gmail query based on merchant type and known variations

    Returns smarter query like:
    - "cambria OR choice hotels" (not generic "receipt OR invoice")
    - Date range (optional, for narrowing)
    - NO amount filtering (amount used for scoring only, not filtering)
    - NO has:attachment requirement (confirmation emails are valuable too)
    """
    merchant_lower = merchant.lower().strip()

    # Get merchant variations
    variations = [merchant]
    for base_merchant, aliases in MERCHANT_ALIASES.items():
        if base_merchant in merchant_lower or any(alias in merchant_lower for alias in aliases):
            variations.extend(aliases)

    # Build query parts
    parts = []

    # Merchant variations (REQUIRED - this is what we search for)
    if variations:
        merchant_query = " OR ".join(f'"{v}"' for v in set(variations[:5]))  # Limit to 5 variations
        parts.append(f"({merchant_query})")

    # Date range (OPTIONAL - helps narrow but not always accurate due to forwarding)
    # Only add dates if they're reasonably recent (not too restrictive)
    if date_after and date_before:
        parts.append(f"after:{date_after}")
        parts.append(f"before:{date_before}")

    # DO NOT filter by amount - many confirmation emails don't have final amount yet
    # DO NOT require has:attachment - confirmation emails are valuable for matching

    return " ".join(parts)

# =============================================================================
# FILE TYPE INTELLIGENCE
# =============================================================================

def should_process_attachment(filename: str, mime_type: str) -> tuple[bool, str]:
    """
    Determine if we should process this attachment

    Returns (should_process, reason)
    """
    if not filename and not mime_type:
        return False, "no filename or mime"

    filename_lower = filename.lower() if filename else ""

    # Skip obvious non-receipts
    skip_patterns = [
        "signature", "logo", "icon", "banner",
        "contract", "agreement", "terms",
        "w-9", "w9", "invoice", "statement",
        ".ics", ".vcf", ".txt", ".doc", ".docx",
        ".xls", ".xlsx", ".csv",
    ]

    if any(pattern in filename_lower for pattern in skip_patterns):
        return False, f"skip pattern: {filename_lower}"

    # Only process images (OpenAI vision only accepts images)
    image_extensions = [".jpg", ".jpeg", ".png", ".webp", ".heic"]
    is_image = any(filename_lower.endswith(ext) for ext in image_extensions)

    if mime_type:
        is_image = is_image or mime_type.startswith("image/")

    if not is_image:
        # Skip PDFs - they fail in vision API
        if ".pdf" in filename_lower or mime_type == "application/pdf":
            return False, "pdf (vision API doesn't support)"
        return False, "not an image"

    # Prefer files with "receipt" in name
    if "receipt" in filename_lower:
        return True, "receipt in filename"

    # Image files are potentially receipts
    return True, "image file"

# =============================================================================
# GLOBAL INSTANCE
# =============================================================================

_intelligence = None

def get_intelligence() -> GmailIntelligence:
    """Get or create global intelligence instance"""
    global _intelligence
    if _intelligence is None:
        _intelligence = GmailIntelligence()
    return _intelligence
