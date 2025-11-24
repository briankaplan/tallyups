"""
Appointment Booking Service
Handles automated booking for various services (haircuts, appointments, etc.)
"""

import os
import json
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from playwright.async_api import async_playwright
import anthropic
import logging

logger = logging.getLogger(__name__)


class AppointmentBookingService:
    """
    Automated appointment booking service that integrates with:
    - Calendar to find available time slots
    - Google Maps for travel time calculation
    - Booking platforms (Mangomint, Vagaro, etc.)
    """

    def __init__(self, db_path: str = 'master.db'):
        self.db_path = db_path
        self.anthropic_client = anthropic.Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))

        # Business configurations
        self.businesses = {
            'moose_grooming': {
                'name': 'The Moose Men\'s Grooming Lounge',
                'url': 'https://booking.mangomint.com/917907',
                'location': {
                    'address': '2817 West End Ave, Nashville, TN 37203',
                    'lat': 36.1384,
                    'lng': -86.8067
                },
                'services': {
                    'haircut': 'Tailored Cut Short Hair',  # Regular men's haircut - $55+
                    'haircut_long': 'Tailored Cut Long Hair',  # Long hair cut - $55+
                    'cut_beard': 'Cut/Beard/Trim',  # Cut with beard trim - $85+
                    'cut_shave': 'Cut/Shave',  # Cut with shave - $110+
                    'scalp_therapy': 'Scalp Therapy',  # Scalp treatment - $20
                    'cut_scalp': 'Cut/Scalp Therapy'  # Cut with scalp treatment - $75+
                },
                'typical_duration_minutes': 60,  # Updated to 60 min for tailored cut
                'platform': 'mangomint'
            }
        }

        # Client information
        self.client_info = {
            'name': os.getenv('CLIENT_NAME', 'Brian Kaplan'),
            'email': os.getenv('CLIENT_EMAIL', 'kaplan.brian@gmail.com'),
            'phone': os.getenv('CLIENT_PHONE', '6153377647')
        }

    async def find_optimal_appointment_slot(
        self,
        service_type: str,
        business_key: str,
        preferred_date: Optional[str] = None,
        time_preference: str = 'morning',  # morning, afternoon, evening, anytime
        days_ahead: int = 7
    ) -> Dict:
        """
        Find the optimal appointment slot based on:
        - Calendar availability
        - Travel time from current/scheduled location
        - Business availability
        - User preferences
        """
        try:
            business = self.businesses.get(business_key)
            if not business:
                raise ValueError(f"Unknown business: {business_key}")

            # Step 1: Get calendar availability for the next N days
            calendar_slots = await self._get_calendar_availability(
                days_ahead=days_ahead,
                preferred_date=preferred_date
            )

            # Step 2: For each available slot, calculate travel time
            viable_slots = []
            for slot in calendar_slots:
                travel_info = await self._calculate_travel_time(
                    from_location=slot.get('location', 'home'),
                    to_location=business['location'],
                    departure_time=slot['start_time']
                )

                # Calculate total time needed (travel to + service + travel back)
                total_minutes = (
                    travel_info['to_duration_minutes'] +
                    business['typical_duration_minutes'] +
                    travel_info['back_duration_minutes']
                )

                # Check if this fits in the calendar slot
                slot_duration = (slot['end_time'] - slot['start_time']).total_seconds() / 60
                if total_minutes <= slot_duration:
                    viable_slots.append({
                        'calendar_slot': slot,
                        'travel_info': travel_info,
                        'appointment_start': slot['start_time'] + timedelta(minutes=travel_info['to_duration_minutes']),
                        'appointment_end': slot['start_time'] + timedelta(minutes=travel_info['to_duration_minutes'] + business['typical_duration_minutes']),
                        'total_minutes': total_minutes,
                        'buffer_minutes': slot_duration - total_minutes
                    })

            # Step 3: Filter by time preference
            filtered_slots = self._filter_by_time_preference(viable_slots, time_preference)

            # Step 4: Check business availability for these slots
            available_slots = await self._check_business_availability(
                business_key=business_key,
                candidate_slots=filtered_slots
            )

            if not available_slots:
                return {
                    'success': False,
                    'message': 'No available slots found that match your schedule and preferences'
                }

            # Return the best slot (earliest with best buffer)
            best_slot = sorted(available_slots, key=lambda x: (x['appointment_start'], -x['buffer_minutes']))[0]

            return {
                'success': True,
                'slot': best_slot,
                'business': business,
                'service_type': service_type
            }

        except Exception as e:
            logger.error(f"Error finding optimal slot: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    async def _get_calendar_availability(
        self,
        days_ahead: int = 7,
        preferred_date: Optional[str] = None
    ) -> List[Dict]:
        """
        Get available time slots from calendar
        Returns blocks of free time with location context
        """
        # This would integrate with the calendar service
        # For now, return mock data - you'd call your calendar API here

        from datetime import datetime, timedelta

        available_slots = []
        start_date = datetime.now()

        for day_offset in range(days_ahead):
            day = start_date + timedelta(days=day_offset)

            # Skip weekends if needed
            if day.weekday() >= 5:  # Saturday = 5, Sunday = 6
                continue

            # Morning slot (9am - 12pm)
            available_slots.append({
                'start_time': day.replace(hour=9, minute=0, second=0),
                'end_time': day.replace(hour=12, minute=0, second=0),
                'location': 'home',  # Would be determined by previous calendar event
                'type': 'morning'
            })

            # Afternoon slot (1pm - 5pm)
            available_slots.append({
                'start_time': day.replace(hour=13, minute=0, second=0),
                'end_time': day.replace(hour=17, minute=0, second=0),
                'location': 'home',
                'type': 'afternoon'
            })

        return available_slots

    async def _calculate_travel_time(
        self,
        from_location: str,
        to_location: Dict,
        departure_time: datetime
    ) -> Dict:
        """
        Calculate travel time using Google Maps API
        """
        # This would integrate with Google Maps Distance Matrix API
        # For now, return estimated times

        # Typical Nashville travel times (you'd use real API here)
        travel_estimates = {
            'home': 15,  # 15 minutes from home
            'downtown': 10,
            'office': 20
        }

        to_duration = travel_estimates.get(from_location, 15)

        return {
            'to_duration_minutes': to_duration,
            'back_duration_minutes': to_duration,  # Assume symmetric
            'from_location': from_location,
            'to_address': to_location['address']
        }

    def _filter_by_time_preference(
        self,
        slots: List[Dict],
        preference: str
    ) -> List[Dict]:
        """Filter slots by time of day preference"""
        if preference == 'anytime':
            return slots

        filtered = []
        for slot in slots:
            hour = slot['appointment_start'].hour

            if preference == 'morning' and 6 <= hour < 12:
                filtered.append(slot)
            elif preference == 'afternoon' and 12 <= hour < 17:
                filtered.append(slot)
            elif preference == 'evening' and 17 <= hour < 21:
                filtered.append(slot)

        return filtered

    async def _check_business_availability(
        self,
        business_key: str,
        candidate_slots: List[Dict]
    ) -> List[Dict]:
        """
        Check which candidate slots are actually available at the business
        Uses Playwright to check real-time availability
        """
        business = self.businesses[business_key]

        if business['platform'] == 'mangomint':
            return await self._check_mangomint_availability(business, candidate_slots)

        # Add other platforms here
        return candidate_slots  # Fallback: assume all available

    async def _check_mangomint_availability(
        self,
        business: Dict,
        candidate_slots: List[Dict]
    ) -> List[Dict]:
        """Check Mangomint platform for actual availability"""
        # For now, return all slots as available
        # In production, you'd use Playwright to check real availability
        return candidate_slots

    async def book_appointment(
        self,
        business_key: str,
        service_type: str,
        appointment_slot: Dict,
        staff_preference: str = 'anyone'
    ) -> Dict:
        """
        Book an appointment using Playwright automation
        """
        business = self.businesses.get(business_key)
        if not business:
            return {'success': False, 'error': 'Unknown business'}

        if business['platform'] == 'mangomint':
            return await self._book_mangomint_appointment(
                business=business,
                service_type=service_type,
                appointment_slot=appointment_slot,
                staff_preference=staff_preference
            )

        return {'success': False, 'error': 'Unsupported platform'}

    async def _book_mangomint_appointment(
        self,
        business: Dict,
        service_type: str,
        appointment_slot: Dict,
        staff_preference: str
    ) -> Dict:
        """
        Book appointment on Mangomint platform using Playwright
        """
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context()
                page = await context.new_page()

                # Navigate to booking page
                await page.goto(business['url'], wait_until='networkidle')
                await asyncio.sleep(3)  # Wait for initial load

                # Step 1: Click service category (e.g., "HAIR")
                await page.click('text=HAIR')
                await asyncio.sleep(2)

                # Step 2: Select specific service
                service_name = business['services'].get(service_type, 'Haircut')
                await page.click(f'text={service_name}')
                await asyncio.sleep(3)

                # Step 3: Select staff member using correct selector
                if staff_preference == 'anyone' or staff_preference == 'Anyone':
                    # Click the "Anyone" option
                    anyone_selector = '.ServiceProviderList_itemCt__IfqGX:has-text("Anyone")'
                    await page.click(anyone_selector)
                else:
                    # Click specific staff member
                    staff_selector = f'.ServiceProviderList_itemCt__IfqGX:has-text("{staff_preference}")'
                    await page.click(staff_selector)

                await asyncio.sleep(3)

                # Navigate to the right date
                target_date = appointment_slot['appointment_start']
                await self._navigate_to_date(page, target_date)

                # Select the time slot
                target_time = target_date.strftime('%I:%M %p').lstrip('0')
                await page.wait_for_selector(".TimeSlot")

                # Try to find and click the specific time slot
                time_slot = page.locator(f".TimeSlot:has-text('{target_time}')").first
                if await time_slot.is_visible():
                    await time_slot.click()
                else:
                    # Fall back to first available slot
                    await page.locator(".TimeSlot").first.click()

                # Fill in client information
                await page.fill("input[placeholder*='Name']", self.client_info['name'])
                await page.fill("input[placeholder*='Email']", self.client_info['email'])
                await page.fill("input[placeholder*='Phone']", self.client_info['phone'])

                # Confirm booking
                await page.click("text='Confirm'")

                # Wait for confirmation
                await page.wait_for_selector("text='Appointment confirmed'", timeout=15000)
                confirmation_text = await page.inner_text("body")

                await browser.close()

                # Extract booking details
                result = {
                    'success': True,
                    'business': business['name'],
                    'service': service_name,
                    'date': target_date.strftime('%Y-%m-%d'),
                    'time': target_time,
                    'client': self.client_info['name'],
                    'confirmation': confirmation_text
                }

                # Add to calendar
                await self._add_to_calendar(result, appointment_slot)

                return result

        except Exception as e:
            logger.error(f"Error booking Mangomint appointment: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    async def _navigate_to_date(self, page, target_date: datetime):
        """Navigate calendar to target date"""
        # Click next month button until we reach target month
        current_month = datetime.now().month
        target_month = target_date.month

        if target_month > current_month:
            clicks_needed = target_month - current_month
            for _ in range(clicks_needed):
                await page.click(".CalendarMonth_next")
                await asyncio.sleep(0.5)

        # Click on the specific day
        day_number = target_date.day
        await page.click(f".CalendarDay[data-day='{day_number}']:not(.is-disabled)")

    async def _add_to_calendar(self, booking: Dict, appointment_slot: Dict):
        """Add booked appointment to Google Calendar"""
        # This would integrate with Google Calendar API
        # You already have calendar integration in unified_app.py
        logger.info(f"Would add to calendar: {booking}")

    async def handle_booking_request(self, user_message: str) -> Dict:
        """
        Parse user's natural language booking request and execute
        Examples:
        - "Book a haircut next week during an open scheduled time"
        - "Schedule a haircut appointment for tomorrow morning"
        - "Find me a time for a haircut this week"
        """
        try:
            # Use Claude to parse the intent
            intent_response = self.anthropic_client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=1000,
                messages=[{
                    "role": "user",
                    "content": f"""Parse this appointment booking request and extract:
                    - service_type (haircut, beard_trim, etc.)
                    - time_preference (morning, afternoon, evening, anytime, specific date)
                    - urgency (next_week, tomorrow, this_week, specific_date)
                    - days_ahead (number)

                    User request: "{user_message}"

                    Respond in JSON format:
                    {{
                        "service_type": "haircut",
                        "time_preference": "morning",
                        "days_ahead": 7,
                        "specific_date": null
                    }}"""
                }]
            )

            # Parse Claude's response
            intent = json.loads(intent_response.content[0].text)

            # Find optimal slot
            slot_result = await self.find_optimal_appointment_slot(
                service_type=intent['service_type'],
                business_key='moose_grooming',
                time_preference=intent.get('time_preference', 'anytime'),
                days_ahead=intent.get('days_ahead', 7)
            )

            if not slot_result['success']:
                return slot_result

            # Book the appointment
            booking_result = await self.book_appointment(
                business_key='moose_grooming',
                service_type=intent['service_type'],
                appointment_slot=slot_result['slot']
            )

            return booking_result

        except Exception as e:
            logger.error(f"Error handling booking request: {e}")
            return {
                'success': False,
                'error': str(e)
            }


# Singleton instance
_booking_service = None

def get_booking_service() -> AppointmentBookingService:
    global _booking_service
    if _booking_service is None:
        _booking_service = AppointmentBookingService()
    return _booking_service
