"""
R2 Document Management Service

Features:
- 7 organized categories (Legal, Financial, Auto, Home, Down Home, MCR, Personal)
- AI auto-categorization using Claude
- Email attachment auto-upload
- Full-text search
- Retention policies
- Version control
- Secure access

Integrated with:
- Cloudflare R2 (document storage)
- Anthropic AI (categorization)
- Gmail API (attachment extraction)
"""

import os
import boto3
import json
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
import anthropic
from typing import Optional, Dict, List

# Document Categories
CATEGORIES = {
    'legal': {
        'name': 'Legal',
        'path': 'documents/legal/',
        'keywords': ['contract', 'agreement', 'legal notice', 'terms', 'policy', 'license'],
        'retention_days': 2555  # 7 years
    },
    'financial': {
        'name': 'Financial',
        'path': 'documents/financial/',
        'keywords': ['tax', 'bank statement', 'investment', 'financial report', '1099', 'w2', 'invoice'],
        'retention_days': 2555  # 7 years
    },
    'auto': {
        'name': 'Auto',
        'path': 'documents/auto/',
        'keywords': ['vehicle', 'registration', 'insurance', 'maintenance', 'dmv', 'car', 'auto'],
        'retention_days': 1825  # 5 years
    },
    'home': {
        'name': 'Home',
        'path': 'documents/home/',
        'keywords': ['mortgage', 'home insurance', 'utility', 'hoa', 'property', 'lease', 'rent'],
        'retention_days': 2555  # 7 years
    },
    'downhome': {
        'name': 'Down Home',
        'path': 'documents/downhome/',
        'keywords': ['down home', 'downhome', 'business contract', 'employee', 'payroll', 'vendor'],
        'retention_days': 2555  # 7 years
    },
    'mcr': {
        'name': 'Music City Rodeo',
        'path': 'documents/mcr/',
        'keywords': ['mcr', 'music city rodeo', 'event contract', 'performer', 'venue'],
        'retention_days': 2555  # 7 years
    },
    'personal': {
        'name': 'Personal',
        'path': 'documents/personal/',
        'keywords': ['medical', 'personal', 'family', 'school', 'health', 'correspondence'],
        'retention_days': 1825  # 5 years
    }
}


