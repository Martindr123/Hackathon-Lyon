from __future__ import annotations

import base64
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

CT_WINDOW_CENTER = -600
CT_WINDOW_WIDTH = 1500

OVERLAY_COLOR = (0, 0, 255)  # red in BGR
OVERLAY_ALPHA = 0.35


def _apply_ct_window(arr: np.ndarray) -> np.ndarray:
    lower = CT_WINDOW_CENTER - CT_WINDOW_WIDTH / 2
    upper = CT_WINDOW_CENTER + CT_WINDOW_WIDTH / 2
    arr = np.clip(arr, lower, upper)
    return ((arr - lower) / (upper - lower) * 255).astype(np.uint8)


def _read_ct_slice(path: Path) -> np.ndarray:
    """Read a single CT DICOM slice and return a windowed uint8 2D array."""
    image = sitk.ReadImage(str(path))
    arr = sitk.GetArrayFromImage(image).astype(np.float32)
    if arr.ndim == 3:
        arr = arr[0]
    return _apply_ct_window(arr)


def _load_seg_volume(seg_path: Path) -> np.ndarray:
    """Load segmentation DICOM and return a boolean 3D array (slices, H, W)."""
    image = sitk.ReadImage(str(seg_path))
    arr = sitk.GetArrayFromImage(image)
    return arr > 0


def _create_overlay(ct_uint8: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Blend a red segmentation mask onto a grayscale CT slice."""
    rgb = cv2.cvtColor(ct_uint8, cv2.COLOR_GRAY2BGR)
    if not mask.any():
        return rgb
    colored = rgb.copy()
    colored[mask] = OVERLAY_COLOR
    return cv2.addWeighted(rgb, 1 - OVERLAY_ALPHA, colored, OVERLAY_ALPHA, 0)


def _to_base64_png(img: np.ndarray) -> str:
    _, png_bytes = cv2.imencode(".png", img)
    return base64.b64encode(png_bytes.tobytes()).decode("utf-8")


def _build_content_parts(msg: PromptMessage) -> list[dict] | str:
    """Convert a PromptMessage into Mistral content format.

    If the message carries a seg_path, CT slices are rendered as overlays
    with the segmentation mask highlighted in red.
    """
    if not msg.image_paths:
        return msg.text or ""

    parts: list[dict] = []
    if msg.text:
        parts.append({"type": "text", "text": msg.text})

    seg_arr = None
    if msg.seg_path:
        try:
            seg_arr = _load_seg_volume(msg.seg_path)
            logger.info("Loaded SEG volume %s, shape %s", msg.seg_path.name, seg_arr.shape)
        except Exception:
            logger.warning("Could not load SEG %s, falling back to plain CT", msg.seg_path)

    for img_path in msg.image_paths:
        ct_slice = _read_ct_slice(img_path)

        if seg_arr is not None and msg.series_files:
            try:
                slice_idx = msg.series_files.index(img_path)
            except ValueError:
                slice_idx = -1

            if 0 <= slice_idx < seg_arr.shape[0]:
                img = _create_overlay(ct_slice, seg_arr[slice_idx])
            else:
                img = cv2.cvtColor(ct_slice, cv2.COLOR_GRAY2BGR)
        else:
            img = ct_slice

        b64 = _to_base64_png(img)
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
