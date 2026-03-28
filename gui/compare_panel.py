"""
Center comparison panel – three side-by-side image panes showing
Reference | Candidate | Diff Heatmap with SSIM labels.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Sequence

import numpy as np
from PIL import Image, ImageTk

_SSIM_GREEN = '#00c050'
_SSIM_RED   = '#e03030'


class _ImagePane(ttk.Frame):
    """Single image pane with a title and an optional SSIM badge."""

    def __init__(self, parent: tk.Widget, title: str):
        super().__init__(parent, relief='flat')
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        ttk.Label(self, text=title, font=('', 9, 'bold')).grid(
            row=0, column=0, pady=(4, 0))

        self._canvas = tk.Canvas(self, bg='#1e1e1e', highlightthickness=0)
        self._canvas.grid(row=1, column=0, sticky='nsew')

        self._ssim_var = tk.StringVar(value='SSIM: —')
        self._ssim_lbl = ttk.Label(self, textvariable=self._ssim_var,
                                    font=('Consolas', 9, 'bold'))
        self._ssim_lbl.grid(row=2, column=0, pady=(0, 4))

        self._photo: ImageTk.PhotoImage | None = None
        self._canvas.bind('<Configure>', self._on_resize)
        self._pending_img: Image.Image | None = None

    def set_image(self, rgb_array: np.ndarray | None):
        if rgb_array is None:
            self._canvas.delete('all')
            self._photo = None
            self._pending_img = None
            return
        self._pending_img = Image.fromarray(rgb_array)
        self._redraw()

    def set_ssim(self, score: float | None, threshold: float = 0.95):
        if score is None:
            self._ssim_var.set('SSIM: —')
            self._ssim_lbl.configure(foreground='gray')
        else:
            self._ssim_var.set(f'SSIM: {score:.4f}')
            color = _SSIM_GREEN if score >= threshold else _SSIM_RED
            self._ssim_lbl.configure(foreground=color)

    def _on_resize(self, _event=None):
        self._redraw()

    def _redraw(self):
        if self._pending_img is None:
            return
        cw = self._canvas.winfo_width()
        ch = self._canvas.winfo_height()
        if cw < 2 or ch < 2:
            return
        img = self._pending_img
        # Fit inside canvas keeping aspect ratio
        ratio = min(cw / img.width, ch / img.height)
        nw = max(1, int(img.width * ratio))
        nh = max(1, int(img.height * ratio))
        resized = img.resize((nw, nh), Image.LANCZOS)
        self._photo = ImageTk.PhotoImage(resized)
        self._canvas.delete('all')
        self._canvas.create_image(cw // 2, ch // 2, image=self._photo, anchor='center')


class ComparePanel(ttk.Frame):
    """
    Three-pane comparison widget.

    Layout: [Reference] [Candidate] [Diff Heatmap]
    """

    def __init__(self, parent: tk.Widget, ssim_threshold: float = 0.95):
        super().__init__(parent)
        self.ssim_threshold = ssim_threshold
        self.columnconfigure((0, 1, 2), weight=1, uniform='col')
        self.rowconfigure(0, weight=1)

        self._ref  = _ImagePane(self, "Reference 參考圖")
        self._cand = _ImagePane(self, "Candidate 候選圖")
        self._diff = _ImagePane(self, "Diff Heatmap 差異熱圖")

        self._ref .grid(row=0, column=0, sticky='nsew', padx=2, pady=2)
        self._cand.grid(row=0, column=1, sticky='nsew', padx=2, pady=2)
        self._diff.grid(row=0, column=2, sticky='nsew', padx=2, pady=2)

        # Separator lines
        ttk.Separator(self, orient='vertical').grid(
            row=0, column=0, sticky='nse', padx=(0, 0))
        ttk.Separator(self, orient='vertical').grid(
            row=0, column=1, sticky='nse', padx=(0, 0))

    # ------------------------------------------------------------------ #

    def update(
        self,
        ref_img:  np.ndarray | None,
        cand_img: np.ndarray | None,
        heatmap:  np.ndarray | None,
        ssim_score: float | None = None,
    ):
        """Update all three panes at once."""
        self._ref .set_image(ref_img)
        self._cand.set_image(cand_img)
        self._diff.set_image(heatmap)
        self._cand.set_ssim(ssim_score, self.ssim_threshold)
        self._diff.set_ssim(ssim_score, self.ssim_threshold)
        self._ref .set_ssim(None)  # reference doesn't get an SSIM label

    def clear(self):
        self._ref .set_image(None)
        self._cand.set_image(None)
        self._diff.set_image(None)
        self._ref .set_ssim(None)
        self._cand.set_ssim(None)
        self._diff.set_ssim(None)
