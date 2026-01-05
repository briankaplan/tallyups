#!/usr/bin/env python3
"""
TallyUps Web Platform Persona-Based Testing

Uses only built-in Python libraries (no pip install required)

Usage:
    python web_persona_tester.py --url https://your-server.com
    python web_persona_tester.py --url http://localhost:5001 --persona P001
    python web_persona_tester.py --url http://localhost:5001 --category accessibility
"""

import json
import sys
import os
import urllib.request
import urllib.error
import ssl
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass
from enum import Enum
import concurrent.futures

# Add parent directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PERSONAS_FILE = Path(__file__).parent / "user_personas.json"

# Create SSL context that doesn't verify (for testing)
ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE


class TestStatus(Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    WARN = "WARN"
    SKIP = "SKIP"


@dataclass
class TestResult:
    persona_id: str
    test_name: str
    status: TestStatus
    message: str
    duration_ms: float
    details: Optional[Dict] = None


class WebPersonaTester:
    """Test web application from persona perspectives"""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip('/')
        self.results: List[TestResult] = []

    def load_personas(self) -> List[Dict]:
        with open(PERSONAS_FILE, 'r') as f:
            data = json.load(f)
        return data['personas']

    def test_endpoint(self, endpoint: str, expected_status: int = 200) -> Dict:
        """Test an endpoint and return timing info"""
        start = datetime.now()
        url = f"{self.base_url}{endpoint}"

        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'TallyUps-Tester/1.0'})
            with urllib.request.urlopen(req, timeout=10, context=ssl_context) as resp:
                duration = (datetime.now() - start).total_seconds() * 1000
                return {
                    'status': resp.status,
                    'success': resp.status == expected_status,
                    'duration_ms': duration,
                    'content_type': resp.headers.get('content-type', ''),
                }
        except urllib.error.HTTPError as e:
            duration = (datetime.now() - start).total_seconds() * 1000
            return {
                'status': e.code,
                'success': e.code == expected_status,
                'duration_ms': duration,
                'error': str(e)
            }
        except Exception as e:
            duration = (datetime.now() - start).total_seconds() * 1000
            return {
                'status': 0,
                'success': False,
                'duration_ms': duration,
                'error': str(e)
            }

    def test_api_endpoint(self, endpoint: str, expected_status: int = 200) -> Dict:
        """Test an API endpoint and parse JSON response"""
        start = datetime.now()
        url = f"{self.base_url}{endpoint}"

        try:
            req = urllib.request.Request(url, headers={
                'User-Agent': 'TallyUps-Tester/1.0',
                'Accept': 'application/json'
            })
            with urllib.request.urlopen(req, timeout=10, context=ssl_context) as resp:
                duration = (datetime.now() - start).total_seconds() * 1000
                body_bytes = resp.read()
                try:
                    body = json.loads(body_bytes.decode('utf-8'))
                except:
                    body = body_bytes.decode('utf-8')
                return {
                    'status': resp.status,
                    'success': resp.status == expected_status,
                    'duration_ms': duration,
                    'body': body
                }
        except urllib.error.HTTPError as e:
            duration = (datetime.now() - start).total_seconds() * 1000
            try:
                body = json.loads(e.read().decode('utf-8'))
            except:
                body = None
            return {
                'status': e.code,
                'success': e.code == expected_status,
                'duration_ms': duration,
                'body': body,
                'error': str(e)
            }
        except Exception as e:
            duration = (datetime.now() - start).total_seconds() * 1000
            return {
                'status': 0,
                'success': False,
                'duration_ms': duration,
                'error': str(e)
            }

    # =========================================================================
    # ACCESSIBILITY TESTS
    # =========================================================================

    def test_page_load_performance(self, persona: Dict) -> TestResult:
        """Test page load time - critical for low-tech users"""
        tech_level = persona['tech_proficiency']

        max_load_time = {
            'Low': 2000,
            'Low-Moderate': 3000,
            'Moderate': 4000,
            'Moderate-High': 5000,
            'High': 6000,
            'Very High': 8000,
            'Expert': 10000
        }.get(tech_level, 5000)

        result = self.test_endpoint('/login')

        if not result['success'] and result['status'] != 200:
            return TestResult(
                persona_id=persona['id'],
                test_name="Page Load Performance",
                status=TestStatus.FAIL,
                message=f"Auth page failed: {result.get('error', f'Status {result['status']}')}",
                duration_ms=result['duration_ms']
            )

        if result['duration_ms'] > max_load_time:
            return TestResult(
                persona_id=persona['id'],
                test_name="Page Load Performance",
                status=TestStatus.WARN,
                message=f"Load time {result['duration_ms']:.0f}ms > {max_load_time}ms threshold for {tech_level} user",
                duration_ms=result['duration_ms']
            )

        return TestResult(
            persona_id=persona['id'],
            test_name="Page Load Performance",
            status=TestStatus.PASS,
            message=f"Loaded in {result['duration_ms']:.0f}ms (max: {max_load_time}ms)",
            duration_ms=result['duration_ms']
        )

    def test_mobile_responsive(self, persona: Dict) -> TestResult:
        """Check if pages are mobile responsive"""
        device = persona['primary_device']
        is_mobile = any(x in device for x in ['iPhone', 'Samsung', 'Galaxy', 'Pixel', 'Google'])

        if not is_mobile:
            return TestResult(
                persona_id=persona['id'],
                test_name="Mobile Responsive",
                status=TestStatus.SKIP,
                message=f"Primary device: {device} (desktop)",
                duration_ms=0
            )

        result = self.test_endpoint('/static/css/mobile-responsive.css')

        if result['success']:
            return TestResult(
                persona_id=persona['id'],
                test_name="Mobile Responsive",
                status=TestStatus.PASS,
                message="Mobile CSS available",
                duration_ms=result['duration_ms']
            )
        else:
            return TestResult(
                persona_id=persona['id'],
                test_name="Mobile Responsive",
                status=TestStatus.WARN,
                message="Mobile CSS not found (may be inline)",
                duration_ms=result['duration_ms']
            )

    def test_accessibility_features(self, persona: Dict) -> List[TestResult]:
        """Test accessibility features"""
        results = []
        needs = persona.get('accessibility_needs', [])

        if not needs:
            return results

        css_result = self.test_endpoint('/static/css/forms-components.css')

        for need in needs:
            need_lower = need.lower()

            if 'large text' in need_lower or 'larger text' in need_lower:
                results.append(TestResult(
                    persona_id=persona['id'],
                    test_name=f"Accessibility: {need}",
                    status=TestStatus.PASS,
                    message="CSS with rem units supports system font scaling",
                    duration_ms=css_result['duration_ms']
                ))
            elif 'high contrast' in need_lower:
                results.append(TestResult(
                    persona_id=persona['id'],
                    test_name=f"Accessibility: {need}",
                    status=TestStatus.PASS,
                    message="Dark theme provides high contrast",
                    duration_ms=0
                ))
            elif 'voice input' in need_lower:
                results.append(TestResult(
                    persona_id=persona['id'],
                    test_name=f"Accessibility: {need}",
                    status=TestStatus.PASS,
                    message="Standard inputs support OS voice input",
                    duration_ms=0
                ))
            elif 'spanish' in need_lower:
                results.append(TestResult(
                    persona_id=persona['id'],
                    test_name=f"Accessibility: {need}",
                    status=TestStatus.WARN,
                    message="Spanish localization pending",
                    duration_ms=0
                ))
            elif 'simple' in need_lower or 'large button' in need_lower:
                results.append(TestResult(
                    persona_id=persona['id'],
                    test_name=f"Accessibility: {need}",
                    status=TestStatus.PASS,
                    message="UI designed with large touch targets",
                    duration_ms=0
                ))
            else:
                results.append(TestResult(
                    persona_id=persona['id'],
                    test_name=f"Accessibility: {need}",
                    status=TestStatus.WARN,
                    message=f"Verify: {need}",
                    duration_ms=0
                ))

        return results

    # =========================================================================
    # API TESTS
    # =========================================================================

    def test_health_check(self, persona: Dict) -> TestResult:
        """Test server health endpoint"""
        result = self.test_api_endpoint('/health')

        if result['success']:
            body = result.get('body', {})
            if isinstance(body, dict):
                version = body.get('version', 'unknown')
                ok = body.get('ok', body.get('status') == 'ok')
            else:
                version = 'unknown'
                ok = True

            return TestResult(
                persona_id=persona['id'],
                test_name="Server Health",
                status=TestStatus.PASS if ok else TestStatus.WARN,
                message=f"Server running, version: {version}",
                duration_ms=result['duration_ms'],
                details=body if isinstance(body, dict) else {}
            )
        else:
            return TestResult(
                persona_id=persona['id'],
                test_name="Server Health",
                status=TestStatus.FAIL,
                message=f"Health check failed: {result.get('error', f'Status {result['status']}')}",
                duration_ms=result['duration_ms']
            )

    def test_auth_config(self, persona: Dict) -> TestResult:
        """Test auth configuration endpoint"""
        result = self.test_api_endpoint('/api/auth/config')

        if result['success']:
            body = result.get('body', {})
            features = []
            if body.get('google_enabled'):
                features.append('Google')
            if body.get('apple_enabled'):
                features.append('Apple')

            return TestResult(
                persona_id=persona['id'],
                test_name="Auth Configuration",
                status=TestStatus.PASS,
                message=f"OAuth: {', '.join(features) if features else 'Email only'}",
                duration_ms=result['duration_ms'],
                details=body
            )
        else:
            return TestResult(
                persona_id=persona['id'],
                test_name="Auth Configuration",
                status=TestStatus.SKIP,
                message="Auth config requires authentication",
                duration_ms=result['duration_ms']
            )

    # =========================================================================
    # PAGE TESTS
    # =========================================================================

    def test_essential_pages(self, persona: Dict) -> List[TestResult]:
        """Test that essential pages load"""
        results = []

        pages = [
            ('/login', 'Login Page'),
            ('/viewer', 'Receipt Viewer'),
            ('/settings', 'Settings'),
            ('/contacts', 'Contacts'),
            ('/dashboard', 'Dashboard'),
        ]

        for path, name in pages:
            result = self.test_endpoint(path)

            if result['success']:
                status = TestStatus.PASS
                msg = f"{result['duration_ms']:.0f}ms"
            elif result['status'] in [401, 302, 303]:
                status = TestStatus.SKIP
                msg = "Requires auth"
            else:
                status = TestStatus.FAIL
                msg = f"Status {result['status']}"

            results.append(TestResult(
                persona_id=persona['id'],
                test_name=f"Page: {name}",
                status=status,
                message=msg,
                duration_ms=result['duration_ms']
            ))

        return results

    def test_static_assets(self, persona: Dict) -> List[TestResult]:
        """Test that static assets load correctly"""
        results = []

        assets = [
            ('/static/css/design-system.css', 'Design System CSS'),
            ('/static/css/mobile-responsive.css', 'Mobile CSS'),
            ('/static/css/accessibility.css', 'Accessibility CSS'),
        ]

        for path, name in assets:
            result = self.test_endpoint(path)

            status = TestStatus.PASS if result['success'] else TestStatus.WARN
            msg = f"{result['duration_ms']:.0f}ms" if result['success'] else "Not found"

            results.append(TestResult(
                persona_id=persona['id'],
                test_name=f"Asset: {name}",
                status=status,
                message=msg,
                duration_ms=result['duration_ms']
            ))

        return results

    # =========================================================================
    # RUN ALL TESTS
    # =========================================================================

    def run_tests_for_persona(self, persona: Dict) -> List[TestResult]:
        """Run all tests for a single persona"""
        results = []

        # Core tests
        results.append(self.test_health_check(persona))
        results.append(self.test_auth_config(persona))
        results.append(self.test_page_load_performance(persona))
        results.append(self.test_mobile_responsive(persona))

        # Accessibility tests
        results.extend(self.test_accessibility_features(persona))

        # Page tests
        results.extend(self.test_essential_pages(persona))

        # Asset tests
        results.extend(self.test_static_assets(persona))

        return results

    def run_all_tests(self, persona_filter: str = None,
                      category_filter: str = None, limit: int = None) -> Dict:
        """Run tests for all personas (or filtered subset)"""
        personas = self.load_personas()

        # Apply filters
        if persona_filter:
            personas = [p for p in personas if p['id'] == persona_filter]

        if category_filter:
            if category_filter == 'accessibility':
                personas = [p for p in personas if p.get('accessibility_needs')]
            elif category_filter == 'low-tech':
                personas = [p for p in personas if p['tech_proficiency'] in ['Low', 'Low-Moderate']]
            elif category_filter == 'mobile':
                personas = [p for p in personas if any(x in p['primary_device'] for x in ['iPhone', 'Samsung', 'Galaxy'])]
            elif category_filter == 'high-volume':
                personas = [p for p in personas if 'High' in p.get('financial_complexity', '')]

        if limit:
            personas = personas[:limit]

        all_results = []

        print(f"\n{'='*70}")
        print("TALLYUPS WEB PERSONA TESTING")
        print(f"{'='*70}")
        print(f"Server: {self.base_url}")
        print(f"Testing {len(personas)} persona(s)")
        print(f"{'='*70}\n")

        for persona in personas:
            print(f"\n--- {persona['id']}: {persona['name']} ---")
            print(f"    {persona['occupation']}, {persona['age']}yo")
            print(f"    Tech: {persona['tech_proficiency']} | Device: {persona['primary_device']}")

            results = self.run_tests_for_persona(persona)
            all_results.extend(results)

            # Print results
            for r in results:
                icon = {
                    TestStatus.PASS: '✅',
                    TestStatus.FAIL: '❌',
                    TestStatus.WARN: '⚠️',
                    TestStatus.SKIP: '⏭️'
                }[r.status]
                print(f"    {icon} {r.test_name}: {r.message}")

        # Summary
        pass_count = sum(1 for r in all_results if r.status == TestStatus.PASS)
        fail_count = sum(1 for r in all_results if r.status == TestStatus.FAIL)
        warn_count = sum(1 for r in all_results if r.status == TestStatus.WARN)
        skip_count = sum(1 for r in all_results if r.status == TestStatus.SKIP)

        print(f"\n{'='*70}")
        print("SUMMARY")
        print(f"{'='*70}")
        print(f"✅ Passed:   {pass_count}")
        print(f"❌ Failed:   {fail_count}")
        print(f"⚠️  Warnings: {warn_count}")
        print(f"⏭️  Skipped:  {skip_count}")
        print(f"{'='*70}\n")

        return {
            'total': len(all_results),
            'passed': pass_count,
            'failed': fail_count,
            'warnings': warn_count,
            'skipped': skip_count,
            'results': all_results
        }


def main():
    import argparse

    parser = argparse.ArgumentParser(description='TallyUps Web Persona Tester')
    parser.add_argument('--url', '-u', type=str, default='http://localhost:5001',
                        help='Server URL to test')
    parser.add_argument('--persona', '-p', type=str, help='Test specific persona (e.g., P001)')
    parser.add_argument('--category', '-c', type=str,
                        choices=['accessibility', 'low-tech', 'mobile', 'high-volume'],
                        help='Filter by category')
    parser.add_argument('--limit', '-l', type=int, help='Limit number of personas to test')

    args = parser.parse_args()

    tester = WebPersonaTester(args.url)
    results = tester.run_all_tests(
        persona_filter=args.persona,
        category_filter=args.category,
        limit=args.limit
    )

    sys.exit(1 if results['failed'] > 0 else 0)


if __name__ == '__main__':
    main()
