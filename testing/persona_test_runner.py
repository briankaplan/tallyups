#!/usr/bin/env python3
"""
TallyUps Persona-Based User Testing Framework

This script loads the 50 user personas and provides tools for:
1. Generating test scenarios from each persona's perspective
2. Creating user journey tests
3. Identifying potential pain points
4. Generating accessibility test cases
5. Creating localization test requirements

Usage:
    python persona_test_runner.py --list                    # List all personas
    python persona_test_runner.py --persona P001           # Get details for one persona
    python persona_test_runner.py --category accessibility  # Filter by category
    python persona_test_runner.py --generate-tests         # Generate test cases
    python persona_test_runner.py --analyze                # Analyze test coverage
"""

import json
import os
from pathlib import Path
from typing import List, Dict, Optional
from collections import defaultdict

# Load personas
PERSONAS_FILE = Path(__file__).parent / "user_personas.json"


def load_personas() -> Dict:
    """Load personas from JSON file"""
    with open(PERSONAS_FILE, 'r') as f:
        return json.load(f)


def list_personas(personas: List[Dict], verbose: bool = False) -> None:
    """List all personas with basic info"""
    print("\n" + "="*80)
    print("TALLYUPS USER TESTING PERSONAS")
    print("="*80 + "\n")

    for p in personas:
        tech = p.get('tech_proficiency', 'Unknown')
        tech_emoji = {'Expert': '🔥', 'Very High': '💻', 'High': '📱',
                      'Moderate-High': '📊', 'Moderate': '👍',
                      'Low-Moderate': '🔰', 'Low': '📖'}.get(tech, '❓')

        print(f"{p['id']}: {p['name']}")
        print(f"    {p['occupation']}, {p['age']}yo, {p['location']}")
        print(f"    Tech: {tech_emoji} {tech} | Device: {p['primary_device']}")

        if verbose:
            print(f"    Industry: {p['industry']}")
            print(f"    Income: {p['income']}")
            print(f"    Pain Points: {', '.join(p['pain_points'][:2])}...")
        print()


def get_persona_detail(personas: List[Dict], persona_id: str) -> None:
    """Get detailed info for a specific persona"""
    persona = next((p for p in personas if p['id'] == persona_id), None)

    if not persona:
        print(f"Persona {persona_id} not found")
        return

    print("\n" + "="*80)
    print(f"PERSONA: {persona['name']} ({persona['id']})")
    print("="*80)

    print(f"\n📋 DEMOGRAPHICS")
    print(f"   Age: {persona['age']} | Gender: {persona['gender']}")
    print(f"   Location: {persona['location']}")
    print(f"   Education: {persona['education']}")
    print(f"   Income: {persona['income']}")

    print(f"\n💼 PROFESSIONAL")
    print(f"   Occupation: {persona['occupation']}")
    print(f"   Industry: {persona['industry']}")
    print(f"   Financial Complexity: {persona['financial_complexity']}")

    print(f"\n📱 TECHNOLOGY")
    print(f"   Tech Proficiency: {persona['tech_proficiency']}")
    print(f"   Primary Device: {persona['primary_device']}")
    print(f"   Secondary Device: {persona['secondary_device']}")

    print(f"\n🧠 PERSONALITY")
    print(f"   Traits: {', '.join(persona['personality'])}")
    print(f"   Values: {', '.join(persona['values'])}")
    print(f"   Language: {persona['language']}")

    print(f"\n😤 PAIN POINTS")
    for pp in persona['pain_points']:
        print(f"   • {pp}")

    print(f"\n🎯 GOALS")
    for goal in persona['goals']:
        print(f"   • {goal}")

    print(f"\n📖 SCENARIO")
    print(f"   {persona['scenario']}")

    print(f"\n🔬 TEST FOCUS AREAS")
    for tf in persona['test_focus']:
        print(f"   • {tf}")

    if persona.get('accessibility_needs'):
        print(f"\n♿ ACCESSIBILITY NEEDS")
        for need in persona['accessibility_needs']:
            print(f"   • {need}")

    print()


