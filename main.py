"""
PDF Layer Splitter – entry point.

Run:
    python main.py
"""

import sys
import tkinter as tk
from tkinter import ttk

from gui.main_window import MainWindow


def main():
    root = tk.Tk()
    root.geometry("1280x780")

    # Apply a built-in theme that looks reasonable on Windows
    style = ttk.Style(root)
    available = style.theme_names()
    for preferred in ('vista', 'winnative', 'clam', 'alt', 'default'):
        if preferred in available:
            style.theme_use(preferred)
            break

    # Dark-ish backgrounds for the canvas areas are set per-widget;
    # here we only set the Tk root colour.
    root.configure(bg='#2b2b2b')

    app = MainWindow(root)
    root.protocol("WM_DELETE_WINDOW", lambda: _on_close(root, app))
    root.mainloop()


def _on_close(root: tk.Tk, app: MainWindow):
    if app._engine and app._engine.is_running():
        app._engine.cancel()
    root.destroy()


if __name__ == '__main__':
    main()
