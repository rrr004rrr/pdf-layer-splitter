# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A Windows desktop tool that splits a PDF into two output files:
- **Text layer** (`text_layer.pdf`): pure text only, no background images or clipping masks
- **Background layer** (`bg_layer.pdf`): visual background graphics only, no text, with clipping mask artifacts removed

The core challenge is handling **clipping masks** — after removal, previously hidden pixels re-appear as noise. The tool uses an iterative SSIM-based comparison loop to detect and suppress this noise until similarity ≥ 95%.

Input: unencrypted PDFs (textbooks with Traditional Chinese, English, and numerals).
Target: Windows 10/11 x64, distributed as a single `.exe` via PyInstaller.

## Development Setup

```bash
# Create virtual environment (recommended to minimize exe size)
python -m venv venv
venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run the application
python main.py
```

## Build (PyInstaller)

```bash
# Must be run on Windows — pymupdf contains C extensions, no cross-compilation
pyinstaller build.spec
# Output: dist/PDF_Splitter.exe (~150–250 MB)
```

Key `build.spec` flags:
- `onefile=True`, `windowed=True` (no cmd window)
- `--collect-submodules cv2` required for opencv-python
- May need `--hidden-import tkinter` on some Python distributions

## Architecture

```
pdf_splitter/
├── main.py                 # Entry point, GUI init
├── gui/
│   ├── main_window.py      # Main window layout and event binding
│   ├── preview_panel.py    # Left panel: per-page thumbnail list
│   ├── compare_panel.py    # Center: 3-panel Reference/Candidate/Diff display
│   ├── settings_dialog.py  # Engine parameter settings dialog
│   └── margin_dialog.py    # Page margin settings dialog (mm, per-scope)
├── engine/
│   ├── pdf_parser.py       # Content-stream tokenizer and layer filters
│   ├── layer_extractor.py  # Text/background layer extraction orchestrator
│   ├── mask_resolver.py    # Clipping mask removal loop (core algorithm)
│   └── image_comparator.py # SSIM comparison and diff heatmap generation
└── utils/
    ├── logger.py
    ├── file_helper.py
    └── margin_helper.py    # CropBox margin application (mm → pt, page scope)
```

## Core Algorithm: Mask Resolver Loop

Implemented in `engine/mask_resolver.py`. Runs **per page independently**:

1. Render page at 300 DPI → **Reference Image**
2. For each component (XObject / Path / Clipping Group):
   - Temporarily remove it and re-render → **Candidate Image**
   - Compute SSIM + pixel diff heatmap
   - SSIM ≥ 0.95 → confirm removal, update Reference, continue
   - SSIM < 0.95 → try partial masking (white rect over diff area), re-compare
   - Still < 0.95 → restore component, continue
3. Output final Reference as background layer page

Convergence condition: final SSIM ≥ 0.95 vs. initial text-removed Reference. Pages that fail convergence are flagged with a warning (yellow marker) but processing continues.

## PDF Object Classification

| Object type | PDF Operator | Text layer | Background layer |
|-------------|-------------|-----------|-----------------|
| Text objects | `BT...ET` | keep | remove |
| Image XObjects | `Do` | remove | keep |
| White fill paths (masks) | `f / F / f*` (white fill) | keep as white rect | keep |
| Coloured fill paths | `f / F / f*` (non-white) | remove | keep |
| Clipping paths | `W / W*` + `n` | keep clip, drop paint | loop-processed |
| Stroke paths | `S / s` | remove | keep |
| Inline images | `BI...EI` | remove | keep |

## Key Configuration Parameters (defaults)

| Parameter | Default | Notes |
|-----------|---------|-------|
| Render DPI | 300 | Higher = more precise, slower |
| SSIM threshold | 0.95 | Threshold to confirm component removal |
| Max iterations | 200 | Per-page component comparison limit |
| Multi-page parallel | Off | Uses threading; higher memory usage |
| Margins (top/bottom/left/right) | 0 mm | Applied via CropBox after saving; scope: all/odd/even/range |

If memory is insufficient for a large PDF, auto-retry at 150 DPI.

## `filter_text_layer` — Key Invariants

`engine/pdf_parser.py:filter_text_layer` is the most complex function. Critical design decisions:

- **`fill_white_stack`** default is `[False]` (PDF default fill colour is black). This stack tracks whether current fill is white across `q`/`Q` nesting.
- **`cs`/`sc`/`scn`** (alternate colorspace operators) are treated as non-white (`_FILL_COLOUR_UNKNOWN`) because the colour value is opaque to our parser.
- **White fill paths** (`fill_white_stack[-1] == True`) are kept and explicitly prepended with `1 g` (white fill operator) so they render white regardless of surrounding state.
- **Non-white `W f`** (clip + coloured fill): clip is preserved but paint is converted to `n` (no paint) to avoid coloured backgrounds bleeding into text layer.
- **`q`/`Q`** are always emitted to result so clip paths stay scoped and don't accumulate globally (without this, intersecting clips produce blank pages).
- **`state_ops`** (colour/line-width ops outside `BT…ET`) are injected just before the next `BT` so text colour is inherited correctly.
- **Strokes (`S`/`s`)** are always dropped from text layer.

## GUI (Tkinter + ttk)

Processing runs on a **background thread** — all GUI updates must be dispatched to the main thread to avoid freezing. The center panel displays three horizontally arranged views updated after every iteration: Reference | Candidate | Diff Map. SSIM values are shown below each view (green ≥ 0.95, red < 0.95).

## Test Assets

`pdf-assets/` contains sample textbooks with known-good separations (files suffixed `_BG`/`_bg` and `_T`/`_text`). Use these as acceptance test inputs:
- `國文1142_book.pdf` + `_BG.pdf` + `_T.pdf`
- `英文1142_book_L1.pdf` + `_BG.pdf` + `_T.pdf`
- `地理1142_book.pdf`, `綜合1142_book.pdf`, `自然1142_book.pdf` (with bg/text variants)

## Recommended Development Phases

1. **Phase 1** — `pdf_parser.py` + `layer_extractor.py`: validate text/background split via CLI
2. **Phase 2** — `mask_resolver.py` + `image_comparator.py`: verify SSIM loop convergence
3. **Phase 3** — Tkinter GUI with threaded processing, live 3-panel display, progress bar
4. **Phase 4** — Integration tests with all sample textbooks
5. **Phase 5** — PyInstaller packaging and standalone exe testing on Windows 10/11
