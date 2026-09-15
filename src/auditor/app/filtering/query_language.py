"""
Hand-rolled recursive-descent parser for the audit query language - a
textual alternative to the visual filter panel that compiles to the exact
same FilterNode AST (ast.py). Deliberately not built on a grammar-parser
dependency (lark/pyparsing): the grammar is small enough that a ~150-line
parser is simpler than pulling in and license-reviewing a new dependency,
matching this project's existing bias against unnecessary dependencies.

Grammar:
    expr        := or_expr
    or_expr     := and_expr ("or" and_expr)*
    and_expr    := unary ("and" unary)*
    unary       := "not" unary | atom
    atom        := "(" expr ")" | comparison | free_text
    comparison  := IDENT ( "=" | "!=" | ":" | "!:" | ">" | "<" | ">=" | "<=" ) value
                 | IDENT ("in" | "not" "in") ("(" | "[") value ("," value)* (")" | "]")
                 | IDENT "is" ("not")? "empty"
    free_text   := ("text" ":")? (STRING | NUMBER | IDENT)
    value       := STRING | NUMBER | IDENT

Notes settled during design:
- Both `in (a, b, c)` and `in ["a", "b", "c"]` spellings are accepted - `[`/`]`
  are treated as aliases for `(`/`)` in in/not-in value lists only.
- `==` is accepted as an alias for `=`.
- Field names are matched case-insensitively (`Error`, `ID` in the examples
  below) - the original casing is preserved in the emitted AST leaf, and
  ast.py's KNOWN_FIELDS lookup itself lowercases when resolving a field spec.
- Free text is a single token (bare word or quoted string) - this project's
  examples never combine multiple bare words into one free-text term, so
  supporting that (and its ambiguity against "and"/"or" as content words) is
  out of scope here.

Verified against the spec's own examples:
    status in ["error", "warning"] or tool in ["Web Search Tool", "Notification Tool"]
    name == "Session Start"
    Error is not empty and not ID == 66
    input : est3285 and output : Greetings
"""

import re
from dataclasses import dataclass

from app.filtering.ast import FilterNode, FilterParseError

_TOKEN_SPEC = [
    ("WS", r"\s+"),
    ("STRING", r'"(?:[^"\\]|\\.)*"'),
    ("NUMBER", r"\d+(?:\.\d+)?"),
    ("OP", r"==|!=|>=|<=|!:|=|:|>|<"),
    ("LPAREN", r"\("),
    ("RPAREN", r"\)"),
    ("LBRACKET", r"\["),
    ("RBRACKET", r"\]"),
    ("COMMA", r","),
    ("IDENT", r"[A-Za-z_][A-Za-z0-9_.]*"),
]
_MASTER_RE = re.compile("|".join(f"(?P<{name}>{pattern})" for name, pattern in _TOKEN_SPEC))

_OP_ALIASES = {
    "==": "equals",
    "=": "equals",
    "!=": "not_equal",
    ":": "contains",
    "!:": "not_contains",
    ">": "gt",
    "<": "lt",
    ">=": "gte",
    "<=": "lte",
}

_OP_TO_SYMBOL = {v: k for k, v in _OP_ALIASES.items() if k not in ("==",)}


@dataclass
class Token:
    kind: str
    value: str
    pos: int


def tokenize(text: str) -> list[Token]:
    tokens: list[Token] = []
    pos = 0
    length = len(text)
    while pos < length:
        m = _MASTER_RE.match(text, pos)
        if not m:
            raise FilterParseError(f"Unexpected character {text[pos]!r} at position {pos}")
        kind = m.lastgroup
        value = m.group()
        if kind != "WS":
            tokens.append(Token(kind, value, pos))
        pos = m.end()
    tokens.append(Token("EOF", "", length))
    return tokens


def _unquote(raw: str) -> str:
    return raw[1:-1].replace('\\"', '"')


