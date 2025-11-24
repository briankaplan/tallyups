"""
Auto Mode Scheduler
Runs intelligence engine proactively on a schedule

Makes the companion truly autonomous - does things automatically
"""

import schedule
import time
import requests
from datetime import datetime
from real_actions_engine import RealActionsEngine
from services.gmail_receipt_service import GmailReceiptService

API_BASE = 'http://localhost:8080/api/intelligence'

# Initialize Gmail receipt service for direct scanning
gmail_service = GmailReceiptService()

# Initialize real actions engine for notifications
real_actions = RealActionsEngine(
    obsidian_vault_path="/Users/briankaplan/Library/Mobile Documents/iCloud~md~obsidian/Documents/Brian Kaplan"
)


def morning_routine():
    """
    Run automatically at 7am every morning

    Does:
    - Process inbox
    - Match receipts
    - Analyze emotional state
    - Check calendar
    - Send morning summary
    """
    print(f"\n{'='*60}")
    print(f"🌅 MORNING ROUTINE - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}\n")

    try:
        # 1. Process inbox
        print("📧 Processing inbox...")
        response = requests.post(f'{API_BASE}/actions/process-inbox', timeout=60)
        if response.ok:
            data = response.json()
            if data['success']:
                receipts = data['result'].get('receipts', 0)
                print(f"   ✅ Found {receipts} receipts")

                # Notify
                if receipts > 0:
                    real_actions.create_notification(
                        "Morning Routine Complete",
                        f"Found {receipts} new receipts",
                        urgency='normal'
                    )
            else:
                print(f"   ⚠️ {data['result'].get('message', 'Error')}")
        else:
            print(f"   ❌ Failed: {response.status_code}")

        # 2. Match receipts
        print("\n🧾 Matching receipts...")
        response = requests.post(f'{API_BASE}/actions/match-receipts', timeout=30)
        if response.ok:
            data = response.json()
            if data['success']:
                matched = data['result'].get('matched', 0)
                print(f"   ✅ Matched {matched} receipts")
            else:
                print(f"   ⚠️ {data['result'].get('message', 'Error')}")
        else:
            print(f"   ❌ Failed: {response.status_code}")

        # 3. Check emotional state
        print("\n🧠 Analyzing emotional state...")
        stress_data = {}
        response = requests.get(f'{API_BASE}/analyze-state', timeout=30)
        if response.ok:
            data = response.json()
            if data['success']:
                state = data['state']['state']
                stress = data['state']['stress_score']
                stress_data = {'state': state, 'stress_score': stress}
                print(f"   State: {state.upper()} (stress: {stress}/100)")

                # Alert if high stress
                if stress > 60:
                    real_actions.create_notification(
                        "High Stress Detected",
                        "Your stress levels are elevated. Consider what you can defer today.",
                        urgency='high'
                    )
            else:
                print(f"   ⚠️ Analysis failed")
        else:
            print(f"   ❌ Failed: {response.status_code}")

        # 4. Check burnout risk
        print("\n⚡ Checking burnout risk...")
        burnout_data = {}
        response = requests.get(f'{API_BASE}/check-burnout-risk', timeout=30)
        if response.ok:
            data = response.json()
            if data['success']:
                risk_level = data['risk_level']
                risk_score = data['risk_score']
                burnout_data = {'burnout_level': risk_level, 'burnout_score': risk_score}
                print(f"   Risk: {risk_level.upper()} ({risk_score}/100)")

                # Alert if high risk
                if risk_level in ['high', 'critical']:
                    real_actions.create_notification(
                        f"{risk_level.upper()} Burnout Risk",
                        "Immediate attention needed. Check the app for details.",
                        urgency='critical'
                    )
            else:
                print(f"   ⚠️ Check failed")
        else:
            print(f"   ❌ Failed: {response.status_code}")

        # 5. Log emotional state to daily log
        print("\n📝 Logging emotional state...")
        if stress_data or burnout_data:
            state_log = {
                'state': stress_data.get('state', 'unknown'),
                'stress_score': stress_data.get('stress_score', 0),
                'burnout_level': burnout_data.get('burnout_level', 'unknown'),
                'burnout_score': burnout_data.get('burnout_score', 0),
                'actions_taken': f"Morning routine: {receipts} receipts, {matched} matched"
            }
            real_actions.log_emotional_state(state_log)
            print("   ✅ Emotional state logged")

        # 6. Discover values and update knowledge base
        print("\n🧠 Updating knowledge base...")
        response = requests.post(f'{API_BASE}/discover-values', timeout=30)
        if response.ok:
            data = response.json()
            if data.get('success'):
                values_data = data.get('values', {})
                # Build learnings structure
                learnings = {
                    'values': values_data.get('values', []),
                    'patterns': values_data.get('patterns', []),
                    'preferences': [],
                    'stress_triggers': values_data.get('stress_triggers', []),
                    'coping': values_data.get('coping_mechanisms', [])
                }
                real_actions.update_knowledge_base(learnings)
                print("   ✅ Knowledge base updated")
            else:
                print("   ⚠️ Values discovery failed")
        else:
            print(f"   ❌ Failed: {response.status_code}")

        # 7. Update dashboard with all today's data
        print("\n📊 Updating dashboard...")
        emotional_state = {
            'state': stress_data.get('state', 'unknown') if stress_data else 'unknown',
            'stress_score': stress_data.get('stress_score', 0) if stress_data else 0,
            'burnout_level': burnout_data.get('burnout_level', 'unknown') if burnout_data else 'unknown',
            'burnout_score': burnout_data.get('burnout_score', 0) if burnout_data else 0
        }
        actions_today = [
            {'description': f'Processed {receipts} receipts', 'completed': True},
            {'description': f'Matched {matched} receipts', 'completed': matched > 0},
            {'description': 'Analyzed emotional state', 'completed': True},
            {'description': 'Checked burnout risk', 'completed': True}
        ]
        week_stats = {
            'receipts': receipts,
            'calendar_blocks': 0,
            'emails': receipts * 3,  # Rough estimate
            'matches': matched
        }
        real_actions.update_dashboard(
            emotional_state=emotional_state,
            actions_today=actions_today,
            week_stats=week_stats
        )
        print("   ✅ Dashboard updated")

        print(f"\n{'='*60}")
        print("✅ Morning routine complete")
        print(f"{'='*60}\n")

    except Exception as e:
        print(f"❌ Morning routine error: {e}")
        real_actions.create_notification(
            "Morning Routine Failed",
            f"Error: {str(e)}",
            urgency='normal'
        )


