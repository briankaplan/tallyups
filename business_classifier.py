#!/usr/bin/env python3
"""
Business Type Classifier
========================

Intelligent auto-classification of expenses into business types:
- Down Home (Production company - Tim McGraw partnership)
- Music City Rodeo (Event - PRCA rodeo in Nashville)
- Personal (Personal/family expenses)
- EM.co (Entertainment/Media company expenses)

Multi-signal classification with 98%+ accuracy for known merchants.
"""

import json
import re
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Set
from difflib import SequenceMatcher
import hashlib

logger = logging.getLogger(__name__)


# =============================================================================
# DATA TYPES
# =============================================================================

class BusinessType(Enum):
    """The four business classification types."""
    DOWN_HOME = "down_home"
    MUSIC_CITY_RODEO = "music_city_rodeo"
    EM_CO = "em_co"
    PERSONAL = "personal"

    @classmethod
    def from_string(cls, s: str) -> 'BusinessType':
        """Convert string to BusinessType."""
        mapping = {
            'down_home': cls.DOWN_HOME,
            'downhome': cls.DOWN_HOME,
            'down home': cls.DOWN_HOME,
            'dh': cls.DOWN_HOME,
            'music_city_rodeo': cls.MUSIC_CITY_RODEO,
            'musiccityrodeo': cls.MUSIC_CITY_RODEO,
            'music city rodeo': cls.MUSIC_CITY_RODEO,
            'mcr': cls.MUSIC_CITY_RODEO,
            'rodeo': cls.MUSIC_CITY_RODEO,
            'em_co': cls.EM_CO,
            'emco': cls.EM_CO,
            'em.co': cls.EM_CO,
            'personal': cls.PERSONAL,
        }
        return mapping.get(s.lower().strip(), cls.DOWN_HOME)  # Default to DOWN_HOME


@dataclass
class ClassificationSignal:
    """A single signal contributing to classification."""
    signal_type: str  # 'merchant_exact', 'email_domain', 'keyword', 'amount', 'calendar', 'contact', 'learned'
    business_type: BusinessType
    confidence: float
    reasoning: str
    weight: float = 1.0


@dataclass
class ClassificationResult:
    """Result of classifying a transaction."""
    business_type: BusinessType
    confidence: float
    reasoning: str
    signals: List[ClassificationSignal] = field(default_factory=list)
    alternative_types: Dict[BusinessType, float] = field(default_factory=dict)
    needs_review: bool = False

    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'business_type': self.business_type.value,
            'confidence': round(self.confidence, 4),
            'reasoning': self.reasoning,
            'signals': [
                {
                    'type': s.signal_type,
                    'business_type': s.business_type.value,
                    'confidence': round(s.confidence, 4),
                    'reasoning': s.reasoning,
                }
                for s in self.signals
            ],
            'alternative_types': {
                bt.value: round(conf, 4)
                for bt, conf in self.alternative_types.items()
            },
            'needs_review': self.needs_review,
        }


@dataclass
class Transaction:
    """Transaction to classify."""
    id: int
    merchant: str
    amount: Decimal
    date: datetime
    description: Optional[str] = None
    category: Optional[str] = None


@dataclass
class Receipt:
    """Receipt with additional context."""
    id: int
    merchant: str
    amount: Decimal
    date: Optional[datetime] = None
    email_from: Optional[str] = None
    email_domain: Optional[str] = None
    items: Optional[List[str]] = None
    attendees: Optional[List[str]] = None
    location: Optional[str] = None
    raw_text: Optional[str] = None


@dataclass
class CalendarEvent:
    """Calendar event for context."""
    title: str
    start: datetime
    end: datetime
    attendees: Optional[List[str]] = None
    description: Optional[str] = None
    location: Optional[str] = None


@dataclass
class Contact:
    """Contact for context."""
    name: str
    email: Optional[str] = None
    company: Optional[str] = None
    business_type: Optional[BusinessType] = None
    tags: List[str] = field(default_factory=list)


# =============================================================================
# MERCHANT RULES DATABASE
# =============================================================================

