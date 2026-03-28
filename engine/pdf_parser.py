"""
PDF content-stream tokenizer and token-level filter utilities.

Provides functions to:
  - tokenize a raw PDF content-stream byte string into a list of string tokens
  - convert a token list back to bytes
  - filter tokens for the text layer (keep only BT…ET blocks)
  - filter tokens for the background layer (remove BT…ET blocks)
  - locate q…Q block boundaries
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Tokeniser
# ---------------------------------------------------------------------------

def tokenize(content_bytes: bytes) -> list[str]:
    """
    Split a PDF content-stream into its atomic tokens.

    Handles:
      - Literal strings  ( … )
      - Hex strings      < … >
      - Dictionaries     << … >>
      - Arrays           [ … ]
      - Name objects     /name
      - Numbers and operators (single contiguous non-whitespace runs)
      - Comment lines    % …
    """
    try:
        content = content_bytes.decode('latin-1')
    except Exception:
        content = content_bytes.decode('utf-8', errors='replace')

    tokens: list[str] = []
    i = 0
    n = len(content)

    while i < n:
        c = content[i]

        # --- whitespace -------------------------------------------------
        if c in ' \t\r\n\x00':
            i += 1
            continue

        # --- comment -----------------------------------------------------
        if c == '%':
            while i < n and content[i] not in '\r\n':
                i += 1
            continue

        # --- literal string  ( … ) ---------------------------------------
        if c == '(':
            start = i
            depth = 0
            i += 1
            while i < n:
                ch = content[i]
                if ch == '\\':
                    i += 2          # escaped char, skip both
                elif ch == '(':
                    depth += 1
                    i += 1
                elif ch == ')':
                    i += 1
                    if depth == 0:
                        break
                    depth -= 1
                else:
                    i += 1
            tokens.append(content[start:i])
            continue

        # --- dictionary  << … >> ----------------------------------------
        # Must correctly skip hex strings (<…>) and literal strings ((…))
        # that may appear as values inside the dict so that their '>'
        # characters are not mistaken for the '>>' dict-close marker.
        if c == '<' and i + 1 < n and content[i + 1] == '<':
            start = i
            depth = 0
            while i < n:
                if content[i:i + 2] == '<<':
                    depth += 1
                    i += 2
                elif content[i:i + 2] == '>>':
                    depth -= 1
                    i += 2
                    if depth == 0:
                        break
                elif content[i] == '(':
                    # Literal string value inside dict – skip to matching ')'
                    i += 1
                    nest = 0
                    while i < n:
                        ch = content[i]
                        if ch == '\\':
                            i += 2
                        elif ch == '(':
                            nest += 1; i += 1
                        elif ch == ')':
                            i += 1
                            if nest == 0:
                                break
                            nest -= 1
                        else:
                            i += 1
                elif content[i] == '<':
                    # Hex string value inside dict  <hexdigits>  – skip to '>'
                    i += 1
                    while i < n and content[i] != '>':
                        i += 1
                    if i < n:
                        i += 1   # consume closing '>'
                else:
                    i += 1
            tokens.append(content[start:i])
            continue

        # --- hex string  < … > ------------------------------------------
        if c == '<':
            start = i
            i += 1
            while i < n and content[i] != '>':
                i += 1
            i += 1  # consume '>'
            tokens.append(content[start:i])
            continue

        # --- array  [ … ] ------------------------------------------------
        if c == '[':
            start = i
            depth = 0
            while i < n:
                if content[i] == '[':
                    depth += 1
                elif content[i] == ']':
                    depth -= 1
                    if depth == 0:
                        i += 1
                        break
                i += 1
            tokens.append(content[start:i])
            continue

        # --- name object  /name  -----------------------------------------
        # Must come BEFORE the generic-token handler so that '/' is consumed
        # as part of the name rather than treated as a lone delimiter.
        if c == '/':
            start = i          # include the leading '/'
            i += 1
            # PDF name chars: anything except whitespace and the PDF delimiters
            # '#' introduces a hex-encoded char – read it as part of the name
            while i < n and content[i] not in ' \t\r\n\x00[]<>(){}/%':
                i += 1
            tokens.append(content[start:i])
            continue

        # --- generic token (number or operator) --------------------------
        start = i
        while i < n and content[i] not in ' \t\r\n\x00[]<>(){}/%':
            i += 1
        if i > start:
            tokens.append(content[start:i])
        else:
            # single unrecognised character (e.g. '{', '}')
            tokens.append(c)
            i += 1

    return tokens


def tokens_to_bytes(tokens: list[str]) -> bytes:
    """Join tokens with spaces and encode to latin-1 bytes."""
    return (' '.join(tokens)).encode('latin-1')


# ---------------------------------------------------------------------------
# q…Q block finder
# ---------------------------------------------------------------------------

def find_q_blocks(tokens: list[str]) -> list[tuple[int, int]]:
    """
    Return a list of (start, end) index pairs for every q…Q block.

    start is the index of 'q'; end is the index *after* the matching 'Q'.
    Only outermost (non-nested) blocks are returned.
    """
    blocks: list[tuple[int, int]] = []
    stack: list[int] = []

    for i, tok in enumerate(tokens):
        if tok == 'q':
            stack.append(i)
        elif tok == 'Q' and stack:
            start = stack.pop()
            if not stack:               # outermost only
                blocks.append((start, i + 1))

    return blocks


def is_clipping_block(tokens: list[str], start: int, end: int) -> bool:
    """Return True if the token slice [start:end] contains W or W*."""
    sub = tokens[start:end]
    return 'W' in sub or 'W*' in sub


# ---------------------------------------------------------------------------
# Layer filters
# ---------------------------------------------------------------------------

def filter_text_layer(tokens: list[str]) -> list[str]:
    """
    Return a token list that contains ONLY the content of BT…ET blocks.

    Also handles inline images (BI…EI) by skipping them entirely.
    Everything outside BT…ET is removed.
    """
    result: list[str] = []
    in_bt = False
    in_bi = False

    for tok in tokens:
        if tok == 'BI':
            in_bi = True
            continue
        if tok == 'EI':
            in_bi = False
            continue
        if in_bi:
            continue

        if tok == 'BT':
            in_bt = True
            result.append(tok)
        elif tok == 'ET':
            result.append(tok)
            in_bt = False
        elif in_bt:
            result.append(tok)

    return result


def filter_bg_layer(tokens: list[str]) -> list[str]:
    """
    Return a token list with all BT…ET blocks removed.

    Everything else (images, paths, clipping groups, etc.) is preserved
    for subsequent mask-resolver processing.
    """
    result: list[str] = []
    in_bt = False

    for tok in tokens:
        if tok == 'BT':
            in_bt = True
        elif tok == 'ET':
            in_bt = False
        elif not in_bt:
            result.append(tok)

    return result