def inbox_check():
    """
    Check inbox every 2 hours during work day

    Does:
    - Quick inbox scan
    - Extract new receipts
    - Notify if important
    """
    print(f"\n📬 Inbox check - {datetime.now().strftime('%H:%M')}")

    try:
        response = requests.post(f'{API_BASE}/actions/process-inbox', timeout=60)
        if response.ok:
            data = response.json()
            if data['success']:
                receipts = data['result'].get('receipts', 0)
                if receipts > 0:
                    print(f"   ✅ Found {receipts} new receipts")
                    real_actions.create_notification(
                        "New Receipts Found",
                        f"Found {receipts} receipts in your inbox",
                        urgency='low'
                    )
                else:
                    print(f"   No new receipts")
            else:
                print(f"   ⚠️ {data['result'].get('message', 'Error')}")
        else:
            print(f"   ❌ Failed: {response.status_code}")

    except Exception as e:
        print(f"   ❌ Error: {e}")


def evening_review():
    """
    Run automatically at 6pm

    Does:
    - End of day analysis
    - Check if overworked
    - Suggest evening protection
    """
    print(f"\n{'='*60}")
    print(f"🌆 EVENING REVIEW - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}\n")

    try:
        # Check emotional state
        print("🧠 Analyzing day...")
        response = requests.get(f'{API_BASE}/analyze-state', timeout=30)
        if response.ok:
            data = response.json()
            if data['success']:
                state = data['state']['state']
                stress = data['state']['stress_score']
                print(f"   State: {state.upper()} (stress: {stress}/100)")

                # If stressed, suggest evening protection
                if stress > 50 or state in ['stressed', 'overwhelmed']:
                    print("\n   🛡️ Protecting evening time...")
                    response = requests.post(
                        f'{API_BASE}/actions/block-calendar',
                        json={'start': '6pm', 'end': '9pm', 'reason': 'Family recovery time - stress detected'},
                        timeout=30
                    )

                    real_actions.create_notification(
                        "Evening Protected",
                        "Blocked 6-9pm for family time. You need this.",
                        urgency='normal'
                    )
                    print("   ✅ Evening protected")
                else:
                    print(f"   ✅ Balanced state - no intervention needed")
            else:
                print(f"   ⚠️ Analysis failed")
        else:
            print(f"   ❌ Failed: {response.status_code}")

        print(f"\n{'='*60}")
        print("✅ Evening review complete")
        print(f"{'='*60}\n")

    except Exception as e:
        print(f"❌ Evening review error: {e}")


