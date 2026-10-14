"""The SQL literal encoder is the security boundary for the whole datastore.

PyroCore's ``/sql/execute`` runs raw SQL with no parameter binding, so every
value that reaches it passes through :func:`encode`. These tests are the control
that makes the ``S608`` lint exemptions in ``pyproject.toml`` acceptable: they
are what stands in for that rule.
"""

from __future__ import annotations

import json
import math

import pytest

from app.repositories.sql import (
    SqlEncodingError,
    encode,
    encode_json,
    in_list,
    safe_identifier,
)


class TestEncodeStrings:
    def test_plain_string_is_quoted(self) -> None:
        assert encode("abc") == "'abc'"

    def test_single_quote_is_doubled(self) -> None:
        assert encode("O'Brien") == "'O''Brien'"

    def test_injection_attempt_is_neutralised(self) -> None:
        # One wrapper quote either side plus the doubled internal quote.
        assert encode("'; DROP TABLE cm_users; --") == "'''; DROP TABLE cm_users; --'"

    def test_backslash_is_literal(self) -> None:
        # SQLite has no backslash escape; doubling it would corrupt the data.
        assert encode("a\\b") == "'a\\b'"

    def test_newline_survives(self) -> None:
        assert encode("a\nb") == "'a\nb'"

    def test_nul_byte_is_rejected(self) -> None:
        # A literal NUL terminates the string early in some engines; refusing it
        # is safer than hoping the parser agrees.
        with pytest.raises(SqlEncodingError):
            encode("a\x00b")

    def test_unicode_is_passed_through(self) -> None:
        assert encode("café ☕") == "'café ☕'"

    def test_empty_string(self) -> None:
        assert encode("") == "''"


class TestEncodeScalars:
    def test_none_is_null(self) -> None:
        assert encode(None) == "NULL"

    def test_bool_precedes_int(self) -> None:
        # bool is a subclass of int; getting this backwards stores 2/3.
        assert encode(True) == "1"
        assert encode(False) == "0"

    def test_int(self) -> None:
        assert encode(42) == "42"
        assert encode(-7) == "-7"

    def test_int_out_of_sqlite_range_is_rejected(self) -> None:
        with pytest.raises(SqlEncodingError):
            encode(2**63)

    def test_float_round_trips(self) -> None:
        assert encode(1.5) == "1.5"
        assert float(encode(0.1)) == 0.1

    @pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
    def test_non_finite_float_is_rejected(self, bad: float) -> None:
        with pytest.raises(SqlEncodingError):
            encode(bad)
        assert math.isnan(bad) or math.isinf(bad)


class TestEncodeRejectsStructures:
    @pytest.mark.parametrize("value", [[1, 2], {"a": 1}, (1, 2)])
    def test_containers_must_be_serialised_explicitly(self, value: object) -> None:
        # Silently stringifying a dict is how "why is this column empty?" bugs
        # are born, so the encoder refuses instead.
        with pytest.raises(SqlEncodingError):
            encode(value)

    def test_unsupported_type(self) -> None:
        with pytest.raises(SqlEncodingError):
            encode(object())


def _decode_sql_text(literal: str) -> str:
    """Undo :func:`encode` for a string literal, so JSON can be read back."""
    assert literal.startswith("'") and literal.endswith("'")
    return literal[1:-1].replace("''", "'")


class TestEncodeJson:
    def test_round_trips(self) -> None:
        payload = {"a": 1, "b": ["x", None, True], "c": "it's"}
        assert json.loads(_decode_sql_text(encode_json(payload))) == payload

    def test_quotes_are_doubled(self) -> None:
        assert encode_json({"k": "it's"}) == "'{\"k\":\"it''s\"}'"

    def test_output_is_stable(self) -> None:
        # Key order must not change the cache key or the ledger row.
        assert encode_json({"b": 1, "a": 2}) == encode_json({"a": 2, "b": 1})

    def test_none_becomes_json_null_text(self) -> None:
        assert encode_json(None) == "'null'"

    def test_non_serialisable_raises(self) -> None:
        with pytest.raises(SqlEncodingError):
            encode_json({1, 2})


class TestSafeIdentifier:
    def test_accepts_normal_names(self) -> None:
        assert safe_identifier("cm_users") == "cm_users"
        assert safe_identifier("_x9") == "_x9"

    @pytest.mark.parametrize(
        "bad",
        [
            "users; DROP TABLE x",
            "a b",
            "1abc",
            "",
            "cm-users",
            'cm"users',
            "cm_users--",
            "cm.users",
        ],
    )
    def test_rejects_anything_outside_the_whitelist(self, bad: str) -> None:
        with pytest.raises(SqlEncodingError):
            safe_identifier(bad)

    def test_error_is_a_value_error(self) -> None:
        # Callers that only catch ValueError still fail safely.
        assert issubclass(SqlEncodingError, ValueError)
        with pytest.raises(ValueError):
            safe_identifier("bad name")


class TestInList:
    def test_empty_matches_nothing_rather_than_being_invalid(self) -> None:
        # "IN ()" is a syntax error in SQLite.
        assert in_list([]) == "(NULL)"

    def test_produces_quoted_values(self) -> None:
        assert in_list(["a", "b"]) == "('a', 'b')"

    def test_encodes_each_value(self) -> None:
        assert in_list(["it's"]) == "('it''s')"

    def test_numbers_are_unquoted(self) -> None:
        assert in_list([1, 2]) == "(1, 2)"