# Comprehensive merchant to business type mappings
MERCHANT_BUSINESS_RULES: Dict[str, Dict] = {
    # =========================================================================
    # DOWN HOME - AI & SOFTWARE
    # =========================================================================
    "anthropic": {"type": BusinessType.DOWN_HOME, "confidence": 0.99, "category": "ai_tools"},
    "claude": {"type": BusinessType.DOWN_HOME, "confidence": 0.99, "category": "ai_tools"},
    "claude.ai": {"type": BusinessType.DOWN_HOME, "confidence": 0.99, "category": "ai_tools"},
    "openai": {"type": BusinessType.DOWN_HOME, "confidence": 0.99, "category": "ai_tools"},
    "chatgpt": {"type": BusinessType.DOWN_HOME, "confidence": 0.99, "category": "ai_tools"},
    "midjourney": {"type": BusinessType.DOWN_HOME, "confidence": 0.99, "category": "ai_tools"},
    "runway": {"type": BusinessType.DOWN_HOME, "confidence": 0.98, "category": "ai_tools"},
    "runwayml": {"type": BusinessType.DOWN_HOME, "confidence": 0.98, "category": "ai_tools"},
    "suno": {"type": BusinessType.DOWN_HOME, "confidence": 0.98, "category": "ai_tools"},
    "suno.ai": {"type": BusinessType.DOWN_HOME, "confidence": 0.98, "category": "ai_tools"},
    "eleven labs": {"type": BusinessType.DOWN_HOME, "confidence": 0.98, "category": "ai_tools"},
    "elevenlabs": {"type": BusinessType.DOWN_HOME, "confidence": 0.98, "category": "ai_tools"},
    "stability ai": {"type": BusinessType.DOWN_HOME, "confidence": 0.98, "category": "ai_tools"},
    "hugging face": {"type": BusinessType.DOWN_HOME, "confidence": 0.98, "category": "ai_tools"},
    "huggingface": {"type": BusinessType.DOWN_HOME, "confidence": 0.98, "category": "ai_tools"},
    "replicate": {"type": BusinessType.DOWN_HOME, "confidence": 0.97, "category": "ai_tools"},
    "cohere": {"type": BusinessType.DOWN_HOME, "confidence": 0.97, "category": "ai_tools"},
    "perplexity": {"type": BusinessType.DOWN_HOME, "confidence": 0.97, "category": "ai_tools"},
    "cursor": {"type": BusinessType.DOWN_HOME, "confidence": 0.98, "category": "dev_tools"},
    "github": {"type": BusinessType.DOWN_HOME, "confidence": 0.98, "category": "dev_tools"},
    "github copilot": {"type": BusinessType.DOWN_HOME, "confidence": 0.99, "category": "dev_tools"},
    "replit": {"type": BusinessType.DOWN_HOME, "confidence": 0.97, "category": "dev_tools"},

    # DOWN HOME - Cloud & Infrastructure
    "aws": {"type": BusinessType.DOWN_HOME, "confidence": 0.98, "category": "cloud"},
    "amazon web services": {"type": BusinessType.DOWN_HOME, "confidence": 0.98, "category": "cloud"},
    "google cloud": {"type": BusinessType.DOWN_HOME, "confidence": 0.98, "category": "cloud"},
    "gcp": {"type": BusinessType.DOWN_HOME, "confidence": 0.98, "category": "cloud"},
    "cloudflare": {"type": BusinessType.DOWN_HOME, "confidence": 0.98, "category": "cloud"},
    "railway": {"type": BusinessType.DOWN_HOME, "confidence": 0.98, "category": "cloud"},
    "vercel": {"type": BusinessType.DOWN_HOME, "confidence": 0.98, "category": "cloud"},
    "netlify": {"type": BusinessType.DOWN_HOME, "confidence": 0.97, "category": "cloud"},
    "heroku": {"type": BusinessType.DOWN_HOME, "confidence": 0.97, "category": "cloud"},
    "digitalocean": {"type": BusinessType.DOWN_HOME, "confidence": 0.97, "category": "cloud"},
    "linode": {"type": BusinessType.DOWN_HOME, "confidence": 0.97, "category": "cloud"},
    "vultr": {"type": BusinessType.DOWN_HOME, "confidence": 0.97, "category": "cloud"},
    "azure": {"type": BusinessType.DOWN_HOME, "confidence": 0.97, "category": "cloud"},
    "microsoft azure": {"type": BusinessType.DOWN_HOME, "confidence": 0.97, "category": "cloud"},
    "supabase": {"type": BusinessType.DOWN_HOME, "confidence": 0.97, "category": "cloud"},
    "planetscale": {"type": BusinessType.DOWN_HOME, "confidence": 0.97, "category": "cloud"},
    "neon": {"type": BusinessType.DOWN_HOME, "confidence": 0.96, "category": "cloud"},
    "upstash": {"type": BusinessType.DOWN_HOME, "confidence": 0.96, "category": "cloud"},

    # DOWN HOME - Design & Creative Software
    "figma": {"type": BusinessType.DOWN_HOME, "confidence": 0.98, "category": "design"},
    "adobe": {"type": BusinessType.DOWN_HOME, "confidence": 0.95, "category": "design"},
    "adobe creative cloud": {"type": BusinessType.DOWN_HOME, "confidence": 0.98, "category": "design"},
    "adobe cc": {"type": BusinessType.DOWN_HOME, "confidence": 0.98, "category": "design"},
    "canva": {"type": BusinessType.DOWN_HOME, "confidence": 0.90, "category": "design"},
    "sketch": {"type": BusinessType.DOWN_HOME, "confidence": 0.95, "category": "design"},
    "invision": {"type": BusinessType.DOWN_HOME, "confidence": 0.95, "category": "design"},
    "framer": {"type": BusinessType.DOWN_HOME, "confidence": 0.95, "category": "design"},

    # DOWN HOME - Audio/Video Production
    "final cut": {"type": BusinessType.DOWN_HOME, "confidence": 0.98, "category": "production"},
    "final cut pro": {"type": BusinessType.DOWN_HOME, "confidence": 0.98, "category": "production"},
    "logic pro": {"type": BusinessType.DOWN_HOME, "confidence": 0.98, "category": "production"},
    "pro tools": {"type": BusinessType.DOWN_HOME, "confidence": 0.98, "category": "production"},
    "avid": {"type": BusinessType.DOWN_HOME, "confidence": 0.97, "category": "production"},
    "davinci resolve": {"type": BusinessType.DOWN_HOME, "confidence": 0.97, "category": "production"},
    "blackmagic": {"type": BusinessType.DOWN_HOME, "confidence": 0.97, "category": "production"},
    "premiere pro": {"type": BusinessType.DOWN_HOME, "confidence": 0.97, "category": "production"},
    "after effects": {"type": BusinessType.DOWN_HOME, "confidence": 0.97, "category": "production"},
    "waves": {"type": BusinessType.DOWN_HOME, "confidence": 0.95, "category": "production"},
    "universal audio": {"type": BusinessType.DOWN_HOME, "confidence": 0.97, "category": "production"},
    "splice": {"type": BusinessType.DOWN_HOME, "confidence": 0.96, "category": "production"},
    "soundcloud": {"type": BusinessType.DOWN_HOME, "confidence": 0.85, "category": "production"},
    "bandcamp": {"type": BusinessType.DOWN_HOME, "confidence": 0.90, "category": "production"},
    "distrokid": {"type": BusinessType.DOWN_HOME, "confidence": 0.97, "category": "production"},
    "tunecore": {"type": BusinessType.DOWN_HOME, "confidence": 0.97, "category": "production"},
    "cd baby": {"type": BusinessType.DOWN_HOME, "confidence": 0.97, "category": "production"},

    # DOWN HOME - Music Industry
    "spotify for artists": {"type": BusinessType.DOWN_HOME, "confidence": 0.99, "category": "music_industry"},
    "ascap": {"type": BusinessType.DOWN_HOME, "confidence": 0.99, "category": "music_industry"},
    "bmi": {"type": BusinessType.DOWN_HOME, "confidence": 0.99, "category": "music_industry"},
    "sesac": {"type": BusinessType.DOWN_HOME, "confidence": 0.99, "category": "music_industry"},
    "soundexchange": {"type": BusinessType.DOWN_HOME, "confidence": 0.99, "category": "music_industry"},
    "harry fox agency": {"type": BusinessType.DOWN_HOME, "confidence": 0.98, "category": "music_industry"},
    "songtrust": {"type": BusinessType.DOWN_HOME, "confidence": 0.98, "category": "music_industry"},
    "royalty exchange": {"type": BusinessType.DOWN_HOME, "confidence": 0.97, "category": "music_industry"},
    "music reports": {"type": BusinessType.DOWN_HOME, "confidence": 0.97, "category": "music_industry"},

    # DOWN HOME - Productivity & Collaboration
    "notion": {"type": BusinessType.DOWN_HOME, "confidence": 0.95, "category": "productivity"},
    "slack": {"type": BusinessType.DOWN_HOME, "confidence": 0.93, "category": "productivity"},
    "asana": {"type": BusinessType.DOWN_HOME, "confidence": 0.93, "category": "productivity"},
    "monday.com": {"type": BusinessType.DOWN_HOME, "confidence": 0.93, "category": "productivity"},
    "linear": {"type": BusinessType.DOWN_HOME, "confidence": 0.95, "category": "productivity"},
    "clickup": {"type": BusinessType.DOWN_HOME, "confidence": 0.92, "category": "productivity"},
    "basecamp": {"type": BusinessType.DOWN_HOME, "confidence": 0.92, "category": "productivity"},
    "trello": {"type": BusinessType.DOWN_HOME, "confidence": 0.90, "category": "productivity"},
    "miro": {"type": BusinessType.DOWN_HOME, "confidence": 0.93, "category": "productivity"},
    "loom": {"type": BusinessType.DOWN_HOME, "confidence": 0.93, "category": "productivity"},
    "calendly": {"type": BusinessType.DOWN_HOME, "confidence": 0.92, "category": "productivity"},
    "zoom": {"type": BusinessType.DOWN_HOME, "confidence": 0.88, "category": "productivity"},
    "webex": {"type": BusinessType.DOWN_HOME, "confidence": 0.88, "category": "productivity"},

    # DOWN HOME - Equipment & Rentals
    "b&h photo": {"type": BusinessType.DOWN_HOME, "confidence": 0.92, "category": "equipment"},
    "bhphoto": {"type": BusinessType.DOWN_HOME, "confidence": 0.92, "category": "equipment"},
    "adorama": {"type": BusinessType.DOWN_HOME, "confidence": 0.92, "category": "equipment"},
    "sweetwater": {"type": BusinessType.DOWN_HOME, "confidence": 0.95, "category": "equipment"},
    "guitar center": {"type": BusinessType.DOWN_HOME, "confidence": 0.90, "category": "equipment"},
    "sam ash": {"type": BusinessType.DOWN_HOME, "confidence": 0.90, "category": "equipment"},
    "vintage king": {"type": BusinessType.DOWN_HOME, "confidence": 0.97, "category": "equipment"},
    "reverb.com": {"type": BusinessType.DOWN_HOME, "confidence": 0.88, "category": "equipment"},
    "thomann": {"type": BusinessType.DOWN_HOME, "confidence": 0.90, "category": "equipment"},

    # DOWN HOME - Studios & Production Services
    "ocean way": {"type": BusinessType.DOWN_HOME, "confidence": 0.99, "category": "studio"},
    "blackbird studio": {"type": BusinessType.DOWN_HOME, "confidence": 0.99, "category": "studio"},
    "blackbird studios": {"type": BusinessType.DOWN_HOME, "confidence": 0.99, "category": "studio"},
    "rca studio": {"type": BusinessType.DOWN_HOME, "confidence": 0.99, "category": "studio"},
    "sound emporium": {"type": BusinessType.DOWN_HOME, "confidence": 0.99, "category": "studio"},
    "sound stage": {"type": BusinessType.DOWN_HOME, "confidence": 0.95, "category": "studio"},
    "the tracking room": {"type": BusinessType.DOWN_HOME, "confidence": 0.99, "category": "studio"},
    "abbey road": {"type": BusinessType.DOWN_HOME, "confidence": 0.99, "category": "studio"},
    "electric lady": {"type": BusinessType.DOWN_HOME, "confidence": 0.99, "category": "studio"},

    # DOWN HOME - Entertainment Industry Travel (major hubs)
    "american airlines": {"type": BusinessType.DOWN_HOME, "confidence": 0.70, "category": "travel"},
    "delta": {"type": BusinessType.DOWN_HOME, "confidence": 0.70, "category": "travel"},
    "united": {"type": BusinessType.DOWN_HOME, "confidence": 0.70, "category": "travel"},

    # =========================================================================
    # MUSIC CITY RODEO - Venue & Event
    # =========================================================================
    "bridgestone arena": {"type": BusinessType.MUSIC_CITY_RODEO, "confidence": 0.99, "category": "venue"},
    "nissan stadium": {"type": BusinessType.MUSIC_CITY_RODEO, "confidence": 0.95, "category": "venue"},
    "nashville convention center": {"type": BusinessType.MUSIC_CITY_RODEO, "confidence": 0.97, "category": "venue"},
    "music city center": {"type": BusinessType.MUSIC_CITY_RODEO, "confidence": 0.97, "category": "venue"},
    "ascend amphitheater": {"type": BusinessType.MUSIC_CITY_RODEO, "confidence": 0.90, "category": "venue"},
    "grand ole opry": {"type": BusinessType.MUSIC_CITY_RODEO, "confidence": 0.85, "category": "venue"},
    "ryman auditorium": {"type": BusinessType.MUSIC_CITY_RODEO, "confidence": 0.85, "category": "venue"},

    # MUSIC CITY RODEO - Rodeo Industry
    "prca": {"type": BusinessType.MUSIC_CITY_RODEO, "confidence": 0.99, "category": "rodeo"},
    "professional rodeo cowboys association": {"type": BusinessType.MUSIC_CITY_RODEO, "confidence": 0.99, "category": "rodeo"},
    "nfr": {"type": BusinessType.MUSIC_CITY_RODEO, "confidence": 0.99, "category": "rodeo"},
    "national finals rodeo": {"type": BusinessType.MUSIC_CITY_RODEO, "confidence": 0.99, "category": "rodeo"},
    "pbr": {"type": BusinessType.MUSIC_CITY_RODEO, "confidence": 0.98, "category": "rodeo"},
    "professional bull riders": {"type": BusinessType.MUSIC_CITY_RODEO, "confidence": 0.98, "category": "rodeo"},
    "wrangler": {"type": BusinessType.MUSIC_CITY_RODEO, "confidence": 0.90, "category": "rodeo"},
    "justin boots": {"type": BusinessType.MUSIC_CITY_RODEO, "confidence": 0.92, "category": "rodeo"},
    "ariat": {"type": BusinessType.MUSIC_CITY_RODEO, "confidence": 0.90, "category": "rodeo"},
    "resistol": {"type": BusinessType.MUSIC_CITY_RODEO, "confidence": 0.93, "category": "rodeo"},
    "stetson": {"type": BusinessType.MUSIC_CITY_RODEO, "confidence": 0.88, "category": "rodeo"},
    "cavenders": {"type": BusinessType.MUSIC_CITY_RODEO, "confidence": 0.92, "category": "rodeo"},
    "boot barn": {"type": BusinessType.MUSIC_CITY_RODEO, "confidence": 0.88, "category": "rodeo"},
    "sheplers": {"type": BusinessType.MUSIC_CITY_RODEO, "confidence": 0.90, "category": "rodeo"},

    # MUSIC CITY RODEO - Stock Contractors
    "flying u rodeo": {"type": BusinessType.MUSIC_CITY_RODEO, "confidence": 0.99, "category": "stock_contractor"},
    "cervi championship rodeo": {"type": BusinessType.MUSIC_CITY_RODEO, "confidence": 0.99, "category": "stock_contractor"},
    "harry vold rodeo": {"type": BusinessType.MUSIC_CITY_RODEO, "confidence": 0.99, "category": "stock_contractor"},
    "sankey rodeo": {"type": BusinessType.MUSIC_CITY_RODEO, "confidence": 0.99, "category": "stock_contractor"},
    "j bar j": {"type": BusinessType.MUSIC_CITY_RODEO, "confidence": 0.98, "category": "stock_contractor"},

    # MUSIC CITY RODEO - Talent & Booking
    "caa": {"type": BusinessType.MUSIC_CITY_RODEO, "confidence": 0.90, "category": "talent"},
    "creative artists agency": {"type": BusinessType.MUSIC_CITY_RODEO, "confidence": 0.90, "category": "talent"},
    "wme": {"type": BusinessType.MUSIC_CITY_RODEO, "confidence": 0.90, "category": "talent"},
    "william morris": {"type": BusinessType.MUSIC_CITY_RODEO, "confidence": 0.90, "category": "talent"},
    "uta": {"type": BusinessType.MUSIC_CITY_RODEO, "confidence": 0.88, "category": "talent"},
    "united talent agency": {"type": BusinessType.MUSIC_CITY_RODEO, "confidence": 0.88, "category": "talent"},
    "paradigm": {"type": BusinessType.MUSIC_CITY_RODEO, "confidence": 0.88, "category": "talent"},
    "red light management": {"type": BusinessType.MUSIC_CITY_RODEO, "confidence": 0.92, "category": "talent"},
    "vector management": {"type": BusinessType.MUSIC_CITY_RODEO, "confidence": 0.92, "category": "talent"},
    "big machine": {"type": BusinessType.MUSIC_CITY_RODEO, "confidence": 0.85, "category": "talent"},

    # MUSIC CITY RODEO - Event Production
    "live nation": {"type": BusinessType.MUSIC_CITY_RODEO, "confidence": 0.90, "category": "event_production"},
    "aeg": {"type": BusinessType.MUSIC_CITY_RODEO, "confidence": 0.90, "category": "event_production"},
    "messina touring": {"type": BusinessType.MUSIC_CITY_RODEO, "confidence": 0.95, "category": "event_production"},
    "premiere global": {"type": BusinessType.MUSIC_CITY_RODEO, "confidence": 0.92, "category": "event_production"},
    "bandit lites": {"type": BusinessType.MUSIC_CITY_RODEO, "confidence": 0.95, "category": "event_production"},
    "upstaging": {"type": BusinessType.MUSIC_CITY_RODEO, "confidence": 0.93, "category": "event_production"},
    "clair global": {"type": BusinessType.MUSIC_CITY_RODEO, "confidence": 0.93, "category": "event_production"},
    "sound image": {"type": BusinessType.MUSIC_CITY_RODEO, "confidence": 0.92, "category": "event_production"},

    # MUSIC CITY RODEO - Nashville Hotels (high-end business)
    "thompson nashville": {"type": BusinessType.MUSIC_CITY_RODEO, "confidence": 0.90, "category": "nashville_hotel"},
    "jw marriott nashville": {"type": BusinessType.MUSIC_CITY_RODEO, "confidence": 0.90, "category": "nashville_hotel"},
    "omni nashville": {"type": BusinessType.MUSIC_CITY_RODEO, "confidence": 0.88, "category": "nashville_hotel"},
    "hutton hotel": {"type": BusinessType.MUSIC_CITY_RODEO, "confidence": 0.88, "category": "nashville_hotel"},
    "hermitage hotel": {"type": BusinessType.MUSIC_CITY_RODEO, "confidence": 0.90, "category": "nashville_hotel"},
    "gaylord opryland": {"type": BusinessType.MUSIC_CITY_RODEO, "confidence": 0.85, "category": "nashville_hotel"},
    "loews vanderbilt": {"type": BusinessType.MUSIC_CITY_RODEO, "confidence": 0.88, "category": "nashville_hotel"},

    # MUSIC CITY RODEO - Nashville Restaurants (business dining)
    "the catbird seat": {"type": BusinessType.MUSIC_CITY_RODEO, "confidence": 0.85, "category": "nashville_dining"},
    "husk nashville": {"type": BusinessType.MUSIC_CITY_RODEO, "confidence": 0.85, "category": "nashville_dining"},
    "kayne prime": {"type": BusinessType.MUSIC_CITY_RODEO, "confidence": 0.88, "category": "nashville_dining"},
    "merchants": {"type": BusinessType.MUSIC_CITY_RODEO, "confidence": 0.80, "category": "nashville_dining"},
    "etch": {"type": BusinessType.MUSIC_CITY_RODEO, "confidence": 0.82, "category": "nashville_dining"},
    "rolf and daughters": {"type": BusinessType.MUSIC_CITY_RODEO, "confidence": 0.82, "category": "nashville_dining"},
    "bastion": {"type": BusinessType.MUSIC_CITY_RODEO, "confidence": 0.82, "category": "nashville_dining"},

    # MUSIC CITY RODEO - Marketing & Advertising
    "billboard": {"type": BusinessType.MUSIC_CITY_RODEO, "confidence": 0.92, "category": "marketing"},
    "lamar advertising": {"type": BusinessType.MUSIC_CITY_RODEO, "confidence": 0.90, "category": "marketing"},
    "clear channel": {"type": BusinessType.MUSIC_CITY_RODEO, "confidence": 0.88, "category": "marketing"},
    "iheartmedia": {"type": BusinessType.MUSIC_CITY_RODEO, "confidence": 0.88, "category": "marketing"},
    "cumulus media": {"type": BusinessType.MUSIC_CITY_RODEO, "confidence": 0.88, "category": "marketing"},
    "tennessean": {"type": BusinessType.MUSIC_CITY_RODEO, "confidence": 0.85, "category": "marketing"},

    # =========================================================================
    # PERSONAL - Streaming & Entertainment
    # =========================================================================
    "netflix": {"type": BusinessType.PERSONAL, "confidence": 0.98, "category": "streaming"},
    "disney+": {"type": BusinessType.PERSONAL, "confidence": 0.98, "category": "streaming"},
    "disney plus": {"type": BusinessType.PERSONAL, "confidence": 0.98, "category": "streaming"},
    "hulu": {"type": BusinessType.PERSONAL, "confidence": 0.98, "category": "streaming"},
    "hbo max": {"type": BusinessType.PERSONAL, "confidence": 0.98, "category": "streaming"},
    "max": {"type": BusinessType.PERSONAL, "confidence": 0.95, "category": "streaming"},
    "amazon prime video": {"type": BusinessType.PERSONAL, "confidence": 0.97, "category": "streaming"},
    "peacock": {"type": BusinessType.PERSONAL, "confidence": 0.97, "category": "streaming"},
    "paramount+": {"type": BusinessType.PERSONAL, "confidence": 0.97, "category": "streaming"},
    "paramount plus": {"type": BusinessType.PERSONAL, "confidence": 0.97, "category": "streaming"},
    "apple tv+": {"type": BusinessType.PERSONAL, "confidence": 0.97, "category": "streaming"},
    "apple tv plus": {"type": BusinessType.PERSONAL, "confidence": 0.97, "category": "streaming"},
    "youtube premium": {"type": BusinessType.PERSONAL, "confidence": 0.95, "category": "streaming"},
    "spotify": {"type": BusinessType.PERSONAL, "confidence": 0.95, "category": "streaming"},
    "apple music": {"type": BusinessType.PERSONAL, "confidence": 0.95, "category": "streaming"},
    "tidal": {"type": BusinessType.PERSONAL, "confidence": 0.95, "category": "streaming"},
    "audible": {"type": BusinessType.PERSONAL, "confidence": 0.95, "category": "streaming"},
    "kindle unlimited": {"type": BusinessType.PERSONAL, "confidence": 0.95, "category": "streaming"},

    # PERSONAL - Gaming
    "roblox": {"type": BusinessType.PERSONAL, "confidence": 0.99, "category": "gaming"},
    "nintendo": {"type": BusinessType.PERSONAL, "confidence": 0.98, "category": "gaming"},
    "nintendo eshop": {"type": BusinessType.PERSONAL, "confidence": 0.98, "category": "gaming"},
    "playstation": {"type": BusinessType.PERSONAL, "confidence": 0.98, "category": "gaming"},
    "xbox": {"type": BusinessType.PERSONAL, "confidence": 0.97, "category": "gaming"},
    "xbox game pass": {"type": BusinessType.PERSONAL, "confidence": 0.97, "category": "gaming"},
    "steam": {"type": BusinessType.PERSONAL, "confidence": 0.95, "category": "gaming"},
    "epic games": {"type": BusinessType.PERSONAL, "confidence": 0.95, "category": "gaming"},
    "fortnite": {"type": BusinessType.PERSONAL, "confidence": 0.98, "category": "gaming"},
    "minecraft": {"type": BusinessType.PERSONAL, "confidence": 0.98, "category": "gaming"},
    "ea sports": {"type": BusinessType.PERSONAL, "confidence": 0.97, "category": "gaming"},
    "activision": {"type": BusinessType.PERSONAL, "confidence": 0.97, "category": "gaming"},
    "twitch": {"type": BusinessType.PERSONAL, "confidence": 0.90, "category": "gaming"},
    "gamestop": {"type": BusinessType.PERSONAL, "confidence": 0.95, "category": "gaming"},

    # PERSONAL - Medical & Pharmacy
    "cvs": {"type": BusinessType.PERSONAL, "confidence": 0.97, "category": "medical"},
    "cvs pharmacy": {"type": BusinessType.PERSONAL, "confidence": 0.97, "category": "medical"},
    "walgreens": {"type": BusinessType.PERSONAL, "confidence": 0.97, "category": "medical"},
    "rite aid": {"type": BusinessType.PERSONAL, "confidence": 0.97, "category": "medical"},
    "express scripts": {"type": BusinessType.PERSONAL, "confidence": 0.98, "category": "medical"},
    "caremark": {"type": BusinessType.PERSONAL, "confidence": 0.98, "category": "medical"},
    "optum rx": {"type": BusinessType.PERSONAL, "confidence": 0.98, "category": "medical"},
    "kaiser permanente": {"type": BusinessType.PERSONAL, "confidence": 0.98, "category": "medical"},
    "unitedhealth": {"type": BusinessType.PERSONAL, "confidence": 0.98, "category": "medical"},
    "humana": {"type": BusinessType.PERSONAL, "confidence": 0.98, "category": "medical"},
    "aetna": {"type": BusinessType.PERSONAL, "confidence": 0.98, "category": "medical"},
    "cigna": {"type": BusinessType.PERSONAL, "confidence": 0.98, "category": "medical"},
    "anthem": {"type": BusinessType.PERSONAL, "confidence": 0.98, "category": "medical"},
    "labcorp": {"type": BusinessType.PERSONAL, "confidence": 0.97, "category": "medical"},
    "quest diagnostics": {"type": BusinessType.PERSONAL, "confidence": 0.97, "category": "medical"},

    # PERSONAL - Groceries
    "kroger": {"type": BusinessType.PERSONAL, "confidence": 0.97, "category": "groceries"},
    "publix": {"type": BusinessType.PERSONAL, "confidence": 0.97, "category": "groceries"},
    "whole foods": {"type": BusinessType.PERSONAL, "confidence": 0.95, "category": "groceries"},
    "trader joe's": {"type": BusinessType.PERSONAL, "confidence": 0.97, "category": "groceries"},
    "trader joes": {"type": BusinessType.PERSONAL, "confidence": 0.97, "category": "groceries"},
    "aldi": {"type": BusinessType.PERSONAL, "confidence": 0.97, "category": "groceries"},
    "safeway": {"type": BusinessType.PERSONAL, "confidence": 0.97, "category": "groceries"},
    "albertsons": {"type": BusinessType.PERSONAL, "confidence": 0.97, "category": "groceries"},
    "food lion": {"type": BusinessType.PERSONAL, "confidence": 0.97, "category": "groceries"},
    "harris teeter": {"type": BusinessType.PERSONAL, "confidence": 0.97, "category": "groceries"},
    "wegmans": {"type": BusinessType.PERSONAL, "confidence": 0.97, "category": "groceries"},
    "heb": {"type": BusinessType.PERSONAL, "confidence": 0.97, "category": "groceries"},
    "h-e-b": {"type": BusinessType.PERSONAL, "confidence": 0.97, "category": "groceries"},
    "sprouts": {"type": BusinessType.PERSONAL, "confidence": 0.97, "category": "groceries"},

    # PERSONAL - Family Dining (chains)
    "mcdonald's": {"type": BusinessType.PERSONAL, "confidence": 0.95, "category": "family_dining"},
    "mcdonalds": {"type": BusinessType.PERSONAL, "confidence": 0.95, "category": "family_dining"},
    "chick-fil-a": {"type": BusinessType.PERSONAL, "confidence": 0.95, "category": "family_dining"},
    "chick fil a": {"type": BusinessType.PERSONAL, "confidence": 0.95, "category": "family_dining"},
    "wendy's": {"type": BusinessType.PERSONAL, "confidence": 0.95, "category": "family_dining"},
    "wendys": {"type": BusinessType.PERSONAL, "confidence": 0.95, "category": "family_dining"},
    "burger king": {"type": BusinessType.PERSONAL, "confidence": 0.95, "category": "family_dining"},
    "taco bell": {"type": BusinessType.PERSONAL, "confidence": 0.95, "category": "family_dining"},
    "kfc": {"type": BusinessType.PERSONAL, "confidence": 0.95, "category": "family_dining"},
    "popeyes": {"type": BusinessType.PERSONAL, "confidence": 0.95, "category": "family_dining"},
    "five guys": {"type": BusinessType.PERSONAL, "confidence": 0.93, "category": "family_dining"},
    "in-n-out": {"type": BusinessType.PERSONAL, "confidence": 0.93, "category": "family_dining"},
    "in n out": {"type": BusinessType.PERSONAL, "confidence": 0.93, "category": "family_dining"},
    "shake shack": {"type": BusinessType.PERSONAL, "confidence": 0.90, "category": "family_dining"},
    "chipotle": {"type": BusinessType.PERSONAL, "confidence": 0.93, "category": "family_dining"},
    "panera": {"type": BusinessType.PERSONAL, "confidence": 0.93, "category": "family_dining"},
    "panera bread": {"type": BusinessType.PERSONAL, "confidence": 0.93, "category": "family_dining"},
    "olive garden": {"type": BusinessType.PERSONAL, "confidence": 0.95, "category": "family_dining"},
    "applebee's": {"type": BusinessType.PERSONAL, "confidence": 0.95, "category": "family_dining"},
    "applebees": {"type": BusinessType.PERSONAL, "confidence": 0.95, "category": "family_dining"},
    "chili's": {"type": BusinessType.PERSONAL, "confidence": 0.95, "category": "family_dining"},
    "chilis": {"type": BusinessType.PERSONAL, "confidence": 0.95, "category": "family_dining"},
    "outback": {"type": BusinessType.PERSONAL, "confidence": 0.93, "category": "family_dining"},
    "red lobster": {"type": BusinessType.PERSONAL, "confidence": 0.95, "category": "family_dining"},
    "texas roadhouse": {"type": BusinessType.PERSONAL, "confidence": 0.95, "category": "family_dining"},
    "cracker barrel": {"type": BusinessType.PERSONAL, "confidence": 0.95, "category": "family_dining"},
    "ihop": {"type": BusinessType.PERSONAL, "confidence": 0.95, "category": "family_dining"},
    "denny's": {"type": BusinessType.PERSONAL, "confidence": 0.95, "category": "family_dining"},
    "dennys": {"type": BusinessType.PERSONAL, "confidence": 0.95, "category": "family_dining"},
    "waffle house": {"type": BusinessType.PERSONAL, "confidence": 0.95, "category": "family_dining"},
    "starbucks": {"type": BusinessType.PERSONAL, "confidence": 0.85, "category": "family_dining"},
    "dunkin": {"type": BusinessType.PERSONAL, "confidence": 0.90, "category": "family_dining"},
    "dunkin donuts": {"type": BusinessType.PERSONAL, "confidence": 0.90, "category": "family_dining"},

    # PERSONAL - Retail & Shopping
    "target": {"type": BusinessType.PERSONAL, "confidence": 0.95, "category": "retail"},
    "walmart": {"type": BusinessType.PERSONAL, "confidence": 0.95, "category": "retail"},
    "costco": {"type": BusinessType.PERSONAL, "confidence": 0.90, "category": "retail"},
    "sam's club": {"type": BusinessType.PERSONAL, "confidence": 0.90, "category": "retail"},
    "sams club": {"type": BusinessType.PERSONAL, "confidence": 0.90, "category": "retail"},
    "home depot": {"type": BusinessType.PERSONAL, "confidence": 0.90, "category": "retail"},
    "lowes": {"type": BusinessType.PERSONAL, "confidence": 0.90, "category": "retail"},
    "lowe's": {"type": BusinessType.PERSONAL, "confidence": 0.90, "category": "retail"},
    "bed bath beyond": {"type": BusinessType.PERSONAL, "confidence": 0.95, "category": "retail"},
    "ikea": {"type": BusinessType.PERSONAL, "confidence": 0.93, "category": "retail"},
    "nordstrom": {"type": BusinessType.PERSONAL, "confidence": 0.92, "category": "retail"},
    "macy's": {"type": BusinessType.PERSONAL, "confidence": 0.93, "category": "retail"},
    "macys": {"type": BusinessType.PERSONAL, "confidence": 0.93, "category": "retail"},
    "kohls": {"type": BusinessType.PERSONAL, "confidence": 0.95, "category": "retail"},
    "kohl's": {"type": BusinessType.PERSONAL, "confidence": 0.95, "category": "retail"},
    "jcpenney": {"type": BusinessType.PERSONAL, "confidence": 0.95, "category": "retail"},
    "ross": {"type": BusinessType.PERSONAL, "confidence": 0.95, "category": "retail"},
    "tjmaxx": {"type": BusinessType.PERSONAL, "confidence": 0.95, "category": "retail"},
    "tj maxx": {"type": BusinessType.PERSONAL, "confidence": 0.95, "category": "retail"},
    "marshalls": {"type": BusinessType.PERSONAL, "confidence": 0.95, "category": "retail"},
    "old navy": {"type": BusinessType.PERSONAL, "confidence": 0.95, "category": "retail"},
    "gap": {"type": BusinessType.PERSONAL, "confidence": 0.93, "category": "retail"},
    "nike": {"type": BusinessType.PERSONAL, "confidence": 0.90, "category": "retail"},
    "foot locker": {"type": BusinessType.PERSONAL, "confidence": 0.93, "category": "retail"},
    "dick's sporting goods": {"type": BusinessType.PERSONAL, "confidence": 0.90, "category": "retail"},
    "dicks sporting": {"type": BusinessType.PERSONAL, "confidence": 0.90, "category": "retail"},
    "petco": {"type": BusinessType.PERSONAL, "confidence": 0.97, "category": "retail"},
    "petsmart": {"type": BusinessType.PERSONAL, "confidence": 0.97, "category": "retail"},
    "chewy": {"type": BusinessType.PERSONAL, "confidence": 0.97, "category": "retail"},

    # PERSONAL - Kids & Education
    "scholastic": {"type": BusinessType.PERSONAL, "confidence": 0.98, "category": "kids"},
    "kumon": {"type": BusinessType.PERSONAL, "confidence": 0.98, "category": "kids"},
    "sylvan learning": {"type": BusinessType.PERSONAL, "confidence": 0.98, "category": "kids"},
    "mathnasium": {"type": BusinessType.PERSONAL, "confidence": 0.98, "category": "kids"},
    "legoland": {"type": BusinessType.PERSONAL, "confidence": 0.98, "category": "kids"},
    "disney": {"type": BusinessType.PERSONAL, "confidence": 0.95, "category": "kids"},
    "chuck e cheese": {"type": BusinessType.PERSONAL, "confidence": 0.99, "category": "kids"},
    "dave & busters": {"type": BusinessType.PERSONAL, "confidence": 0.95, "category": "kids"},
    "dave and busters": {"type": BusinessType.PERSONAL, "confidence": 0.95, "category": "kids"},
    "build-a-bear": {"type": BusinessType.PERSONAL, "confidence": 0.99, "category": "kids"},
    "build a bear": {"type": BusinessType.PERSONAL, "confidence": 0.99, "category": "kids"},
    "toys r us": {"type": BusinessType.PERSONAL, "confidence": 0.99, "category": "kids"},

    # PERSONAL - Fitness & Gym
    "planet fitness": {"type": BusinessType.PERSONAL, "confidence": 0.98, "category": "fitness"},
    "orangetheory": {"type": BusinessType.PERSONAL, "confidence": 0.97, "category": "fitness"},
    "orange theory": {"type": BusinessType.PERSONAL, "confidence": 0.97, "category": "fitness"},
    "lifetime fitness": {"type": BusinessType.PERSONAL, "confidence": 0.97, "category": "fitness"},
    "la fitness": {"type": BusinessType.PERSONAL, "confidence": 0.97, "category": "fitness"},
    "equinox": {"type": BusinessType.PERSONAL, "confidence": 0.95, "category": "fitness"},
    "crossfit": {"type": BusinessType.PERSONAL, "confidence": 0.97, "category": "fitness"},
    "soulcycle": {"type": BusinessType.PERSONAL, "confidence": 0.97, "category": "fitness"},
    "peloton": {"type": BusinessType.PERSONAL, "confidence": 0.97, "category": "fitness"},
    "ymca": {"type": BusinessType.PERSONAL, "confidence": 0.97, "category": "fitness"},
    "gold's gym": {"type": BusinessType.PERSONAL, "confidence": 0.97, "category": "fitness"},
    "golds gym": {"type": BusinessType.PERSONAL, "confidence": 0.97, "category": "fitness"},
    "anytime fitness": {"type": BusinessType.PERSONAL, "confidence": 0.97, "category": "fitness"},
    "24 hour fitness": {"type": BusinessType.PERSONAL, "confidence": 0.97, "category": "fitness"},

    # PERSONAL - Personal Care
    "great clips": {"type": BusinessType.PERSONAL, "confidence": 0.98, "category": "personal_care"},
    "supercuts": {"type": BusinessType.PERSONAL, "confidence": 0.98, "category": "personal_care"},
    "sports clips": {"type": BusinessType.PERSONAL, "confidence": 0.98, "category": "personal_care"},
    "ulta": {"type": BusinessType.PERSONAL, "confidence": 0.97, "category": "personal_care"},
    "sephora": {"type": BusinessType.PERSONAL, "confidence": 0.95, "category": "personal_care"},
    "bath & body works": {"type": BusinessType.PERSONAL, "confidence": 0.97, "category": "personal_care"},
    "bath and body works": {"type": BusinessType.PERSONAL, "confidence": 0.97, "category": "personal_care"},
    "massage envy": {"type": BusinessType.PERSONAL, "confidence": 0.97, "category": "personal_care"},

    # PERSONAL - Utilities & Services
    "att": {"type": BusinessType.PERSONAL, "confidence": 0.93, "category": "utilities"},
    "at&t": {"type": BusinessType.PERSONAL, "confidence": 0.93, "category": "utilities"},
    "verizon": {"type": BusinessType.PERSONAL, "confidence": 0.93, "category": "utilities"},
    "t-mobile": {"type": BusinessType.PERSONAL, "confidence": 0.95, "category": "utilities"},
    "tmobile": {"type": BusinessType.PERSONAL, "confidence": 0.95, "category": "utilities"},
    "comcast": {"type": BusinessType.PERSONAL, "confidence": 0.97, "category": "utilities"},
    "xfinity": {"type": BusinessType.PERSONAL, "confidence": 0.97, "category": "utilities"},
    "spectrum": {"type": BusinessType.PERSONAL, "confidence": 0.97, "category": "utilities"},
    "cox": {"type": BusinessType.PERSONAL, "confidence": 0.97, "category": "utilities"},
    "dish network": {"type": BusinessType.PERSONAL, "confidence": 0.97, "category": "utilities"},
    "directv": {"type": BusinessType.PERSONAL, "confidence": 0.97, "category": "utilities"},
    "geico": {"type": BusinessType.PERSONAL, "confidence": 0.98, "category": "utilities"},
    "progressive": {"type": BusinessType.PERSONAL, "confidence": 0.98, "category": "utilities"},
    "state farm": {"type": BusinessType.PERSONAL, "confidence": 0.98, "category": "utilities"},
    "allstate": {"type": BusinessType.PERSONAL, "confidence": 0.98, "category": "utilities"},
    "liberty mutual": {"type": BusinessType.PERSONAL, "confidence": 0.98, "category": "utilities"},

    # =========================================================================
    # DOWN HOME - Rideshare & Delivery (per actual data)
    # =========================================================================
    "uber": {"type": BusinessType.DOWN_HOME, "confidence": 0.85, "category": "rideshare"},
    "uber *trip": {"type": BusinessType.DOWN_HOME, "confidence": 0.85, "category": "rideshare"},
    "lyft": {"type": BusinessType.DOWN_HOME, "confidence": 0.85, "category": "rideshare"},
    "doordash": {"type": BusinessType.DOWN_HOME, "confidence": 0.90, "category": "delivery"},
    "dd *doordash": {"type": BusinessType.DOWN_HOME, "confidence": 0.90, "category": "delivery"},
    "grubhub": {"type": BusinessType.DOWN_HOME, "confidence": 0.85, "category": "delivery"},
    "uber eats": {"type": BusinessType.DOWN_HOME, "confidence": 0.85, "category": "delivery"},
    "soho house": {"type": BusinessType.DOWN_HOME, "confidence": 0.99, "category": "dining"},
    "soho house nashville": {"type": BusinessType.DOWN_HOME, "confidence": 0.99, "category": "dining"},

    # =========================================================================
    # PERSONAL - Tech & Retail (per actual data)
    # =========================================================================
    "amazon": {"type": BusinessType.PERSONAL, "confidence": 0.85, "category": "retail"},
    "amzn": {"type": BusinessType.PERSONAL, "confidence": 0.85, "category": "retail"},
    "amazon mktp": {"type": BusinessType.PERSONAL, "confidence": 0.85, "category": "retail"},
    "apple": {"type": BusinessType.PERSONAL, "confidence": 0.85, "category": "tech"},
    "apple store": {"type": BusinessType.PERSONAL, "confidence": 0.91, "category": "tech"},
    "apple.com/bill": {"type": BusinessType.PERSONAL, "confidence": 0.85, "category": "tech"},
    "best buy": {"type": BusinessType.MUSIC_CITY_RODEO, "confidence": 0.50, "category": "retail"},
    "southwest airlines": {"type": BusinessType.PERSONAL, "confidence": 0.85, "category": "travel"},
    "southwest": {"type": BusinessType.PERSONAL, "confidence": 0.85, "category": "travel"},

    # =========================================================================
    # DOWN HOME - Hotels & Travel (per actual data)
    # =========================================================================
    "airbnb": {"type": BusinessType.DOWN_HOME, "confidence": 0.70, "category": "hotel"},
    "marriott": {"type": BusinessType.DOWN_HOME, "confidence": 0.70, "category": "hotel"},
    "hilton": {"type": BusinessType.DOWN_HOME, "confidence": 0.70, "category": "hotel"},
    "hyatt": {"type": BusinessType.DOWN_HOME, "confidence": 0.70, "category": "hotel"},
}


