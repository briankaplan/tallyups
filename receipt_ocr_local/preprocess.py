"""
Receipt Image Preprocessing - OpenCV Only
Improves receipt images before Vision AI processing
"""
import cv2
import numpy as np
from pathlib import Path
from typing import Tuple, Dict
from PIL import Image, ExifTags

class ReceiptPreprocessor:
    """Preprocesses receipt images using OpenCV"""

    def __init__(self, config):
        self.config = config

    def process(self, image_path: str) -> Tuple[np.ndarray, Dict]:
        """
        Main preprocessing pipeline

        Returns:
            (preprocessed_image, metadata)
        """
        metadata = {
            'original_size': None,
            'final_size': None,
            'rotation_deg': 0,
            'skew_angle': 0.0,
            'steps_applied': []
        }

        # Load with EXIF rotation
        img = self._load_with_exif(image_path)
        metadata['original_size'] = img.shape[:2]

        # Auto-rotate (detect text orientation)
        if self.config.auto_rotate:
            img, rotation = self._auto_rotate(img)
            metadata['rotation_deg'] = rotation
            if rotation != 0:
                metadata['steps_applied'].append(f'rotated_{rotation}deg')

        # Deskew
        if self.config.deskew:
            img, angle = self._deskew(img)
            metadata['skew_angle'] = angle
            if abs(angle) > 0.5:
                metadata['steps_applied'].append(f'deskewed_{angle:.1f}deg')

        # Perspective correction
        if self.config.perspective_correction:
            corrected = self._correct_perspective(img)
            if corrected is not None:
                img = corrected
                metadata['steps_applied'].append('perspective_corrected')

        # Denoise
        if self.config.denoise:
            img = self._denoise(img)
            metadata['steps_applied'].append('denoised')

        # Enhance thermal receipts
        img = self._enhance_thermal(img)

        # Normalize size
        img = self._normalize_size(img)

        # Crop borders
        img = self._crop_borders(img)

        # Enhance contrast
        if self.config.enhance_contrast:
            img = self._enhance_contrast(img)
            metadata['steps_applied'].append('contrast_enhanced')

        metadata['final_size'] = img.shape[:2]

        # Save if requested
        if self.config.save_preprocessed:
            self._save_preprocessed(img, image_path, metadata)

        return img, metadata

    def _load_with_exif(self, image_path: str) -> np.ndarray:
        """Load image and apply EXIF rotation"""
        try:
            pil_img = Image.open(image_path)

            # Check for EXIF orientation
            for orientation in ExifTags.TAGS.keys():
                if ExifTags.TAGS[orientation] == 'Orientation':
                    break

            exif = pil_img._getexif()
            if exif is not None:
                exif = dict(exif.items())
                orientation_value = exif.get(orientation)

                # Apply rotation based on EXIF
                if orientation_value == 3:
                    pil_img = pil_img.rotate(180, expand=True)
                elif orientation_value == 6:
                    pil_img = pil_img.rotate(270, expand=True)
                elif orientation_value == 8:
                    pil_img = pil_img.rotate(90, expand=True)

            # Convert to OpenCV format
            img = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
            return img
        except:
            # Fallback to basic OpenCV load
            return cv2.imread(str(image_path))

    def _auto_rotate(self, img: np.ndarray) -> Tuple[np.ndarray, int]:
        """Detect and correct rotation (0, 90, 180, 270)"""
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # Try each rotation and score text-like features
        best_score = 0
        best_rotation = 0

        for rotation in [0, 90, 180, 270]:
            if rotation == 0:
                rotated = gray
            elif rotation == 90:
                rotated = cv2.rotate(gray, cv2.ROTATE_90_CLOCKWISE)
            elif rotation == 180:
                rotated = cv2.rotate(gray, cv2.ROTATE_180)
            else:  # 270
                rotated = cv2.rotate(gray, cv2.ROTATE_90_COUNTERCLOCKWISE)

            # Score based on horizontal edges (text typically has strong horizontal features)
            edges = cv2.Sobel(rotated, cv2.CV_64F, 0, 1, ksize=3)
            score = np.sum(np.abs(edges))

            if score > best_score:
                best_score = score
                best_rotation = rotation

        # Apply best rotation
        if best_rotation == 0:
            return img, 0
        elif best_rotation == 90:
            return cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE), 90
        elif best_rotation == 180:
            return cv2.rotate(img, cv2.ROTATE_180), 180
        else:
            return cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE), 270

    def _deskew(self, img: np.ndarray) -> Tuple[np.ndarray, float]:
        """Detect and correct skew angle"""
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # Detect edges
        edges = cv2.Canny(gray, 50, 150, apertureSize=3)

        # Hough transform to find lines
        lines = cv2.HoughLines(edges, 1, np.pi/180, 100)

        if lines is None:
            return img, 0.0

        # Calculate dominant angle
        angles = []
        for rho, theta in lines[:, 0]:
            angle = np.degrees(theta) - 90
            if abs(angle) < 45:  # Only consider reasonable skews
                angles.append(angle)

        if not angles:
            return img, 0.0

        # Use median angle
        skew_angle = np.median(angles)

        # Only correct if significant
        if abs(skew_angle) < 0.5:
            return img, skew_angle

        # Rotate to correct skew
        (h, w) = img.shape[:2]
        center = (w // 2, h // 2)
        M = cv2.getRotationMatrix2D(center, skew_angle, 1.0)
        corrected = cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)

        return corrected, skew_angle

    def _correct_perspective(self, img: np.ndarray) -> np.ndarray:
        """Detect and correct perspective distortion"""
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blurred, 50, 150)

        # Find contours
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        if not contours:
            return None

        # Find largest rectangular contour
        max_area = 0
        best_contour = None

        for contour in contours:
            area = cv2.contourArea(contour)
            if area > max_area:
                peri = cv2.arcLength(contour, True)
                approx = cv2.approxPolyDP(contour, 0.02 * peri, True)

                if len(approx) == 4:
                    max_area = area
                    best_contour = approx

        if best_contour is None or max_area < img.shape[0] * img.shape[1] * 0.3:
            return None

        # Get corners
        pts = best_contour.reshape(4, 2)
        rect = self._order_points(pts)

        # Calculate target dimensions
        (tl, tr, br, bl) = rect
        widthA = np.linalg.norm(br - bl)
        widthB = np.linalg.norm(tr - tl)
        maxWidth = max(int(widthA), int(widthB))

        heightA = np.linalg.norm(tr - br)
        heightB = np.linalg.norm(tl - bl)
        maxHeight = max(int(heightA), int(heightB))

        # Perspective transform
        dst = np.array([
            [0, 0],
            [maxWidth - 1, 0],
            [maxWidth - 1, maxHeight - 1],
            [0, maxHeight - 1]
        ], dtype="float32")

        M = cv2.getPerspectiveTransform(rect.astype("float32"), dst)
        warped = cv2.warpPerspective(img, M, (maxWidth, maxHeight))

        return warped

    def _order_points(self, pts):
        """Order points: top-left, top-right, bottom-right, bottom-left"""
        rect = np.zeros((4, 2), dtype="float32")

        s = pts.sum(axis=1)
        rect[0] = pts[np.argmin(s)]
        rect[2] = pts[np.argmax(s)]

        diff = np.diff(pts, axis=1)
        rect[1] = pts[np.argmin(diff)]
        rect[3] = pts[np.argmax(diff)]

        return rect

    def _denoise(self, img: np.ndarray) -> np.ndarray:
        """Remove noise from image"""
        return cv2.fastNlMeansDenoisingColored(img, None, 10, 10, 7, 21)

    def _enhance_thermal(self, img: np.ndarray) -> np.ndarray:
        """Enhance faded thermal receipts"""
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # Check if looks like thermal receipt (light background, faded text)
        mean_brightness = np.mean(gray)

        if mean_brightness > 200:  # Likely thermal receipt
            # Apply aggressive adaptive thresholding
            enhanced = cv2.adaptiveThreshold(
                gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
            )
            # Convert back to BGR
            img = cv2.cvtColor(enhanced, cv2.COLOR_GRAY2BGR)

        return img

    def _normalize_size(self, img: np.ndarray) -> np.ndarray:
        """Resize to target width while maintaining aspect ratio"""
        (h, w) = img.shape[:2]

        if w > self.config.target_width:
            ratio = self.config.target_width / w
            new_height = int(h * ratio)
            img = cv2.resize(img, (self.config.target_width, new_height), interpolation=cv2.INTER_AREA)

        return img

    def _crop_borders(self, img: np.ndarray) -> np.ndarray:
        """Remove empty borders"""
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray, 1, 255, cv2.THRESH_BINARY)

        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        if contours:
            x, y, w, h = cv2.boundingRect(contours[0])
            # Add small padding
            padding = 10
            x = max(0, x - padding)
            y = max(0, y - padding)
            w = min(img.shape[1] - x, w + 2 * padding)
            h = min(img.shape[0] - y, h + 2 * padding)

            img = img[y:y+h, x:x+w]

        return img

    def _enhance_contrast(self, img: np.ndarray) -> np.ndarray:
        """Enhance contrast using CLAHE"""
        lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)

        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        l = clahe.apply(l)

        enhanced = cv2.merge([l, a, b])
        enhanced = cv2.cvtColor(enhanced, cv2.COLOR_LAB2BGR)

        return enhanced

    def _save_preprocessed(self, img: np.ndarray, original_path: str, metadata: Dict):
        """Save preprocessed image"""
        output_dir = Path(self.config.preprocessed_dir)
        output_dir.mkdir(exist_ok=True)

        original_name = Path(original_path).stem
        output_path = output_dir / f"{original_name}_preprocessed.jpg"

        cv2.imwrite(str(output_path), img)
