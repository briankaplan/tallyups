#!/usr/bin/env python3
"""
Reconciliation Agent - Intelligent Receipt-to-Transaction Matching
===================================================================

This agent THINKS like a human accountant:
1. Looks at the ACTUAL receipt image with vision
2. Compares it intelligently to the transaction
3. Uses common sense (tips, date delays, merchant variations)
4. Writes REAL notes that sound human, not template garbage
5. Searches Gmail/iMessage when receipts are missing
6. Generates expense reports

Usage:
    python reconciliation_agent.py --mode=full        # Process all unmatched
    python reconciliation_agent.py --mode=review      # Preview what it would do
    python reconciliation_agent.py --mode=single --tx=123  # Single transaction
    python reconciliation_agent.py --report           # Generate expense report
"""

import os
import sys
import json
import base64
import argparse
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum

from dotenv import load_dotenv

load_dotenv()

# =============================================================================
# CONFIG
# =============================================================================

BASE_DIR = Path(__file__).resolve().parent
RECEIPT_DIR = BASE_DIR / "receipts"

# API clients
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")

# Thresholds
CONFIDENCE_AUTO_ACCEPT = 0.85   # 85%+ = auto-attach, no review needed
CONFIDENCE_LIKELY_MATCH = 0.70  # 70-85% = likely match, quick review
CONFIDENCE_MAYBE_MATCH = 0.50   # 50-70% = possible match, needs review
CONFIDENCE_REJECT = 0.50        # Below 50% = reject

# =============================================================================
# DATA CLASSES
# =============================================================================

class MatchDecision(Enum):
    ACCEPT = "accept"           # High confidence, auto-attach
    LIKELY = "likely"           # Probably correct, quick review
    MAYBE = "maybe"             # Possible, needs human review
    REJECT = "reject"           # Not a match
    NO_RECEIPT = "no_receipt"   # No receipt found, need to search


@dataclass
class ReceiptAnalysis:
    """What the agent sees when looking at a receipt"""
    filename: str
    merchant: str
    date: Optional[str]
    total: float
    subtotal: Optional[float] = None
    tip: Optional[float] = None
    tax: Optional[float] = None
    items: List[str] = field(default_factory=list)
    raw_text: str = ""
    confidence: float = 0.0

    # What the agent noticed
    observations: List[str] = field(default_factory=list)

    # e.g., "handwritten tip", "no date visible", "faded receipt"
    issues: List[str] = field(default_factory=list)


@dataclass
class TransactionContext:
    """Everything the agent knows about a transaction"""
    index: int
    merchant: str
    amount: float
    date: str
    category: str = ""
    business_type: str = ""

    # Existing data
    current_receipt: Optional[str] = None
    current_note: Optional[str] = None

    # Agent's analysis
    merchant_type: str = ""  # restaurant, subscription, retail, parking, travel
    expected_receipt_traits: List[str] = field(default_factory=list)
    date_tolerance_days: int = 3


@dataclass
class MatchResult:
    """The agent's decision about a receipt-transaction match"""
    transaction: TransactionContext
    receipt: Optional[ReceiptAnalysis]
    decision: MatchDecision
    confidence: float

    # The reasoning (for human review)
    reasoning: str

    # Score breakdown
    amount_score: float = 0.0
    merchant_score: float = 0.0
    date_score: float = 0.0

    # What adjustments were made
    adjustments: List[str] = field(default_factory=list)

    # The human-quality note
    note: str = ""


# =============================================================================
# VISION: Actually Look at Receipts
# =============================================================================

