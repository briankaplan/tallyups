#!/usr/bin/env python3
"""
MERCHANT INTELLIGENCE - Advanced merchant normalization and matching
Makes matching PERFECT by understanding merchant variations, chains, and patterns
"""

import re
from typing import Dict, List, Optional, Tuple
from difflib import SequenceMatcher

class MerchantIntelligence:
    """Advanced merchant name normalization and matching"""

    # Chain restaurant/business mappings
    CHAIN_PATTERNS = {
        # Nashville restaurants
        'soho house': ['soho house nashville', 'sh nashville', 'sohohouse'],
        '12 south taproom': ['12 south taproom', '12south', 'taproom'],
        'corner pub': ['corner pub green hills', 'corner pub', 'cornerpub'],
        'optimist': ['optimist nashville', 'the optimist'],
        'britannia pub': ['britannia pub', 'britannia'],
        'hattie bs': ['hattie bs', 'hattieb'],
        'panchosbar': ['panchosbar', 'panchos'],

        # Digital services
        'apple': ['apple.com/bill', 'apple com', 'apple.com', 'applecombill'],
        'spotify': ['spotify usa', 'spotify.com'],
        'claude': ['claude ai', 'anthropic', 'claude-ai'],
        'cursor': ['cursor ai', 'cursor.ai', 'cursor-ai-powered-ide'],
        'google': ['google gsuite', 'google workspace', 'google storage'],
        'midjourney': ['midjourney inc', 'midjourney.com'],
        'huggingface': ['hugging face inc', 'huggingface'],
        'cloudflare': ['cloudflare inc', 'cloudflare.com'],
        'kit': ['kit.com', 'kit co', 'stripe kit', 'convertkit'],  # Kit (formerly ConvertKit)
        'replit': ['replit.com', 'replit inc'],
        'ideogram': ['ideogram.ai', 'ideogram ai'],
        'suno': ['suno.ai', 'suno ai'],
        'runway': ['runway ml', 'runwayml'],
        'openai': ['openai.com', 'open ai', 'chatgpt'],

        # Parking
        'pmc': ['pmc paid parking', 'pmc parking', 'premium parking'],
        'metropolis': ['metropolis parking', 'metropolis-parking'],

        # Delivery services
        'doordash': ['dd doordash', 'doordash inc'],
        'uber': ['uber trip', 'uber eats', 'uber.com'],

        # Other services
        'southwest': ['southwest airlines', 'southwest air'],
        'away': ['away travel', 'away.com'],
    }

    # Merchant category detection
    MERCHANT_CATEGORIES = {
        'restaurant': ['bar', 'grill', 'pub', 'house', 'kitchen', 'tavern', 'cafe', 'restaurant'],
        'parking': ['parking', 'pmc', 'metropolis', 'garage'],
        'digital': ['ai', 'software', 'cloud', 'app', 'subscription'],
        'travel': ['airlines', 'hotel', 'uber', 'lyft', 'taxi'],
    }

    def __init__(self):
        """Initialize merchant intelligence"""
        # Build reverse lookup for chains
        self.chain_lookup = {}
        for canonical, variants in self.CHAIN_PATTERNS.items():
            for variant in variants:
                self.chain_lookup[variant.lower()] = canonical

    def normalize(self, merchant: str) -> str:
        """
        Advanced merchant normalization

        Examples:
            "APPLE.COM/BILL" -> "apple"
            "SH NASHVILLE OTHER" -> "soho house"
            "DD DOORDASH CVS" -> "DoorDash - CVS"
            "UBER EATS CHIPOTLE" -> "Uber Eats - Chipotle"
            "12 South Taproom & Grill" -> "12 south taproom"
        """
        if not merchant:
            return ""

        # Step 0: Special handling for delivery services
        # Preserve restaurant name for DoorDash, Uber Eats, Grubhub
        original = merchant.strip()
        m_check = merchant.lower().strip()

        # DoorDash: "DD DOORDASH CVS" -> "DoorDash - CVS"
        if 'doordash' in m_check:
            doordash_match = re.search(r'(?:dd\s+)?doordash(?:\s+inc)?(?:\s+(.+))?', m_check)
            if doordash_match:
                restaurant = doordash_match.group(1) if doordash_match.group(1) else None
                if restaurant:
                    restaurant = restaurant.strip()
                    # Clean up restaurant name
                    restaurant = re.sub(r'\s*(inc|llc|corp|ltd)\s*$', '', restaurant, flags=re.IGNORECASE)
                    if restaurant and restaurant not in ['inc', 'llc', 'corp', 'ltd', 'the']:
                        return f"DoorDash - {restaurant.title()}"
                return "DoorDash"

        # Uber Eats: "UBER EATS CHIPOTLE" -> "Uber Eats - Chipotle"
        if 'uber' in m_check and 'eat' in m_check:
            ubereats_match = re.search(r'uber\s+eats?(?:\s+(.+))?', m_check)
            if ubereats_match:
                restaurant = ubereats_match.group(1) if ubereats_match.group(1) else None
                if restaurant:
                    restaurant = restaurant.strip()
                    restaurant = re.sub(r'\s*(inc|llc|corp|ltd)\s*$', '', restaurant, flags=re.IGNORECASE)
                    if restaurant and restaurant not in ['inc', 'llc', 'corp', 'ltd', 'the']:
                        return f"Uber Eats - {restaurant.title()}"
                return "Uber Eats"

        # Grubhub: "GRUBHUB TACO BELL" -> "Grubhub - Taco Bell"
        if 'grubhub' in m_check:
            grubhub_match = re.search(r'grubhub(?:\s+(.+))?', m_check)
            if grubhub_match:
                restaurant = grubhub_match.group(1) if grubhub_match.group(1) else None
                if restaurant:
                    restaurant = restaurant.strip()
                    restaurant = re.sub(r'\s*(inc|llc|corp|ltd)\s*$', '', restaurant, flags=re.IGNORECASE)
                    if restaurant and restaurant not in ['inc', 'llc', 'corp', 'ltd', 'the']:
                        return f"Grubhub - {restaurant.title()}"
                return "Grubhub"

        # Step 1: Clean and lowercase
        m = merchant.lower().strip()

        # Step 2: Remove common noise
        m = re.sub(r'(llc|inc|corp|ltd|co\.?|&\s*co)(\s|$)', ' ', m)
        m = re.sub(r'\s*(the|and|&)\s*', ' ', m)

        # Step 3: Extract merchant from URLs/domains INTELLIGENTLY
        # Handle domain-based merchants: apple.com/bill -> apple
        domain_match = re.search(r'([a-z0-9-]+)\.(com|net|org|ai)(/[^\s]*)?', m)
        if domain_match:
            # Extract just the domain name (e.g., "apple" from "apple.com/bill")
            domain_name = domain_match.group(1)
            # Replace the full domain with just the name
            m = re.sub(r'([a-z0-9-]+)\.(com|net|org|ai)(/[^\s]*)?', domain_name, m)

        # Remove URL artifacts
        m = re.sub(r'/bill|/payment|/subscription', '', m)

        # Step 4: Early chain lookup BEFORE removing locations
        # This catches "SH NASHVILLE" before "nashville" gets removed
        m_clean = ' '.join(m.split())
        for pattern, canonical in self.chain_lookup.items():
            if pattern in m_clean:
                return canonical

        # Step 5: Remove addresses and locations (AFTER chain lookup)
        m = re.sub(r'\d+\s+\w+\s+(ave|avenue|st|street|rd|road|blvd|boulevard|dr|drive|ln|lane)', '', m)
        m = re.sub(r'\s+(nashville|las vegas|green hills|downtown|other)\s*', ' ', m)

        # Step 6: Remove confirmation numbers and codes
        m = re.sub(r'\b[A-Z0-9]{8,}\b', '', m)
        m = re.sub(r'#\d+', '', m)

        # Step 7: Check chain patterns again after cleanup
        m_clean = ' '.join(m.split())
        for pattern, canonical in self.chain_lookup.items():
            if pattern in m_clean:
                return canonical

        # Step 8: Smart word filtering - keep short words if they're significant
        words = m_clean.split()
        # Keep words with len > 2, OR keep first word if it's len == 2 (abbreviations like "SH", "DD")
        filtered_words = []
        for i, w in enumerate(words):
            if len(w) > 2 or (i == 0 and len(w) == 2):
                filtered_words.append(w)

        # Step 9: Keep first 2-3 significant words
        result = ' '.join(filtered_words[:3])

        return result.strip()

    def get_category(self, merchant: str) -> Optional[str]:
        """Detect merchant category"""
        m = merchant.lower()
        for category, keywords in self.MERCHANT_CATEGORIES.items():
            if any(kw in m for kw in keywords):
                return category
        return None

    def fuzzy_match(self, merchant1: str, merchant2: str) -> float:
        """
        Advanced fuzzy matching with chain awareness

        Returns: 0.0 to 1.0 similarity score
        """
        # Normalize both
        m1 = self.normalize(merchant1)
        m2 = self.normalize(merchant2)

        if not m1 or not m2:
            return 0.0

        # Exact match after normalization
        if m1 == m2:
            return 1.0

        # Check if both map to same chain
        if m1 in self.chain_lookup and m2 in self.chain_lookup:
            if self.chain_lookup[m1] == self.chain_lookup[m2]:
                return 1.0

        # Substring match
        if m1 in m2 or m2 in m1:
            return 0.9

        # Word overlap
        words1 = set(m1.split())
        words2 = set(m2.split())
        if words1 and words2:
            overlap = len(words1 & words2)
            max_words = max(len(words1), len(words2))
            word_score = overlap / max_words
            if word_score >= 0.5:
                return 0.7 + (word_score * 0.2)

        # Sequence matching (last resort)
        return SequenceMatcher(None, m1, m2).ratio()

    def extract_merchant_hints(self, transaction_desc: str) -> Dict[str, any]:
        """
        Extract merchant hints from transaction description

        Returns: {
            'category': 'restaurant',
            'expected_merchant': 'soho house',
            'has_tip': True,
            'is_subscription': False
        }
        """
        desc = transaction_desc.lower()

        hints = {
            'category': self.get_category(desc),
            'expected_merchant': self.normalize(desc),
            'has_tip': False,
            'is_subscription': False,
            'is_digital': False
        }

        # Detect tip scenarios
        if hints['category'] == 'restaurant':
            hints['has_tip'] = True

        # Detect subscriptions (monthly recurring)
        subscription_keywords = ['subscription', 'monthly', 'renewal', 'membership']
        if any(kw in desc for kw in subscription_keywords):
            hints['is_subscription'] = True

        # Detect digital services
        if hints['category'] == 'digital':
            hints['is_digital'] = True

        return hints


