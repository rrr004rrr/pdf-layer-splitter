"""Margin control dialog – lets the user add page margins to output PDFs."""

from __future__ import annotations
import tkinter as tk
from tkinter import ttk


class MarginDialog(tk.Toplevel):
    """
    Modal dialog for configuring page margins (in mm) applied to output PDFs.

    Margins are applied via CropBox adjustment after saving.
    Default is 0 mm on all sides (no processing).
    """

    def __init__(self, parent: tk.Widget, current: dict):
        super().__init__(parent)
        self.title("頁邊距設定 / Margin Settings")
        self.resizable(False, False)
        self.grab_set()  # modal

        self._result: dict | None = None

        # ---- variables -------------------------------------------------------
        self._top    = tk.DoubleVar(value=current.get('top',    0.0))
        self._bottom = tk.DoubleVar(value=current.get('bottom', 0.0))
        self._left   = tk.DoubleVar(value=current.get('left',   0.0))
        self._right  = tk.DoubleVar(value=current.get('right',  0.0))
        self._scope  = tk.StringVar(value=current.get('scope',  'all'))
        self._pages  = tk.StringVar(value=current.get('pages',  ''))

        # ---- layout ----------------------------------------------------------
        pad = {'padx': 10, 'pady': 5}
        frame = ttk.Frame(self, padding=12)
        frame.grid(row=0, column=0, sticky='nsew')

        row = 0

        # Margin spinboxes
        ttk.Label(frame, text="邊距設定 / Margins (mm):",
                  font=('', 9, 'bold')).grid(
            row=row, column=0, columnspan=2, sticky='w', **pad)
        row += 1

        spin_opts = dict(from_=0.0, to=50.0, increment=1.0,
                         format='%.1f', width=8)

        for label_text, var in [
            ("上 / Top:",    self._top),
            ("下 / Bottom:", self._bottom),
            ("左 / Left:",   self._left),
            ("右 / Right:",  self._right),
        ]:
            ttk.Label(frame, text=label_text).grid(
                row=row, column=0, sticky='w', **pad)
            ttk.Spinbox(frame, textvariable=var, **spin_opts).grid(
                row=row, column=1, sticky='w', **pad)
            row += 1

        ttk.Separator(frame, orient='horizontal').grid(
            row=row, column=0, columnspan=2, sticky='ew', pady=6)
        row += 1

        # Scope selector
        ttk.Label(frame, text="套用範圍 / Apply to:",
                  font=('', 9, 'bold')).grid(
            row=row, column=0, columnspan=2, sticky='w', **pad)
        row += 1

        scopes = [
            ('all',   '全部頁面 / All pages'),
            ('odd',   '奇數頁 / Odd pages'),
            ('even',  '偶數頁 / Even pages'),
            ('range', '指定頁碼 / Page range'),
        ]
        for val, text in scopes:
            ttk.Radiobutton(frame, text=text, variable=self._scope, value=val,
                            command=self._on_scope_change).grid(
                row=row, column=0, columnspan=2, sticky='w', padx=20, pady=2)
            row += 1

        # Page range entry (shown only when scope='range')
        self._range_label = ttk.Label(
            frame, text="頁碼範圍 / Pages (e.g. 1-3,5,7-9):")
        self._range_entry = ttk.Entry(frame, textvariable=self._pages, width=20)
        self._range_row_label = row - 1   # placeholder, will grid below
        self._range_label.grid(row=row, column=0, sticky='w', **pad)
        self._range_entry.grid(row=row, column=1, sticky='w', **pad)
        row += 1

        self._on_scope_change()   # hide range entry if not needed

        # ---- buttons ---------------------------------------------------------
        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=row, column=0, columnspan=2, pady=10)
        ttk.Button(btn_frame, text="OK",     command=self._ok,       width=10).pack(side='left', padx=5)
        ttk.Button(btn_frame, text="Cancel", command=self.destroy,   width=10).pack(side='left', padx=5)
        ttk.Button(btn_frame, text="全部清零 / Reset",
                   command=self._reset, width=14).pack(side='left', padx=5)

        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self._centre(parent)

    # ------------------------------------------------------------------ #

    def _on_scope_change(self):
        is_range = self._scope.get() == 'range'
        state = 'normal' if is_range else 'disabled'
        self._range_label.configure(foreground='' if is_range else 'gray')
        self._range_entry.configure(state=state)

    def _reset(self):
        for var in (self._top, self._bottom, self._left, self._right):
            var.set(0.0)

    def _ok(self):
        self._result = {
            'top':    round(self._top.get(),    1),
            'bottom': round(self._bottom.get(), 1),
            'left':   round(self._left.get(),   1),
            'right':  round(self._right.get(),  1),
            'scope':  self._scope.get(),
            'pages':  self._pages.get().strip(),
        }
        self.destroy()

    def _centre(self, parent: tk.Widget):
        self.update_idletasks()
        pw = parent.winfo_rootx() + parent.winfo_width()  // 2
        ph = parent.winfo_rooty() + parent.winfo_height() // 2
        w, h = self.winfo_width(), self.winfo_height()
        self.geometry(f"+{pw - w//2}+{ph - h//2}")

    def get_result(self) -> dict | None:
        """Returns margin settings dict or None if cancelled."""
        return self._result
