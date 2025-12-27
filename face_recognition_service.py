#!/usr/bin/env python3
"""
Face Recognition Service
Encodes faces from contact photos and matches unknown faces

Features:
- Extract face encodings from contact photos
- Match unknown faces against database
- Identify multiple faces in group photos
- Track face encoding quality and confidence
"""

import os
import io
import asyncio
import logging
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass
from datetime import datetime
import numpy as np
import httpx

# face_recognition requires dlib which can be tricky to install
# pip install face_recognition (requires cmake and dlib)
try:
    import face_recognition
    FACE_RECOGNITION_AVAILABLE = True
except ImportError:
    FACE_RECOGNITION_AVAILABLE = False
    logging.warning("face_recognition not available. Install with: pip install face_recognition")

from PIL import Image

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class FaceMatch:
    """Result of a face match"""
    contact_id: int
    contact_name: str
    confidence: float  # 0-1, higher is better
    distance: float  # Lower is better match
    face_location: Tuple[int, int, int, int]  # (top, right, bottom, left)


@dataclass
class FaceEncoding:
    """Face encoding for a contact"""
    contact_id: int
    encoding: np.ndarray  # 128-dimensional face encoding
    source_photo_id: Optional[int] = None
    created_at: Optional[datetime] = None
    quality_score: float = 1.0  # Quality of the source photo


