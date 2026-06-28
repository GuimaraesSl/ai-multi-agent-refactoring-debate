"""Tests for the AST representation."""

from __future__ import annotations

from refactoring_debate.core.ast_parser import parse_code


def test_parses_functions_classes_imports(sample_code: str) -> None:
    rep = parse_code(sample_code, "sample.py")
    assert rep.syntax_ok
    assert rep.num_functions >= 1
    assert any(c.name == "ReportManager" for c in rep.classes)
    assert any(i.module == "os" for i in rep.imports)


def test_detects_nested_loop_depth() -> None:
    rep = parse_code(
        "def f(xs):\n"
        "    for a in xs:\n"
        "        for b in xs:\n"
        "            print(a, b)\n",
        "f.py",
    )
    fn = rep.functions[0]
    assert fn.max_loop_depth == 2
    assert fn.num_loops == 2
    assert rep.max_loop_depth == 2


def test_method_vs_function_and_args() -> None:
    rep = parse_code(
        "class C:\n    def m(self, a, b, c): return a\n\ndef g(x): return x\n", "c.py"
    )
    methods = [f for f in rep.functions if f.is_method]
    assert methods and methods[0].is_method
    assert methods[0].num_args == 4  # self, a, b, c


def test_syntax_error_is_captured_not_raised() -> None:
    rep = parse_code("def broken(:\n    pass\n", "bad.py")
    assert rep.syntax_ok is False
    assert rep.syntax_error is not None
    # downstream code still gets a usable (empty) representation
    assert rep.functions == []


def test_complexity_hint_grows_with_branches() -> None:
    simple = parse_code("def f(x):\n    return x\n", "s.py").functions[0]
    branchy = parse_code(
        "def f(x):\n    if x: return 1\n    elif x>2: return 2\n    for i in x:\n        pass\n",
        "b.py",
    ).functions[0]
    assert branchy.complexity_hint > simple.complexity_hint
