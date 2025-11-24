# helpers.py
from __future__ import annotations
import os
import math
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, Tuple

import pandas as pd


# -----------------------------------------------------------------------------
# ENV
# -----------------------------------------------------------------------------
def require_env(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return v


# -----------------------------------------------------------------------------
# SANITIZERS / JSON-SAFE
# -----------------------------------------------------------------------------
def sanitize_value(val: Any) -> str:
    """
    Make a single cell safe for CSV / JSON:
    - Remove NaN/inf -> empty string
    - Strip CR/LF so viewer JSON doesn't break
    """
    if isinstance(val, float):
        if math.isnan(val) or math.isinf(val):
            return ""
    if isinstance(val, str):
        v = val.replace("\r", " ").replace("\n", " ")
        return v
    if pd.isna(val):
        return ""
    v = str(val)
    v = v.replace("\r", " ").replace("\n", " ")
    return v


def sanitize_csv(df_in: pd.DataFrame) -> pd.DataFrame:
    """
    Sanitize all columns EXCEPT _index (which must stay numeric).
    """
    df_local = df_in.copy()
    for col in df_local.columns:
        if col == "_index":
            continue
        df_local[col] = df_local[col].apply(sanitize_value)
    return df_local


def safe_json(data: Any) -> Any:
    """
    Recursively walk a structure and replace NaN/inf with None so
    Flask/json doesn't emit invalid JS tokens.
    """
    def clean(v: Any):
        if isinstance(v, float):
            if math.isnan(v) or math.isinf(v):
                return None
            return v
        elif isinstance(v, dict):
            return {k: clean(v2) for k, v2 in v.items()}
        elif isinstance(v, list):
            return [clean(x) for x in v]
        return v

    return clean(data)


# -----------------------------------------------------------------------------
# PARSERS / NORMALIZERS
# -----------------------------------------------------------------------------
def parse_amount_str(val: Any) -> float:
    """Parse an amount from CSV-style strings like '$123.45' or '-1,234.56'."""
    if val is None:
        return 0.0
    s = str(val)
    if not s.strip():
        return 0.0
    cleaned = "".join(ch for ch in s if ch.isdigit() or ch in ".-")
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def norm_text_for_match(s: str | None) -> str:
    """Lowercase alnum-ish representation for fuzzy merchant matching."""
    if not s:
        return ""
    s = s.lower()
    kept = []
    for ch in s:
        if ch.isalnum():
            kept.append(ch)
        elif ch.isspace():
            kept.append(" ")
    return " ".join("".join(kept).split())


def parse_date_fuzzy(s: str | None):
    if not s:
        return None
    s = s.strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    # last resort: pandas
    try:
        d = pd.to_datetime(s, errors="coerce")
        if pd.isna(d):
            return None
        return d.date()
    except Exception:
        return None


def strip_confirmation_numbers(merchant_desc: str) -> str:
    """
    Strip confirmation numbers and booking codes from transaction descriptions.

    Examples:
      'SOUTHWES 5262533925711' → 'SOUTHWES'
      'UNITED 123ABC456789' → 'UNITED'
      'MARRIOTT 789XYZ012' → 'MARRIOTT'
      'DELTA AIR 0067417548291' → 'DELTA AIR'
      'TST* PANERA BREAD #600874' → 'TST* PANERA BREAD'

    Patterns stripped:
      - Long numeric sequences (8+ digits)
      - Alphanumeric codes (8+ chars with both letters and numbers)
      - Store/location numbers after # symbol (e.g., #600874)
    """
    import re

    if not merchant_desc:
        return ""

    cleaned = merchant_desc.strip()

    # Strip long numeric sequences (8+ consecutive digits)
    # e.g., "SOUTHWES 5262533925711" → "SOUTHWES"
    cleaned = re.sub(r'\s+\d{8,}', '', cleaned)

    # Strip alphanumeric confirmation codes (8+ chars with both letters and numbers)
    # e.g., "UNITED 123ABC456" → "UNITED"
    cleaned = re.sub(r'\s+(?=.*[A-Za-z])(?=.*\d)[A-Za-z0-9]{8,}', '', cleaned)

    # Strip store/location numbers after # symbol
    # e.g., "PANERA BREAD #600874" → "PANERA BREAD"
    cleaned = re.sub(r'\s*#\d+', '', cleaned)

    # Strip trailing numbers preceded by space (likely confirmation/reference numbers)
    # e.g., "DELTA AIR 0067417548291" → "DELTA AIR"
    cleaned = re.sub(r'\s+\d{7,}$', '', cleaned)

    return cleaned.strip()


def normalize_merchant_name(s: str | None) -> str:
    """
    Normalize merchant names for matching, including some custom brand logic:
      - Anthropic / Claude cluster
      - Soho House / SH Nashville cluster
      - Strip confirmation numbers (airlines, hotels, travel)
      - Travel merchant normalization (airlines, hotels, rental cars)
    """
    if not s:
        return ""
    raw = s.strip()

    # STEP 1: Strip confirmation numbers BEFORE normalization
    # This fixes matching for airlines, hotels, rental cars, etc.
    cleaned = strip_confirmation_numbers(raw)

    low = cleaned.lower()

    # =============================================================================
    # BRAND CLUSTERS (exact name normalization)
    # =============================================================================

    # Soho House / SH Nashville cluster
    if any(x in low for x in ["sh nashville", "soho house", "shnash", "sh house", "sh nash"]):
        return "Soho House Nashville"

    # Anthropic / Claude cluster
    if any(x in low for x in ["anthropic", "claude", "anthropic ai"]):
        return "Anthropic / Claude"

    # =============================================================================
    # TRAVEL MERCHANTS (airlines, hotels, rental cars)
    # =============================================================================
    # Normalize common variations to improve matching
    # e.g., "United Airlines" → "united", "Southwest Air" → "southwest"

    # Airlines - strip "airlines", "air", "airways" suffixes
    airline_keywords = ["airlines", "airways", "air lines", "air ways"]
    for keyword in airline_keywords:
        if keyword in low:
            low = low.replace(keyword, "").strip()

    # Strip standalone "air" when it's a suffix (e.g., "DELTA AIR" → "DELTA")
    # but NOT when it's part of the merchant name (e.g., "Air Conditioner Repair")
    if low.endswith(" air"):
        low = low[:-4].strip()

    # Hotels - strip "hotel", "hotels", "suites", "inn" suffixes
    hotel_keywords = ["hotels", "hotel", "suites", "inn & suites", "inn"]
    for keyword in hotel_keywords:
        if low.endswith(keyword):
            low = low[:-len(keyword)].strip()

    # Rental cars - normalize to base brand
    if "hertz" in low:
        return "hertz"
    if "enterprise" in low:
        return "enterprise"
    if "avis" in low:
        return "avis"
    if "budget" in low:
        return "budget"
    if "national" in low and "car" in low:
        return "national"

    # =============================================================================
    # FINAL NORMALIZATION
    # =============================================================================
    low_norm = norm_text_for_match(low)
    return low_norm


# -----------------------------------------------------------------------------
# CSV LOAD / REPAIR
# -----------------------------------------------------------------------------
def _diagnose_bad_lines(csv_path: Path) -> Tuple[int | None, list[tuple[int, int, str]]]:
    expected_cols = None
    corrupt_lines: list[tuple[int, int, str]] = []

    with csv_path.open("r", encoding="utf-8", errors="replace") as f:
        for i, line in enumerate(f, start=1):
            cols = line.count(",") + 1
            if expected_cols is None:
                expected_cols = cols
            elif cols != expected_cols:
                corrupt_lines.append((i, cols, line.strip()))

    return expected_cols, corrupt_lines


def _auto_repair_csv(csv_path: Path) -> Path:
    with csv_path.open("r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    repaired_lines = []
    for ln in lines:
        ln = ln.replace("\x00", "")
        # if odd number of quotes, strip them to avoid poison rows
        if ln.count('"') % 2 != 0:
            ln = ln.replace('"', "")
        repaired_lines.append(ln)

    repaired_path = csv_path.with_suffix(".repaired.csv")
    with repaired_path.open("w", encoding="utf-8") as f:
        f.writelines(repaired_lines)

    return repaired_path


def load_csv_with_repair(csv_path: Path) -> Tuple[pd.DataFrame, Path]:
    """
    Load CSV robustly:
      - Diagnose corrupt lines
      - Generate .repaired.csv if needed
      - Ensure _index exists and is numeric
    Returns (df, used_path).
    """
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV not found at {csv_path}")

    print(f"📥 Loading CSV: {csv_path}")

    try:
        raw = pd.read_csv(
            csv_path,
            dtype=str,
            keep_default_na=False,
            quotechar='"',
            escapechar='\\',
        )
        used_path = csv_path
    except Exception as e:
        print("\n" + "=" * 80)
        print("❌ CSV PARSE FAILURE — DIAGNOSTICS".center(80))
        print("=" * 80 + "\n")
        print(f"📄 File: {csv_path}")
        print(f"⚠️ Pandas Error: {e}\n")

        expected_cols, corrupt_lines = _diagnose_bad_lines(csv_path)

        if corrupt_lines:
            print(f"❗ Found {len(corrupt_lines)} malformed line(s):\n")
            for line_no, col_count, text in corrupt_lines[:10]:
                print(f"  • Line {line_no}: {col_count} columns (expected {expected_cols})")
                preview = text[:200]
                if len(text) > 200:
                    preview += "..."
                print(f"    → {preview}\n")
            if len(corrupt_lines) > 10:
                print(f"  …and {len(corrupt_lines) - 10} more.\n")
        else:
            print("⚠️ No obvious malformed rows; likely quoting/escape issue.\n")

        print("=" * 80)
        print("🛠 Attempting to auto-repair CSV…")
        repaired_path = _auto_repair_csv(csv_path)
        print(f"📄 Wrote repaired candidate CSV → {repaired_path.name}")

        raw = pd.read_csv(
            repaired_path,
            dtype=str,
            keep_default_na=False,
            on_bad_lines="skip",
            engine="python",
        )
        used_path = repaired_path
        print("✅ Loaded repaired CSV successfully.")

    # Ensure _index exists:
    if "_index" not in raw.columns:
        raw["_index"] = list(range(len(raw)))
    else:
        try:
            raw["_index"] = raw["_index"].astype(int)
        except Exception:
            raw["_index"] = list(range(len(raw)))

    df_clean = sanitize_csv(raw)
    print(f"✅ Loaded CSV with {len(df_clean)} rows from {used_path.name}, "
          f"columns={list(df_clean.columns)}")
    return df_clean, used_path