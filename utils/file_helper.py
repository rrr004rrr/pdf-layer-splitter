"""File path and I/O utilities."""

import os


def ensure_dir(path: str) -> str:
    """Create directory if it does not exist; return the path."""
    os.makedirs(path, exist_ok=True)
    return path


def output_path(input_pdf: str, suffix: str, output_dir: str | None = None) -> str:
    """
    Build an output file path.

    If output_dir is None, place the file in the same folder as input_pdf.
    suffix should include the leading underscore or separator, e.g. '_text_layer'.
    """
    base, _ = os.path.splitext(input_pdf)
    base_name = os.path.basename(base)
    folder = output_dir if output_dir else os.path.dirname(input_pdf)
    ensure_dir(folder)
    return os.path.join(folder, f"{base_name}{suffix}.pdf")


def is_encrypted(path: str) -> bool:
    """Return True if the PDF is encrypted / password-protected."""
    try:
        import fitz
        doc = fitz.open(path)
        encrypted = doc.is_encrypted
        doc.close()
        return encrypted
    except Exception:
        return True
