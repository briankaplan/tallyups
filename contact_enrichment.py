#!/usr/bin/env python3
"""
Contact Enrichment Engine
Automatically enriches contacts with external data:
- Photos (LinkedIn, Gravatar, Google, company sites)
- LinkedIn profile data
- Company information
- News mentions
- Social media profiles
- Job changes

Runs on schedule and on-demand
"""

import os
import re
import json
import asyncio
import hashlib
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass
from pathlib import Path
import httpx
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class EnrichmentResult:
    """Result of enrichment for a contact"""
    contact_id: int
    source: str
    enriched_at: datetime
    data: Dict[str, Any]
    photo_url: Optional[str] = None
    photo_data: Optional[bytes] = None
    is_significant_change: bool = False  # Job change, news, etc.
    change_summary: Optional[str] = None


class PhotoFetcher:
    """Fetches contact photos from multiple sources"""

    def __init__(self):
        self.proxycurl_api_key = os.getenv("PROXYCURL_API_KEY")
        self.serpapi_key = os.getenv("SERPAPI_KEY")

    async def fetch_photo(self, contact: Dict) -> Optional[Tuple[bytes, str]]:
        """Fetch photo from best available source. Returns (photo_bytes, source)"""

        strategies = [
            ("google_contacts", self._from_google_contacts),
            ("linkedin", self._from_linkedin),
            ("gravatar", self._from_gravatar),
            ("twitter", self._from_twitter),
            ("company_website", self._from_company_website),
            ("google_search", self._from_google_search),
        ]

        for source, strategy in strategies:
            try:
                photo = await strategy(contact)
                if photo:
                    logger.info(f"Found photo for {contact.get('display_name')} from {source}")
                    return photo, source
            except Exception as e:
                logger.debug(f"Photo fetch failed from {source}: {e}")

        return None

    async def _from_google_contacts(self, contact: Dict) -> Optional[bytes]:
        """Get photo from Google Contacts if already synced"""
        photo_url = contact.get("photo_url")
        if photo_url and "googleusercontent.com" in photo_url:
            async with httpx.AsyncClient() as client:
                response = await client.get(photo_url)
                if response.status_code == 200:
                    return response.content
        return None

    async def _from_gravatar(self, contact: Dict) -> Optional[bytes]:
        """Fetch from Gravatar using email hash"""
        emails = contact.get("emails", [])

        for email_obj in emails:
            email = email_obj.get("email", "").lower().strip()
            if not email:
                continue

            email_hash = hashlib.md5(email.encode()).hexdigest()
            url = f"https://www.gravatar.com/avatar/{email_hash}?d=404&s=400"

            async with httpx.AsyncClient() as client:
                response = await client.get(url)
                if response.status_code == 200:
                    return response.content

        return None

    async def _from_linkedin(self, contact: Dict) -> Optional[bytes]:
        """Fetch LinkedIn profile photo via Proxycurl"""
        linkedin_url = contact.get("linkedin_url")

        if not linkedin_url or not self.proxycurl_api_key:
            return None

        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://nubela.co/proxycurl/api/v2/linkedin",
                params={"url": linkedin_url},
                headers={"Authorization": f"Bearer {self.proxycurl_api_key}"},
                timeout=30.0
            )

            if response.status_code == 200:
                data = response.json()
                photo_url = data.get("profile_pic_url")

                if photo_url:
                    img_response = await client.get(photo_url)
                    if img_response.status_code == 200:
                        return img_response.content

        return None

    async def _from_twitter(self, contact: Dict) -> Optional[bytes]:
        """Fetch Twitter/X profile photo"""
        twitter_handle = contact.get("twitter_handle")

        if not twitter_handle:
            return None

        # Clean handle
        handle = twitter_handle.lstrip("@")

        # Twitter CDN pattern (may change, use as fallback)
        # This requires Twitter API or scraping
        # Placeholder for now

        return None

    async def _from_company_website(self, contact: Dict) -> Optional[bytes]:
        """Try to find photo on company website team page"""
        company = contact.get("company")
        website = contact.get("website")
        name = contact.get("display_name")

        if not company or not name:
            return None

        # Try common team page patterns
        domains_to_try = []

        if website:
            domains_to_try.append(website.rstrip("/"))
        else:
            # Generate likely domain
            company_slug = re.sub(r'[^a-z0-9]', '', company.lower())
            domains_to_try.extend([
                f"https://{company_slug}.com",
                f"https://www.{company_slug}.com",
            ])

        team_paths = ["/about", "/team", "/about-us", "/our-team", "/people", "/leadership"]

        async with httpx.AsyncClient(timeout=10.0) as client:
            for domain in domains_to_try:
                for path in team_paths:
                    try:
                        url = f"{domain}{path}"
                        response = await client.get(url, follow_redirects=True)

                        if response.status_code == 200:
                            soup = BeautifulSoup(response.text, 'html.parser')

                            # Look for images near the person's name
                            first_name = name.split()[0].lower()
                            last_name = name.split()[-1].lower() if len(name.split()) > 1 else ""

                            # Find text containing the name
                            for text_elem in soup.find_all(string=re.compile(first_name, re.I)):
                                parent = text_elem.parent

                                # Look for nearby img
                                for ancestor in [parent] + list(parent.parents)[:3]:
                                    img = ancestor.find('img')
                                    if img and img.get('src'):
                                        img_url = img['src']
                                        if not img_url.startswith('http'):
                                            img_url = f"{domain}{img_url}"

                                        img_response = await client.get(img_url)
                                        if img_response.status_code == 200:
                                            return img_response.content
                    except:
                        continue

        return None

    async def _from_google_search(self, contact: Dict) -> Optional[bytes]:
        """Last resort: Google Image Search"""
        if not self.serpapi_key:
            return None

        name = contact.get("display_name")
        company = contact.get("company", "")

        if not name:
            return None

        query = f"{name} {company}".strip()

        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://serpapi.com/search",
                params={
                    "engine": "google_images",
                    "q": query,
                    "api_key": self.serpapi_key,
                    "num": 5,
                }
            )

            if response.status_code == 200:
                data = response.json()
                images = data.get("images_results", [])

                for img in images[:5]:
                    img_url = img.get("original")
                    if img_url:
                        try:
                            img_response = await client.get(img_url, timeout=5.0)
                            if img_response.status_code == 200:
                                # Basic check that it's an image
                                content_type = img_response.headers.get("content-type", "")
                                if "image" in content_type:
                                    return img_response.content
                        except:
                            continue

        return None