class ReceiptVision:
    """
    Uses AI vision to actually READ receipts like a human would.
    Not just OCR - understanding what the receipt shows.
    """

    def __init__(self):
        self.client = None
        self.gemini_model = None
        self._init_clients()

    def _init_clients(self):
        """Initialize AI clients"""
        if OPENAI_API_KEY:
            from openai import OpenAI
            self.client = OpenAI(api_key=OPENAI_API_KEY)

        if GEMINI_API_KEY:
            try:
                import google.generativeai as genai
                genai.configure(api_key=GEMINI_API_KEY)
                self.gemini_model = genai.GenerativeModel('gemini-1.5-flash')
            except Exception as e:
                print(f"Gemini init error: {e}")

    def analyze_receipt(self, image_path: Path) -> ReceiptAnalysis:
        """
        Look at a receipt image and extract everything a human would notice.
        """
        if not image_path.exists():
            return ReceiptAnalysis(
                filename=image_path.name,
                merchant="",
                date=None,
                total=0.0,
                issues=["File not found"]
            )

        # Encode image
        with open(image_path, "rb") as f:
            image_data = f.read()
        b64_image = base64.b64encode(image_data).decode("utf-8")

        # Use GPT-4 Vision for detailed analysis
        if self.client:
            return self._analyze_with_openai(image_path.name, b64_image)
        elif self.gemini_model:
            return self._analyze_with_gemini(image_path, image_path.name)
        else:
            return ReceiptAnalysis(
                filename=image_path.name,
                merchant="",
                date=None,
                total=0.0,
                issues=["No vision API available"]
            )

    def _analyze_with_openai(self, filename: str, b64_image: str) -> ReceiptAnalysis:
        """Use GPT-4 Vision for receipt analysis"""

        prompt = """You are looking at a receipt image. Analyze it like a human accountant would.

Return a JSON object with:
{
    "merchant": "The business name (not address)",
    "date": "YYYY-MM-DD or null if not visible/legible",
    "total": 0.00,
    "subtotal": 0.00 or null,
    "tip": 0.00 or null (look for handwritten tips!),
    "tax": 0.00 or null,
    "items": ["item1", "item2"] (main items, max 5),
    "observations": [
        "Things you notice - e.g., 'handwritten tip of $15', 'receipt is faded',
        'this is a bar tab', 'itemized grocery receipt', 'parking garage receipt'"
    ],
    "issues": [
        "Problems that affect matching - e.g., 'date not visible',
        'total is unclear', 'might be customer copy without final total'"
    ],
    "confidence": 0.0 to 1.0 (how confident are you in this extraction?)
}

IMPORTANT:
- Look for HANDWRITTEN tips (common on restaurant receipts)
- If you see a subtotal and a handwritten total, the handwritten one is the final charge
- Customer copies often don't have the final tip amount
- Parking receipts often just show duration and rate
- If the date is cut off or faded, say so in issues
- Be specific in observations - these help with matching"""

        try:
            resp = self.client.chat.completions.create(
                model="gpt-4o",
                response_format={"type": "json_object"},
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {
                            "url": f"data:image/jpeg;base64,{b64_image}",
                            "detail": "high"
                        }}
                    ]
                }],
                max_tokens=1000
            )

            data = json.loads(resp.choices[0].message.content)

            return ReceiptAnalysis(
                filename=filename,
                merchant=data.get("merchant", ""),
                date=data.get("date"),
                total=float(data.get("total", 0)),
                subtotal=data.get("subtotal"),
                tip=data.get("tip"),
                tax=data.get("tax"),
                items=data.get("items", []),
                observations=data.get("observations", []),
                issues=data.get("issues", []),
                confidence=float(data.get("confidence", 0.5))
            )

        except Exception as e:
            print(f"Vision error: {e}")
            return ReceiptAnalysis(
                filename=filename,
                merchant="",
                date=None,
                total=0.0,
                issues=[f"Vision API error: {str(e)}"]
            )

    def _analyze_with_gemini(self, image_path: Path, filename: str) -> ReceiptAnalysis:
        """Use Gemini Vision as fallback"""
        from PIL import Image

        prompt = """Analyze this receipt image. Return JSON:
{
    "merchant": "business name",
    "date": "YYYY-MM-DD or null",
    "total": 0.00,
    "subtotal": null,
    "tip": null,
    "observations": ["what you notice"],
    "issues": ["problems for matching"],
    "confidence": 0.0-1.0
}
Look for handwritten tips. Be specific about what you see."""

        try:
            img = Image.open(image_path)
            response = self.gemini_model.generate_content([prompt, img])

            # Parse JSON from response
            text = response.text
            # Find JSON in response
            start = text.find('{')
            end = text.rfind('}') + 1
            if start >= 0 and end > start:
                data = json.loads(text[start:end])
                return ReceiptAnalysis(
                    filename=filename,
                    merchant=data.get("merchant", ""),
                    date=data.get("date"),
                    total=float(data.get("total", 0)),
                    subtotal=data.get("subtotal"),
                    tip=data.get("tip"),
                    observations=data.get("observations", []),
                    issues=data.get("issues", []),
                    confidence=float(data.get("confidence", 0.5))
                )
        except Exception as e:
            print(f"Gemini error: {e}")

        return ReceiptAnalysis(
            filename=filename,
            merchant="",
            date=None,
            total=0.0,
            issues=["Gemini analysis failed"]
        )

    def compare_receipt_to_transaction(
        self,
        receipt: ReceiptAnalysis,
        transaction: TransactionContext
    ) -> Tuple[float, str, List[str]]:
        """
        Have the AI compare a receipt to a transaction and explain its reasoning.
        Returns (confidence, reasoning, adjustments)
        """
        if not self.client:
            # Fallback to rule-based comparison
            return self._rule_based_comparison(receipt, transaction)

        prompt = f"""You are a smart accountant comparing a receipt to a bank transaction.

TRANSACTION (from bank statement):
- Merchant: {transaction.merchant}
- Amount charged: ${transaction.amount:.2f}
- Date: {transaction.date}
- Category: {transaction.category}

RECEIPT (what you see):
- Merchant on receipt: {receipt.merchant}
- Receipt date: {receipt.date or 'NOT VISIBLE'}
- Receipt total: ${receipt.total:.2f}
- Subtotal: ${receipt.subtotal or 'N/A'}
- Tip: ${receipt.tip or 'N/A'}
- What I noticed: {'; '.join(receipt.observations) if receipt.observations else 'Nothing special'}
- Issues: {'; '.join(receipt.issues) if receipt.issues else 'None'}

QUESTION: Is this receipt for this transaction?

Think through this step by step:
1. Do the merchants match (considering variations like "SQ *STARBUCKS" = "Starbucks")?
2. Do the amounts match? Consider:
   - Tips: If bank charge is 15-25% more than receipt subtotal, probably includes tip
   - Fees: Small differences ($1-2) could be service fees
   - Exact match is best, but tip variance is normal for restaurants
3. Do the dates match? Consider:
   - Same day = perfect
   - 1-2 days off = normal (processing time)
   - Weekends can cause 3-day delays
   - Subscriptions can be billed at start/end of period

Return JSON:
{{
    "is_match": true/false,
    "confidence": 0.0-1.0,
    "reasoning": "2-3 sentence explanation of your decision",
    "adjustments": ["list of factors you considered, e.g., 'tip added', 'date delay normal'"]
}}"""

        try:
            resp = self.client.chat.completions.create(
                model="gpt-4o-mini",
                response_format={"type": "json_object"},
                messages=[{"role": "user", "content": prompt}],
                max_tokens=500
            )

            data = json.loads(resp.choices[0].message.content)
            return (
                float(data.get("confidence", 0.5)),
                data.get("reasoning", ""),
                data.get("adjustments", [])
            )

        except Exception as e:
            print(f"Comparison error: {e}")
            return self._rule_based_comparison(receipt, transaction)

    def _rule_based_comparison(
        self,
        receipt: ReceiptAnalysis,
        transaction: TransactionContext
    ) -> Tuple[float, str, List[str]]:
        """Fallback rule-based comparison"""
        adjustments = []

        # Amount comparison
        amount_diff = abs(receipt.total - transaction.amount)
        amount_pct = amount_diff / transaction.amount if transaction.amount > 0 else 1.0

        if amount_diff < 0.02:
            amount_score = 1.0
        elif amount_diff < 2.00:
            amount_score = 0.95
            adjustments.append("Small amount variance (fees/rounding)")
        elif 0.15 <= (transaction.amount - receipt.total) / receipt.total <= 0.30 if receipt.total > 0 else False:
            amount_score = 0.90
            adjustments.append("Amount suggests tip was added (15-30% over subtotal)")
        elif amount_pct < 0.05:
            amount_score = 0.85
        elif amount_pct < 0.10:
            amount_score = 0.70
        else:
            amount_score = 0.30

        # Merchant comparison (simple for fallback)
        tx_merchant = transaction.merchant.lower()
        rx_merchant = receipt.merchant.lower()

        if rx_merchant in tx_merchant or tx_merchant in rx_merchant:
            merchant_score = 0.95
        elif any(word in tx_merchant for word in rx_merchant.split()[:2]):
            merchant_score = 0.80
        else:
            merchant_score = 0.40

        # Date comparison
        date_score = 0.5  # Neutral if no date
        if receipt.date:
            adjustments.append("Date on receipt")
        else:
            adjustments.append("No date visible on receipt - matching on amount/merchant")

        # Combined score
        confidence = (amount_score * 0.50 + merchant_score * 0.35 + date_score * 0.15)

        reasoning = f"Amount {'matches' if amount_score > 0.8 else 'differs'}, " \
                    f"merchant {'matches' if merchant_score > 0.7 else 'unclear'}"

        return confidence, reasoning, adjustments