class FaceRecognitionService:
    """Service for face recognition operations"""

    def __init__(self, atlas_api_url: str):
        self.api_url = atlas_api_url
        self.encoding_cache: Dict[int, np.ndarray] = {}
        self.tolerance = 0.6  # Face distance threshold (lower = stricter)

    def is_available(self) -> bool:
        """Check if face recognition is available"""
        return FACE_RECOGNITION_AVAILABLE

    def encode_face_from_bytes(self, image_bytes: bytes) -> Optional[np.ndarray]:
        """Extract face encoding from image bytes"""
        if not FACE_RECOGNITION_AVAILABLE:
            return None

        try:
            # Load image
            image = face_recognition.load_image_file(io.BytesIO(image_bytes))

            # Find faces
            face_locations = face_recognition.face_locations(image)

            if not face_locations:
                logger.debug("No faces found in image")
                return None

            # Get encoding for first face
            encodings = face_recognition.face_encodings(image, face_locations)

            if encodings:
                return encodings[0]

        except Exception as e:
            logger.error(f"Error encoding face: {e}")

        return None

    def encode_face_from_file(self, file_path: str) -> Optional[np.ndarray]:
        """Extract face encoding from image file"""
        with open(file_path, 'rb') as f:
            return self.encode_face_from_bytes(f.read())

    def encode_face_from_url(self, url: str) -> Optional[np.ndarray]:
        """Extract face encoding from image URL"""
        try:
            import httpx
            response = httpx.get(url, timeout=10.0)
            if response.status_code == 200:
                return self.encode_face_from_bytes(response.content)
        except Exception as e:
            logger.error(f"Error fetching image from URL: {e}")

        return None

    def find_faces_in_image(self, image_bytes: bytes) -> List[Tuple[Tuple[int, int, int, int], np.ndarray]]:
        """Find all faces in an image and return locations + encodings"""
        if not FACE_RECOGNITION_AVAILABLE:
            return []

        try:
            image = face_recognition.load_image_file(io.BytesIO(image_bytes))
            face_locations = face_recognition.face_locations(image)
            face_encodings = face_recognition.face_encodings(image, face_locations)

            return list(zip(face_locations, face_encodings))
        except Exception as e:
            logger.error(f"Error finding faces: {e}")

        return []

    def compare_faces(
        self,
        unknown_encoding: np.ndarray,
        known_encodings: List[Tuple[int, np.ndarray]],  # [(contact_id, encoding), ...]
        tolerance: Optional[float] = None
    ) -> List[FaceMatch]:
        """Compare unknown face against known faces"""
        if not FACE_RECOGNITION_AVAILABLE:
            return []

        if tolerance is None:
            tolerance = self.tolerance

        matches = []

        known_enc_array = np.array([enc for _, enc in known_encodings])

        if len(known_enc_array) == 0:
            return []

        # Calculate distances
        distances = face_recognition.face_distance(known_enc_array, unknown_encoding)

        for i, (contact_id, _) in enumerate(known_encodings):
            distance = distances[i]

            if distance < tolerance:
                # Convert distance to confidence (0-1, higher is better)
                confidence = 1 - (distance / tolerance)

                matches.append(FaceMatch(
                    contact_id=contact_id,
                    contact_name="",  # Will be filled in later
                    confidence=confidence,
                    distance=distance,
                    face_location=(0, 0, 0, 0)  # Will be filled in for group photos
                ))

        # Sort by confidence (highest first)
        matches.sort(key=lambda m: m.confidence, reverse=True)

        return matches

    async def load_known_encodings(self) -> List[Tuple[int, np.ndarray]]:
        """Load all known face encodings from ATLAS"""
        encodings = []

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.api_url}/face-encodings",
                params={"limit": 10000}
            )

            if response.status_code == 200:
                data = response.json()

                for item in data.get("items", []):
                    contact_id = item.get("contact_id")
                    encoding_data = item.get("encoding")

                    if contact_id and encoding_data:
                        # Convert from stored format back to numpy array
                        encoding = np.array(encoding_data)
                        encodings.append((contact_id, encoding))
                        self.encoding_cache[contact_id] = encoding

        logger.info(f"Loaded {len(encodings)} face encodings")
        return encodings

    async def identify_faces(
        self,
        image_bytes: bytes,
        min_confidence: float = 0.5
    ) -> List[Dict[str, Any]]:
        """Identify all faces in an image against known contacts"""

        # Load known encodings if not cached
        if not self.encoding_cache:
            known_encodings = await self.load_known_encodings()
        else:
            known_encodings = [(cid, enc) for cid, enc in self.encoding_cache.items()]

        # Find all faces in image
        faces = self.find_faces_in_image(image_bytes)

        results = []

        for location, encoding in faces:
            top, right, bottom, left = location

            # Find matches
            matches = self.compare_faces(encoding, known_encodings)

            if matches and matches[0].confidence >= min_confidence:
                best_match = matches[0]

                # Get contact name
                contact_name = await self._get_contact_name(best_match.contact_id)

                results.append({
                    "location": {
                        "top": top,
                        "right": right,
                        "bottom": bottom,
                        "left": left
                    },
                    "match": {
                        "contact_id": best_match.contact_id,
                        "contact_name": contact_name,
                        "confidence": round(best_match.confidence, 3),
                        "distance": round(best_match.distance, 3)
                    }
                })
            else:
                results.append({
                    "location": {
                        "top": top,
                        "right": right,
                        "bottom": bottom,
                        "left": left
                    },
                    "match": None
                })

        return results

    async def identify_single_face(
        self,
        image_bytes: bytes
    ) -> Optional[Dict[str, Any]]:
        """Identify a single face (for profile photos)"""
        results = await self.identify_faces(image_bytes)

        if results:
            return results[0]

        return None

    async def encode_and_store(
        self,
        contact_id: int,
        image_bytes: bytes,
        source_photo_id: Optional[int] = None
    ) -> bool:
        """Encode a face and store it for a contact"""

        encoding = self.encode_face_from_bytes(image_bytes)

        if encoding is None:
            logger.warning(f"Could not encode face for contact {contact_id}")
            return False

        # Store encoding
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.api_url}/contacts/{contact_id}/face-encoding",
                json={
                    "encoding": encoding.tolist(),
                    "source_photo_id": source_photo_id
                }
            )

            if response.status_code in (200, 201):
                self.encoding_cache[contact_id] = encoding
                logger.info(f"Stored face encoding for contact {contact_id}")
                return True

        return False

    async def encode_all_contacts(self) -> Dict[str, int]:
        """Encode faces for all contacts with photos"""
        stats = {"total": 0, "encoded": 0, "no_face": 0, "errors": 0}

        async with httpx.AsyncClient() as client:
            # Get contacts with photos but no encoding
            response = await client.get(
                f"{self.api_url}/contacts",
                params={"has_photo": True, "has_face_encoding": False, "page_size": 100}
            )

            if response.status_code != 200:
                return stats

            contacts = response.json().get("items", [])
            stats["total"] = len(contacts)

            for contact in contacts:
                contact_id = contact.get("id")
                photo_url = contact.get("photo_url")

                if not photo_url:
                    continue

                try:
                    # Fetch photo
                    img_response = await client.get(photo_url, timeout=10.0)

                    if img_response.status_code == 200:
                        if await self.encode_and_store(contact_id, img_response.content):
                            stats["encoded"] += 1
                        else:
                            stats["no_face"] += 1
                    else:
                        stats["errors"] += 1

                except Exception as e:
                    logger.error(f"Error encoding contact {contact_id}: {e}")
                    stats["errors"] += 1

        return stats

    async def _get_contact_name(self, contact_id: int) -> str:
        """Get contact name by ID"""
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{self.api_url}/contacts/{contact_id}")

            if response.status_code == 200:
                contact = response.json()
                return contact.get("display_name", f"Contact {contact_id}")

        return f"Contact {contact_id}"

    def annotate_image(
        self,
        image_bytes: bytes,
        face_results: List[Dict[str, Any]]
    ) -> bytes:
        """Annotate image with face recognition results"""
        from PIL import Image, ImageDraw, ImageFont

        # Load image
        image = Image.open(io.BytesIO(image_bytes))
        draw = ImageDraw.Draw(image)

        # Try to load a font
        try:
            font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 20)
        except:
            font = ImageFont.load_default()

        for result in face_results:
            loc = result["location"]
            match = result.get("match")

            top, right, bottom, left = loc["top"], loc["right"], loc["bottom"], loc["left"]

            if match:
                # Known face - green box
                color = "green"
                label = f"{match['contact_name']} ({match['confidence']:.0%})"
            else:
                # Unknown face - red box
                color = "red"
                label = "Unknown"

            # Draw rectangle
            draw.rectangle([(left, top), (right, bottom)], outline=color, width=3)

            # Draw label background
            text_bbox = draw.textbbox((left, bottom), label, font=font)
            draw.rectangle([text_bbox[0]-2, text_bbox[1]-2, text_bbox[2]+2, text_bbox[3]+2], fill=color)

            # Draw label
            draw.text((left, bottom), label, fill="white", font=font)

        # Save to bytes
        output = io.BytesIO()
        image.save(output, format="JPEG")
        return output.getvalue()


