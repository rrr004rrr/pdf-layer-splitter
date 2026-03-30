"""
Main application window.

Layout
------
  [Toolbar]
  +-----------------+-------------------------------+
  | PreviewPanel    | ComparePanel (3-pane)         |
  | (left 30%)      | (right 70%)                   |
  +-----------------+-------------------------------+
  [StatusBar]
  [LogDrawer]  (collapsible, below status bar)
"""

from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import fitz

from engine.layer_extractor import ProcessingEngine
from gui.compare_panel import ComparePanel
from gui.preview_panel import PreviewPanel
from gui.settings_dialog import SettingsDialog
from gui.margin_dialog import MarginDialog
from utils.logger import logger


class MainWindow(ttk.Frame):
    """Root widget of the application."""

    DEFAULT_SETTINGS = {
        'dpi': 300,
        'ssim_threshold': 0.95,
        'max_iterations': 200,
        'output_dir': '',
        'parallel_pages': False,
    }

    def __init__(self, root: tk.Tk):
        super().__init__(root)
        self.root = root
        root.title("PDF Layer Splitter / PDF 圖文分離工具")
        root.minsize(1000, 620)

        self._settings = dict(self.DEFAULT_SETTINGS)
        self._margin_settings: dict = {}   # empty = no margins
        self._pdf_path: str | None = None
        self._doc: fitz.Document | None = None
        self._engine: ProcessingEngine | None = None
        self._queue: queue.Queue = queue.Queue()
        self._total_pages = 0
        self._current_page = 0

        self.pack(fill='both', expand=True)
        self._build()
        self._poll_queue()

        # Wire logger to the log drawer
        logger.add_listener(self._on_log)

    # ------------------------------------------------------------------ #
    #  Widget construction
    # ------------------------------------------------------------------ #

    def _build(self):
        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)

        self._build_toolbar()
        self._build_main_area()
        self._build_status_bar()
        self._build_log_drawer()

    def _build_toolbar(self):
        tb = ttk.Frame(self, relief='flat', padding=(6, 4))
        tb.grid(row=0, column=0, sticky='ew')

        self._btn_open = ttk.Button(tb, text="📂 Open PDF", command=self._open_pdf)
        self._btn_open.pack(side='left', padx=3)

        self._btn_start = ttk.Button(tb, text="▶ Start", command=self._start,
                                      state='disabled')
        self._btn_start.pack(side='left', padx=3)

        self._btn_stop = ttk.Button(tb, text="⏹ Stop", command=self._stop,
                                     state='disabled')
        self._btn_stop.pack(side='left', padx=3)

        ttk.Separator(tb, orient='vertical').pack(side='left', fill='y', padx=6)

        ttk.Button(tb, text="⚙ Settings", command=self._open_settings).pack(
            side='left', padx=3)

        ttk.Button(tb, text="📐 頁邊距", command=self._open_margins).pack(
            side='left', padx=3)

        self._file_label = ttk.Label(tb, text="No file loaded", foreground='gray')
        self._file_label.pack(side='left', padx=12)

    def _build_main_area(self):
        pane = ttk.PanedWindow(self, orient='horizontal')
        pane.grid(row=1, column=0, sticky='nsew', padx=4, pady=4)

        # Left: page thumbnails
        self._preview = PreviewPanel(pane, on_select=self._on_page_select)
        pane.add(self._preview, weight=1)

        # Right: 3-panel comparison
        self._compare = ComparePanel(pane, ssim_threshold=self._settings['ssim_threshold'])
        pane.add(self._compare, weight=3)

    def _build_status_bar(self):
        sb = ttk.Frame(self, relief='sunken', padding=(4, 2))
        sb.grid(row=2, column=0, sticky='ew')
        sb.columnconfigure(1, weight=1)

        self._progress = ttk.Progressbar(sb, length=200, mode='determinate')
        self._progress.grid(row=0, column=0, padx=(0, 8))

        self._status_var = tk.StringVar(value="Ready")
        ttk.Label(sb, textvariable=self._status_var, anchor='w').grid(
            row=0, column=1, sticky='ew')

        self._ssim_var = tk.StringVar(value="")
        self._ssim_lbl = ttk.Label(sb, textvariable=self._ssim_var,
                                    font=('Consolas', 9, 'bold'), width=14)
        self._ssim_lbl.grid(row=0, column=2, padx=(8, 0))

        # Toggle log drawer
        self._log_open = tk.BooleanVar(value=False)
        ttk.Checkbutton(sb, text="Log", variable=self._log_open,
                        command=self._toggle_log).grid(row=0, column=3, padx=4)

    def _build_log_drawer(self):
        self._log_frame = ttk.Frame(self)
        # Not gridded initially (collapsed)

        self._log_text = tk.Text(self._log_frame, height=8, state='disabled',
                                  bg='#1e1e1e', fg='#cccccc', font=('Consolas', 8),
                                  wrap='word')
        sb = ttk.Scrollbar(self._log_frame, command=self._log_text.yview)
        self._log_text.configure(yscrollcommand=sb.set)
        self._log_text.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y')

    # ------------------------------------------------------------------ #
    #  Actions
    # ------------------------------------------------------------------ #

    def _open_pdf(self):
        path = filedialog.askopenfilename(
            title="Open PDF",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            if self._doc:
                self._doc.close()
            self._doc = fitz.open(path)
            if self._doc.is_encrypted:
                messagebox.showerror("Error", "不支援加密 PDF\nEncrypted PDF is not supported.")
                self._doc.close()
                self._doc = None
                return
            self._pdf_path = path
            self._file_label.config(
                text=os.path.basename(path), foreground='white')
            self._preview.load(self._doc)
            self._compare.clear()
            self._total_pages = len(self._doc)
            self._btn_start.config(state='normal')
            self._set_status(f"Loaded {self._total_pages} page(s) – {os.path.basename(path)}")
            logger.info(f"Loaded: {path}  ({self._total_pages} pages)")
        except Exception as exc:
            messagebox.showerror("Error", f"Failed to open PDF:\n{exc}")

    def _start(self):
        if not self._pdf_path:
            return
        self._btn_start.config(state='disabled')
        self._btn_open.config(state='disabled')
        self._btn_stop.config(state='normal')
        self._compare.clear()
        self._progress['value'] = 0

        out_dir = self._settings.get('output_dir') or os.path.dirname(
            os.path.abspath(self._pdf_path))

        self._engine = ProcessingEngine(
            dpi=self._settings['dpi'],
            ssim_threshold=self._settings['ssim_threshold'],
            max_iterations=self._settings['max_iterations'],
            output_dir=out_dir,
            parallel_pages=self._settings['parallel_pages'],
            margin_settings=self._margin_settings,
        )
        self._engine.start(self._pdf_path, callback=self._engine_callback)
        self._set_status("Processing …")
        logger.info("Processing started.")

    def _stop(self):
        if self._engine:
            self._engine.cancel()
            self._set_status("Stopping …")
            logger.info("User requested cancellation.")

    def _open_settings(self):
        dlg = SettingsDialog(self.root, self._settings)
        self.root.wait_window(dlg)
        result = dlg.get_result()
        if result:
            self._settings.update(result)
            self._compare.ssim_threshold = self._settings['ssim_threshold']
            logger.info(f"Settings updated: {result}")

    def _open_margins(self):
        dlg = MarginDialog(self.root, self._margin_settings)
        self.root.wait_window(dlg)
        result = dlg.get_result()
        if result is not None:
            # Only store non-zero margin settings
            has_margin = any(result.get(k, 0) != 0 for k in ('top', 'bottom', 'left', 'right'))
            self._margin_settings = result if has_margin else {}
            logger.info(f"Margin settings updated: {result}")

    def _on_page_select(self, page_index: int):
        self._current_page = page_index
        self._set_status(f"Page {page_index + 1} selected")

    def _toggle_log(self):
        if self._log_open.get():
            self._log_frame.grid(row=3, column=0, sticky='ew',
                                  padx=4, pady=(0, 4))
        else:
            self._log_frame.grid_remove()

    # ------------------------------------------------------------------ #
    #  Engine callback → queue → GUI thread
    # ------------------------------------------------------------------ #

    def _engine_callback(self, phase, page, total, ref_img, cand_img,
                          heatmap, ssim, action):
        """Called from the worker thread – only enqueue, never touch widgets."""
        self._queue.put((phase, page, total, ref_img, cand_img, heatmap, ssim, action))

    def _poll_queue(self):
        """Drain the queue and update the GUI (runs in the Tk main thread)."""
        try:
            while True:
                item = self._queue.get_nowait()
                self._handle_update(*item)
        except queue.Empty:
            pass
        self.after(40, self._poll_queue)

    def _handle_update(self, phase, page, total, ref_img, cand_img,
                        heatmap, ssim, action):
        if phase == 'text_layer':
            pct = int((page + 1) / max(total, 1) * 50)   # first 50 %
            self._progress['value'] = pct
            self._set_status(
                f"[Text Layer] Page {page + 1}/{total}")

        elif phase == 'bg_layer':
            pct = 50 + int((page + 1) / max(total, 1) * 50)
            self._progress['value'] = pct
            self._set_status(
                f"[BG Layer] Page {page + 1}/{total}  Action: {action}")
            if ref_img is not None:
                self._compare.update(ref_img, cand_img, heatmap, ssim)
            if ssim is not None and ssim > 0:
                color = '#00c050' if ssim >= self._settings['ssim_threshold'] else '#e03030'
                self._ssim_var.set(f"SSIM: {ssim:.4f}")
                self._ssim_lbl.configure(foreground=color)
            # Sync page highlight in preview
            self._preview.highlight_page(page)

        elif phase == 'done':
            self._progress['value'] = 100
            self._set_status(f"Done! Output: {action}")
            self._btn_start.config(state='normal')
            self._btn_open.config(state='normal')
            self._btn_stop.config(state='disabled')
            messagebox.showinfo(
                "Completed / 完成",
                f"Processing finished.\n\nOutput files:\n{action}"
            )

        elif phase == 'error':
            self._set_status(f"Error: {action}")
            self._btn_start.config(state='normal')
            self._btn_open.config(state='normal')
            self._btn_stop.config(state='disabled')
            messagebox.showerror("Error / 錯誤", str(action))

    # ------------------------------------------------------------------ #
    #  Helpers
    # ------------------------------------------------------------------ #

    def _set_status(self, msg: str):
        self._status_var.set(msg)

    def _on_log(self, line: str):
        """Append a log line (called from any thread via after())."""
        self.after(0, self._append_log, line)

    def _append_log(self, line: str):
        self._log_text.configure(state='normal')
        self._log_text.insert('end', line + '\n')
        self._log_text.see('end')
        self._log_text.configure(state='disabled')
