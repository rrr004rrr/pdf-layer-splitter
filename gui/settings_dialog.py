"""Settings dialog – lets the user tune processing parameters."""

from __future__ import annotations
import tkinter as tk
from tkinter import ttk, filedialog


class SettingsDialog(tk.Toplevel):
    """Modal dialog that exposes all configurable engine parameters."""

    def __init__(self, parent: tk.Widget, current: dict):
        super().__init__(parent)
        self.title("Settings / 設定")
        self.resizable(False, False)
        self.grab_set()                     # modal

        self._result: dict | None = None

        # ---- variables ---------------------------------------------------
        self._dpi        = tk.IntVar(value=current.get('dpi', 300))
        self._ssim       = tk.DoubleVar(value=current.get('ssim_threshold', 0.95))
        self._max_iter   = tk.IntVar(value=current.get('max_iterations', 200))
        self._output_dir = tk.StringVar(value=current.get('output_dir', ''))
        self._parallel   = tk.BooleanVar(value=current.get('parallel_pages', False))

        # ---- layout ------------------------------------------------------
        pad = {'padx': 10, 'pady': 5}
        frame = ttk.Frame(self, padding=12)
        frame.grid(row=0, column=0, sticky='nsew')

        row = 0

        def label(text, r):
            ttk.Label(frame, text=text).grid(row=r, column=0, sticky='w', **pad)

        label("Render DPI / 渲染解析度:", row)
        ttk.Spinbox(frame, from_=72, to=600, increment=50,
                    textvariable=self._dpi, width=8).grid(row=row, column=1, sticky='w', **pad)
        row += 1

        label("SSIM Threshold / 相似度門檻:", row)
        ttk.Spinbox(frame, from_=0.80, to=1.00, increment=0.01, format='%.2f',
                    textvariable=self._ssim, width=8).grid(row=row, column=1, sticky='w', **pad)
        row += 1

        label("Max Iterations / 最大迭代次數:", row)
        ttk.Spinbox(frame, from_=10, to=1000, increment=10,
                    textvariable=self._max_iter, width=8).grid(row=row, column=1, sticky='w', **pad)
        row += 1

        label("Output Directory / 輸出資料夾:", row)
        dir_frame = ttk.Frame(frame)
        dir_frame.grid(row=row, column=1, sticky='ew', **pad)
        ttk.Entry(dir_frame, textvariable=self._output_dir, width=28).pack(side='left')
        ttk.Button(dir_frame, text="…", width=3,
                   command=self._browse).pack(side='left', padx=2)
        row += 1

        label("Parallel Pages / 多頁並行:", row)
        ttk.Checkbutton(frame, variable=self._parallel).grid(row=row, column=1, sticky='w', **pad)
        row += 1

        # ---- buttons -----------------------------------------------------
        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=row, column=0, columnspan=2, pady=10)
        ttk.Button(btn_frame, text="OK", command=self._ok, width=10).pack(side='left', padx=5)
        ttk.Button(btn_frame, text="Cancel", command=self.destroy, width=10).pack(side='left', padx=5)

        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self._centre(parent)

    def _browse(self):
        d = filedialog.askdirectory(parent=self)
        if d:
            self._output_dir.set(d)

    def _ok(self):
        self._result = {
            'dpi':            self._dpi.get(),
            'ssim_threshold': round(self._ssim.get(), 2),
            'max_iterations': self._max_iter.get(),
            'output_dir':     self._output_dir.get(),
            'parallel_pages': self._parallel.get(),
        }
        self.destroy()

    def _centre(self, parent: tk.Widget):
        self.update_idletasks()
        pw = parent.winfo_rootx() + parent.winfo_width()  // 2
        ph = parent.winfo_rooty() + parent.winfo_height() // 2
        w, h = self.winfo_width(), self.winfo_height()
        self.geometry(f"+{pw - w//2}+{ph - h//2}")

    def get_result(self) -> dict | None:
        """Returns settings dict or None if cancelled."""
        return self._result
