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

# ---------------------------------------------------------------------------
# Operator sets used by filter_text_layer
# ---------------------------------------------------------------------------

# State operators that may appear outside BT…ET but affect text rendering.
_INHERITED_OPS: frozenset[str] = frozenset({
    'g', 'rg', 'k', 'sc', 'scn', 'cs',          # fill colour
    'G', 'RG', 'K', 'SC', 'SCN', 'CS',           # stroke colour
    'w', 'M', 'J', 'j', 'ri', 'gs',              # line/text properties
})

# Fill-colour operators whose operands determine if colour is white.
_FILL_COLOUR_OPS: frozenset[str] = frozenset({'g', 'rg', 'k'})

# Fill-colour operators whose colour value is opaque / unknown (alternate colorspace).
# When seen, assume fill is non-white so we don't accidentally keep coloured fills.
_FILL_COLOUR_UNKNOWN: frozenset[str] = frozenset({'cs', 'sc', 'scn'})

# Path-construction operators.
_PATH_OPS: frozenset[str] = frozenset({'m', 'l', 'c', 'v', 'y', 'h', 're'})

# Operators that paint (fill / stroke / both).
_FILL_OPS:   frozenset[str] = frozenset({'f', 'F', 'f*', 'B', 'B*', 'b', 'b*'})
_STROKE_OPS: frozenset[str] = frozenset({'S', 's'})
_CLIP_OPS:   frozenset[str] = frozenset({'W', 'W*'})


def _is_operator(tok: str) -> bool:
    """Return True if *tok* looks like a PDF operator (not a number/name/string)."""
    if not tok:
        return False
    c = tok[0]
    return c not in '/([<' and not (c.isdigit() or c in '.+-')


def _colour_is_white(op: str, operands: list[str]) -> bool:
    """Return True when op+operands set a white (or near-white) fill colour."""
    try:
        vals = [float(v) for v in operands]
    except (ValueError, TypeError):
        return False
    if op == 'g':   return bool(vals) and vals[0] >= 0.9
    if op == 'rg':  return len(vals) >= 3 and all(v >= 0.9 for v in vals[:3])
    if op == 'k':   return len(vals) >= 4 and all(v <= 0.1 for v in vals[:4])
    return False


def filter_text_layer(tokens: list[str]) -> list[str]:
    """
    Return a token list for the text layer.

    Keeps only BT…ET text blocks and the graphics-state colour/property
    operators needed to preserve text colour.  All images (BI…EI, Do),
    paths, and XObjects are dropped.

    q/Q pairs are forwarded so that graphics-state nesting is maintained
    and text colour inherited from enclosing q blocks is preserved.
    """
    result: list[str] = []
    in_bt = False
    in_bi = False
    pending: list[str] = []
    state_ops: list[str] = []

    for tok in tokens:
        # Drop inline images entirely
        if tok == 'BI':
            in_bi = True; pending = []; continue
        if tok == 'EI':
            in_bi = False; continue
        if in_bi:
            continue

        if tok == 'BT':
            result.extend(state_ops)
            state_ops = []
            in_bt = True
            result.append(tok)
        elif tok == 'ET':
            result.append(tok)
            in_bt = False
            pending = []
        elif in_bt:
            result.append(tok)

        # Outside BT…ET
        else:
            if not _is_operator(tok):
                pending.append(tok)
            elif tok == 'q':
                result.append(tok)
                pending = []
            elif tok == 'Q':
                result.append(tok)
                pending = []
            elif tok in _INHERITED_OPS:
                # Accumulate colour/state ops to inject before the next BT
                state_ops.extend(pending)
                state_ops.append(tok)
                pending = []
            else:
                # Do, path ops, paint ops, cm, etc. → drop
                pending = []

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