def analyze_personas(personas: List[Dict]) -> None:
    """Analyze persona distribution and coverage"""

    print("\n" + "="*80)
    print("PERSONA ANALYSIS & TEST COVERAGE")
    print("="*80)

    # Tech proficiency distribution
    tech_dist = defaultdict(int)
    for p in personas:
        tech_dist[p['tech_proficiency']] += 1

    print("\n📱 TECH PROFICIENCY DISTRIBUTION")
    for tech, count in sorted(tech_dist.items(), key=lambda x: x[1], reverse=True):
        bar = "█" * count
        print(f"   {tech:15} {bar} ({count})")

    # Industry distribution
    industry_dist = defaultdict(int)
    for p in personas:
        industry_dist[p['industry']] += 1

    print("\n🏢 TOP INDUSTRIES")
    for ind, count in sorted(industry_dist.items(), key=lambda x: x[1], reverse=True)[:10]:
        print(f"   {ind}: {count}")

    # Age distribution
    ages = [p['age'] for p in personas]
    print(f"\n👥 AGE DISTRIBUTION")
    print(f"   Range: {min(ages)} - {max(ages)}")
    print(f"   Average: {sum(ages)/len(ages):.1f}")
    age_brackets = {'18-30': 0, '31-45': 0, '46-60': 0, '60+': 0}
    for age in ages:
        if age <= 30: age_brackets['18-30'] += 1
        elif age <= 45: age_brackets['31-45'] += 1
        elif age <= 60: age_brackets['46-60'] += 1
        else: age_brackets['60+'] += 1
    for bracket, count in age_brackets.items():
        bar = "█" * count
        print(f"   {bracket:10} {bar} ({count})")

    # Accessibility needs
    accessibility_personas = [p for p in personas if p.get('accessibility_needs')]
    print(f"\n♿ ACCESSIBILITY COVERAGE")
    print(f"   Personas with accessibility needs: {len(accessibility_personas)}")
    all_needs = []
    for p in accessibility_personas:
        all_needs.extend(p['accessibility_needs'])
    need_counts = defaultdict(int)
    for need in all_needs:
        need_counts[need] += 1
    for need, count in sorted(need_counts.items(), key=lambda x: x[1], reverse=True):
        print(f"   • {need}: {count} personas")

    # Language coverage
    languages = set()
    for p in personas:
        languages.add(p['language'].split(' ')[0].replace('(primary),', '').strip())
    print(f"\n🌍 LANGUAGES REPRESENTED")
    print(f"   {', '.join(sorted(languages))}")

    # Device distribution
    ios_count = sum(1 for p in personas if 'iPhone' in p['primary_device'])
    android_count = sum(1 for p in personas if 'Samsung' in p['primary_device'] or 'Galaxy' in p['primary_device'] or 'Google' in p['primary_device'])
    print(f"\n📱 DEVICE PLATFORMS")
    print(f"   iOS: {ios_count} ({ios_count/len(personas)*100:.0f}%)")
    print(f"   Android: {android_count} ({android_count/len(personas)*100:.0f}%)")

    # Test focus areas
    all_focus = []
    for p in personas:
        all_focus.extend(p['test_focus'])
    focus_counts = defaultdict(int)
    for focus in all_focus:
        focus_counts[focus] += 1

    print(f"\n🔬 TOP TEST FOCUS AREAS")
    for focus, count in sorted(focus_counts.items(), key=lambda x: x[1], reverse=True)[:15]:
        print(f"   • {focus}: {count} personas")


