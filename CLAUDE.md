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
│   └── settings_dialog.py  # Settings dialog
├── engine/
│   ├── pdf_parser.py       # PyMuPDF object tree parsing and classification
│   ├── layer_extractor.py  # Text/background layer extraction
│   ├── mask_resolver.py    # Clipping mask removal loop (core algorithm)
│   └── image_comparator.py # SSIM comparison and diff heatmap generation
└── utils/
    ├── logger.py
    └── file_helper.py
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
| Fill paths (background) | `f / F / f*` | remove | keep |
| Clipping paths | `W / W*` + clip | remove | loop-processed |
| Stroke paths | `S / s` | remove | keep (usually) |

## Key Configuration Parameters (defaults)

| Parameter | Default | Notes |
|-----------|---------|-------|
| Render DPI | 300 | Higher = more precise, slower |
| SSIM threshold | 0.95 | Threshold to confirm component removal |
| Max iterations | 200 | Per-page component comparison limit |
| Multi-page parallel | Off | Uses threading; higher memory usage |

If memory is insufficient for a large PDF, auto-retry at 150 DPI.

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