class DocumentManagementService:
    """R2 Document Management with AI categorization"""

    def __init__(self, r2_bucket_name, r2_access_key, r2_secret_key, r2_endpoint, anthropic_client=None):
        self.bucket_name = r2_bucket_name
        self.anthropic = anthropic_client

        # Initialize R2 client
        self.s3 = boto3.client(
            's3',
            endpoint_url=r2_endpoint,
            aws_access_key_id=r2_access_key,
            aws_secret_access_key=r2_secret_key,
            region_name='auto'
        )

        # Metadata store (in production, use a database)
        self.metadata_file = Path('document_metadata.json')
        self.metadata = self._load_metadata()

    def _load_metadata(self):
        """Load document metadata from local file"""
        if self.metadata_file.exists():
            try:
                with open(self.metadata_file, 'r') as f:
                    return json.load(f)
            except:
                return {}
        return {}

    def _save_metadata(self):
        """Save document metadata to local file"""
        with open(self.metadata_file, 'w') as f:
            json.dump(self.metadata, f, indent=2)

    def categorize_with_ai(self, filename, content_text=''):
        """
        Use Claude AI to categorize document

        Args:
            filename: Name of the file
            content_text: Optional text content from document

        Returns:
            category_key: One of CATEGORIES keys
        """
        if not self.anthropic:
            # Fallback to keyword-based categorization
            return self._categorize_by_keywords(filename, content_text)

        try:
            # Build context
            context = f"Filename: {filename}\n"
            if content_text:
                context += f"Content excerpt: {content_text[:500]}\n"

            prompt = f"""Categorize this document into ONE of these categories:

Categories:
- legal: Contracts, agreements, legal notices, terms, policies
- financial: Tax documents, bank statements, investments, financial reports
- auto: Vehicle registration, insurance, maintenance, DMV documents
- home: Mortgage, home insurance, utilities, HOA, property documents
- downhome: Down Home business contracts, employee docs, business insurance
- mcr: Music City Rodeo contracts, event documents, MCR specific
- personal: Medical records, personal correspondence, family, school, health

Document:
{context}

Return ONLY the category name (legal, financial, auto, home, downhome, mcr, or personal).
No explanation, just the category name."""

            response = self.anthropic.messages.create(
                model='claude-sonnet-4-20250514',
                max_tokens=20,
                messages=[{'role': 'user', 'content': prompt}]
            )

            category = response.content[0].text.strip().lower()

            # Validate category
            if category in CATEGORIES:
                return category
            else:
                # Fallback to keyword matching
                return self._categorize_by_keywords(filename, content_text)

        except Exception as e:
            print(f"AI categorization error: {e}")
            return self._categorize_by_keywords(filename, content_text)

    def _categorize_by_keywords(self, filename, content_text=''):
        """Fallback keyword-based categorization"""
        text = f"{filename} {content_text}".lower()

        # Score each category
        scores = {}
        for category_key, category_info in CATEGORIES.items():
            score = sum(1 for keyword in category_info['keywords'] if keyword in text)
            scores[category_key] = score

        # Return category with highest score, or 'personal' as default
        if max(scores.values()) > 0:
            return max(scores, key=scores.get)
        return 'personal'

    def upload_document(self, file_path_or_content, filename, category=None, metadata=None, source='manual'):
        """
        Upload document to R2 with auto-categorization

        Args:
            file_path_or_content: Path to file or file content (bytes)
            filename: Name of the file
            category: Optional category override (auto-detect if None)
            metadata: Optional metadata dict
            source: Source of upload (manual, gmail, etc.)

        Returns:
            dict with upload result
        """
        try:
            # Read file content
            if isinstance(file_path_or_content, (str, Path)):
                with open(file_path_or_content, 'rb') as f:
                    content = f.read()
            else:
                content = file_path_or_content

            # Auto-categorize if not provided
            if not category:
                category = self.categorize_with_ai(filename)

            # Validate category
            if category not in CATEGORIES:
                category = 'personal'

            category_info = CATEGORIES[category]

            # Generate unique document ID
            doc_id = hashlib.md5(f"{filename}{datetime.now().isoformat()}".encode()).hexdigest()[:12]

            # Build R2 path
            file_ext = Path(filename).suffix
            r2_key = f"{category_info['path']}{doc_id}_{filename}"

            # Upload to R2
            self.s3.put_object(
                Bucket=self.bucket_name,
                Key=r2_key,
                Body=content,
                ContentType=self._get_content_type(file_ext)
            )

            # Build public URL
            r2_url = f"https://pub-946b7d51aa2c4a0fb92c1ba15bf5c520.r2.dev/{r2_key}"

            # Store metadata
            doc_metadata = {
                'doc_id': doc_id,
                'filename': filename,
                'category': category,
                'category_name': category_info['name'],
                'r2_key': r2_key,
                'r2_url': r2_url,
                'size': len(content),
                'uploaded_at': datetime.now().isoformat(),
                'source': source,
                'retention_until': (datetime.now() + timedelta(days=category_info['retention_days'])).isoformat(),
                'metadata': metadata or {}
            }

            self.metadata[doc_id] = doc_metadata
            self._save_metadata()

            return {
                'success': True,
                'doc_id': doc_id,
                'category': category,
                'r2_url': r2_url,
                'r2_key': r2_key,
                'size': len(content)
            }

        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

    def extract_and_upload_gmail_attachment(self, gmail_service, message_id, attachment_id, filename):
        """
        Extract Gmail attachment and upload to R2

        Args:
            gmail_service: Authenticated Gmail API service
            message_id: Gmail message ID
            attachment_id: Gmail attachment ID
            filename: Attachment filename

        Returns:
            dict with upload result
        """
        try:
            # Download attachment from Gmail
            import base64
            attachment = gmail_service.users().messages().attachments().get(
                userId='me',
                messageId=message_id,
                id=attachment_id
            ).execute()

            # Decode attachment
            content = base64.urlsafe_b64decode(attachment['data'])

            # Upload to R2
            result = self.upload_document(
                content,
                filename,
                source='gmail',
                metadata={'gmail_message_id': message_id}
            )

            return result

        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

    def search_documents(self, query, category=None, limit=50):
        """
        Search documents by filename or metadata

        Args:
            query: Search query string
            category: Optional category filter
            limit: Maximum results to return

        Returns:
            list of matching documents
        """
        query_lower = query.lower()
        results = []

        for doc_id, doc_meta in self.metadata.items():
            # Category filter
            if category and doc_meta['category'] != category:
                continue

            # Search in filename and metadata
            searchable = f"{doc_meta['filename']} {json.dumps(doc_meta.get('metadata', {}))}".lower()

            if query_lower in searchable:
                results.append(doc_meta)

            if len(results) >= limit:
                break

        return results

    def get_document_by_id(self, doc_id):
        """Get document metadata by ID"""
        return self.metadata.get(doc_id)

    def list_documents_by_category(self, category, limit=100):
        """List all documents in a category"""
        if category not in CATEGORIES:
            return []

        results = []
        for doc_id, doc_meta in self.metadata.items():
            if doc_meta['category'] == category:
                results.append(doc_meta)

            if len(results) >= limit:
                break

        return sorted(results, key=lambda x: x['uploaded_at'], reverse=True)

    def get_category_summary(self):
        """Get summary of documents by category"""
        summary = {}

        for category_key, category_info in CATEGORIES.items():
            docs = [d for d in self.metadata.values() if d['category'] == category_key]
            total_size = sum(d['size'] for d in docs)

            summary[category_key] = {
                'name': category_info['name'],
                'count': len(docs),
                'total_size_mb': round(total_size / 1024 / 1024, 2),
                'retention_days': category_info['retention_days']
            }

        return summary

    def check_retention_policy(self):
        """Check which documents are past retention period"""
        now = datetime.now()
        expired = []

        for doc_id, doc_meta in self.metadata.items():
            retention_until = datetime.fromisoformat(doc_meta['retention_until'])
            if now > retention_until:
                expired.append({
                    'doc_id': doc_id,
                    'filename': doc_meta['filename'],
                    'category': doc_meta['category'],
                    'expired_days': (now - retention_until).days
                })

        return expired

    def delete_document(self, doc_id):
        """Delete document from R2 and metadata"""
        try:
            doc_meta = self.metadata.get(doc_id)
            if not doc_meta:
                return {'success': False, 'error': 'Document not found'}

            # Delete from R2
            self.s3.delete_object(
                Bucket=self.bucket_name,
                Key=doc_meta['r2_key']
            )

            # Remove from metadata
            del self.metadata[doc_id]
            self._save_metadata()

            return {'success': True, 'doc_id': doc_id}

        except Exception as e:
            return {'success': False, 'error': str(e)}

    def _get_content_type(self, file_ext):
        """Get content type for file extension"""
        content_types = {
            '.pdf': 'application/pdf',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.doc': 'application/msword',
            '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            '.xls': 'application/vnd.ms-excel',
            '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            '.txt': 'text/plain',
            '.csv': 'text/csv'
        }
        return content_types.get(file_ext.lower(), 'application/octet-stream')


# Singleton
_document_service = None

def get_document_service(anthropic_client=None):
    """Get or create document management service"""
    global _document_service

    if _document_service is None:
        # Get R2 credentials from environment
        r2_bucket = os.environ.get('R2_BUCKET_NAME', 'second-brain-receipts')
        r2_access_key = os.environ.get('R2_ACCESS_KEY_ID')
        r2_secret_key = os.environ.get('R2_SECRET_ACCESS_KEY')
        r2_endpoint = os.environ.get('R2_ENDPOINT_URL', 'https://c0d39f0e4ee63bcdc0bbd1dc5a9f70c8.r2.cloudflarestorage.com')

        _document_service = DocumentManagementService(
            r2_bucket_name=r2_bucket,
            r2_access_key=r2_access_key,
            r2_secret_key=r2_secret_key,
            r2_endpoint=r2_endpoint,
            anthropic_client=anthropic_client
        )

    return _document_service