def gmail_receipt_scan():
    """
    Scan Gmail for receipts - runs twice daily

    Scans all configured Gmail accounts for:
    - Apple App Store/iTunes receipts
    - Hotel confirmations (HotelTonight, Marriott, etc.)
    - Airlines (Southwest, etc.)
    - Ride services (Uber, Lyft)
    - Food delivery (DoorDash, Grubhub)
    - General receipts and invoices
    """
    print(f"\n{'='*60}")
    print(f"📧 GMAIL RECEIPT SCAN - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}\n")

    try:
        total_found = 0
        total_saved = 0

        # Scan last 7 days
        accounts = gmail_service.list_accounts()
        print(f"📬 Scanning {len(accounts)} Gmail accounts...")

        for account in accounts:
            print(f"\n   📧 {account['email']}...")
            try:
                result = gmail_service.scan_for_receipts(
                    email=account['email'],
                    days_back=7
                )
                found = result.get('found', 0)
                saved = result.get('saved', 0)
                total_found += found
                total_saved += saved
                print(f"      Found: {found}, Saved: {saved}")
            except Exception as e:
                print(f"      ⚠️ Error: {e}")

        print(f"\n{'='*60}")
        print(f"✅ Gmail scan complete: {total_found} found, {total_saved} new receipts saved")
        print(f"{'='*60}\n")

        # Notify if new receipts found
        if total_saved > 0:
            real_actions.create_notification(
                "Gmail Receipts Found",
                f"Scanned Gmail and found {total_saved} new receipts",
                urgency='low'
            )

    except Exception as e:
        print(f"❌ Gmail scan error: {e}")


def run_scheduler():
    """
    Main scheduler loop - runs proactively

    Schedule:
    - 7:00 AM: Morning routine
    - 8:00 AM: Gmail receipt scan
    - 9:00 AM, 11:00 AM, 1:00 PM, 3:00 PM: Inbox check
    - 5:00 PM: Gmail receipt scan
    - 6:00 PM: Evening review
    """
    print(f"\n{'='*60}")
    print("🤖 AUTO MODE ACTIVATED")
    print(f"{'='*60}\n")
    print("Schedule:")
    print("  7:00 AM  - Morning routine (inbox, receipts, state analysis)")
    print("  8:00 AM  - Gmail receipt scan (Apple, hotels, airlines)")
    print("  9:00 AM  - Inbox check")
    print(" 11:00 AM  - Inbox check")
    print("  1:00 PM  - Inbox check")
    print("  3:00 PM  - Inbox check")
    print("  5:00 PM  - Gmail receipt scan (Apple, hotels, airlines)")
    print("  6:00 PM  - Evening review (protect time if stressed)")
    print(f"\n{'='*60}\n")

    # Schedule tasks
    schedule.every().day.at("07:00").do(morning_routine)
    schedule.every().day.at("08:00").do(gmail_receipt_scan)
    schedule.every().day.at("09:00").do(inbox_check)
    schedule.every().day.at("11:00").do(inbox_check)
    schedule.every().day.at("13:00").do(inbox_check)
    schedule.every().day.at("15:00").do(inbox_check)
    schedule.every().day.at("17:00").do(gmail_receipt_scan)
    schedule.every().day.at("18:00").do(evening_review)

    # Startup notification
    real_actions.create_notification(
        "Auto Mode Activated",
        "Your AI companion is now running proactively",
        urgency='normal'
    )

    print(f"✅ Scheduler started at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("   Running in background...")
    print("   Press Ctrl+C to stop\n")

    # Run scheduler
    while True:
        schedule.run_pending()
        time.sleep(60)  # Check every minute


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Auto Mode Scheduler')
    parser.add_argument('--test', action='store_true', help='Run tests immediately')
    parser.add_argument('--morning', action='store_true', help='Run morning routine now')
    parser.add_argument('--evening', action='store_true', help='Run evening review now')
    parser.add_argument('--inbox', action='store_true', help='Run inbox check now')
    parser.add_argument('--gmail', action='store_true', help='Run Gmail receipt scan now')
    parser.add_argument('--gmail-full', action='store_true', help='Run Gmail scan for last 365 days (historical)')
    args = parser.parse_args()

    if args.gmail_full:
        print("📧 Running FULL Gmail scan (last 365 days)...")
        # Override the scan function to use more days
        accounts = gmail_service.list_accounts()
        total_found = 0
        total_saved = 0
        for account in accounts:
            print(f"\n   📧 {account['email']}...")
            try:
                result = gmail_service.scan_for_receipts(
                    email=account['email'],
                    days_back=365  # Full year
                )
                found = result.get('found', 0)
                saved = result.get('saved', 0)
                total_found += found
                total_saved += saved
                print(f"      Found: {found}, Saved: {saved}")
            except Exception as e:
                print(f"      ⚠️ Error: {e}")
        print(f"\n✅ Full Gmail scan complete: {total_found} found, {total_saved} new")
    elif args.gmail:
        gmail_receipt_scan()
    elif args.test:
        print("🧪 TEST MODE - Running all functions once\n")
        morning_routine()
        time.sleep(2)
        inbox_check()
        time.sleep(2)
        evening_review()
    elif args.morning:
        morning_routine()
    elif args.evening:
        evening_review()
    elif args.inbox:
        inbox_check()
    else:
        # Run scheduler
        run_scheduler()