# Global singleton
_merchant_intel = None

def get_merchant_intelligence() -> MerchantIntelligence:
    """Get global merchant intelligence instance"""
    global _merchant_intel
    if _merchant_intel is None:
        _merchant_intel = MerchantIntelligence()
    return _merchant_intel


# Convenience functions
def normalize_merchant(merchant: str) -> str:
    """Normalize merchant name"""
    return get_merchant_intelligence().normalize(merchant)

def match_merchants(merchant1: str, merchant2: str) -> float:
    """Match two merchant names (0.0 to 1.0)"""
    return get_merchant_intelligence().fuzzy_match(merchant1, merchant2)

def get_merchant_hints(transaction_desc: str) -> Dict:
    """Get merchant extraction hints"""
    return get_merchant_intelligence().extract_merchant_hints(transaction_desc)


# =============================================================================
# ENHANCED MI PROCESSING - Integrates with scripts/merchant_intelligence.py
# =============================================================================

def process_transaction_mi(row: Dict) -> Dict:
    """
    Process a transaction through full Merchant Intelligence
    Returns MI fields to update in database
    """
    try:
        import importlib.util
        from pathlib import Path

        # Load scripts/merchant_intelligence.py directly to avoid name collision
        scripts_mi_path = Path(__file__).parent / "scripts" / "merchant_intelligence.py"
        spec = importlib.util.spec_from_file_location("scripts_merchant_intelligence", scripts_mi_path)
        scripts_mi = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(scripts_mi)

        return scripts_mi.process_transaction(row)
    except Exception as e:
        print(f"⚠️ MI processing error: {e}")
        # Fallback to basic processing
        return {
            "mi_merchant": get_merchant_intelligence().normalize(row.get("chase_description", "")),
            "mi_category": row.get("chase_category", ""),
            "mi_description": row.get("notes", ""),
            "mi_confidence": 0.5,
            "mi_is_subscription": 0,
            "mi_subscription_name": None,
            "mi_processed_at": __import__('datetime').datetime.now().isoformat()
        }