# =============================================================================
# INTELLIGENT MATCHING: Common Sense Rules
# =============================================================================

class IntelligentMatcher:
    """
    Applies human-like reasoning to receipt matching.
    Knows about tips, date delays, merchant variations, etc.
    """

    def __init__(self):
        self.vision = ReceiptVision()

        # Merchant type detection patterns
        self.restaurant_patterns = [
            'grill', 'bar', 'pub', 'restaurant', 'cafe', 'coffee', 'kitchen',
            'tavern', 'bistro', 'diner', 'steakhouse', 'pizzeria', 'sushi',
            'taco', 'burger', 'bbq', 'doordash', 'uber eats', 'grubhub',
            'soho house', 'starbucks', 'dunkin'
        ]

        self.subscription_patterns = [
            'anthropic', 'openai', 'spotify', 'netflix', 'apple', 'google',
            'microsoft', 'adobe', 'github', 'slack', 'zoom', 'dropbox',
            'notion', 'figma', 'canva', 'cursor', 'railway', 'vercel',
            'cloudflare', 'aws', 'hulu', 'disney'
        ]

        self.parking_patterns = [
            'parking', 'pmc', 'metropolis', 'spothero', 'parkwhiz', 'garage'
        ]

        self.travel_patterns = [
            'airline', 'delta', 'united', 'american', 'southwest', 'hotel',
            'marriott', 'hilton', 'hyatt', 'airbnb', 'uber', 'lyft', 'taxi',
            'hertz', 'enterprise', 'national'
        ]

    def analyze_transaction(self, tx: Dict) -> TransactionContext:
        """Build rich context about a transaction"""
        merchant = tx.get("chase_description") or tx.get("merchant") or ""
        amount = abs(float(tx.get("chase_amount") or tx.get("amount") or 0))
        date = tx.get("chase_date") or tx.get("transaction_date") or ""

        ctx = TransactionContext(
            index=tx.get("_index", 0),
            merchant=merchant,
            amount=amount,
            date=date,
            category=tx.get("chase_category") or tx.get("category") or "",
            business_type=tx.get("business_type") or "",
            current_receipt=tx.get("receipt_file"),
            current_note=tx.get("ai_note")
        )

        # Determine merchant type and set expectations
        merchant_lower = merchant.lower()

        if any(p in merchant_lower for p in self.restaurant_patterns):
            ctx.merchant_type = "restaurant"
            ctx.expected_receipt_traits = ["may include tip", "subtotal + tip = total"]
            ctx.date_tolerance_days = 2

        elif any(p in merchant_lower for p in self.subscription_patterns):
            ctx.merchant_type = "subscription"
            ctx.expected_receipt_traits = ["email receipt likely", "recurring charge"]
            ctx.date_tolerance_days = 7  # Subscription billing varies

        elif any(p in merchant_lower for p in self.parking_patterns):
            ctx.merchant_type = "parking"
            ctx.expected_receipt_traits = ["duration and rate", "may be exit receipt"]
            ctx.date_tolerance_days = 1

        elif any(p in merchant_lower for p in self.travel_patterns):
            ctx.merchant_type = "travel"
            ctx.expected_receipt_traits = ["booking confirmation", "may be pre-auth"]
            ctx.date_tolerance_days = 14  # Travel can have auth/charge delays

        else:
            ctx.merchant_type = "retail"
            ctx.expected_receipt_traits = ["standard receipt"]
            ctx.date_tolerance_days = 3

        return ctx

    def find_best_match(
        self,
        transaction: TransactionContext,
        receipt_dir: Path = RECEIPT_DIR
    ) -> MatchResult:
        """
        Find the best matching receipt for a transaction.
        Uses vision + intelligent comparison.
        """
        if not receipt_dir.exists():
            return MatchResult(
                transaction=transaction,
                receipt=None,
                decision=MatchDecision.NO_RECEIPT,
                confidence=0.0,
                reasoning="Receipt directory not found"
            )

        # Get all receipt images
        receipt_files = [
            f for f in receipt_dir.iterdir()
            if f.suffix.lower() in ['.jpg', '.jpeg', '.png', '.webp']
        ]

        if not receipt_files:
            return MatchResult(
                transaction=transaction,
                receipt=None,
                decision=MatchDecision.NO_RECEIPT,
                confidence=0.0,
                reasoning="No receipt images found"
            )

        best_result = None
        best_confidence = 0.0

        for receipt_file in receipt_files:
            # Analyze the receipt image
            receipt = self.vision.analyze_receipt(receipt_file)

            # Skip if analysis failed
            if not receipt.merchant and not receipt.total:
                continue

            # Compare to transaction
            confidence, reasoning, adjustments = self.vision.compare_receipt_to_transaction(
                receipt, transaction
            )

            if confidence > best_confidence:
                best_confidence = confidence

                # Determine decision based on confidence
                if confidence >= CONFIDENCE_AUTO_ACCEPT:
                    decision = MatchDecision.ACCEPT
                elif confidence >= CONFIDENCE_LIKELY_MATCH:
                    decision = MatchDecision.LIKELY
                elif confidence >= CONFIDENCE_MAYBE_MATCH:
                    decision = MatchDecision.MAYBE
                else:
                    decision = MatchDecision.REJECT

                best_result = MatchResult(
                    transaction=transaction,
                    receipt=receipt,
                    decision=decision,
                    confidence=confidence,
                    reasoning=reasoning,
                    adjustments=adjustments
                )

        if best_result:
            return best_result

        return MatchResult(
            transaction=transaction,
            receipt=None,
            decision=MatchDecision.NO_RECEIPT,
            confidence=0.0,
            reasoning="No matching receipt found in local folder"
        )