class LinkedInEnricher:
    """Enriches contacts with LinkedIn data"""

    def __init__(self):
        self.api_key = os.getenv("PROXYCURL_API_KEY")

    async def enrich(self, contact: Dict) -> Optional[Dict]:
        """Fetch LinkedIn profile data"""
        linkedin_url = contact.get("linkedin_url")

        if not linkedin_url or not self.api_key:
            return None

        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://nubela.co/proxycurl/api/v2/linkedin",
                params={"url": linkedin_url},
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=30.0
            )

            if response.status_code == 200:
                return response.json()

        return None

    async def find_linkedin_url(self, contact: Dict) -> Optional[str]:
        """Try to find LinkedIn URL for a contact"""
        if not self.api_key:
            return None

        name = contact.get("display_name")
        company = contact.get("company")

        if not name:
            return None

        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://nubela.co/proxycurl/api/linkedin/profile/resolve",
                params={
                    "first_name": name.split()[0],
                    "last_name": name.split()[-1] if len(name.split()) > 1 else "",
                    "company_domain": self._company_to_domain(company) if company else None,
                },
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=30.0
            )

            if response.status_code == 200:
                data = response.json()
                return data.get("url")

        return None

    def _company_to_domain(self, company: str) -> str:
        """Convert company name to likely domain"""
        slug = re.sub(r'[^a-z0-9]', '', company.lower())
        return f"{slug}.com"

    def detect_job_change(self, old_data: Dict, new_data: Dict) -> Optional[str]:
        """Detect if there's been a job change"""
        old_company = old_data.get("company") or old_data.get("experiences", [{}])[0].get("company")
        new_company = new_data.get("company") or new_data.get("experiences", [{}])[0].get("company")

        old_title = old_data.get("job_title") or old_data.get("experiences", [{}])[0].get("title")
        new_title = new_data.get("job_title") or new_data.get("experiences", [{}])[0].get("title")

        changes = []

        if old_company and new_company and old_company.lower() != new_company.lower():
            changes.append(f"Company: {old_company} -> {new_company}")

        if old_title and new_title and old_title.lower() != new_title.lower():
            changes.append(f"Title: {old_title} -> {new_title}")

        if changes:
            return "; ".join(changes)

        return None


