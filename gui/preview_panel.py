"""Left panel – shows per-page thumbnails of the loaded PDF."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable

import fitz
from PIL import Image, ImageTk

THUMB_W = 120   # thumbnail display width in pixels


class PreviewPanel(ttk.Frame):
    """Scrollable list of page thumbnails with click-to-select support."""

    def __init__(self, parent: tk.Widget, on_select: Callable[[int], None] | None = None):
        super().__init__(parent)
        self._on_select = on_select
        self._photos: list[ImageTk.PhotoImage] = []  # keep refs alive
        self._page_labels: list[ttk.Label] = []
        self._selected: int = -1
        self._build()

    # ------------------------------------------------------------------ #

    def _build(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        ttk.Label(self, text="Pages / 頁面", font=('', 10, 'bold')).grid(
            row=0, column=0, pady=(6, 2))

        container = ttk.Frame(self)
        container.grid(row=1, column=0, sticky='nsew')
        container.rowconfigure(0, weight=1)
        container.columnconfigure(0, weight=1)

        self._canvas = tk.Canvas(container, bg='#2b2b2b', highlightthickness=0)
        sb = ttk.Scrollbar(container, orient='vertical', command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=sb.set)

        self._canvas.grid(row=0, column=0, sticky='nsew')
        sb.grid(row=0, column=1, sticky='ns')

        self._inner = ttk.Frame(self._canvas)
        self._canvas_window = self._canvas.create_window(
            (0, 0), window=self._inner, anchor='nw')

        self._inner.bind('<Configure>', self._on_inner_configure)
        self._canvas.bind('<Configure>', self._on_canvas_configure)

        # Mouse-wheel scrolling
        self._canvas.bind_all('<MouseWheel>', self._on_mousewheel)

    def _on_inner_configure(self, _event=None):
        self._canvas.configure(scrollregion=self._canvas.bbox('all'))

    def _on_canvas_configure(self, event):
        self._canvas.itemconfigure(self._canvas_window, width=event.width)

    def _on_mousewheel(self, event):
        self._canvas.yview_scroll(int(-1 * (event.delta / 120)), 'units')

    # ------------------------------------------------------------------ #
    #  Public API
    # ------------------------------------------------------------------ #

    def load(self, doc: fitz.Document):
        """Render thumbnails for all pages of *doc*."""
        self.clear()
        n = len(doc)
        for i in range(n):
            page = doc[i]
            # Render at low DPI for thumbnails
            mat = fitz.Matrix(72 / 72, 72 / 72)           # 72 DPI → quick
            pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB, alpha=False)
            img = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
            # Scale to THUMB_W keeping aspect ratio
            ratio = THUMB_W / img.width
            thumb_h = max(1, int(img.height * ratio))
            img = img.resize((THUMB_W, thumb_h), Image.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            self._photos.append(photo)

            frame = ttk.Frame(self._inner, relief='flat', padding=4)
            frame.pack(fill='x', padx=4, pady=3)

            lbl = tk.Label(frame, image=photo, bg='#444444',
                           cursor='hand2', bd=2, relief='flat')
            lbl.pack()
            page_num_lbl = ttk.Label(frame, text=f"Page {i + 1}", font=('', 8))
            page_num_lbl.pack()

            idx = i
            lbl.bind('<Button-1>', lambda e, p=idx: self._click(p))
            self._page_labels.append(lbl)

        if n > 0:
            self._click(0)

    def clear(self):
        for widget in self._inner.winfo_children():
            widget.destroy()
        self._photos.clear()
        self._page_labels.clear()
        self._selected = -1

    def highlight_page(self, page_index: int):
        """Visually highlight the given page thumbnail."""
        for i, lbl in enumerate(self._page_labels):
            lbl.config(relief='solid' if i == page_index else 'flat',
                       bg='#0078d7' if i == page_index else '#444444')
        self._selected = page_index

    def _click(self, page_index: int):
        self.highlight_page(page_index)
        if self._on_select:
            self._on_select(page_index)