# =============================================================================
# REAL NOTE GENERATION: Human-Quality Descriptions
# =============================================================================

class HumanNoteGenerator:
    """
    Generates notes that sound like a human wrote them.
    Not "Business expense at Starbucks" garbage.
    """

    def __init__(self):
        self.client = None
        if OPENAI_API_KEY:
            from openai import OpenAI
            self.client = OpenAI(api_key=OPENAI_API_KEY)

        # Load context sources
        self._load_context_sources()

    def _load_context_sources(self):
        """Load calendar, contacts, etc."""
        self.calendar_available = False
        self.contacts_available = False

        try:
            from calendar_service import get_events_around_date
            self.get_calendar_events = get_events_around_date
            self.calendar_available = True
        except:
            self.get_calendar_events = None

        try:
            from smart_notes_engine import get_contacts_db
            self.contacts_db = get_contacts_db()
            self.contacts_available = True
        except:
            self.contacts_db = None

    def generate_note(
        self,
        transaction: TransactionContext,
        receipt: Optional[ReceiptAnalysis] = None,
        match_result: Optional[MatchResult] = None
    ) -> str:
        """
        Generate a human-quality note for the transaction.

        BAD: "Business expense at Soho House Nashville"
        GOOD: "Dinner meeting with Scott Siman to discuss publishing deal for new artist"

        BAD: "Software subscription - Anthropic"
        GOOD: "Claude Pro subscription - using for lyric writing assistance and contract review"
        """
        if not self.client:
            return self._fallback_note(transaction, receipt)

        # Gather context
        context_parts = []

        # Calendar context
        calendar_events = []
        if self.calendar_available and self.get_calendar_events:
            try:
                events = self.get_calendar_events(transaction.date, days_before=0, days_after=0)
                calendar_events = [e.get('title', '') for e in events if e.get('title')]
                if calendar_events:
                    context_parts.append(f"Calendar events on this date: {', '.join(calendar_events[:3])}")
            except:
                pass

        # Receipt details
        receipt_context = ""
        if receipt:
            receipt_parts = []
            if receipt.items:
                receipt_parts.append(f"Items purchased: {', '.join(receipt.items[:5])}")
            if receipt.observations:
                receipt_parts.append(f"Receipt shows: {'; '.join(receipt.observations[:3])}")
            receipt_context = "\n".join(receipt_parts)

        prompt = f"""You are Brian Kaplan's assistant writing expense notes. Brian works in the music industry (publishing, artist management, production).

Write a SHORT, NATURAL expense note (1 sentence, max 15 words) that:
1. Sounds like a human wrote it quickly
2. Explains the business purpose if obvious
3. Mentions who he was with if the calendar shows a meeting
4. Is specific, not generic

TRANSACTION:
- Where: {transaction.merchant}
- Amount: ${transaction.amount:.2f}
- Date: {transaction.date}
- Category: {transaction.category}
- Business: {transaction.business_type}

{f"CALENDAR CONTEXT: {chr(10).join(context_parts)}" if context_parts else ""}

{f"RECEIPT SHOWS: {receipt_context}" if receipt_context else ""}

EXAMPLES OF GOOD NOTES:
- "Lunch with Scott Siman, discussing new artist signing"
- "Monthly Claude subscription for songwriting and research"
- "Parking for meeting at Sony Music"
- "Coffee while reviewing contract drafts"
- "Team dinner after studio session"
- "Uber to BMI awards ceremony"

EXAMPLES OF BAD NOTES (don't write these):
- "Business expense at restaurant"
- "Food and beverage purchase"
- "Software subscription payment"
- "Transportation expense"

If you can't determine the specific purpose, write something brief and natural like:
- "Working lunch downtown"
- "Client meeting"
- "Studio supplies"

Write ONLY the note, nothing else:"""

        try:
            resp = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=50,
                temperature=0.7
            )
            note = resp.choices[0].message.content.strip()
            # Clean up
            note = note.strip('"\'')
            if note.startswith("Note:"):
                note = note[5:].strip()
            return note

        except Exception as e:
            print(f"Note generation error: {e}")
            return self._fallback_note(transaction, receipt)

    def _fallback_note(
        self,
        transaction: TransactionContext,
        receipt: Optional[ReceiptAnalysis] = None
    ) -> str:
        """Simple fallback note generation"""
        merchant = transaction.merchant

        # Clean up merchant name
        prefixes = ['sq *', 'sq*', 'tst*', 'dd*', 'dd ']
        for p in prefixes:
            if merchant.lower().startswith(p):
                merchant = merchant[len(p):]

        if transaction.merchant_type == "restaurant":
            return f"Meal at {merchant}"
        elif transaction.merchant_type == "subscription":
            return f"{merchant} subscription"
        elif transaction.merchant_type == "parking":
            return f"Parking - {merchant}"
        elif transaction.merchant_type == "travel":
            return f"Travel - {merchant}"
        else:
            return merchant


