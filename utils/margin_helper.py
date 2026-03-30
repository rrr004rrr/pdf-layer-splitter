"""Utilities for applying page margin adjustments to PDF files."""

from __future__ import annotations

import fitz

MM_TO_PT = 72.0 / 25.4   # 1 mm ≈ 2.8346 pt


def parse_page_range(spec: str, total: int) -> set[int]:
    """
    Parse a page-range string like "1-3,5,7-9" into a set of 0-based page indices.

    Page numbers in *spec* are 1-based; returned indices are 0-based.
    Out-of-range numbers are silently clamped / ignored.
    """
    indices: set[int] = set()
    for part in spec.split(','):
        part = part.strip()
        if not part:
            continue
        if '-' in part:
            a, _, b = part.partition('-')
            try:
                lo = int(a.strip()) - 1
                hi = int(b.strip()) - 1
                for i in range(max(0, lo), min(total - 1, hi) + 1):
                    indices.add(i)
            except ValueError:
                pass
        else:
            try:
                idx = int(part) - 1
                if 0 <= idx < total:
                    indices.add(idx)
            except ValueError:
                pass
    return indices


def _affected_pages(margin_settings: dict, total: int) -> set[int]:
    """Return the 0-based set of page indices that margins should be applied to."""
    scope = margin_settings.get('scope', 'all')
    if scope == 'all':
        return set(range(total))
    if scope == 'odd':
        return {i for i in range(total) if i % 2 == 0}   # 0-based: page 1,3,5… → 0,2,4…
    if scope == 'even':
        return {i for i in range(total) if i % 2 == 1}   # 0-based: page 2,4,6… → 1,3,5…
    if scope == 'range':
        return parse_page_range(margin_settings.get('pages', ''), total)
    return set()


def apply_margins(pdf_path: str, margin_settings: dict) -> None:
    """
    Apply margin settings to *pdf_path* in-place by adjusting each affected
    page's CropBox.

    margin_settings keys:
        top, bottom, left, right  — floats in mm (default 0)
        scope  — 'all' | 'odd' | 'even' | 'range'
        pages  — page-range string used when scope == 'range'
    """
    top    = margin_settings.get('top',    0.0) * MM_TO_PT
    bottom = margin_settings.get('bottom', 0.0) * MM_TO_PT
    left   = margin_settings.get('left',   0.0) * MM_TO_PT
    right  = margin_settings.get('right',  0.0) * MM_TO_PT

    # Nothing to do if all margins are zero
    if top == 0 and bottom == 0 and left == 0 and right == 0:
        return

    doc = fitz.open(pdf_path)
    affected = _affected_pages(margin_settings, len(doc))

    for i in affected:
        page = doc[i]
        mb = page.mediabox           # full page rect in PDF coordinates
        # PyMuPDF uses top-left origin; CropBox shrinks by adding margins
        new_rect = fitz.Rect(
            mb.x0 + left,
            mb.y0 + top,
            mb.x1 - right,
            mb.y1 - bottom,
        )
        # Guard against degenerate rect
        if new_rect.is_valid and new_rect.width > 0 and new_rect.height > 0:
            page.set_cropbox(new_rect)

    doc.save(pdf_path, incremental=True, encryption=fitz.PDF_ENCRYPT_KEEP)
    doc.close()