class NewsEnricher:
    """Finds news mentions for contacts"""

    def __init__(self):
        self.newsapi_key = os.getenv("NEWSAPI_KEY")
        self.serpapi_key = os.getenv("SERPAPI_KEY")

    async def find_news(
        self,
        contact: Dict,
        days_back: int = 30
    ) -> List[Dict]:
        """Find recent news mentions"""

        name = contact.get("display_name")
        company = contact.get("company")

        if not name:
            return []

        articles = []

        # Try NewsAPI
        if self.newsapi_key:
            articles.extend(await self._search_newsapi(name, company, days_back))

        # Try SerpAPI Google News
        if self.serpapi_key and len(articles) < 5:
            articles.extend(await self._search_google_news(name, company, days_back))

        return articles[:10]  # Limit results

    async def _search_newsapi(
        self,
        name: str,
        company: Optional[str],
        days_back: int
    ) -> List[Dict]:
        """Search NewsAPI"""

        query = f'"{name}"'
        if company:
            query += f' OR "{company}"'

        from_date = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y-%m-%d")

        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://newsapi.org/v2/everything",
                params={
                    "q": query,
                    "from": from_date,
                    "sortBy": "relevancy",
                    "pageSize": 10,
                    "apiKey": self.newsapi_key,
                }
            )

            if response.status_code == 200:
                data = response.json()
                return [
                    {
                        "title": a.get("title"),
                        "description": a.get("description"),
                        "url": a.get("url"),
                        "source": a.get("source", {}).get("name"),
                        "published_at": a.get("publishedAt"),
                    }
                    for a in data.get("articles", [])
                ]

        return []

    async def _search_google_news(
        self,
        name: str,
        company: Optional[str],
        days_back: int
    ) -> List[Dict]:
        """Search Google News via SerpAPI"""

        query = f'"{name}"'
        if company:
            query += f' {company}'

        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://serpapi.com/search",
                params={
                    "engine": "google_news",
                    "q": query,
                    "api_key": self.serpapi_key,
                }
            )

            if response.status_code == 200:
                data = response.json()
                return [
                    {
                        "title": a.get("title"),
                        "description": a.get("snippet"),
                        "url": a.get("link"),
                        "source": a.get("source", {}).get("name"),
                        "published_at": a.get("date"),
                    }
                    for a in data.get("news_results", [])
                ]

        return []


class CompanyEnricher:
    """Enriches company information"""

    def __init__(self):
        self.clearbit_key = os.getenv("CLEARBIT_API_KEY")

    async def enrich(self, company_name: str, domain: Optional[str] = None) -> Optional[Dict]:
        """Fetch company data"""

        if not domain:
            domain = self._company_to_domain(company_name)

        if self.clearbit_key:
            return await self._from_clearbit(domain)

        return await self._from_web(domain)

    async def _from_clearbit(self, domain: str) -> Optional[Dict]:
        """Fetch from Clearbit Company API"""

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://company.clearbit.com/v2/companies/find",
                params={"domain": domain},
                headers={"Authorization": f"Bearer {self.clearbit_key}"}
            )

            if response.status_code == 200:
                return response.json()

        return None

    async def _from_web(self, domain: str) -> Optional[Dict]:
        """Scrape basic company info from website"""

        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.get(f"https://{domain}", follow_redirects=True)

                if response.status_code == 200:
                    soup = BeautifulSoup(response.text, 'html.parser')

                    return {
                        "domain": domain,
                        "name": soup.title.string if soup.title else None,
                        "description": soup.find("meta", {"name": "description"})["content"] if soup.find("meta", {"name": "description"}) else None,
                    }
            except:
                pass

        return None

    def _company_to_domain(self, company: str) -> str:
        """Convert company name to likely domain"""
        slug = re.sub(r'[^a-z0-9]', '', company.lower())
        return f"{slug}.com"