# =============================================================================
# DATABASE INTEGRATION
# =============================================================================

# =============================================================================
# EMAIL ESCALATION: Search Gmail/iMessage When No Local Receipt
# =============================================================================

class EmailEscalation:
    """
    When no local receipt is found, search Gmail and iMessage.
    """

    def __init__(self):
        self.gmail_available = False
        self.imessage_available = False
        self._init_services()

    def _init_services(self):
        """Initialize email search services"""
        # Try multiple import paths for gmail_search
        self.find_gmail_receipt = None
        for module_path in ['gmail_search', 'scripts.search.gmail_search']:
            try:
                if module_path == 'gmail_search':
                    from gmail_search import find_best_gmail_receipt_for_row
                else:
                    from scripts.search.gmail_search import find_best_gmail_receipt_for_row
                self.find_gmail_receipt = find_best_gmail_receipt_for_row
                self.gmail_available = True
                break
            except Exception:
                continue

        if not self.find_gmail_receipt:
            # Try importing from orchestrator which may have it
            try:
                from orchestrator import find_best_receipt_for_transaction
                # We can use orchestrator's gmail functionality
                self.gmail_available = False  # But not directly
            except:
                pass
            print(f"Gmail search: Using orchestrator fallback")

        # Try multiple import paths for imessage_search
        self.search_imessage = None
        self.download_imessage_receipt = None
        for module_path in ['imessage_search', 'scripts.search.imessage_search']:
            try:
                if module_path == 'imessage_search':
                    from imessage_search import search_imessage, download_imessage_receipt
                else:
                    from scripts.search.imessage_search import search_imessage, download_imessage_receipt
                self.search_imessage = search_imessage
                self.download_imessage_receipt = download_imessage_receipt
                self.imessage_available = True
                break
            except Exception:
                continue

        if not self.search_imessage:
            print(f"iMessage search: Not available")

    def search_for_receipt(
        self,
        transaction: TransactionContext
    ) -> Optional[Tuple[str, float, str]]:
        """
        Search Gmail and iMessage for a receipt matching this transaction.
        Returns (filename, confidence, source) or None.
        """
        # Convert to the format expected by existing search functions
        tx_dict = {
            "Chase Description": transaction.merchant,
            "Chase Amount": transaction.amount,
            "Chase Date": transaction.date,
            "chase_description": transaction.merchant,
            "chase_amount": transaction.amount,
            "chase_date": transaction.date,
        }

        # Try Gmail first
        if self.gmail_available and self.find_gmail_receipt:
            print(f"  Searching Gmail for receipt...")
            try:
                gmail_match = self.find_gmail_receipt(tx_dict, threshold=0.65)
                if gmail_match:
                    print(f"  Found Gmail match: {gmail_match.saved_filename} "
                          f"(score: {gmail_match.score:.0%})")
                    return (
                        gmail_match.saved_filename,
                        gmail_match.score,
                        "gmail"
                    )
            except Exception as e:
                print(f"  Gmail search error: {e}")

        # Try iMessage
        if self.imessage_available and self.search_imessage:
            print(f"  Searching iMessage for receipt...")
            try:
                candidates = self.search_imessage(tx_dict)
                if candidates and len(candidates) > 0:
                    best = candidates[0]
                    if best['score'] >= 0.65 and best.get('urls'):
                        # Download the receipt from URL
                        url = best['urls'][0]
                        downloaded = self.download_imessage_receipt(url, tx_dict)
                        if downloaded:
                            print(f"  Found iMessage match: {downloaded} "
                                  f"(score: {best['score']:.0%})")
                            return (downloaded, best['score'], "imessage")
            except Exception as e:
                print(f"  iMessage search error: {e}")

        return None