# =============================================================================
# CLI
# =============================================================================

async def main():
    import argparse

    parser = argparse.ArgumentParser(description="ATLAS Face Recognition")
    parser.add_argument("command", choices=["encode-all", "identify", "test"])
    parser.add_argument("--api-url", default=os.getenv("ATLAS_API_URL", "http://localhost:8000"))
    parser.add_argument("--image", help="Image file to identify faces in")
    parser.add_argument("--output", help="Output file for annotated image")

    args = parser.parse_args()

    service = FaceRecognitionService(args.api_url)

    if not service.is_available():
        print("Error: face_recognition library not available")
        print("Install with: pip install face_recognition")
        return

    if args.command == "encode-all":
        stats = await service.encode_all_contacts()
        print(f"Face encoding complete:")
        print(f"  Total: {stats['total']}")
        print(f"  Encoded: {stats['encoded']}")
        print(f"  No face found: {stats['no_face']}")
        print(f"  Errors: {stats['errors']}")

    elif args.command == "identify" and args.image:
        with open(args.image, 'rb') as f:
            image_bytes = f.read()

        results = await service.identify_faces(image_bytes)

        print(f"Found {len(results)} faces:")
        for i, result in enumerate(results):
            match = result.get("match")
            if match:
                print(f"  Face {i+1}: {match['contact_name']} ({match['confidence']:.0%} confidence)")
            else:
                print(f"  Face {i+1}: Unknown")

        if args.output:
            annotated = service.annotate_image(image_bytes, results)
            with open(args.output, 'wb') as f:
                f.write(annotated)
            print(f"Annotated image saved to {args.output}")

    elif args.command == "test":
        print("Face recognition is working!")
        print(f"Available: {service.is_available()}")


if __name__ == "__main__":
    asyncio.run(main())