def process_all_mi():
    """Process all transactions through MI and update database"""
    try:
        import importlib.util
        from pathlib import Path

        # Load scripts/merchant_intelligence.py directly to avoid name collision
        scripts_mi_path = Path(__file__).parent / "scripts" / "merchant_intelligence.py"
        spec = importlib.util.spec_from_file_location("scripts_merchant_intelligence", scripts_mi_path)
        scripts_mi = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(scripts_mi)

        return scripts_mi.process_all_transactions()
    except Exception as e:
        print(f"⚠️ Batch MI processing error: {e}")
        return 0


if __name__ == '__main__':
    # Test normalization
    print("🧪 Testing Merchant Intelligence\n")

    test_cases = [
        ("APPLE.COM/BILL", "Apple"),
        ("SH NASHVILLE OTHER", "Soho House Nashville"),
        ("DD DOORDASH CVS", "DoorDash"),
        ("12 South Taproom & Grill", "12 South Taproom"),
        ("PMC PAID PARKING", "Premium Parking"),
        ("CURSOR-AI-POWERED-IDE", "Cursor AI"),
        ("Soho House Nashville 061024", "SH NASHVILLE"),
    ]

    mi = MerchantIntelligence()

    for tx_desc, receipt_merchant in test_cases:
        tx_norm = mi.normalize(tx_desc)
        rcpt_norm = mi.normalize(receipt_merchant)
        score = mi.fuzzy_match(tx_desc, receipt_merchant)

        print(f"Transaction: '{tx_desc}'")
        print(f"  → Normalized: '{tx_norm}'")
        print(f"Receipt: '{receipt_merchant}'")
        print(f"  → Normalized: '{rcpt_norm}'")
        print(f"Match Score: {score:.0%}")
        print(f"Result: {'✅ MATCH' if score >= 0.7 else '❌ NO MATCH'}")
        print()
