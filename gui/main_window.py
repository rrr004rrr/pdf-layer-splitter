"""
Main application window.

Layout
------
  [Toolbar]
  [Queue Frame  — PDF list + per-PDF margins + drag-and-drop]
  +-----------------+-------------------------------+
  | PreviewPanel    | ComparePanel (3-pane)         |
  | (left 30%)      | (right 70%)                   |
  +-----------------+-------------------------------+
  [StatusBar]
  [LogDrawer]  (collapsible)
"""

from __future__ import annotations

import os
import queue
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import fitz

from engine.layer_extractor import ProcessingEngine
from gui.compare_panel import ComparePanel
from gui.preview_panel import PreviewPanel
from gui.settings_dialog import SettingsDialog
from gui.margin_dialog import MarginDialog
from utils.logger import logger

try:
    from tkinterdnd2 import DND_FILES
    _HAS_DND = True
except ImportError:
    _HAS_DND = False


def _fmt_margins(m: dict) -> str:
    """Format margin dict to a compact display string."""
    if not m:
        return '—'
    parts = []
    for k, lbl in [('top', 'T'), ('bottom', 'B'), ('left', 'L'), ('right', 'R')]:
        v = m.get(k, 0)
        if v:
            parts.append(f"{lbl}:{v}")
    return ' '.join(parts) if parts else '—'


