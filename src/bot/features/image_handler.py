"""
Handle image uploads for Claude vision analysis.

Downloads images from Telegram, converts to base64, and builds
prompts for Claude's multimodal input.
"""

import base64
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, Dict, Optional

from telegram import PhotoSize

from src.config import Settings


@dataclass
class ProcessedImage:
    """Processed image result"""

    prompt: str
    base64_data: str
    size: int
    metadata: Dict[str, str] = field(default_factory=dict)


class ImageHandler:
    """Process image uploads for Claude vision analysis."""

    def __init__(self, config: Settings):
        self.config = config

    async def process_image(
        self,
        photo: PhotoSize,
        caption: Optional[str] = None,
        on_progress: Optional[Callable[[str], Awaitable[None]]] = None,
    ) -> ProcessedImage:
        """Download and process an uploaded image."""
        if on_progress:
            await on_progress("downloading")
        file = await photo.get_file()
        image_bytes = await file.download_as_bytearray()

        # Validate
        if on_progress:
            await on_progress("validating")
        valid, error = self._validate_image(image_bytes)
        if not valid:
            raise ValueError(error)

        if on_progress:
            await on_progress("encoding")
        img_format = self._detect_format(image_bytes)
        base64_image = base64.b64encode(image_bytes).decode("utf-8")

        # Build prompt - keep it simple, Claude can see the image
        if caption:
            prompt = caption
        else:
            prompt = "Please analyze this image and describe what you see."

        return ProcessedImage(
            prompt=prompt,
            base64_data=base64_image,
            size=len(image_bytes),
            metadata={"format": img_format},
        )

    def _detect_format(self, image_bytes: bytes) -> str:
        """Detect image format from magic bytes."""
        if image_bytes.startswith(b"\x89PNG"):
            return "png"
        elif image_bytes.startswith(b"\xff\xd8\xff"):
            return "jpeg"
        elif image_bytes.startswith(b"GIF87a") or image_bytes.startswith(b"GIF89a"):
            return "gif"
        elif image_bytes.startswith(b"RIFF") and b"WEBP" in image_bytes[:12]:
            return "webp"
        return "jpeg"  # Default to jpeg for unknown formats

    def _validate_image(self, image_bytes: bytes) -> tuple[bool, Optional[str]]:
        """Validate image data."""
        max_size = 10 * 1024 * 1024  # 10MB
        if len(image_bytes) > max_size:
            return False, "Image too large (max 10MB)"
        if len(image_bytes) < 100:
            return False, "Invalid image data"
        return True, None

    @staticmethod
    def cleanup_old_images(base_directory: Path, max_age_hours: int) -> int:
        """Delete stale files under `.claude-images` and return deleted count."""
        images_dir = base_directory / ".claude-images"
        if not images_dir.exists() or not images_dir.is_dir():
            return 0

        max_age_seconds = max(1, int(max_age_hours)) * 3600
        cutoff = time.time() - max_age_seconds
        deleted = 0

        for file_path in images_dir.rglob("*"):
            if not file_path.is_file():
                continue
            try:
                if file_path.stat().st_mtime < cutoff:
                    file_path.unlink()
                    deleted += 1
            except OSError:
                continue

        # Best effort: prune empty directories after file cleanup.
        for directory in sorted(
            [path for path in images_dir.rglob("*") if path.is_dir()],
            reverse=True,
        ):
            try:
                directory.rmdir()
            except OSError:
                continue

        return deleted