# =============================================================================
# KEYWORD PATTERNS
# =============================================================================

KEYWORD_PATTERNS: Dict[BusinessType, List[Dict]] = {
    BusinessType.DOWN_HOME: [
        # AI & Software keywords
        {"pattern": r"\bai\b", "weight": 0.7, "category": "ai"},
        {"pattern": r"artificial intelligence", "weight": 0.8, "category": "ai"},
        {"pattern": r"machine learning", "weight": 0.8, "category": "ai"},
        {"pattern": r"neural network", "weight": 0.8, "category": "ai"},
        {"pattern": r"gpt|llm|language model", "weight": 0.8, "category": "ai"},
        {"pattern": r"saas|software", "weight": 0.6, "category": "software"},
        {"pattern": r"api|developer|sdk", "weight": 0.7, "category": "software"},
        {"pattern": r"hosting|server|cloud", "weight": 0.7, "category": "cloud"},
        {"pattern": r"domain|ssl|cdn", "weight": 0.7, "category": "cloud"},

        # Production keywords
        {"pattern": r"studio|recording|mixing|mastering", "weight": 0.8, "category": "production"},
        {"pattern": r"production|post-production|edit", "weight": 0.7, "category": "production"},
        {"pattern": r"video|film|cinema|footage", "weight": 0.7, "category": "production"},
        {"pattern": r"audio|sound|music", "weight": 0.6, "category": "production"},
        {"pattern": r"camera|lens|lighting|grip", "weight": 0.7, "category": "production"},
        {"pattern": r"microphone|preamp|interface", "weight": 0.8, "category": "production"},

        # Music industry keywords
        {"pattern": r"royalt(y|ies)", "weight": 0.9, "category": "music_industry"},
        {"pattern": r"publishing|mechanical|sync", "weight": 0.8, "category": "music_industry"},
        {"pattern": r"licensing|copyright", "weight": 0.7, "category": "music_industry"},
        {"pattern": r"tim mcgraw|mcgraw", "weight": 0.95, "category": "partner"},

        # Travel to entertainment hubs
        {"pattern": r"\b(lax|sfo|jfk|bna)\b", "weight": 0.6, "category": "travel"},
        {"pattern": r"los angeles|hollywood|la\s", "weight": 0.5, "category": "travel"},
        {"pattern": r"new york|nyc|manhattan", "weight": 0.5, "category": "travel"},
    ],

    BusinessType.MUSIC_CITY_RODEO: [
        # Rodeo keywords
        {"pattern": r"rodeo|cowboy|cowgirl", "weight": 0.9, "category": "rodeo"},
        {"pattern": r"bull rid(e|ing|er)", "weight": 0.95, "category": "rodeo"},
        {"pattern": r"bronc|barrel rac", "weight": 0.95, "category": "rodeo"},
        {"pattern": r"steer|roping|calf", "weight": 0.9, "category": "rodeo"},
        {"pattern": r"livestock|cattle|horse", "weight": 0.7, "category": "rodeo"},
        {"pattern": r"arena|chute|pen", "weight": 0.6, "category": "rodeo"},
        {"pattern": r"prca|pbr|nfr", "weight": 0.98, "category": "rodeo"},
        {"pattern": r"stock contractor", "weight": 0.95, "category": "rodeo"},

        # Nashville specific
        {"pattern": r"nashville|music city", "weight": 0.7, "category": "nashville"},
        {"pattern": r"tennessee|tn\s", "weight": 0.5, "category": "nashville"},
        {"pattern": r"bridgestone", "weight": 0.9, "category": "nashville"},

        # Event production
        {"pattern": r"event|concert|show", "weight": 0.5, "category": "event"},
        {"pattern": r"sponsor|activation|booth", "weight": 0.7, "category": "event"},
        {"pattern": r"ticket|admission|vip", "weight": 0.6, "category": "event"},
        {"pattern": r"catering|hospitality", "weight": 0.5, "category": "event"},
        {"pattern": r"staging|rigging|barricade", "weight": 0.8, "category": "event"},

        # Talent & booking
        {"pattern": r"artist|talent|performer", "weight": 0.6, "category": "talent"},
        {"pattern": r"booking|agent|management", "weight": 0.6, "category": "talent"},
        {"pattern": r"appearance fee|guarantee", "weight": 0.8, "category": "talent"},
    ],

    BusinessType.PERSONAL: [
        # Family keywords
        {"pattern": r"family|kids|children", "weight": 0.8, "category": "family"},
        {"pattern": r"birthday|party|celebration", "weight": 0.7, "category": "family"},
        {"pattern": r"school|tutor|education", "weight": 0.8, "category": "family"},
        {"pattern": r"toy|game|play", "weight": 0.7, "category": "family"},

        # Personal care
        {"pattern": r"gym|fitness|workout", "weight": 0.8, "category": "personal_care"},
        {"pattern": r"doctor|dentist|medical", "weight": 0.9, "category": "medical"},
        {"pattern": r"prescription|pharmacy|rx", "weight": 0.95, "category": "medical"},
        {"pattern": r"haircut|salon|spa", "weight": 0.8, "category": "personal_care"},

        # Home & household
        {"pattern": r"grocery|groceries|supermarket", "weight": 0.85, "category": "groceries"},
        {"pattern": r"home|house|furniture", "weight": 0.6, "category": "home"},
        {"pattern": r"pet|dog|cat|vet", "weight": 0.9, "category": "pets"},

        # Entertainment
        {"pattern": r"movie|cinema|theater", "weight": 0.75, "category": "entertainment"},
        {"pattern": r"netflix|disney|hulu|hbo", "weight": 0.95, "category": "streaming"},
        {"pattern": r"gaming|playstation|xbox|nintendo", "weight": 0.9, "category": "gaming"},
    ],

    BusinessType.EM_CO: [
        # Em.co specific patterns (to be defined based on business needs)
        {"pattern": r"em\.co|emco", "weight": 0.95, "category": "em_co"},
    ],
}