class _Parser:
    def __init__(self, tokens: list[Token]):
        self._tokens = tokens
        self._i = 0

    def _peek(self, offset: int = 0) -> Token:
        idx = min(self._i + offset, len(self._tokens) - 1)
        return self._tokens[idx]

    def _advance(self) -> Token:
        tok = self._tokens[self._i]
        self._i += 1
        return tok

    def _match_keyword(self, *keywords: str) -> str | None:
        tok = self._peek()
        if tok.kind == "IDENT" and tok.value.lower() in keywords:
            self._advance()
            return tok.value.lower()
        return None

    def _expect_keyword(self, keyword: str) -> None:
        if self._match_keyword(keyword) is None:
            tok = self._peek()
            raise FilterParseError(f"Expected {keyword!r} at position {tok.pos}, got {tok.value!r}")

    def parse(self) -> FilterNode:
        node = self._or_expr()
        if self._peek().kind != "EOF":
            tok = self._peek()
            raise FilterParseError(f"Unexpected trailing input {tok.value!r} at position {tok.pos}")
        return node

    def _or_expr(self) -> FilterNode:
        children = [self._and_expr()]
        while self._match_keyword("or"):
            children.append(self._and_expr())
        return children[0] if len(children) == 1 else {"op": "or", "children": children}

    def _and_expr(self) -> FilterNode:
        children = [self._unary()]
        while self._match_keyword("and"):
            children.append(self._unary())
        return children[0] if len(children) == 1 else {"op": "and", "children": children}

    def _unary(self) -> FilterNode:
        if self._match_keyword("not"):
            return {"op": "not", "child": self._unary()}
        return self._atom()

    def _atom(self) -> FilterNode:
        tok = self._peek()
        if tok.kind == "LPAREN":
            self._advance()
            node = self._or_expr()
            if self._peek().kind != "RPAREN":
                raise FilterParseError(f"Expected ')' at position {self._peek().pos}")
            self._advance()
            return node
        return self._comparison_or_free_text()

    def _comparison_or_free_text(self) -> FilterNode:
        tok = self._peek()

        if tok.kind == "IDENT" and tok.value.lower() == "text":
            save = self._i
            self._advance()
            nxt = self._peek()
            if nxt.kind == "OP" and nxt.value == ":":
                self._advance()
                return {"field": "__text__", "op": "contains", "value": self._value()}
            self._i = save  # "text" wasn't the `text:` prefix - fall through

        if tok.kind == "IDENT":
            save = self._i
            field = tok.value
            self._advance()

            op_tok = self._peek()
            if op_tok.kind == "OP":
                self._advance()
                canonical = _OP_ALIASES[op_tok.value]
                return {"field": field, "op": canonical, "value": self._value()}

            if self._match_keyword("in"):
                return {"field": field, "op": "in", "value": self._bracketed_list()}

            if self._match_keyword("not"):
                if self._match_keyword("in"):
                    return {"field": field, "op": "not_in", "value": self._bracketed_list()}
                raise FilterParseError(f"Expected 'in' after 'not' at position {self._peek().pos}")

            if self._match_keyword("is"):
                negate = self._match_keyword("not") is not None
                self._expect_keyword("empty")
                return {"field": field, "op": "is_not_empty" if negate else "is_empty"}

            # Not actually a comparison (e.g. a bare word that happens to be
            # a known field name, or just any other bare word) - backtrack
            # and treat the whole token as free text instead.
            self._i = save

        return self._free_text_bare()

    def _free_text_bare(self) -> FilterNode:
        tok = self._advance()
        if tok.kind not in ("IDENT", "STRING", "NUMBER"):
            raise FilterParseError(f"Unexpected token {tok.value!r} at position {tok.pos}")
        term = _unquote(tok.value) if tok.kind == "STRING" else tok.value
        return {"field": "__text__", "op": "contains", "value": term}

    def _bracketed_list(self) -> list:
        open_tok = self._peek()
        if open_tok.kind not in ("LPAREN", "LBRACKET"):
            raise FilterParseError(f"Expected '(' or '[' at position {open_tok.pos}")
        closing = "RPAREN" if open_tok.kind == "LPAREN" else "RBRACKET"
        self._advance()
        values = [self._value()]
        while self._peek().kind == "COMMA":
            self._advance()
            values.append(self._value())
        if self._peek().kind != closing:
            raise FilterParseError(f"Expected matching closing bracket at position {self._peek().pos}")
        self._advance()
        return values

    def _value(self):
        tok = self._advance()
        if tok.kind == "STRING":
            return _unquote(tok.value)
        if tok.kind == "NUMBER":
            return float(tok.value) if "." in tok.value else int(tok.value)
        if tok.kind == "IDENT":
            return tok.value
        raise FilterParseError(f"Expected a value at position {tok.pos}, got {tok.value!r}")


def parse_query(text: str) -> FilterNode:
    if not text or not text.strip():
        raise FilterParseError("Empty query")
    return _Parser(tokenize(text)).parse()


def _quote(value) -> str:
    if isinstance(value, str):
        return f'"{value.replace(chr(34), chr(92) + chr(34))}"'
    return str(value)


def ast_to_query_text(node: FilterNode) -> str:
    """Inverse of parse_query - "copy as query". Round-trips to a
    semantically identical AST, not necessarily byte-identical text
    (bracket style / operator alias / field casing may differ)."""
    return _serialize(node, top=True)


def _serialize(node: FilterNode, *, top: bool = False) -> str:
    op = node.get("op")

    if op in ("and", "or"):
        joined = f" {op} ".join(_serialize(c) for c in node["children"])
        return joined if top else f"({joined})"

    if op == "not":
        return f"not {_serialize(node['child'])}"

    field = node["field"]
    leaf_op = node["op"]

    if field == "__text__":
        return f"text: {_quote(node['value'])}"

    if leaf_op in ("in", "not_in"):
        values = ", ".join(_quote(v) for v in node["value"])
        keyword = "in" if leaf_op == "in" else "not in"
        return f"{field} {keyword} ({values})"

    if leaf_op == "is_empty":
        return f"{field} is empty"
    if leaf_op == "is_not_empty":
        return f"{field} is not empty"

    symbol = _OP_TO_SYMBOL.get(leaf_op)
    if symbol is None:
        raise FilterParseError(
            f"Cannot serialize op {leaf_op!r} on field {field!r} back to query "
            "text - it has no symbol in the query-language grammar"
        )
    return f"{field} {symbol} {_quote(node['value'])}"
