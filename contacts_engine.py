# contacts_engine.py
from __future__ import annotations
from typing import Dict, List
from helpers import parse_amount_str


# Core people list
VIP_PEOPLE = [
    # You
    "Brian Kaplan",

    # Secondary staff
    "Patrick Humes",
    "Barry Stephenson",
    "Paige",

    # Business Team
    "Jason Ross",
    "Tim Staples",
    "Joel Bergvall",
    "Kevin Sabbe",
    "Andrew Cohen",
    "Celeste Stange",
    "Tom May",

    # People you could meet with
    "Stephen Person",
    "Tom Etzel",
    "Cindy Mabe",
    "Ken Robold",
    "Taylor Lindsey",
    "Ben Kline",
    "Nick Barnes",
    "Copeland Isaacson",
    "Margarette Hart",
    "Sarah Moore",
    "Shanna Strassberg",
    "Sarah Hilly",
    "Sarah DeMarco",
    "Dawn Gates",

    # Extra from your note
    "Scott Siman",
]

MCR_TEAM = ["Brian Kaplan", "Patrick Humes", "Barry Stephenson", "Paige"]
BUSINESS_TEAM = [
    "Brian Kaplan",
    "Jason Ross",
    "Tim Staples",
    "Joel Bergvall",
    "Kevin Sabbe",
    "Andrew Cohen",
    "Celeste Stange",
    "Tom May",
]
INDUSTRY_EXEC_TEAM = [
    "Brian Kaplan",
    "Cindy Mabe",
    "Ken Robold",
    "Taylor Lindsey",
    "Ben Kline",
    "Nick Barnes",
    "Stephen Person",
    "Tom Etzel",
    "Scott Siman",
]


def merchant_hint_for_row(row: Dict) -> str:
    """
    Human-readable hint about the merchant; this is injected into AI Note.
    Also used to bias reasoning (Soho House == meal/meeting, etc).
    """
    desc = (row.get("Chase Description") or row.get("merchant") or "").lower()
    cat = (row.get("Chase Category") or row.get("category") or "").lower()

    if "sh nashville" in desc or "soho house" in desc:
        return "Soho House Nashville — members club; always meals or meetings."

    if "anthropic" in desc or "claude" in desc:
        return "Anthropic / Claude — AI assistant used for writing, coding, and strategy."

    if "apple one" in desc:
        return "Apple One — Apple premium monthly bundle (iCloud, TV, Music, etc.)."

    if "apple.com/bill" in desc:
        return "Apple subscription or app store charge."

    if "clear" in desc:
        return "CLEAR — airport security fast-track service."

    if "uber" in desc or "lyft" in desc:
        return "Rideshare / local transportation."

    if "imdbpro" in desc:
        return "IMDbPro — industry trade / research subscription."

    if "expensify" in desc:
        return "Expensify — expense reporting / corporate card software."

    if any(k in cat for k in ["food & drink", "restaurants", "dining"]):
        return "Meal / hospitality expense for meetings or work dinners."

    if "hotel" in desc or "marriott" in desc or "hilton" in desc:
        return "Hotel / lodging during work travel."

    if "parking" in desc or "park happy" in desc:
        return "Parking for meetings, events, or airport."

    return ""


def _looks_like_meal(row: Dict) -> bool:
    desc = (row.get("Chase Description") or "").lower()
    cat = (row.get("Chase Category") or "").lower()
    if "sh nashville" in desc or "soho house" in desc:
        return True
    meal_words = ["bar", "grill", "steak", "house", "cafe", "deli", "restaurant", "brew", "coffee"]
    if any(w in desc for w in meal_words):
        return True
    if any(k in cat for k in ["food & drink", "restaurants", "dining"]):
        return True
    return False


def guess_attendees_for_row(row: Dict) -> List[str]:
    """
    Heuristic attendee picker for meals / hospitality:
      - Always includes Brian
      - Uses Business Type + Merchant to bias groups
      - Deterministic randomness based on row to stay stable
    """
    import random

    if not _looks_like_meal(row):
        return ["Brian Kaplan"]

    desc = (row.get("Chase Description") or "").lower()
    biz = (row.get("Business Type") or "").lower()

    base = ["Brian Kaplan"]

    if "secondary" in biz:
        pool = MCR_TEAM
    elif "business" in biz:
        pool = BUSINESS_TEAM
    else:
        # Soho / SH Nashville / general exec dinners
        if "soho house" in desc or "sh nashville" in desc:
            pool = INDUSTRY_EXEC_TEAM
        else:
            pool = VIP_PEOPLE

    pool = [p for p in pool if p != "Brian Kaplan"]

    # Heavier weight for Scott on exec / Soho House stuff
    if "soho house" in desc or "sh nashville" in desc:
        pool = pool + ["Scott Siman"] * 2

    seed_key = f"{row.get('Chase Date') or ''}|{row.get('Chase Description') or ''}"
    random.seed(seed_key)
    k = random.choice([1, 2, 3])
    k = min(k, len(pool)) if pool else 0
    extra = random.sample(pool, k=k) if k > 0 else []

    attendees = base + extra
    seen = set()
    uniq = []
    for a in attendees:
        if a not in seen:
            seen.add(a)
            uniq.append(a)
    return uniq