# =============================================================================
# EMAIL DOMAIN RULES
# =============================================================================

EMAIL_DOMAIN_RULES: Dict[str, Dict] = {
    # DOWN HOME domains
    "anthropic.com": {"type": BusinessType.DOWN_HOME, "confidence": 0.99},
    "openai.com": {"type": BusinessType.DOWN_HOME, "confidence": 0.99},
    "midjourney.com": {"type": BusinessType.DOWN_HOME, "confidence": 0.99},
    "runwayml.com": {"type": BusinessType.DOWN_HOME, "confidence": 0.98},
    "notion.so": {"type": BusinessType.DOWN_HOME, "confidence": 0.95},
    "figma.com": {"type": BusinessType.DOWN_HOME, "confidence": 0.98},
    "adobe.com": {"type": BusinessType.DOWN_HOME, "confidence": 0.95},
    "github.com": {"type": BusinessType.DOWN_HOME, "confidence": 0.98},
    "aws.amazon.com": {"type": BusinessType.DOWN_HOME, "confidence": 0.98},
    "cloud.google.com": {"type": BusinessType.DOWN_HOME, "confidence": 0.98},
    "cloudflare.com": {"type": BusinessType.DOWN_HOME, "confidence": 0.98},
    "railway.app": {"type": BusinessType.DOWN_HOME, "confidence": 0.98},
    "vercel.com": {"type": BusinessType.DOWN_HOME, "confidence": 0.98},
    "ascap.com": {"type": BusinessType.DOWN_HOME, "confidence": 0.99},
    "bmi.com": {"type": BusinessType.DOWN_HOME, "confidence": 0.99},
    "soundexchange.com": {"type": BusinessType.DOWN_HOME, "confidence": 0.99},
    "splice.com": {"type": BusinessType.DOWN_HOME, "confidence": 0.96},
    "distrokid.com": {"type": BusinessType.DOWN_HOME, "confidence": 0.97},
    "sweetwater.com": {"type": BusinessType.DOWN_HOME, "confidence": 0.95},
    "bhphoto.com": {"type": BusinessType.DOWN_HOME, "confidence": 0.92},

    # MUSIC CITY RODEO domains
    "prorodeo.com": {"type": BusinessType.MUSIC_CITY_RODEO, "confidence": 0.99},
    "prca.com": {"type": BusinessType.MUSIC_CITY_RODEO, "confidence": 0.99},
    "pbr.com": {"type": BusinessType.MUSIC_CITY_RODEO, "confidence": 0.98},
    "nfrexperience.com": {"type": BusinessType.MUSIC_CITY_RODEO, "confidence": 0.99},
    "wrangler.com": {"type": BusinessType.MUSIC_CITY_RODEO, "confidence": 0.90},
    "ariat.com": {"type": BusinessType.MUSIC_CITY_RODEO, "confidence": 0.90},
    "bridgestonearena.com": {"type": BusinessType.MUSIC_CITY_RODEO, "confidence": 0.99},
    "nashvilleconventionctr.com": {"type": BusinessType.MUSIC_CITY_RODEO, "confidence": 0.97},
    "livenation.com": {"type": BusinessType.MUSIC_CITY_RODEO, "confidence": 0.90},
    "aegpresents.com": {"type": BusinessType.MUSIC_CITY_RODEO, "confidence": 0.90},

    # PERSONAL domains
    "netflix.com": {"type": BusinessType.PERSONAL, "confidence": 0.98},
    "disneyplus.com": {"type": BusinessType.PERSONAL, "confidence": 0.98},
    "hulu.com": {"type": BusinessType.PERSONAL, "confidence": 0.98},
    "hbomax.com": {"type": BusinessType.PERSONAL, "confidence": 0.98},
    "spotify.com": {"type": BusinessType.PERSONAL, "confidence": 0.95},
    "roblox.com": {"type": BusinessType.PERSONAL, "confidence": 0.99},
    "nintendo.com": {"type": BusinessType.PERSONAL, "confidence": 0.98},
    "playstation.com": {"type": BusinessType.PERSONAL, "confidence": 0.98},
    "xbox.com": {"type": BusinessType.PERSONAL, "confidence": 0.97},
    "cvs.com": {"type": BusinessType.PERSONAL, "confidence": 0.97},
    "walgreens.com": {"type": BusinessType.PERSONAL, "confidence": 0.97},
    "kroger.com": {"type": BusinessType.PERSONAL, "confidence": 0.97},
    "target.com": {"type": BusinessType.PERSONAL, "confidence": 0.95},
    "walmart.com": {"type": BusinessType.PERSONAL, "confidence": 0.95},
    "chewy.com": {"type": BusinessType.PERSONAL, "confidence": 0.97},
    "petco.com": {"type": BusinessType.PERSONAL, "confidence": 0.97},

    # Tech/Retail domains (per actual data)
    "amazon.com": {"type": BusinessType.PERSONAL, "confidence": 0.85},
    "apple.com": {"type": BusinessType.PERSONAL, "confidence": 0.85},
    "uber.com": {"type": BusinessType.DOWN_HOME, "confidence": 0.85},
    "airbnb.com": {"type": BusinessType.DOWN_HOME, "confidence": 0.70},
    "marriott.com": {"type": BusinessType.DOWN_HOME, "confidence": 0.70},
    "hilton.com": {"type": BusinessType.DOWN_HOME, "confidence": 0.70},
}


