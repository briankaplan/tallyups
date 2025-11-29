"""
Configuration for ReceiptAI Local OCR System
"""
from dataclasses import dataclass
from typing import Optional

@dataclass
class OCRConfig:
    """Configuration for OCR processing"""

    # Donut Model (PRIMARY - 97-98% accuracy)
    use_donut: bool = True
    donut_model_path: Optional[str] = None  # Auto-finds best model if None
    donut_confidence_threshold: float = 0.5  # Below this, try fallback

    # Fallback to ensemble OCR
    fallback_to_ensemble: bool = True

    # Preprocessing options
    auto_rotate: bool = True
    deskew: bool = True
    perspective_correction: bool = True
    denoise: bool = True
    enhance_contrast: bool = True
    target_width: int = 2000

    # OCR Layer (DISABLED - compatibility issues on Python 3.14)
    use_paddle_ocr: bool = False
    paddle_lang: str = 'en'
    paddle_use_gpu: bool = False

    # Vision AI Layer (GPT-4.1 fallback)
    use_vision_ai: bool = True
    vision_backend: str = "gpt41"  # Fallback to GPT-4.1 Vision

    # Output
    save_preprocessed: bool = False
    preprocessed_dir: str = "./receipts_preprocessed"

    # Metadata
    metadata_file: str = "./receipt_preprocessing_metadata.csv"

    @classmethod
    def donut_only(cls):
        """Use only Donut model (fastest, no API costs)"""
        return cls(
            use_donut=True,
            fallback_to_ensemble=False,
            use_vision_ai=False
        )

    @classmethod
    def with_fallback(cls):
        """Donut primary with ensemble + GPT-4.1 fallback (most reliable)"""
        return cls(
            use_donut=True,
            fallback_to_ensemble=True,
            use_vision_ai=True
        )

    @classmethod
    def ensemble_only(cls):
        """Use only ensemble OCR (no Donut)"""
        return cls(
            use_donut=False,
            fallback_to_ensemble=True,
            use_vision_ai=False
        )