class EnrichmentEngine:
    """Main enrichment engine that orchestrates all enrichers"""

    def __init__(self, atlas_api_url: str):
        self.api_url = atlas_api_url
        self.photo_fetcher = PhotoFetcher()
        self.linkedin_enricher = LinkedInEnricher()
        self.news_enricher = NewsEnricher()
        self.company_enricher = CompanyEnricher()

    async def enrich_contact(self, contact: Dict, force: bool = False) -> EnrichmentResult:
        """Run full enrichment for a contact"""

        contact_id = contact.get("id")
        result = EnrichmentResult(
            contact_id=contact_id,
            source="enrichment_engine",
            enriched_at=datetime.utcnow(),
            data={}
        )

        # 1. Photo
        if not contact.get("photo_url") or force:
            photo_result = await self.photo_fetcher.fetch_photo(contact)
            if photo_result:
                photo_bytes, source = photo_result
                result.photo_data = photo_bytes
                result.data["photo_source"] = source

        # 2. LinkedIn
        if contact.get("linkedin_url"):
            linkedin_data = await self.linkedin_enricher.enrich(contact)
            if linkedin_data:
                result.data["linkedin"] = linkedin_data

                # Detect job change
                job_change = self.linkedin_enricher.detect_job_change(contact, linkedin_data)
                if job_change:
                    result.is_significant_change = True
                    result.change_summary = f"Job change detected: {job_change}"
        elif contact.get("first_name") and contact.get("last_name"):
            # Try to find LinkedIn URL
            linkedin_url = await self.linkedin_enricher.find_linkedin_url(contact)
            if linkedin_url:
                result.data["linkedin_url"] = linkedin_url

        # 3. News
        news = await self.news_enricher.find_news(contact)
        if news:
            result.data["news"] = news
            result.is_significant_change = True
            result.change_summary = (result.change_summary or "") + f" | {len(news)} news mentions found"

        # 4. Company
        if contact.get("company"):
            company_data = await self.company_enricher.enrich(contact["company"])
            if company_data:
                result.data["company"] = company_data

        return result

    async def enrich_all_contacts(
        self,
        batch_size: int = 10,
        delay_between_batches: float = 1.0
    ) -> Dict[str, int]:
        """Enrich all contacts that need enrichment"""

        stats = {"total": 0, "enriched": 0, "photos_found": 0, "news_found": 0, "errors": 0}

        async with httpx.AsyncClient() as client:
            # Get contacts needing enrichment
            response = await client.get(
                f"{self.api_url}/contacts",
                params={"needs_enrichment": True, "page_size": 100}
            )

            if response.status_code != 200:
                return stats

            contacts = response.json().get("items", [])
            stats["total"] = len(contacts)

            # Process in batches
            for i in range(0, len(contacts), batch_size):
                batch = contacts[i:i+batch_size]

                for contact in batch:
                    try:
                        result = await self.enrich_contact(contact)

                        # Save enrichment results
                        await self._save_enrichment(result)

                        stats["enriched"] += 1
                        if result.photo_data:
                            stats["photos_found"] += 1
                        if result.data.get("news"):
                            stats["news_found"] += 1

                    except Exception as e:
                        logger.error(f"Error enriching {contact.get('display_name')}: {e}")
                        stats["errors"] += 1

                await asyncio.sleep(delay_between_batches)

        return stats

    async def _save_enrichment(self, result: EnrichmentResult):
        """Save enrichment results to ATLAS"""

        async with httpx.AsyncClient() as client:
            # Update contact with enriched data
            update_data = {}

            if result.photo_data:
                # Save photo separately
                await client.post(
                    f"{self.api_url}/contacts/{result.contact_id}/photo",
                    files={"photo": ("photo.jpg", result.photo_data, "image/jpeg")}
                )

            if result.data.get("linkedin_url"):
                update_data["linkedin_url"] = result.data["linkedin_url"]

            if result.data.get("linkedin"):
                linkedin = result.data["linkedin"]
                if linkedin.get("headline"):
                    update_data["job_title"] = linkedin["headline"]

            if update_data:
                await client.put(
                    f"{self.api_url}/contacts/{result.contact_id}",
                    json=update_data
                )

            # Save enrichment record
            await client.post(
                f"{self.api_url}/contacts/{result.contact_id}/enrichments",
                json={
                    "source": result.source,
                    "data": result.data,
                    "is_significant_change": result.is_significant_change,
                    "change_summary": result.change_summary,
                }
            )


# =============================================================================
# CLI
# =============================================================================

async def main():
    import argparse

    parser = argparse.ArgumentParser(description="ATLAS Contact Enrichment")
    parser.add_argument("command", choices=["enrich", "enrich-all", "find-photos", "find-news"])
    parser.add_argument("--api-url", default=os.getenv("ATLAS_API_URL", "http://localhost:8000"))
    parser.add_argument("--contact-id", type=int, help="Specific contact to enrich")
    parser.add_argument("--batch-size", type=int, default=10)

    args = parser.parse_args()

    engine = EnrichmentEngine(args.api_url)

    if args.command == "enrich" and args.contact_id:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{args.api_url}/contacts/{args.contact_id}")
            if response.status_code == 200:
                contact = response.json()
                result = await engine.enrich_contact(contact)
                print(f"Enriched {contact.get('display_name')}")
                print(f"  Photo found: {result.photo_data is not None}")
                print(f"  Data: {json.dumps(result.data, indent=2, default=str)}")

    elif args.command == "enrich-all":
        stats = await engine.enrich_all_contacts(batch_size=args.batch_size)
        print(f"Enrichment complete:")
        print(f"  Total: {stats['total']}")
        print(f"  Enriched: {stats['enriched']}")
        print(f"  Photos found: {stats['photos_found']}")
        print(f"  News found: {stats['news_found']}")
        print(f"  Errors: {stats['errors']}")


if __name__ == "__main__":
    asyncio.run(main())