def generate_test_cases(personas: List[Dict]) -> None:
    """Generate test cases from persona insights"""

    print("\n" + "="*80)
    print("GENERATED TEST CASES")
    print("="*80)

    # Group test cases by category
    test_categories = {
        'Accessibility': [],
        'Onboarding': [],
        'Receipt Capture': [],
        'Expense Categorization': [],
        'Multi-User/Team': [],
        'Reports & Export': [],
        'Integration': [],
        'Mobile UX': [],
        'Internationalization': [],
        'Performance': []
    }

    for p in personas:
        # Accessibility tests
        if p.get('accessibility_needs'):
            for need in p['accessibility_needs']:
                test_categories['Accessibility'].append({
                    'persona': p['id'],
                    'test': f"Verify {need} works for {p['name']} ({p['age']}yo, {p['tech_proficiency']} tech)",
                    'priority': 'High'
                })

        # Tech proficiency based onboarding tests
        if p['tech_proficiency'] in ['Low', 'Low-Moderate']:
            test_categories['Onboarding'].append({
                'persona': p['id'],
                'test': f"Tech-averse user onboarding: {p['name']} can complete first receipt capture without help",
                'priority': 'High'
            })

        # Industry-specific categorization
        test_categories['Expense Categorization'].append({
            'persona': p['id'],
            'test': f"Verify {p['industry']} expense categories exist for {p['name']}'s use case",
            'priority': 'Medium'
        })

        # Multi-user tests
        if any('team' in tf.lower() or 'multi' in tf.lower() or 'employee' in tf.lower()
               for tf in p['test_focus']):
            test_categories['Multi-User/Team'].append({
                'persona': p['id'],
                'test': f"Multi-user workflow for {p['name']} ({p['occupation']})",
                'priority': 'High'
            })

        # Mobile-specific tests
        if 'rugged' in ' '.join(p['test_focus']).lower() or 'quick' in ' '.join(p['test_focus']).lower():
            test_categories['Mobile UX'].append({
                'persona': p['id'],
                'test': f"Quick/rugged capture for {p['name']} ({p['occupation']})",
                'priority': 'High'
            })

        # Internationalization
        if ',' in p['language'] or 'multi' in ' '.join(p['test_focus']).lower():
            test_categories['Internationalization'].append({
                'persona': p['id'],
                'test': f"Multi-language support for {p['name']} (speaks {p['language']})",
                'priority': 'Medium'
            })

    # Print test cases
    for category, tests in test_categories.items():
        if tests:
            print(f"\n## {category.upper()} ({len(tests)} tests)")
            print("-" * 60)
            for i, test in enumerate(tests[:5], 1):  # Show top 5
                priority_emoji = {'High': '🔴', 'Medium': '🟡', 'Low': '🟢'}.get(test['priority'], '⚪')
                print(f"   {i}. [{test['persona']}] {priority_emoji} {test['test']}")
            if len(tests) > 5:
                print(f"   ... and {len(tests) - 5} more tests")


def filter_personas(personas: List[Dict], category: str) -> List[Dict]:
    """Filter personas by category"""
    filters = {
        'accessibility': lambda p: p.get('accessibility_needs'),
        'low-tech': lambda p: p['tech_proficiency'] in ['Low', 'Low-Moderate'],
        'high-tech': lambda p: p['tech_proficiency'] in ['High', 'Very High', 'Expert'],
        'android': lambda p: 'Samsung' in p['primary_device'] or 'Galaxy' in p['primary_device'] or 'Google' in p['primary_device'],
        'ios': lambda p: 'iPhone' in p['primary_device'],
        'senior': lambda p: p['age'] >= 55,
        'young': lambda p: p['age'] <= 30,
        'multilingual': lambda p: ',' in p['language'],
        'high-volume': lambda p: 'high' in p['financial_complexity'].lower() or 'very high' in p['financial_complexity'].lower(),
        'team': lambda p: any('team' in tf.lower() or 'multi-user' in tf.lower() or 'employee' in tf.lower() for tf in p['test_focus']),
    }

    if category not in filters:
        print(f"Unknown category: {category}")
        print(f"Available: {', '.join(filters.keys())}")
        return []

    return [p for p in personas if filters[category](p)]


def main():
    import argparse

    parser = argparse.ArgumentParser(description='TallyUps Persona Testing Framework')
    parser.add_argument('--list', '-l', action='store_true', help='List all personas')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    parser.add_argument('--persona', '-p', type=str, help='Get details for specific persona (e.g., P001)')
    parser.add_argument('--category', '-c', type=str, help='Filter by category')
    parser.add_argument('--generate-tests', '-g', action='store_true', help='Generate test cases')
    parser.add_argument('--analyze', '-a', action='store_true', help='Analyze persona coverage')

    args = parser.parse_args()

    data = load_personas()
    personas = data['personas']

    if args.category:
        personas = filter_personas(personas, args.category)
        if not personas:
            return
        print(f"\nFiltered to {len(personas)} personas in category: {args.category}")

    if args.persona:
        get_persona_detail(data['personas'], args.persona)
    elif args.generate_tests:
        generate_test_cases(personas)
    elif args.analyze:
        analyze_personas(personas)
    elif args.list:
        list_personas(personas, args.verbose)
    else:
        # Default: show summary
        print(f"\nLoaded {len(personas)} personas")
        print("Use --help to see available commands")
        print("\nQuick commands:")
        print("  --list              List all personas")
        print("  --analyze           Analyze coverage")
        print("  --generate-tests    Generate test cases")
        print("  --persona P001      View specific persona")
        print("  --category android  Filter by category")


if __name__ == '__main__':
    main()
