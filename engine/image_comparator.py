"""
Image comparison utilities.

Provides:
  - render_page()        – render a fitz page to an RGB numpy array
  - compare_images()     – compute SSIM and return a diff heatmap
"""

from __future__ import annotations

import numpy as np
import cv2
import fitz
from skimage.metrics import structural_similarity as _ssim


def render_page(doc: fitz.Document, page_index: int, dpi: int = 300) -> np.ndarray:
    """
    Render *page_index* of *doc* at *dpi* and return an (H, W, 3) uint8 RGB array.
    """
    page = doc[page_index]
    mat = fitz.Matrix(dpi / 72.0, dpi / 72.0)
    pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB, alpha=False)
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
    return arr.copy()


def compare_images(
    ref_img: np.ndarray,
    cand_img: np.ndarray,
) -> tuple[float, np.ndarray]:
    """
    Compare two RGB images with SSIM.

    Returns
    -------
    score : float
        SSIM in [0, 1].  1 = identical.
    heatmap : np.ndarray
        RGB uint8 heatmap where differences are shown in red/orange.
    """
    # Resize candidate to reference size if they differ (shouldn't normally happen)
    if ref_img.shape != cand_img.shape:
        cand_img = cv2.resize(cand_img, (ref_img.shape[1], ref_img.shape[0]))

    gray_ref  = cv2.cvtColor(ref_img,  cv2.COLOR_RGB2GRAY)
    gray_cand = cv2.cvtColor(cand_img, cv2.COLOR_RGB2GRAY)

    score, diff_map = _ssim(gray_ref, gray_cand, full=True)

    # diff_map ∈ [-1, 1]; 1 = same, lower = more different
    # Map to [0, 255] where 255 = maximally different
    diff_uint8 = np.clip((1.0 - diff_map) * 127.5, 0, 255).astype(np.uint8)

    heatmap_bgr = cv2.applyColorMap(diff_uint8, cv2.COLORMAP_HOT)
    heatmap_rgb = cv2.cvtColor(heatmap_bgr, cv2.COLOR_BGR2RGB)

    return float(score), heatmap_rgb


def build_diff_mask(
    ref_img: np.ndarray,
    cand_img: np.ndarray,
    threshold: int = 10,
) -> np.ndarray:
    """
    Return a binary mask (uint8, 0 or 255) of pixels that differ
    between ref_img and cand_img by more than *threshold*.
    """
    if ref_img.shape != cand_img.shape:
        cand_img = cv2.resize(cand_img, (ref_img.shape[1], ref_img.shape[0]))
    diff = cv2.absdiff(ref_img, cand_img)
    gray = cv2.cvtColor(diff, cv2.COLOR_RGB2GRAY)
    _, mask = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY)
    return mask