class DatabaseManager:
    """Handles database operations"""

    def __init__(self):
        self.conn = None
        self._connect()

    def _connect(self):
        """Connect to MySQL database"""
        try:
            from db_mysql import get_db_connection
            self.conn = get_db_connection()
        except Exception as e:
            print(f"Database connection error: {e}")

    def get_unmatched_transactions(self, days_back: int = 90) -> List[Dict]:
        """Get transactions without receipts"""
        if not self.conn:
            return []

        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT _index, chase_date, chase_description, chase_amount,
                       chase_category, business_type, ai_note, receipt_file, receipt_url
                FROM transactions
                WHERE (receipt_file IS NULL OR receipt_file = '')
                AND (receipt_url IS NULL OR receipt_url = '')
                AND deleted != 1
                AND chase_date >= DATE_SUB(CURDATE(), INTERVAL %s DAY)
                ORDER BY chase_date DESC
            """, (days_back,))

            rows = cursor.fetchall()
            cursor.close()
            return rows

        except Exception as e:
            print(f"Query error: {e}")
            return []

    def get_all_transactions(self, days_back: int = 90) -> List[Dict]:
        """Get all transactions for review"""
        if not self.conn:
            return []

        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT _index, chase_date, chase_description, chase_amount,
                       chase_category, business_type, ai_note, receipt_file,
                       receipt_url, review_status
                FROM transactions
                WHERE deleted != 1
                AND chase_date >= DATE_SUB(CURDATE(), INTERVAL %s DAY)
                ORDER BY chase_date DESC
            """, (days_back,))

            rows = cursor.fetchall()
            cursor.close()
            return rows

        except Exception as e:
            print(f"Query error: {e}")
            return []

    def update_transaction(
        self,
        tx_index: int,
        receipt_file: Optional[str] = None,
        ai_note: Optional[str] = None,
        ai_confidence: Optional[float] = None
    ):
        """Update a transaction with match results"""
        if not self.conn:
            return

        try:
            cursor = self.conn.cursor()

            updates = []
            values = []

            if receipt_file:
                updates.append("receipt_file = %s")
                values.append(receipt_file)

            if ai_note:
                updates.append("ai_note = %s")
                values.append(ai_note)

            if ai_confidence is not None:
                updates.append("ai_confidence = %s")
                values.append(int(ai_confidence * 100))

            if updates:
                values.append(tx_index)
                cursor.execute(
                    f"UPDATE transactions SET {', '.join(updates)} WHERE _index = %s",
                    values
                )
                self.conn.commit()

            cursor.close()

        except Exception as e:
            print(f"Update error: {e}")

    def close(self):
        if self.conn:
            self.conn.close()


