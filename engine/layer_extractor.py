"""
High-level layer extraction orchestrator.

Provides ProcessingEngine – the single class the GUI calls to run
the full text-layer + background-layer pipeline.

Processing flow
---------------
1. Validate that the PDF is not encrypted.
2. For each page:
   a. Text layer  – filter content stream to BT…ET only, prepend white bg.
   b. Background  – filter content stream to remove BT…ET, run mask resolver.
      The final rendered image for each page is embedded into bg_layer.pdf.
3. Save text_layer.pdf and bg_layer.pdf to output_dir.
"""

from __future__ import annotations

import io
import os
import threading
from typing import Callable

import fitz
import numpy as np
from PIL import Image

from .pdf_parser import filter_text_layer, filter_bg_layer, tokenize, tokens_to_bytes
from .image_comparator import render_page
from .mask_resolver import resolve_page
from utils.logger import logger
from utils.file_helper import is_encrypted
from utils.margin_helper import apply_margins

# ---------------------------------------------------------------------------
# Callback type
# ---------------------------------------------------------------------------
# phase     : 'text_layer' | 'bg_layer' | 'done' | 'error'
# page      : 0-based page index being processed
# total     : total number of pages
# ref_img   : current reference image (or None for text_layer phase)
# cand_img  : candidate image (or None)
# heatmap   : diff heatmap (or None)
# ssim      : SSIM score (or 0.0)
# action    : 'remove' | 'partial_mask' | 'keep' | 'extracting' | ...
ProgressCallback = Callable[
    [str, int, int, "np.ndarray|None", "np.ndarray|None", "np.ndarray|None", float, str],
    None,
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _copy_doc(orig: fitz.Document) -> fitz.Document:
    """Return an in-memory copy of a PyMuPDF document."""
    buf = io.BytesIO()
    orig.save(buf)
    buf.seek(0)
    return fitz.open(stream=buf, filetype='pdf')


def _get_tokens(doc: fitz.Document, page: fitz.Page) -> list[str]:
    """Return the tokenised content stream of a page (cleans first)."""
    page.clean_contents()
    contents = page.get_contents()
    if not contents:
        return []
    raw = doc.xref_stream(contents[0])
    return tokenize(raw)


def _set_tokens(doc: fitz.Document, page: fitz.Page, tokens: list[str]) -> None:
    """Write tokens as the page's content stream."""
    page.clean_contents()
    contents = page.get_contents()
    data = tokens_to_bytes(tokens)
    if contents:
        doc.update_stream(contents[0], data)


def _img_to_pdf_page(out_doc: fitz.Document, img_array: np.ndarray,
                      width: float, height: float) -> None:
    """Embed an RGB numpy image into a new page of out_doc."""
    new_page = out_doc.new_page(width=width, height=height)
    pil_img = Image.fromarray(img_array)
    buf = io.BytesIO()
    pil_img.save(buf, format='PNG')
    buf.seek(0)
    rect = fitz.Rect(0, 0, width, height)
    new_page.insert_image(rect, stream=buf.getvalue())


# ---------------------------------------------------------------------------
# ProcessingEngine
# ---------------------------------------------------------------------------

class ProcessingEngine:
    """
    Orchestrates text-layer and background-layer extraction.

    Thread-safe: call start() from any thread; it spawns a worker thread
    and posts updates via the callback.  Call cancel() to request early stop.
    """

    def __init__(
        self,
        dpi: int = 300,
        ssim_threshold: float = 0.95,
        max_iterations: int = 200,
        output_dir: str | None = None,
        parallel_pages: bool = False,
        margin_settings: dict | None = None,
    ):
        self.dpi = dpi
        self.ssim_threshold = ssim_threshold
        self.max_iterations = max_iterations
        self.output_dir = output_dir
        self.parallel_pages = parallel_pages
        self.margin_settings = margin_settings or {}
        self._cancelled = threading.Event()
        self._worker: threading.Thread | None = None

    # ------------------------------------------------------------------ #
    #  Public control
    # ------------------------------------------------------------------ #

    def start(
        self,
        input_path: str,
        callback: ProgressCallback | None = None,
    ) -> None:
        """Start processing in a background thread."""
        self._cancelled.clear()
        self._worker = threading.Thread(
            target=self._run,
            args=(input_path, callback),
            daemon=True,
        )
        self._worker.start()

    def cancel(self) -> None:
        """Request cancellation of the running job."""
        self._cancelled.set()

    def is_running(self) -> bool:
        return self._worker is not None and self._worker.is_alive()

    # ------------------------------------------------------------------ #
    #  Internal worker
    # ------------------------------------------------------------------ #

    def _run(self, input_path: str, callback: ProgressCallback | None) -> None:
        try:
            self._process(input_path, callback)
        except Exception as exc:
            logger.error(f"Processing failed: {exc}")
            if callback:
                callback('error', 0, 0, None, None, None, 0.0, str(exc))

    def _process(self, input_path: str, cb: ProgressCallback | None) -> None:
        if is_encrypted(input_path):
            raise ValueError("不支援加密 PDF（Encrypted PDF is not supported）")

        out_dir = self.output_dir or os.path.dirname(os.path.abspath(input_path))
        base = os.path.splitext(os.path.basename(input_path))[0]
        text_out = os.path.join(out_dir, f"{base}_text_layer.pdf")
        bg_out   = os.path.join(out_dir, f"{base}_bg_layer.pdf")

        logger.info(f"Opening: {input_path}")
        orig_doc = fitz.open(input_path)
        n = len(orig_doc)

        # ---- Phase 1: text layer ----------------------------------------
        logger.info("Phase 1: Extracting text layer …")
        text_doc = _copy_doc(orig_doc)
        for i in range(n):
            if self._cancelled.is_set():
                orig_doc.close(); text_doc.close()
                return
            page = text_doc[i]
            rect = page.rect
            tokens = _get_tokens(text_doc, page)
            text_toks = filter_text_layer(tokens)
            # White background rect before text
            bg_ops = [
                '1', '1', '1', 'rg',
                '0', '0', str(round(rect.width, 2)), str(round(rect.height, 2)), 're',
                'f',
            ]
            _set_tokens(text_doc, page, bg_ops + text_toks)
            logger.info(f"  Text layer page {i+1}/{n}")
            if cb:
                cb('text_layer', i, n, None, None, None, 0.0, 'extracting')

        text_doc.save(text_out, garbage=4, deflate=True)
        text_doc.close()
        logger.info(f"Text layer saved → {text_out}")
        if self.margin_settings:
            apply_margins(text_out, self.margin_settings)
            logger.info(f"Margins applied to text layer")

        # ---- Phase 2: background layer with mask resolver ----------------
        logger.info("Phase 2: Extracting background layer …")
        bg_out_doc = fitz.open()

        for i in range(n):
            if self._cancelled.is_set():
                break

            logger.info(f"  Background page {i+1}/{n}: removing text …")

            # Build a working copy for this page's mask-resolver run
            work_doc = _copy_doc(orig_doc)
            work_page = work_doc[i]
            tokens = _get_tokens(work_doc, work_page)
            bg_toks = filter_bg_layer(tokens)
            _set_tokens(work_doc, work_page, bg_toks)

            # Iteration callback – forwards images to the GUI callback
            def _iter_cb(ref_img, cand_img, heatmap, score, action, iteration,
                         _page=i, _n=n):
                logger.debug(
                    f"    p{_page+1} iter={iteration} ssim={score:.4f} action={action}"
                )
                if cb:
                    cb('bg_layer', _page, _n, ref_img, cand_img, heatmap, score, action)

            final_img = resolve_page(
                work_doc, i,
                dpi=self.dpi,
                ssim_threshold=self.ssim_threshold,
                max_iterations=self.max_iterations,
                callback=_iter_cb,
            )
            work_doc.close()

            orig_rect = orig_doc[i].rect
            _img_to_pdf_page(bg_out_doc, final_img, orig_rect.width, orig_rect.height)
            logger.info(f"  Background page {i+1}/{n} done.")

        bg_out_doc.save(bg_out, deflate=True)
        bg_out_doc.close()
        orig_doc.close()

        logger.info(f"Background layer saved → {bg_out}")
        if self.margin_settings:
            apply_margins(bg_out, self.margin_settings)
            logger.info(f"Margins applied to background layer")
        if cb:
            cb('done', n - 1, n, None, None, None, 1.0, f"{text_out}\n{bg_out}")
