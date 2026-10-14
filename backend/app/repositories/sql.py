"""A strict encoder for inline SQL literals.

Why this exists
---------------
PyroCore's ``POST /api/projects/{id}/sql/execute`` runs raw SQL with **no
parameter binding** - the body is a SQL string and the server executes it
verbatim inside one transaction. The table REST endpoints do bind parameters,
but they cannot express the conditional update the credit model depends on
(``UPDATE ... WHERE used + n <= limit`` with the row count returned), which is
exactly the operation ARCHITECTURE.md §16.5.2 requires.

So values have to travel as SQL literals. That makes this module the single
most security-sensitive piece of the backend, and it is deliberately paranoid:

* it accepts a **closed set of Python types** and raises on anything else -
  there is no coercion and no ``str()`` fallback;
* strings are emitted as a single-quoted literal with ``'`` doubled, which is
  the complete escaping rule for SQLite string literals;
* NUL bytes are rejected outright rather than escaped, because several SQLite
  builds truncate C strings at NUL;
* identifiers never come from here. Callers pass them through
  :func:`safe_identifier`, which only accepts ``[A-Za-z_][A-Za-z0-9_]*``.

Anything this module cannot represent safely is an error, not a guess.
"""

from __future__ import annotations

import math
import re
from typing import Any

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# : Values SQLite stores as a distinct type from a float/decimal string.
_BLOB = (bytes, bytearray, memoryview)

class SqlEncodingError(ValueError):
    """A value could not be encoded as a SQL literal without losing safety."""

def safe_identifier(name: str) -> str:
    """Validate a table or column name.

    Identifiers cannot be quoted-as-data, so they are held to a strict shape and
    never derived from user input. Anything else is a programming error.
    """
    if not isinstance(name, str) or not _IDENT_RE.match(name):
        raise SqlEncodingError(f"unsafe identifier: {name!r}")
    return name

def encode(value: Any) -> str:
    """Render one Python value as a SQL literal."""
    if value is None:
        return "NULL"

    if isinstance(value, bool):
        # Must precede the int branch: bool is a subclass of int.
        return "1" if value else "0"

    if isinstance(value, int):
        if not (-(2**63) <= value < 2**63):
            raise SqlEncodingError("integer out of SQLite range")
        return str(value)

    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            raise SqlEncodingError("non-finite float cannot be stored")
        # repr() round-trips exactly and never emits a locale-specific decimal.
        return repr(value)

    if isinstance(value, str):
        if "\x00" in value:
            raise SqlEncodingError("NUL byte in string literal")
        return "'" + value.replace("'", "''") + "'"

    if isinstance(value, _BLOB):
        raw = bytes(value)
        return "X'" + raw.hex() + "'"

    if isinstance(value, (list, tuple, dict)):
        # Callers must serialise structured values themselves; silently turning
        # a dict into a quoted string is how "why is this column empty?" bugs
        # are born.
        raise SqlEncodingError(
            f"{type(value).__name__} must be serialised before encoding; "
            "use json.dumps and pass the resulting str"
        )

    raise SqlEncodingError(f"unsupported type for SQL literal: {type(value).__name__}")

def encode_json(value: Any) -> str:
    """Serialise structured data and encode the result as a text literal."""
    import json

    from ..core.logging import text_fingerprint  # noqa: F401  (kept adjacent to its only user)

    try:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise SqlEncodingError(f"value is not JSON-serialisable: {exc}") from exc
    return encode(text)

def in_list(values: list[Any]) -> str:
    """Render a parenthesised literal list, or ``(NULL)`` when empty.

    An empty ``IN ()`` is a syntax error in SQLite, so the empty case has to
    return something that matches no row without special-casing at the call site.
    """
    if not values:
        return "(NULL)"
    return "(" + ", ".join(encode(v) for v in values) + ")"