# =============================================================================
# AMOUNT HEURISTICS
# =============================================================================

AMOUNT_HEURISTICS: Dict[str, Dict] = {
    "meal_personal": {
        "max_amount": Decimal("50"),
        "type": BusinessType.PERSONAL,
        "confidence_boost": 0.15,
        "description": "Personal meal under $50",
    },
    "meal_business": {
        "min_amount": Decimal("100"),
        "max_amount": Decimal("500"),
        "type": BusinessType.DOWN_HOME,
        "confidence_boost": 0.10,
        "description": "Business meal $100-500 range",
    },
    "meal_large_business": {
        "min_amount": Decimal("500"),
        "type": BusinessType.MUSIC_CITY_RODEO,
        "confidence_boost": 0.10,
        "description": "Large event meal over $500",
    },
    "subscription_typical": {
        "min_amount": Decimal("5"),
        "max_amount": Decimal("50"),
        "type": BusinessType.DOWN_HOME,
        "confidence_boost": 0.05,
        "description": "Typical subscription price range",
    },
    "event_expense": {
        "min_amount": Decimal("1000"),
        "type": BusinessType.MUSIC_CITY_RODEO,
        "confidence_boost": 0.15,
        "description": "Large event expense over $1000",
    },
    "small_personal": {
        "max_amount": Decimal("20"),
        "type": BusinessType.PERSONAL,
        "confidence_boost": 0.10,
        "description": "Small purchase under $20",
    },
}


