from __future__ import annotations

import base64
import io
import os
import time
import logging
from pathlib import Path

import numpy as np
import SimpleITK as sitk
import cv2
from dotenv import load_dotenv
from mistralai import Mistral

from src.services.llm_prompt_service import LLMPrompt, PromptMessage

load_dotenv()
logger = logging.getLogger(__name__)

DEFAULT_MODEL = "mistral-small-latest"
MAX_RETRIES = 3
RETRY_DELAY_S = 2

# CT lung window (good default for pulmonary nodules)
CT_WINDOW_CENTER = -600
CT_WINDOW_WIDTH = 1500


def _dicom_to_base64_png(path: Path) -> str:
    """Read a DICOM file and return a base64-encoded PNG string."""
    image = sitk.ReadImage(str(path))
    arr = sitk.GetArrayFromImage(image).astype(np.float32)
    if arr.ndim == 3:
        arr = arr[0]

    # Apply CT windowing
    lower = CT_WINDOW_CENTER - CT_WINDOW_WIDTH / 2
    upper = CT_WINDOW_CENTER + CT_WINDOW_WIDTH / 2
    arr = np.clip(arr, lower, upper)
    arr = ((arr - lower) / (upper - lower) * 255).astype(np.uint8)

    _, png_bytes = cv2.imencode(".png", arr)
    return base64.b64encode(png_bytes.tobytes()).decode("utf-8")


def _build_content_parts(msg: PromptMessage) -> list[dict] | str:
    """Convert a PromptMessage into Mistral content format."""
    if not msg.image_paths:
        return msg.text or ""

    parts: list[dict] = []
    if msg.text:
        parts.append({"type": "text", "text": msg.text})

    for img_path in msg.image_paths:
        b64 = _dicom_to_base64_png(img_path)
        parts.append({
            "type": "image_url",
            "image_url": f"data:image/png;base64,{b64}",
        })

    return parts


class LLMService:
    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
    ):
        self._api_key = api_key or os.getenv("API_KEY")
        if not self._api_key:
            raise ValueError(
                "Mistral API key not found. Set API_KEY in .env or pass it explicitly."
            )
        self._model = model
        self._client = Mistral(api_key=self._api_key)

    def send(self, prompt: LLMPrompt) -> str:
        """Send an LLMPrompt to Mistral and return the assistant's text response."""
        messages = self._format_messages(prompt)

        logger.info(
            "Sending prompt to %s (%d messages, %d images)",
            self._model,
            len(messages),
            len(prompt.all_image_paths),
        )

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = self._client.chat.complete(
                    model=self._model,
                    messages=messages,
                )
                content = response.choices[0].message.content
                logger.info(
                    "Response received (%d tokens prompt, %d tokens completion)",
                    response.usage.prompt_tokens,
                    response.usage.completion_tokens,
                )
                return content
            except Exception as exc:
                logger.warning("Attempt %d/%d failed: %s", attempt, MAX_RETRIES, exc)
                if attempt == MAX_RETRIES:
                    raise
                time.sleep(RETRY_DELAY_S * attempt)

    def _format_messages(self, prompt: LLMPrompt) -> list[dict]:
        formatted: list[dict] = []
        for msg in prompt.messages:
            formatted.append({
                "role": msg.role,
                "content": _build_content_parts(msg),
            })
        return formatted
