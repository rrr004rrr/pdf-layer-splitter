"""
Mask-removal loop (core algorithm).

For a single PDF page (with text already removed) this module:
  1. Identifies q…Q blocks in the content stream.
  2. Tries removing each block and measures the visual impact via SSIM.
  3. If SSIM ≥ threshold after removal  → the block was a clipping artifact; keep removed.
  4. If SSIM < threshold                → try partial masking (white rects over diff area).
  5. If still < threshold               → restore the block.
  6. Repeats until no more blocks can be removed or max_iterations is reached.
  7. Returns the final rendered background image.
"""

from __future__ import annotations

import io
from typing import Callable

import cv2
import fitz
import numpy as np
from PIL import Image

from .pdf_parser import (
    find_q_blocks,
    tokenize,
    tokens_to_bytes,
)
from .image_comparator import compare_images, build_diff_mask, render_page

# Type alias for the per-iteration callback
IterationCallback = Callable[
    [
        np.ndarray,  # ref_img
        np.ndarray,  # cand_img
        np.ndarray,  # heatmap
        float,       # ssim_score
        str,         # action: 'remove' | 'partial_mask' | 'keep'
        int,         # iteration index (0-based)
    ],
    None,
]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_page_xref_and_tokens(doc: fitz.Document, page_index: int) -> tuple[int, list[str]]:
    """Clean the page's content streams and return (xref, tokens)."""
    page = doc[page_index]
    page.clean_contents()
    contents = page.get_contents()
    if not contents:
        return -1, []
    xref = contents[0]
    raw = doc.xref_stream(xref)
    return xref, tokenize(raw)


def _set_tokens(doc: fitz.Document, xref: int, tokens: list[str]) -> None:
    doc.update_stream(xref, tokens_to_bytes(tokens))


def _build_white_rect_tokens(
    diff_mask: np.ndarray,
    page: fitz.Page,
    img_shape: tuple[int, int],  # (H, W)
    padding: float = 4.0,
) -> list[str]:
    """
    Given a binary diff mask (H×W), compute bounding boxes of connected
    difference regions in PDF user-space and return PDF operators that draw
    white filled rectangles over them.
    """
    rect = page.rect
    page_w, page_h = rect.width, rect.height
    img_h, img_w = img_shape

    sx = page_w / img_w
    sy = page_h / img_h

    contours, _ = cv2.findContours(diff_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return []

    ops: list[str] = ['q', '1', '1', '1', 'rg']  # save state + white fill
    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        # PDF coordinates: origin bottom-left, y increases upward
        pdf_x = x * sx - padding
        pdf_y = page_h - (y + h) * sy - padding
        pdf_w = w * sx + padding * 2
        pdf_h = h * sy + padding * 2
        ops += [
            str(round(pdf_x, 2)),
            str(round(pdf_y, 2)),
            str(round(pdf_w, 2)),
            str(round(pdf_h, 2)),
            're',
        ]
    ops += ['f', 'Q']  # fill + restore state
    return ops


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def resolve_page(
    doc: fitz.Document,
    page_index: int,
    dpi: int = 300,
    ssim_threshold: float = 0.95,
    max_iterations: int = 200,
    callback: IterationCallback | None = None,
) -> np.ndarray:
    """
    Run the mask-removal loop on *page_index* of *doc*.

    *doc* must already have text removed from this page before calling.
    The document's content stream for the page will be modified in-place
    during processing and left in its final cleaned state.

    Returns
    -------
    np.ndarray
        RGB uint8 image of the final clean background at *dpi*.
    """
    xref, tokens = _get_page_xref_and_tokens(doc, page_index)

    if xref == -1:
        # Empty page – just render blank
        return render_page(doc, page_index, dpi)

    # Ensure the doc reflects the current (text-removed) token state
    _set_tokens(doc, xref, tokens)
    ref_img = render_page(doc, page_index, dpi)

    iteration = 0
    any_removed = True

    while any_removed and iteration < max_iterations:
        any_removed = False
        q_blocks = find_q_blocks(tokens)

        for start, end in q_blocks:
            if iteration >= max_iterations:
                break
            iteration += 1

            # ---- Trial 1: remove block entirely -------------------------
            cand_tokens = tokens[:start] + tokens[end:]
            _set_tokens(doc, xref, cand_tokens)
            cand_img = render_page(doc, page_index, dpi)
            score, heatmap = compare_images(ref_img, cand_img)

            if score >= ssim_threshold:
                # Block confirmed as artifact – keep removal
                tokens = cand_tokens
                ref_img = cand_img
                any_removed = True
                if callback:
                    callback(ref_img, cand_img, heatmap, score, 'remove', iteration)
                break  # restart the outer loop with updated tokens

            # ---- Trial 2: partial masking (white rects over diff area) --
            diff_mask = build_diff_mask(ref_img, cand_img)
            page_obj = doc[page_index]
            white_ops = _build_white_rect_tokens(diff_mask, page_obj, ref_img.shape[:2])

            if white_ops:
                partial_tokens = cand_tokens + white_ops
                _set_tokens(doc, xref, partial_tokens)
                partial_img = render_page(doc, page_index, dpi)
                partial_score, partial_heatmap = compare_images(ref_img, partial_img)

                if partial_score >= ssim_threshold:
                    tokens = partial_tokens
                    ref_img = partial_img
                    any_removed = True
                    if callback:
                        callback(ref_img, partial_img, partial_heatmap,
                                 partial_score, 'partial_mask', iteration)
                    break

            # ---- Restore and continue to next block ---------------------
            _set_tokens(doc, xref, tokens)
            if callback:
                callback(ref_img, cand_img, heatmap, score, 'keep', iteration)

    # Leave document in final state
    _set_tokens(doc, xref, tokens)
    return ref_img