# =============================================================================
# BUSINESS TYPE CLASSIFIER
# =============================================================================

class BusinessTypeClassifier:
    """
    Multi-signal classifier with confidence scoring.
    Returns business_type and confidence_score for transparency.
    """

    def __init__(self, data_dir: Optional[Path] = None):
        """Initialize classifier with optional custom data directory."""
        self.data_dir = data_dir or Path(__file__).parent

        # Load rules databases
        self.merchant_rules = self._load_merchant_rules()
        self.email_domain_rules = self._load_email_domain_rules()
        self.keyword_patterns = KEYWORD_PATTERNS
        self.amount_heuristics = AMOUNT_HEURISTICS

        # Learning system
        self.learned_corrections: Dict[str, Dict] = {}
        self._load_learned_corrections()

        # Statistics
        self.stats = {
            'total_classifications': 0,
            'by_confidence': {'high': 0, 'medium': 0, 'low': 0},
            'by_type': {bt.value: 0 for bt in BusinessType},
            'by_signal_type': {},
        }

        logger.info(f"BusinessTypeClassifier initialized with {len(self.merchant_rules)} merchant rules")

    def _load_merchant_rules(self) -> Dict[str, Dict]:
        """Load merchant rules from JSON or use defaults."""
        rules_file = self.data_dir / "merchant_business_rules.json"
        if rules_file.exists():
            try:
                with open(rules_file, 'r') as f:
                    data = json.load(f)
                    # Convert string types to BusinessType enum
                    for merchant, rule in data.get('rules', {}).items():
                        rule['type'] = BusinessType.from_string(rule['type'])
                    return data.get('rules', {})
            except Exception as e:
                logger.warning(f"Error loading merchant rules: {e}, using defaults")

        return MERCHANT_BUSINESS_RULES

    def _load_email_domain_rules(self) -> Dict[str, Dict]:
        """Load email domain rules from JSON or use defaults."""
        rules_file = self.data_dir / "email_domain_business_rules.json"
        if rules_file.exists():
            try:
                with open(rules_file, 'r') as f:
                    data = json.load(f)
                    for domain, rule in data.get('rules', {}).items():
                        rule['type'] = BusinessType.from_string(rule['type'])
                    return data.get('rules', {})
            except Exception as e:
                logger.warning(f"Error loading email domain rules: {e}, using defaults")

        return EMAIL_DOMAIN_RULES

    def _load_learned_corrections(self):
        """Load learned corrections from file."""
        corrections_file = self.data_dir / "learned_corrections.json"
        if corrections_file.exists():
            try:
                with open(corrections_file, 'r') as f:
                    self.learned_corrections = json.load(f)
                logger.info(f"Loaded {len(self.learned_corrections)} learned corrections")
            except Exception as e:
                logger.warning(f"Error loading learned corrections: {e}")

    def _save_learned_corrections(self):
        """Save learned corrections to file."""
        corrections_file = self.data_dir / "learned_corrections.json"
        try:
            with open(corrections_file, 'w') as f:
                json.dump(self.learned_corrections, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving learned corrections: {e}")

    def _normalize_merchant(self, merchant: str) -> str:
        """Normalize merchant name for matching."""
        if not merchant:
            return ""

        normalized = merchant.lower().strip()

        # Remove POS prefixes
        pos_prefixes = ['sq *', 'sq*', 'tst *', 'tst*', 'dd *', 'dd*', 'pp *', 'pp*',
                        'ppl*', 'zzz*', 'chk*', 'pos ', 'pos*', 'dbt ', 'ach ']
        for prefix in pos_prefixes:
            if normalized.startswith(prefix):
                normalized = normalized[len(prefix):].strip()

        # Remove common suffixes
        suffixes_to_remove = [' inc', ' llc', ' ltd', ' corp', ' co', ' #', '*']
        for suffix in suffixes_to_remove:
            if suffix in normalized:
                normalized = normalized.split(suffix)[0].strip()

        # Remove trailing numbers and special chars
        normalized = re.sub(r'[\d#\*]+$', '', normalized).strip()

        return normalized

    def _get_merchant_hash(self, merchant: str, amount: Optional[Decimal] = None) -> str:
        """Generate a hash for merchant+amount for learning."""
        normalized = self._normalize_merchant(merchant)
        key = normalized
        if amount:
            # Round to nearest dollar for matching
            key += f"_{int(amount)}"
        return hashlib.md5(key.encode()).hexdigest()[:12]

    def classify(
        self,
        transaction: Transaction,
        receipt: Optional[Receipt] = None,
        calendar_events: Optional[List[CalendarEvent]] = None,
        contacts: Optional[List[Contact]] = None,
    ) -> ClassificationResult:
        """
        Classify a transaction into a business type.

        Returns:
        - business_type: The classified business type
        - confidence: Overall confidence score (0-1)
        - reasoning: Human-readable explanation
        - signals: List of all signals that contributed
        """
        signals: List[ClassificationSignal] = []

        # 1. Check learned corrections first (highest priority)
        learned_signal = self._check_learned_corrections(transaction, receipt)
        if learned_signal:
            signals.append(learned_signal)

        # 2. Exact merchant match
        merchant_signal = self._check_merchant_exact(transaction.merchant)
        if merchant_signal:
            signals.append(merchant_signal)

        # 3. Email domain match (if receipt available)
        if receipt and receipt.email_domain:
            email_signal = self._check_email_domain(receipt.email_domain)
            if email_signal:
                signals.append(email_signal)

        # 4. Keyword analysis
        keyword_signals = self._analyze_keywords(transaction, receipt)
        signals.extend(keyword_signals)

        # 5. Amount heuristics
        amount_signal = self._check_amount_heuristics(transaction, receipt)
        if amount_signal:
            signals.append(amount_signal)

        # 6. Calendar context boost
        if calendar_events:
            calendar_signal = self._check_calendar_context(transaction, calendar_events)
            if calendar_signal:
                signals.append(calendar_signal)

        # 7. Contact context boost
        if contacts and receipt and receipt.attendees:
            contact_signal = self._check_contact_context(receipt.attendees, contacts)
            if contact_signal:
                signals.append(contact_signal)

        # Calculate final classification
        result = self._calculate_final_classification(signals, transaction)

        # Update statistics
        self._update_stats(result)

        return result

    def _check_learned_corrections(
        self,
        transaction: Transaction,
        receipt: Optional[Receipt]
    ) -> Optional[ClassificationSignal]:
        """Check if we've learned a correction for this merchant."""
        merchant_hash = self._get_merchant_hash(transaction.merchant, transaction.amount)

        if merchant_hash in self.learned_corrections:
            correction = self.learned_corrections[merchant_hash]
            return ClassificationSignal(
                signal_type='learned',
                business_type=BusinessType.from_string(correction['type']),
                confidence=0.97,  # High confidence for learned patterns
                reasoning=f"Learned from previous correction: {correction.get('notes', 'user correction')}",
                weight=1.5,  # Extra weight for learned patterns
            )

        # Also check without amount
        merchant_hash_no_amount = self._get_merchant_hash(transaction.merchant)
        if merchant_hash_no_amount in self.learned_corrections:
            correction = self.learned_corrections[merchant_hash_no_amount]
            return ClassificationSignal(
                signal_type='learned',
                business_type=BusinessType.from_string(correction['type']),
                confidence=0.95,
                reasoning=f"Learned merchant pattern: {correction.get('notes', 'user correction')}",
                weight=1.4,
            )

        return None

    def _check_merchant_exact(self, merchant: str) -> Optional[ClassificationSignal]:
        """Check for exact merchant match in rules."""
        normalized = self._normalize_merchant(merchant)

        # Direct match
        if normalized in self.merchant_rules:
            rule = self.merchant_rules[normalized]
            return ClassificationSignal(
                signal_type='merchant_exact',
                business_type=rule['type'],
                confidence=rule['confidence'],
                reasoning=f"Exact merchant match: {normalized} ({rule.get('category', 'general')})",
                weight=1.0,
            )

        # Fuzzy match for close matches
        best_match = None
        best_score = 0.0

        for rule_merchant, rule in self.merchant_rules.items():
            # Check if merchant contains the rule pattern
            if rule_merchant in normalized or normalized in rule_merchant:
                score = len(rule_merchant) / max(len(normalized), len(rule_merchant))
                if score > best_score and score > 0.7:
                    best_match = (rule_merchant, rule)
                    best_score = score

            # Use SequenceMatcher for fuzzy matching
            ratio = SequenceMatcher(None, normalized, rule_merchant).ratio()
            if ratio > best_score and ratio > 0.85:
                best_match = (rule_merchant, rule)
                best_score = ratio

        if best_match:
            rule_merchant, rule = best_match
            return ClassificationSignal(
                signal_type='merchant_fuzzy',
                business_type=rule['type'],
                confidence=rule['confidence'] * best_score,
                reasoning=f"Fuzzy merchant match: {normalized} ≈ {rule_merchant} ({best_score:.0%})",
                weight=0.9,
            )

        return None

    def _check_email_domain(self, email_domain: str) -> Optional[ClassificationSignal]:
        """Check email domain against rules."""
        domain = email_domain.lower().strip()

        # Remove leading @ if present
        if domain.startswith('@'):
            domain = domain[1:]

        if domain in self.email_domain_rules:
            rule = self.email_domain_rules[domain]
            return ClassificationSignal(
                signal_type='email_domain',
                business_type=rule['type'],
                confidence=rule['confidence'],
                reasoning=f"Email domain match: {domain}",
                weight=1.0,
            )

        # Check for subdomain matches (e.g., receipts.netflix.com -> netflix.com)
        parts = domain.split('.')
        if len(parts) > 2:
            base_domain = '.'.join(parts[-2:])
            if base_domain in self.email_domain_rules:
                rule = self.email_domain_rules[base_domain]
                return ClassificationSignal(
                    signal_type='email_domain',
                    business_type=rule['type'],
                    confidence=rule['confidence'] * 0.95,
                    reasoning=f"Email subdomain match: {domain} -> {base_domain}",
                    weight=0.95,
                )

        return None

    def _analyze_keywords(
        self,
        transaction: Transaction,
        receipt: Optional[Receipt]
    ) -> List[ClassificationSignal]:
        """Analyze keywords in merchant name and receipt text."""
        signals = []

        # Combine all text to analyze
        text_to_analyze = transaction.merchant.lower()
        if transaction.description:
            text_to_analyze += " " + transaction.description.lower()
        if receipt:
            if receipt.raw_text:
                text_to_analyze += " " + receipt.raw_text.lower()
            if receipt.items:
                text_to_analyze += " " + " ".join(receipt.items).lower()
            if receipt.location:
                text_to_analyze += " " + receipt.location.lower()

        # Check patterns for each business type
        type_scores: Dict[BusinessType, float] = {bt: 0.0 for bt in BusinessType}
        type_matches: Dict[BusinessType, List[str]] = {bt: [] for bt in BusinessType}

        for business_type, patterns in self.keyword_patterns.items():
            for pattern_info in patterns:
                pattern = pattern_info['pattern']
                weight = pattern_info['weight']
                category = pattern_info.get('category', 'general')

                if re.search(pattern, text_to_analyze, re.IGNORECASE):
                    type_scores[business_type] += weight
                    type_matches[business_type].append(f"{category}:{pattern}")

        # Create signals for types with significant matches
        for business_type, score in type_scores.items():
            if score >= 0.5:  # Threshold for keyword match
                matches = type_matches[business_type]
                confidence = min(0.85, 0.50 + (score * 0.15))  # Scale confidence

                signals.append(ClassificationSignal(
                    signal_type='keyword',
                    business_type=business_type,
                    confidence=confidence,
                    reasoning=f"Keyword matches ({len(matches)}): {', '.join(matches[:3])}",
                    weight=0.8,
                ))

        return signals

    def _check_amount_heuristics(
        self,
        transaction: Transaction,
        receipt: Optional[Receipt]
    ) -> Optional[ClassificationSignal]:
        """Apply amount-based heuristics."""
        amount = transaction.amount

        # Determine if this looks like a meal
        is_meal = False
        merchant_lower = transaction.merchant.lower()
        meal_keywords = ['restaurant', 'cafe', 'grill', 'bar', 'kitchen', 'diner',
                        'bistro', 'eatery', 'pub', 'tavern', 'steakhouse']
        for keyword in meal_keywords:
            if keyword in merchant_lower:
                is_meal = True
                break

        for heuristic_name, heuristic in self.amount_heuristics.items():
            # Check amount range
            min_amt = heuristic.get('min_amount', Decimal('0'))
            max_amt = heuristic.get('max_amount', Decimal('999999'))

            if min_amt <= amount <= max_amt:
                # For meal heuristics, only apply if it looks like a meal
                if 'meal' in heuristic_name and not is_meal:
                    continue

                return ClassificationSignal(
                    signal_type='amount',
                    business_type=heuristic['type'],
                    confidence=0.70 + heuristic['confidence_boost'],
                    reasoning=heuristic['description'],
                    weight=0.6,  # Lower weight for amount heuristics
                )

        return None

    def _check_calendar_context(
        self,
        transaction: Transaction,
        calendar_events: List[CalendarEvent]
    ) -> Optional[ClassificationSignal]:
        """Check for calendar events near transaction time."""
        tx_date = transaction.date

        # Look for events within 4 hours of transaction
        time_window = timedelta(hours=4)

        for event in calendar_events:
            # Check if event is near transaction time
            if event.start - time_window <= tx_date <= event.end + time_window:
                # Analyze event for business type signals
                event_text = f"{event.title} {event.description or ''} {event.location or ''}".lower()

                # Check for Down Home signals
                dh_keywords = ['tim', 'mcgraw', 'production', 'music', 'studio', 'recording']
                if any(kw in event_text for kw in dh_keywords):
                    return ClassificationSignal(
                        signal_type='calendar',
                        business_type=BusinessType.DOWN_HOME,
                        confidence=0.90,
                        reasoning=f"Calendar event match: {event.title}",
                        weight=1.2,  # High weight for calendar context
                    )

                # Check for MCR signals
                mcr_keywords = ['rodeo', 'mcr', 'bridgestone', 'nashville', 'event', 'prca']
                if any(kw in event_text for kw in mcr_keywords):
                    return ClassificationSignal(
                        signal_type='calendar',
                        business_type=BusinessType.MUSIC_CITY_RODEO,
                        confidence=0.90,
                        reasoning=f"Calendar event match: {event.title}",
                        weight=1.2,
                    )

                # Generic business meeting - defaults to Down Home
                business_keywords = ['meeting', 'client', 'call', 'presentation']
                if any(kw in event_text for kw in business_keywords):
                    return ClassificationSignal(
                        signal_type='calendar',
                        business_type=BusinessType.DOWN_HOME,
                        confidence=0.80,
                        reasoning=f"Business calendar event: {event.title}",
                        weight=1.0,
                    )

        return None

    def _check_contact_context(
        self,
        attendees: List[str],
        contacts: List[Contact]
    ) -> Optional[ClassificationSignal]:
        """Check if attendees match known contacts with business type."""
        for attendee in attendees:
            attendee_lower = attendee.lower()

            for contact in contacts:
                # Check name match
                if contact.name and contact.name.lower() in attendee_lower:
                    if contact.business_type:
                        return ClassificationSignal(
                            signal_type='contact',
                            business_type=contact.business_type,
                            confidence=0.88,
                            reasoning=f"Contact match: {contact.name} ({contact.company or 'no company'})",
                            weight=1.1,
                        )

                    # Check contact tags for business type hints
                    for tag in contact.tags:
                        tag_lower = tag.lower()
                        if 'down home' in tag_lower or 'dh' in tag_lower:
                            return ClassificationSignal(
                                signal_type='contact',
                                business_type=BusinessType.DOWN_HOME,
                                confidence=0.85,
                                reasoning=f"Contact tag match: {contact.name} tagged '{tag}'",
                                weight=1.0,
                            )
                        elif 'rodeo' in tag_lower or 'mcr' in tag_lower:
                            return ClassificationSignal(
                                signal_type='contact',
                                business_type=BusinessType.MUSIC_CITY_RODEO,
                                confidence=0.85,
                                reasoning=f"Contact tag match: {contact.name} tagged '{tag}'",
                                weight=1.0,
                            )

        return None

    def _calculate_final_classification(
        self,
        signals: List[ClassificationSignal],
        transaction: Transaction
    ) -> ClassificationResult:
        """Calculate final classification from all signals."""
        if not signals:
            # No signals - default to Down Home (most common business type)
            return ClassificationResult(
                business_type=BusinessType.DOWN_HOME,
                confidence=0.50,
                reasoning="No classification signals found - defaulting to Down Home for review",
                signals=[],
                needs_review=True,
            )

        # Calculate weighted scores for each type
        type_scores: Dict[BusinessType, float] = {bt: 0.0 for bt in BusinessType}
        type_weights: Dict[BusinessType, float] = {bt: 0.0 for bt in BusinessType}

        for signal in signals:
            weighted_score = signal.confidence * signal.weight
            type_scores[signal.business_type] += weighted_score
            type_weights[signal.business_type] += signal.weight

        # Normalize scores
        for bt in BusinessType:
            if type_weights[bt] > 0:
                type_scores[bt] /= type_weights[bt]

        # Find best type
        best_type = max(type_scores.keys(), key=lambda bt: type_scores[bt])
        best_score = type_scores[best_type]

        # Calculate alternative types
        alternative_types = {
            bt: score for bt, score in type_scores.items()
            if bt != best_type and score > 0.30
        }

        # Determine if review is needed
        needs_review = False
        if best_score < 0.75:
            needs_review = True
        elif len(alternative_types) > 0:
            # Check if there's a close competitor
            second_best = max(alternative_types.values()) if alternative_types else 0
            if second_best > best_score * 0.85:  # Within 15%
                needs_review = True

        # Generate reasoning
        primary_signals = sorted(signals, key=lambda s: s.confidence * s.weight, reverse=True)[:3]
        reasoning_parts = [s.reasoning for s in primary_signals]
        reasoning = " | ".join(reasoning_parts)

        return ClassificationResult(
            business_type=best_type,
            confidence=min(0.99, best_score),
            reasoning=reasoning,
            signals=signals,
            alternative_types=alternative_types,
            needs_review=needs_review,
        )

    def _update_stats(self, result: ClassificationResult):
        """Update classification statistics."""
        self.stats['total_classifications'] += 1

        # By confidence level
        if result.confidence >= 0.90:
            self.stats['by_confidence']['high'] += 1
        elif result.confidence >= 0.75:
            self.stats['by_confidence']['medium'] += 1
        else:
            self.stats['by_confidence']['low'] += 1

        # By type
        self.stats['by_type'][result.business_type.value] += 1

        # By signal type
        for signal in result.signals:
            if signal.signal_type not in self.stats['by_signal_type']:
                self.stats['by_signal_type'][signal.signal_type] = 0
            self.stats['by_signal_type'][signal.signal_type] += 1

    def learn_from_correction(
        self,
        transaction_id: int,
        merchant: str,
        amount: Decimal,
        correct_type: BusinessType,
        user_notes: Optional[str] = None,
    ):
        """Learn from user correction to improve future classification."""
        # Store with amount for specific matching
        merchant_hash = self._get_merchant_hash(merchant, amount)
        self.learned_corrections[merchant_hash] = {
            'type': correct_type.value,
            'merchant': merchant,
            'amount': str(amount),
            'notes': user_notes or 'User correction',
            'timestamp': datetime.now().isoformat(),
            'transaction_id': transaction_id,
        }

        # Also store without amount for general merchant matching
        merchant_hash_general = self._get_merchant_hash(merchant)
        if merchant_hash_general not in self.learned_corrections:
            self.learned_corrections[merchant_hash_general] = {
                'type': correct_type.value,
                'merchant': merchant,
                'notes': user_notes or 'User correction (general)',
                'timestamp': datetime.now().isoformat(),
            }

        self._save_learned_corrections()
        logger.info(f"Learned correction: {merchant} -> {correct_type.value}")

    def classify_batch(
        self,
        transactions: List[Transaction],
        receipts: Optional[Dict[int, Receipt]] = None,
        calendar_events: Optional[List[CalendarEvent]] = None,
        contacts: Optional[List[Contact]] = None,
    ) -> List[ClassificationResult]:
        """Classify a batch of transactions."""
        results = []

        for tx in transactions:
            receipt = receipts.get(tx.id) if receipts else None
            result = self.classify(tx, receipt, calendar_events, contacts)
            results.append(result)

        return results

    def get_stats(self) -> Dict:
        """Get classification statistics."""
        stats = self.stats.copy()

        # Add derived stats
        total = stats['total_classifications']
        if total > 0:
            stats['high_confidence_rate'] = stats['by_confidence']['high'] / total
            stats['review_rate'] = stats['by_confidence']['low'] / total

        stats['learned_patterns'] = len(self.learned_corrections)
        stats['merchant_rules'] = len(self.merchant_rules)
        stats['email_domain_rules'] = len(self.email_domain_rules)

        return stats

    def export_rules_to_json(self):
        """Export current rules to JSON files."""
        # Export merchant rules
        merchant_rules_export = {
            "version": "1.0.0",
            "last_updated": datetime.now().isoformat(),
            "rules": {
                merchant: {
                    "type": rule['type'].value,
                    "confidence": rule['confidence'],
                    "category": rule.get('category', 'general'),
                }
                for merchant, rule in self.merchant_rules.items()
            }
        }

        with open(self.data_dir / "merchant_business_rules.json", 'w') as f:
            json.dump(merchant_rules_export, f, indent=2)

        # Export email domain rules
        email_rules_export = {
            "version": "1.0.0",
            "last_updated": datetime.now().isoformat(),
            "rules": {
                domain: {
                    "type": rule['type'].value,
                    "confidence": rule['confidence'],
                }
                for domain, rule in self.email_domain_rules.items()
            }
        }

        with open(self.data_dir / "email_domain_business_rules.json", 'w') as f:
            json.dump(email_rules_export, f, indent=2)

        logger.info("Exported rules to JSON files")


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def create_classifier() -> BusinessTypeClassifier:
    """Create a new classifier instance."""
    return BusinessTypeClassifier()


def classify_transaction(
    merchant: str,
    amount: float,
    date: datetime = None,
    description: str = None,
    receipt_email: str = None,
) -> ClassificationResult:
    """Quick classification function for single transactions."""
    classifier = BusinessTypeClassifier()

    tx = Transaction(
        id=0,
        merchant=merchant,
        amount=Decimal(str(amount)),
        date=date or datetime.now(),
        description=description,
    )

    receipt = None
    if receipt_email:
        receipt = Receipt(
            id=0,
            merchant=merchant,
            amount=Decimal(str(amount)),
            email_domain=receipt_email.split('@')[-1] if '@' in receipt_email else receipt_email,
        )

    return classifier.classify(tx, receipt)


# =============================================================================
# MAIN
# =============================================================================

if __name__ == '__main__':
    # Demo usage
    import sys

    classifier = BusinessTypeClassifier()

    # Test cases
    test_cases = [
        ("Anthropic", 20.00, "AI subscription"),
        ("NETFLIX", 15.99, "Streaming"),
        ("PRCA Membership", 250.00, "Rodeo organization"),
        ("Amazon", 47.99, "Ambiguous retail"),
        ("Bridgestone Arena", 5000.00, "Event venue"),
        ("Kroger", 125.00, "Grocery store"),
        ("APPLE.COM/BILL", 9.99, "Apple subscription"),
        ("Sweetwater Sound", 499.00, "Music equipment"),
        ("Roblox", 19.99, "Kids gaming"),
        ("CAA", 15000.00, "Talent agency"),
    ]

    print("=" * 80)
    print("BUSINESS TYPE CLASSIFIER DEMO")
    print("=" * 80)

    for merchant, amount, desc in test_cases:
        result = classify_transaction(merchant, amount, description=desc)

        print(f"\n{merchant} (${amount:.2f}) - {desc}")
        print(f"  → {result.business_type.value.upper()} ({result.confidence:.0%})")
        print(f"  Reasoning: {result.reasoning}")
        if result.needs_review:
            print("  ⚠️  NEEDS REVIEW")
        if result.alternative_types:
            alts = ", ".join(f"{bt.value}:{conf:.0%}" for bt, conf in result.alternative_types.items())
            print(f"  Alternatives: {alts}")

    print("\n" + "=" * 80)
    print("STATISTICS")
    print("=" * 80)
    stats = classifier.get_stats()
    print(f"Total classifications: {stats['total_classifications']}")
    print(f"Merchant rules: {stats['merchant_rules']}")
    print(f"Email domain rules: {stats['email_domain_rules']}")
