#!/usr/bin/env python3
"""
HTML Validation Script for Tallyups
Checks for common issues in HTML files without needing a running server.
"""

import os
import re
import sys
from pathlib import Path
from collections import defaultdict

# ANSI colors
GREEN = '\033[0;32m'
RED = '\033[0;31m'
YELLOW = '\033[1;33m'
NC = '\033[0m'

class HTMLValidator:
    def __init__(self, root_dir):
        self.root_dir = Path(root_dir)
        self.issues = defaultdict(list)
        self.passed = 0
        self.failed = 0

    def check_file(self, filepath):
        """Check a single HTML file for common issues."""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            self.issues[filepath].append(f"Could not read file: {e}")
            return

        filename = os.path.basename(filepath)

        # Check for duplicate CSS imports
        css_imports = re.findall(r'<link[^>]*href=["\']([^"\']*\.css)["\']', content)
        css_counts = defaultdict(int)
        for css in css_imports:
            css_counts[css] += 1

        for css, count in css_counts.items():
            if count > 1:
                self.issues[filepath].append(f"Duplicate CSS import: {css} (found {count} times)")

        # Check for duplicate JS imports
        js_imports = re.findall(r'<script[^>]*src=["\']([^"\']*\.js)["\']', content)
        js_counts = defaultdict(int)
        for js in js_imports:
            js_counts[js] += 1

        for js, count in js_counts.items():
            if count > 1:
                self.issues[filepath].append(f"Duplicate JS import: {js} (found {count} times)")

        # Check for design-system.css
        if 'design-system.css' not in content:
            # Skip template files that don't need it
            if not any(skip in filename for skip in ['privacy', 'terms', 'demo', 'cursor_receipt', 'receipt_']):
                self.issues[filepath].append("Missing design-system.css")

        # Check for design-system.js (theme management)
        if 'design-system.js' not in content:
            # Only flag main app pages
            if any(page in filename for page in ['dashboard', 'viewer', 'library', 'settings', 'incoming', 'scanner', 'swipe', 'uploader', 'converter', 'review', 'report', 'contacts', 'bank']):
                self.issues[filepath].append("Missing design-system.js (theme flash prevention)")

        # Check for proper doctype
        if not content.strip().lower().startswith('<!doctype html>'):
            self.issues[filepath].append("Missing or incorrect DOCTYPE declaration")

        # Check for charset
        if '<meta charset' not in content.lower():
            self.issues[filepath].append("Missing charset meta tag")

        # Check for viewport
        if 'viewport' not in content.lower():
            self.issues[filepath].append("Missing viewport meta tag")

        # Check for unclosed tags (basic check)
        open_tags = len(re.findall(r'<(script|style|div|span|a|button)[^>]*[^/]>', content, re.I))
        close_tags = len(re.findall(r'</(script|style|div|span|a|button)>', content, re.I))
        # This is a rough check - HTML parsers do this better
        if abs(open_tags - close_tags) > 5:  # Allow some tolerance
            self.issues[filepath].append(f"Potential unclosed tags (open: {open_tags}, close: {close_tags})")

        # Check for multiple <html> or <head> or <body> tags (exact match, not <header>)
        for tag in ['html', 'body']:
            count = len(re.findall(f'<{tag}[^>]*>', content, re.I))
            if count > 1:
                self.issues[filepath].append(f"Multiple <{tag}> tags found ({count})")
        # Special handling for <head> to not match <header>
        head_count = len(re.findall(r'<head\s*>', content, re.I)) + len(re.findall(r'<head\s+[^>]*>', content, re.I))
        if head_count > 1:
            self.issues[filepath].append(f"Multiple <head> tags found ({head_count})")

        # Check for broken image/script paths (skip JS template literals like ${var})
        broken_paths = re.findall(r'(src|href)=["\'](?!/|http|data:|#|\$\{)([^"\']+)["\']', content)
        for attr, path in broken_paths:
            # Skip template literals and Jinja2 templates
            if path.startswith(('/', 'http', 'data:', '#', 'mailto:', 'tel:', '${', '{{', '{%')):
                continue
            if '${' in path or '{{' in path:
                continue
            # Could be relative path, check if file exists
            full_path = self.root_dir / path
            if not full_path.exists():
                self.issues[filepath].append(f"Potentially broken path: {path}")

    def validate_all(self):
        """Validate all HTML files in the project."""
        html_files = []

        # Root level HTML files
        for f in self.root_dir.glob('*.html'):
            if f.name not in ['anthropic_receipt_new.html', 'suno_receipt_72.html']:  # Skip generated receipts
                html_files.append(f)

        # Templates
        for f in (self.root_dir / 'templates').glob('*.html'):
            html_files.append(f)

        print("=" * 50)
        print("Tallyups HTML Validation")
        print("=" * 50)
        print(f"Checking {len(html_files)} HTML files...")
        print()

        for filepath in sorted(html_files):
            self.check_file(filepath)

        # Print results
        print("=== Results ===")
        print()

        for filepath, file_issues in sorted(self.issues.items()):
            print(f"{RED}[ISSUES]{NC} {os.path.basename(filepath)}")
            for issue in file_issues:
                print(f"  - {issue}")
                self.failed += 1
            print()

        # Files without issues
        clean_files = [f for f in html_files if f not in self.issues]
        for filepath in clean_files:
            print(f"{GREEN}[CLEAN]{NC} {os.path.basename(filepath)}")
            self.passed += 1

        print()
        print("=" * 50)
        print(f"Summary: {self.passed} clean files, {len(self.issues)} files with issues ({self.failed} total issues)")
        print("=" * 50)

        return len(self.issues) == 0


if __name__ == '__main__':
    root_dir = Path(__file__).parent.parent
    validator = HTMLValidator(root_dir)
    success = validator.validate_all()
    sys.exit(0 if success else 1)