# =============================================================================
# MAIN AGENT
# =============================================================================

class ReconciliationAgent:
    """
    The main agent that orchestrates everything.
    """

    def __init__(self):
        self.matcher = IntelligentMatcher()
        self.note_generator = HumanNoteGenerator()
        self.db = DatabaseManager()
        self.email_escalation = EmailEscalation()

    def process_single_transaction(self, tx_index: int) -> MatchResult:
        """Process a single transaction"""
        # Get transaction from DB
        transactions = self.db.get_all_transactions(days_back=365)
        tx_data = next((t for t in transactions if t.get('_index') == tx_index), None)

        if not tx_data:
            print(f"Transaction {tx_index} not found")
            return None

        return self._process_transaction(tx_data)

    def _process_transaction(self, tx_data: Dict, search_email: bool = True) -> MatchResult:
        """Process a single transaction dict"""
        # Analyze transaction
        transaction = self.matcher.analyze_transaction(tx_data)

        print(f"\n{'='*60}")
        print(f"Transaction: {transaction.merchant}")
        print(f"Amount: ${transaction.amount:.2f}")
        print(f"Date: {transaction.date}")
        print(f"Type: {transaction.merchant_type}")
        print(f"{'='*60}")

        # Find best matching receipt in local folder
        result = self.matcher.find_best_match(transaction)

        if result.receipt:
            print(f"\nBest local match: {result.receipt.filename}")
            print(f"Confidence: {result.confidence:.0%}")
            print(f"Decision: {result.decision.value}")
            print(f"Reasoning: {result.reasoning}")
            if result.adjustments:
                print(f"Adjustments: {', '.join(result.adjustments)}")

        # If no good local match, escalate to email search
        elif result.decision == MatchDecision.NO_RECEIPT and search_email:
            print(f"\nNo local receipt - escalating to email search...")

            email_result = self.email_escalation.search_for_receipt(transaction)

            if email_result:
                filename, confidence, source = email_result
                print(f"\nFound receipt via {source}: {filename}")
                print(f"Confidence: {confidence:.0%}")

                # Re-analyze the downloaded receipt with vision
                receipt_path = RECEIPT_DIR / filename
                if receipt_path.exists():
                    receipt = self.matcher.vision.analyze_receipt(receipt_path)

                    # Re-compare with the transaction
                    new_confidence, reasoning, adjustments = \
                        self.matcher.vision.compare_receipt_to_transaction(receipt, transaction)

                    # Use the better of email search score and vision score
                    final_confidence = max(confidence, new_confidence)

                    if final_confidence >= CONFIDENCE_AUTO_ACCEPT:
                        decision = MatchDecision.ACCEPT
                    elif final_confidence >= CONFIDENCE_LIKELY_MATCH:
                        decision = MatchDecision.LIKELY
                    elif final_confidence >= CONFIDENCE_MAYBE_MATCH:
                        decision = MatchDecision.MAYBE
                    else:
                        decision = MatchDecision.REJECT

                    result = MatchResult(
                        transaction=transaction,
                        receipt=receipt,
                        decision=decision,
                        confidence=final_confidence,
                        reasoning=f"Found via {source}: {reasoning}",
                        adjustments=adjustments + [f"source: {source}"]
                    )
                else:
                    # Just use the email search result
                    result = MatchResult(
                        transaction=transaction,
                        receipt=ReceiptAnalysis(
                            filename=filename,
                            merchant=transaction.merchant,
                            date=transaction.date,
                            total=transaction.amount
                        ),
                        decision=MatchDecision.LIKELY if confidence >= 0.70 else MatchDecision.MAYBE,
                        confidence=confidence,
                        reasoning=f"Found via {source} search",
                        adjustments=[f"source: {source}"]
                    )
            else:
                print(f"\nNo receipt found in email either")
                print(f"Decision: {result.decision.value}")
        else:
            print(f"\nNo receipt match found")
            print(f"Decision: {result.decision.value}")

        # Generate human-quality note
        result.note = self.note_generator.generate_note(
            transaction,
            result.receipt,
            result
        )
        print(f"\nGenerated note: {result.note}")

        return result

    def process_all_unmatched(self, dry_run: bool = False) -> List[MatchResult]:
        """Process all unmatched transactions"""
        transactions = self.db.get_unmatched_transactions()

        print(f"\nFound {len(transactions)} unmatched transactions")

        results = []

        for i, tx_data in enumerate(transactions):
            print(f"\n[{i+1}/{len(transactions)}]", end=" ")

            result = self._process_transaction(tx_data)
            results.append(result)

            # Apply if confident and not dry run
            if not dry_run and result.decision == MatchDecision.ACCEPT:
                print(f"\n>>> AUTO-ATTACHING receipt and note")
                self.db.update_transaction(
                    result.transaction.index,
                    receipt_file=result.receipt.filename if result.receipt else None,
                    ai_note=result.note,
                    ai_confidence=result.confidence
                )

        # Summary
        print(f"\n{'='*60}")
        print("SUMMARY")
        print(f"{'='*60}")

        accepted = [r for r in results if r.decision == MatchDecision.ACCEPT]
        likely = [r for r in results if r.decision == MatchDecision.LIKELY]
        maybe = [r for r in results if r.decision == MatchDecision.MAYBE]
        no_receipt = [r for r in results if r.decision == MatchDecision.NO_RECEIPT]

        print(f"Auto-accepted: {len(accepted)}")
        print(f"Likely matches (review): {len(likely)}")
        print(f"Maybe matches (review): {len(maybe)}")
        print(f"No receipt found: {len(no_receipt)}")

        return results

    def generate_report(self, business_type: str = None, days_back: int = 30):
        """Generate an expense report"""
        transactions = self.db.get_all_transactions(days_back=days_back)

        if business_type:
            transactions = [t for t in transactions if t.get('business_type') == business_type]

        # Group by business type
        by_business = {}
        for tx in transactions:
            biz = tx.get('business_type') or 'Unassigned'
            if biz not in by_business:
                by_business[biz] = []
            by_business[biz].append(tx)

        print(f"\n{'='*60}")
        print(f"EXPENSE REPORT - Last {days_back} days")
        print(f"{'='*60}")

        total_all = 0

        for biz, txs in sorted(by_business.items()):
            total = sum(abs(float(t.get('chase_amount') or 0)) for t in txs)
            total_all += total

            print(f"\n{biz}: ${total:.2f} ({len(txs)} transactions)")
            print("-" * 40)

            for tx in sorted(txs, key=lambda x: x.get('chase_date', ''), reverse=True)[:10]:
                date = tx.get('chase_date', '')[:10]
                merchant = tx.get('chase_description', '')[:30]
                amount = abs(float(tx.get('chase_amount', 0)))
                has_receipt = '✓' if tx.get('receipt_file') or tx.get('receipt_url') else '✗'
                note = (tx.get('ai_note') or '')[:40]

                print(f"  {date} | ${amount:>8.2f} | {has_receipt} | {merchant}")
                if note:
                    print(f"         Note: {note}")

        print(f"\n{'='*60}")
        print(f"TOTAL: ${total_all:.2f}")
        print(f"{'='*60}")

    def close(self):
        self.db.close()


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Intelligent Receipt Reconciliation Agent"
    )
    parser.add_argument(
        "--mode",
        choices=["full", "review", "single"],
        default="review",
        help="Processing mode"
    )
    parser.add_argument(
        "--tx",
        type=int,
        help="Transaction index (for single mode)"
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="Generate expense report"
    )
    parser.add_argument(
        "--business",
        help="Filter by business type (for report)"
    )
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Days to look back"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview only, don't make changes"
    )

    args = parser.parse_args()

    print("=" * 60)
    print("RECONCILIATION AGENT")
    print("=" * 60)

    agent = ReconciliationAgent()

    try:
        if args.report:
            agent.generate_report(
                business_type=args.business,
                days_back=args.days
            )

        elif args.mode == "single" and args.tx:
            result = agent.process_single_transaction(args.tx)

        elif args.mode == "full":
            results = agent.process_all_unmatched(dry_run=args.dry_run)

        elif args.mode == "review":
            print("\nReview mode - showing what would be matched...")
            results = agent.process_all_unmatched(dry_run=True)

    finally:
        agent.close()

    print("\nDone!")


if __name__ == "__main__":
    main()
