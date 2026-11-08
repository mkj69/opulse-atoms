import re
from dataclasses import dataclass

from .nodes import Call, Def, If, Let, Lit, Program, Var
from .worlds import MAX_NAT


class AmlSyntaxError(ValueError):
    def __init__(self, message, line, col):
        self.message = message
        self.line = line
        self.col = col
        super().__init__(f"{message} at line {line}, column {col}")


KEYWORDS = frozenset(("def", "op", "save", "let", "in", "if", "then", "else"))


@dataclass(frozen=True)
class Token:
    text: str
    line: int
    col: int
    kind: str


def tokenize(text):
    tokens = []
    line = col = 1
    index = 0
    while index < len(text):
        char = text[index]
        if char == "\n":
            line += 1
            col = 1
            index += 1
        elif char.isspace():
            index += 1
            col += 1
        elif char == "#":
            while index < len(text) and text[index] != "\n":
                index += 1
                col += 1
        else:
            start = index
            start_col = col
            if char.isascii() and (char.isalpha() or char == "_"):
                index += 1
                while index < len(text) and text[index].isascii() and (text[index].isalnum() or text[index] == "_"):
                    index += 1
                kind = "keyword" if text[start:index] in KEYWORDS else "name"
            elif char.isascii() and char.isdigit():
                index += 1
                while index < len(text) and text[index].isascii() and text[index].isdigit():
                    index += 1
                kind = "int"
            elif char in "(),=:-":
                index += 1
                kind = "symbol"
                if char == "-" and index < len(text) and text[index] == ">":
                    index += 1
            else:
                raise AmlSyntaxError(f"unexpected character {char!r}", line, col)
            tokens.append(Token(text[start:index], line, start_col, kind))
            col += index - start
    tokens.append(Token("<end>", line, col, "end"))
    return tokens


class Parser:
    def __init__(self, text):
        self.tokens = tokenize(text)
        self.index = 0
        self.depth = 0

    def peek(self):
        return self.tokens[self.index]

    def take(self, text=None, kind=None):
        token = self.peek()
        if (text is not None and token.text != text) or (kind is not None and token.kind != kind):
            expected = repr(text) if text is not None else kind
            raise AmlSyntaxError(f"expected {expected}, found {token.text!r}", token.line, token.col)
        self.index += 1
        return token.text

    def name(self):
        return self.take(kind="name")

    def sort(self):
        token = self.peek()
        if token.text not in ("Nat", "Bool"):
            raise AmlSyntaxError("expected sort Nat or Bool", token.line, token.col)
        return self.take()

    def expr(self):
        token = self.peek()
        if self.depth >= 200:
            raise AmlSyntaxError("expression nested too deeply", token.line, token.col)
        self.depth += 1
        try:
            return self._expr()
        finally:
            self.depth -= 1

    def _expr(self):
        token = self.peek()
        if token.text == "let":
            self.take("let")
            name = self.name()
            self.take("=")
            bound = self.expr()
            self.take("in")
            return Let(name, bound, self.expr())
        if token.text == "if":
            self.take("if")
            cond = self.expr()
            self.take("then")
            then = self.expr()
            self.take("else")
            return If(cond, then, self.expr())
        if token.text == "(":
            self.take("(")
            result = self.expr()
            self.take(")")
            return result
        if token.kind == "int":
            self.take()
            if len(token.text) > 10 or int(token.text) > MAX_NAT:
                raise AmlSyntaxError("literal too large", token.line, token.col)
            return Lit(int(token.text))
        if token.kind == "name":
            name = self.name()
            if self.peek().text != "(":
                return Var(name)
            self.take("(")
            args = []
            if self.peek().text != ")":
                args.append(self.expr())
                while self.peek().text == ",":
                    self.take(",")
                    args.append(self.expr())
            self.take(")")
            return Call(name, tuple(args))
        raise AmlSyntaxError(f"expected an expression, found {token.text!r}", token.line, token.col)

    def parse(self):
        defs, saves = [], []
        while self.peek().kind != "end":
            if self.peek().text == "def":
                token = self.peek()
                raise AmlSyntaxError("use op NAME(a: Nat) -> Nat = ... instead of def", token.line, token.col)
            if self.peek().text == "op":
                self.take("op")
                name = self.name()
                self.take("(")
                params = []
                sorts = []
                if self.peek().text != ")":
                    params.append(self.name())
                    self.take(":")
                    sorts.append(self.sort())
                    while self.peek().text == ",":
                        self.take(",")
                        params.append(self.name())
                        self.take(":")
                        sorts.append(self.sort())
                self.take(")")
                self.take("->")
                result_sort = self.sort()
                self.take("=")
                defs.append(Def(name, tuple(params), self.expr(), tuple(sorts), result_sort))
                if re.fullmatch(r"L[1-9][0-9]*", self.peek().text):
                    self.take()
            elif self.peek().text == "save":
                self.take("save")
                saves.append(self.name())
            else:
                token = self.peek()
                raise AmlSyntaxError(f"expected 'op' or 'save', found {token.text!r}", token.line, token.col)
        return Program(tuple(defs), tuple(saves))


def parse_program(text):
    parser = Parser(text)
    try:
        return parser.parse()
    except RecursionError as error:
        token = parser.peek()
        raise AmlSyntaxError("expression nested too deeply", token.line, token.col) from error
