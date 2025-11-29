#!/usr/bin/env python3
"""
Email HTML Screenshot Service
Takes HTML email content and creates a clean screenshot of the receipt portion
"""
from pathlib import Path
import re
import hashlib
from playwright.sync_api import sync_playwright
import base64

def extract_receipt_html(full_html: str) -> str:
    """
    Extract just the receipt/charges portion from email HTML.
    Looks for tables with monetary amounts, summary sections, etc.
    """
    # Try to find the receipt table/section
    # Common patterns: "Summary of Charges", "Total", "$" signs, tables

    # Simple approach: find tables with $ amounts
    # More sophisticated: look for specific keywords

    # For now, return the full HTML but could be refined to extract just the receipt section
    return full_html


def screenshot_email_html(html_content: str, output_path: Path, viewport_width: int = 800) -> bool:
    """
    Use Playwright to screenshot HTML email content.

    Intelligently finds and crops to just the receipt/charges section.
    Returns True if successful, False otherwise.
    """
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={'width': viewport_width, 'height': 2400},  # Taller viewport for long emails
                device_scale_factor=2  # Retina quality
            )
            page = context.new_page()

            # Load HTML content
            page.set_content(html_content)

            # Wait for content to render
            page.wait_for_load_state('networkidle')

            # Smart receipt section detection - prioritize by specificity
            # Try multiple strategies to find JUST the receipt portion
            screenshot_taken = False

            try:
                # STRATEGY 1: Find "Summary of Charges" heading + immediately following table
                summary_selectors = [
                    ':text("Summary of Charges")',
                    ':text("Summary of charges")',
                    ':text("SUMMARY OF CHARGES")',
                ]

                for selector in summary_selectors:
                    try:
                        heading = page.locator(selector).first
                        if heading.is_visible():
                            print(f"✅ Found '{selector}' heading")

                            # APPROACH A: Try to find the next table element after this heading
                            # This should be the charges table, not a parent container
                            try:
                                # Look for following table (any descendant or sibling after this heading)
                                following_table = heading.locator('xpath=following::table[1]')
                                if following_table.is_visible():
                                    text = following_table.text_content()
                                    dollar_count = text.count('$')

                                    # Verify this is the charges table (should have multiple amounts, not too much text)
                                    if dollar_count >= 2 and len(text) < 2000:  # Charges table should be concise
                                        print(f"  → Found following table with {dollar_count} amounts, {len(text)} chars")
                                        following_table.screenshot(path=str(output_path))
                                        screenshot_taken = True
                                        print(f"📸 Captured: Charges table after heading ({dollar_count} amounts)")
                                        break
                            except Exception as e:
                                print(f"  → Following table approach failed: {e}")

                            # APPROACH B: If no following table, try parent's next sibling table
                            if not screenshot_taken:
                                try:
                                    parent_sibling_table = heading.locator('xpath=../following-sibling::*//table[1]')
                                    if parent_sibling_table.is_visible():
                                        text = parent_sibling_table.text_content()
                                        dollar_count = text.count('$')
                                        if dollar_count >= 2 and len(text) < 2000:
                                            print(f"  → Found sibling table with {dollar_count} amounts")
                                            parent_sibling_table.screenshot(path=str(output_path))
                                            screenshot_taken = True
                                            print(f"📸 Captured: Charges table after parent ({dollar_count} amounts)")
                                            break
                                except Exception as e:
                                    print(f"  → Sibling table approach failed: {e}")

                            if screenshot_taken:
                                break
                    except Exception as e:
                        print(f"  → Error with selector {selector}: {e}")
                        continue

                # STRATEGY 2: Find table with monetary amounts AND specific keywords
                if not screenshot_taken:
                    table_selectors = [
                        'table:has-text("Estimated Total")',
                        'table:has-text("Total:")',
                        'table:has-text("Room Type")',
                        'table:has-text("Number of Rooms")',
                        'table:has-text("Daily Rates")',
                    ]

                    for selector in table_selectors:
                        try:
                            table = page.locator(selector).first
                            if table.is_visible():
                                # Check if table contains money amounts
                                text = table.text_content()
                                if '$' in text and any(keyword in text.lower() for keyword in ['total', 'charges', 'rate', 'tax']):
                                    table.screenshot(path=str(output_path))
                                    screenshot_taken = True
                                    print(f"📸 Captured: Receipt table with amounts")
                                    break
                        except:
                            continue

                # STRATEGY 3: Find any table with multiple $ amounts (likely a receipt)
                if not screenshot_taken:
                    try:
                        tables = page.locator('table').all()
                        for table in tables:
                            if table.is_visible():
                                text = table.text_content()
                                # Count dollar signs - receipt tables have multiple amounts
                                dollar_count = text.count('$')
                                if dollar_count >= 3:  # At least 3 monetary values
                                    table.screenshot(path=str(output_path))
                                    screenshot_taken = True
                                    print(f"📸 Captured: Table with {dollar_count} amounts")
                                    break
                    except:
                        pass

                # STRATEGY 4: Find element with "charges" or "invoice" in class/id
                if not screenshot_taken:
                    receipt_containers = [
                        '[class*="charges"]',
                        '[class*="summary"]',
                        '[class*="receipt"]',
                        '[class*="invoice"]',
                        '[id*="charges"]',
                        '[id*="summary"]',
                    ]

                    for selector in receipt_containers:
                        try:
                            element = page.locator(selector).first
                            if element.is_visible():
                                text = element.text_content()
                                if '$' in text and len(text) < 3000:  # Not too large
                                    element.screenshot(path=str(output_path))
                                    screenshot_taken = True
                                    print(f"📸 Captured: Receipt container")
                                    break
                        except:
                            continue

                # FALLBACK: Screenshot full page (but this is a last resort)
                if not screenshot_taken:
                    print(f"⚠️ No specific receipt section found, capturing full page")
                    page.screenshot(path=str(output_path), full_page=True)

            except Exception as e:
                print(f"⚠️ Error in smart detection: {e}, falling back to full page")
                page.screenshot(path=str(output_path), full_page=True)

            browser.close()
            return True

    except Exception as e:
        print(f"⚠️ Screenshot error: {e}")
        return False


def create_email_receipt_screenshot(
    html_content: str,
    email_subject: str,
    message_id: str,
    receipts_dir: Path
) -> Path | None:
    """
    Create a screenshot from email HTML and save to receipts directory.

    Returns path to screenshot file, or None if failed.
    """
    # Create unique filename based on message ID
    safe_subject = re.sub(r'[^\w\s-]', '', email_subject)[:50]
    safe_subject = re.sub(r'[-\s]+', '_', safe_subject)

    # Use message ID hash for uniqueness
    msg_hash = hashlib.md5(message_id.encode()).hexdigest()[:8]

    filename = f"email_{safe_subject}_{msg_hash}.png"
    output_path = receipts_dir / filename

    # Skip if already exists
    if output_path.exists():
        print(f"📸 Email screenshot already exists: {filename}")
        return output_path

    print(f"📸 Creating email screenshot: {filename}")

    # Extract receipt portion (or use full HTML)
    receipt_html = extract_receipt_html(html_content)

    # Create screenshot
    success = screenshot_email_html(receipt_html, output_path)

    if success and output_path.exists():
        print(f"✅ Screenshot saved: {filename}")
        return output_path
    else:
        print(f"❌ Screenshot failed")
        return None