class MainWindow(ttk.Frame):
    """Root widget of the application."""

    DEFAULT_SETTINGS = {
        'dpi': 300,
        'ssim_threshold': 1.0,
        'max_iterations': 1000,
        'output_dir': '',
        'parallel_pages': True,
    }

    def __init__(self, root: tk.Tk):
        super().__init__(root)
        self.root = root
        root.title("PDF Layer Splitter / PDF 圖文分離工具")
        root.minsize(1000, 660)

        self._settings = dict(self.DEFAULT_SETTINGS)
        self._queue_entries: list[dict] = []   # {path, status, margin_settings}
        self._processing_index: int = -1
        self._doc: fitz.Document | None = None
        self._engine: ProcessingEngine | None = None
        self._cb_queue: queue.Queue = queue.Queue()

        self.pack(fill='both', expand=True)
        self._build()
        self._poll_cb_queue()

        logger.add_listener(self._on_log)

    # ------------------------------------------------------------------ #
    #  Widget construction
    # ------------------------------------------------------------------ #

    def _build(self):
        self.rowconfigure(2, weight=1)   # main area expands
        self.columnconfigure(0, weight=1)

        self._build_toolbar()
        self._build_queue_frame()
        self._build_main_area()
        self._build_status_bar()
        self._build_log_drawer()

    def _build_toolbar(self):
        tb = ttk.Frame(self, relief='flat', padding=(6, 4))
        tb.grid(row=0, column=0, sticky='ew')

        ttk.Button(tb, text="📂 新增 PDF", command=self._add_pdfs).pack(side='left', padx=3)

        self._btn_start = ttk.Button(tb, text="▶ 開始處理", command=self._start,
                                      state='disabled')
        self._btn_start.pack(side='left', padx=3)

        self._btn_stop = ttk.Button(tb, text="⏹ 停止", command=self._stop,
                                     state='disabled')
        self._btn_stop.pack(side='left', padx=3)

        ttk.Separator(tb, orient='vertical').pack(side='left', fill='y', padx=6)

        ttk.Button(tb, text="⚙ 設定", command=self._open_settings).pack(side='left', padx=3)

        self._badge_var = tk.StringVar(value="")
        ttk.Label(tb, textvariable=self._badge_var,
                  foreground='gray', font=('', 9)).pack(side='right', padx=8)

    def _build_queue_frame(self):
        hint = "（可拖曳 PDF 加入佇列）" if _HAS_DND else ""
        qf = ttk.LabelFrame(self, text=f" PDF 排程佇列 {hint}", padding=(4, 2))
        qf.grid(row=1, column=0, sticky='nsew', padx=4, pady=(2, 0))
        qf.columnconfigure(0, weight=1)
        qf.rowconfigure(0, weight=1)

        # Treeview
        cols = ('status', 'margins', 'path')
        self._queue_tree = ttk.Treeview(
            qf, columns=cols, show='headings', height=4, selectmode='browse')
        self._queue_tree.heading('status',  text='狀態 / Status')
        self._queue_tree.heading('margins', text='邊距 / Margins')
        self._queue_tree.heading('path',    text='檔案路徑 / File')
        self._queue_tree.column('status',  width=90,  stretch=False)
        self._queue_tree.column('margins', width=130, stretch=False)
        self._queue_tree.column('path',    width=500, stretch=True)
        self._queue_tree.tag_configure('done',       foreground='#00aa44')
        self._queue_tree.tag_configure('processing', foreground='#0088cc')
        self._queue_tree.tag_configure('error',      foreground='#cc3333')

        vsb = ttk.Scrollbar(qf, orient='vertical', command=self._queue_tree.yview)
        self._queue_tree.configure(yscrollcommand=vsb.set)
        self._queue_tree.grid(row=0, column=0, sticky='nsew')
        vsb.grid(row=0, column=1, sticky='ns')

        # Side buttons
        btn_col = ttk.Frame(qf)
        btn_col.grid(row=0, column=2, sticky='ns', padx=(6, 2), pady=2)
        for text, cmd in [
            ("+ 新增",   self._add_pdfs),
            ("− 移除",   self._remove_selected),
            ("📐 邊距",  self._edit_selected_margins),
            ("清除完成", self._clear_done),
            ("全部清除", self._clear_all),
        ]:
            ttk.Button(btn_col, text=text, width=9, command=cmd).pack(fill='x', pady=1)

        # Drag-and-drop
        if _HAS_DND:
            self._queue_tree.drop_target_register(DND_FILES)
            self._queue_tree.dnd_bind('<<Drop>>', self._on_dnd_drop)

        # Double-click = edit margins for selected entry
        self._queue_tree.bind('<Double-1>', lambda _: self._edit_selected_margins())

    def _build_main_area(self):
        pane = ttk.PanedWindow(self, orient='horizontal')
        pane.grid(row=2, column=0, sticky='nsew', padx=4, pady=4)

        self._preview = PreviewPanel(pane, on_select=self._on_page_select)
        pane.add(self._preview, weight=1)

        self._compare = ComparePanel(pane, ssim_threshold=self._settings['ssim_threshold'])
        pane.add(self._compare, weight=3)

    def _build_status_bar(self):
        sb = ttk.Frame(self, relief='sunken', padding=(4, 2))
        sb.grid(row=3, column=0, sticky='ew')
        sb.columnconfigure(1, weight=1)

        self._progress = ttk.Progressbar(sb, length=200, mode='determinate')
        self._progress.grid(row=0, column=0, padx=(0, 8))

        self._status_var = tk.StringVar(value="就緒 / Ready")
        ttk.Label(sb, textvariable=self._status_var, anchor='w').grid(
            row=0, column=1, sticky='ew')

        self._ssim_var = tk.StringVar(value="")
        self._ssim_lbl = ttk.Label(sb, textvariable=self._ssim_var,
                                    font=('Consolas', 9, 'bold'), width=14)
        self._ssim_lbl.grid(row=0, column=2, padx=(8, 0))

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
    #  Queue management
    # ------------------------------------------------------------------ #

    def _add_pdfs(self):
        paths = filedialog.askopenfilenames(
            title="選擇 PDF / Select PDF(s)",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
        )
        for path in paths:
            self._add_pdf_to_queue(path)

    def _add_pdf_to_queue(self, path: str):
        path = os.path.normpath(path)
        if any(e['path'] == path for e in self._queue_entries):
            return
        try:
            doc = fitz.open(path)
            encrypted = doc.is_encrypted
            doc.close()
            if encrypted:
                messagebox.showwarning("警告", f"不支援加密 PDF:\n{os.path.basename(path)}")
                return
        except Exception as exc:
            messagebox.showerror("錯誤", f"無法開啟 PDF:\n{exc}")
            return

        self._queue_entries.append({
            'path': path,
            'status': 'pending',
            'margin_settings': {},
        })
        self._refresh_queue_display()
        self._update_start_button()
        logger.info(f"Added to queue: {path}")

    def _remove_selected(self):
        sel = self._queue_tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        if self._queue_entries[idx]['status'] == 'processing':
            return
        self._queue_entries.pop(idx)
        self._refresh_queue_display()
        self._update_start_button()

    def _edit_selected_margins(self):
        sel = self._queue_tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        entry = self._queue_entries[idx]
        dlg = MarginDialog(self.root, entry['margin_settings'])
        self.root.wait_window(dlg)
        result = dlg.get_result()
        if result is not None:
            has_margin = any(result.get(k, 0) != 0
                             for k in ('top', 'bottom', 'left', 'right'))
            entry['margin_settings'] = result if has_margin else {}
            self._refresh_queue_display()
            logger.info(f"Margins updated for {os.path.basename(entry['path'])}: {result}")

    def _clear_done(self):
        self._queue_entries = [e for e in self._queue_entries if e['status'] != 'done']
        self._refresh_queue_display()
        self._update_start_button()

    def _clear_all(self):
        if any(e['status'] == 'processing' for e in self._queue_entries):
            messagebox.showwarning("警告", "有 PDF 正在處理中，請先停止。")
            return
        self._queue_entries.clear()
        self._refresh_queue_display()
        self._update_start_button()

    def _on_dnd_drop(self, event):
        paths = self.root.tk.splitlist(event.data)
        for path in paths:
            if path.lower().endswith('.pdf'):
                self._add_pdf_to_queue(path)

    def _refresh_queue_display(self):
        sel = self._queue_tree.selection()
        prev_sel = int(sel[0]) if sel else None

        for item in self._queue_tree.get_children():
            self._queue_tree.delete(item)

        status_labels = {
            'pending':    '待處理',
            'processing': '處理中...',
            'done':       '✓ 完成',
            'error':      '✗ 錯誤',
        }
        for i, entry in enumerate(self._queue_entries):
            tag = entry['status'] if entry['status'] in ('done', 'processing', 'error') else ''
            self._queue_tree.insert(
                '', 'end', iid=str(i),
                values=(
                    status_labels.get(entry['status'], entry['status']),
                    _fmt_margins(entry['margin_settings']),
                    entry['path'],
                ),
                tags=(tag,) if tag else (),
            )

        if prev_sel is not None and prev_sel < len(self._queue_entries):
            self._queue_tree.selection_set(str(prev_sel))

    def _update_start_button(self):
        has_pending = any(e['status'] == 'pending' for e in self._queue_entries)
        is_running  = bool(self._engine and self._engine.is_running())
        self._btn_start.config(
            state='normal' if (has_pending and not is_running) else 'disabled')

    # ------------------------------------------------------------------ #
    #  Processing
    # ------------------------------------------------------------------ #

    def _start(self):
        if not any(e['status'] == 'pending' for e in self._queue_entries):
            return
        self._btn_start.config(state='disabled')
        self._btn_stop.config(state='normal')
        self._processing_index = -1
        self._process_next()

    def _process_next(self):
        """Start the next pending queue entry, or finish if none remain."""
        for i, entry in enumerate(self._queue_entries):
            if entry['status'] == 'pending':
                self._processing_index = i
                self._process_entry(entry)
                return
        self._on_queue_finished()

    def _process_entry(self, entry: dict):
        entry['status'] = 'processing'
        self._refresh_queue_display()
        self._progress['value'] = 0
        self._compare.clear()

        # Load preview for this PDF
        if self._doc:
            self._doc.close()
            self._doc = None
        try:
            self._doc = fitz.open(entry['path'])
            self._preview.load(self._doc)
        except Exception:
            pass

        out_dir = self._settings.get('output_dir') or os.path.dirname(
            os.path.abspath(entry['path']))

        self._engine = ProcessingEngine(
            dpi=self._settings['dpi'],
            ssim_threshold=self._settings['ssim_threshold'],
            max_iterations=self._settings['max_iterations'],
            output_dir=out_dir,
            parallel_pages=self._settings['parallel_pages'],
            margin_settings=entry['margin_settings'],
        )
        self._engine.start(entry['path'], callback=self._engine_callback)

        total = len(self._queue_entries)
        fname = os.path.basename(entry['path'])
        self._set_status(f"處理中 [{self._processing_index+1}/{total}]: {fname}")
        self._update_badge()
        logger.info(f"Processing [{self._processing_index+1}/{total}]: {entry['path']}")

    def _stop(self):
        if self._engine:
            self._engine.cancel()
            self._set_status("停止中...")
            logger.info("User requested cancellation.")

    def _on_queue_finished(self):
        self._btn_stop.config(state='disabled')
        self._update_start_button()
        n_done = sum(1 for e in self._queue_entries if e['status'] == 'done')
        n_err  = sum(1 for e in self._queue_entries if e['status'] == 'error')
        self._set_status(f"佇列完成！完成: {n_done}, 失敗: {n_err}")
        self._update_badge()
        messagebox.showinfo("完成 / Done",
                            f"全部 PDF 處理完畢！\n✓ 完成: {n_done}  ✗ 失敗: {n_err}")

    def _update_badge(self):
        n = len(self._queue_entries)
        n_done = sum(1 for e in self._queue_entries if e['status'] == 'done')
        n_err  = sum(1 for e in self._queue_entries if e['status'] == 'error')
        if n == 0:
            self._badge_var.set("")
        else:
            color = '#cc8800' if n_err else ('#00aa44' if n_done == n else 'gray')
            self._badge_var.set(f"佇列 {n_done}/{n} 完成")

    # ------------------------------------------------------------------ #
    #  Engine callback → queue → GUI thread
    # ------------------------------------------------------------------ #

    def _engine_callback(self, phase, page, total, ref_img, cand_img,
                          heatmap, ssim, action):
        """Called from the worker thread – only enqueue, never touch widgets."""
        self._cb_queue.put((phase, page, total, ref_img, cand_img, heatmap, ssim, action))

    def _poll_cb_queue(self):
        """Drain the callback queue and update the GUI (runs in Tk main thread)."""
        try:
            while True:
                item = self._cb_queue.get_nowait()
                self._handle_update(*item)
        except queue.Empty:
            pass
        self.after(40, self._poll_cb_queue)

    def _handle_update(self, phase, page, total, ref_img, cand_img,
                        heatmap, ssim, action):
        entry = (self._queue_entries[self._processing_index]
                 if 0 <= self._processing_index < len(self._queue_entries) else None)
        fname = os.path.basename(entry['path']) if entry else ''

        if phase == 'text_layer':
            pct = int((page + 1) / max(total, 1) * 50)
            self._progress['value'] = pct
            self._set_status(f"[Text Layer] {fname}  頁 {page+1}/{total}")

        elif phase == 'bg_layer':
            pct = 50 + int((page + 1) / max(total, 1) * 50)
            self._progress['value'] = pct
            self._set_status(f"[BG Layer] {fname}  頁 {page+1}/{total}  {action}")
            if ref_img is not None:
                self._compare.update(ref_img, cand_img, heatmap, ssim)
            if ssim and ssim > 0:
                color = '#00c050' if ssim >= self._settings['ssim_threshold'] else '#e03030'
                self._ssim_var.set(f"SSIM: {ssim:.4f}")
                self._ssim_lbl.configure(foreground=color)
            self._preview.highlight_page(page)

        elif phase == 'done':
            self._progress['value'] = 100
            if entry:
                entry['status'] = 'done'
                self._refresh_queue_display()
            logger.info(f"Done: {action}")
            self._process_next()

        elif phase == 'error':
            self._set_status(f"錯誤: {action}")
            if entry:
                entry['status'] = 'error'
                self._refresh_queue_display()
            messagebox.showerror("錯誤 / Error", f"{fname}\n\n{action}")
            self._process_next()

    # ------------------------------------------------------------------ #
    #  Settings / Helpers
    # ------------------------------------------------------------------ #

    def _open_settings(self):
        dlg = SettingsDialog(self.root, self._settings)
        self.root.wait_window(dlg)
        result = dlg.get_result()
        if result:
            self._settings.update(result)
            self._compare.ssim_threshold = self._settings['ssim_threshold']
            logger.info(f"Settings updated: {result}")

    def _on_page_select(self, page_index: int):
        self._set_status(f"頁面 {page_index + 1} 已選")

    def _toggle_log(self):
        if self._log_open.get():
            self._log_frame.grid(row=4, column=0, sticky='ew', padx=4, pady=(0, 4))
        else:
            self._log_frame.grid_remove()

    def _set_status(self, msg: str):
        self._status_var.set(msg)

    def _on_log(self, line: str):
        self.after(0, self._append_log, line)

    def _append_log(self, line: str):
        self._log_text.configure(state='normal')
        self._log_text.insert('end', line + '\n')
        self._log_text.see('end')
        self._log_text.configure(state='disabled')
