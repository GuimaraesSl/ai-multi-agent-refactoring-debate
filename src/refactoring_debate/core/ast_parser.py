"""AST parsing and syntactic representation.

The first stage of the pipeline (paper §4.2): the submitted code is parsed into a
Python Abstract Syntax Tree and reduced to a structured representation. Agents later
correlate this representation with the deterministic metrics to localize and justify
refactorings.
"""

from __future__ import annotations

import ast

from pydantic import BaseModel, Field

_DEF_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
_LOOP_NODES = (ast.For, ast.AsyncFor, ast.While)
_NESTING_NODES = (
    ast.If,
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.With,
    ast.AsyncWith,
    ast.Try,
)
_COMPREHENSIONS = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)


class FunctionInfo(BaseModel):
    """Syntactic signals for a single function/method."""

    name: str
    qualname: str
    lineno: int
    end_lineno: int | None = None
    is_method: bool = False
    is_async: bool = False
    num_args: int = 0
    num_statements: int = 0
    max_nesting: int = 0
    max_loop_depth: int = 0
    num_loops: int = 0
    num_branches: int = 0
    num_returns: int = 0
    num_calls: int = 0
    has_docstring: bool = False
    decorators: list[str] = Field(default_factory=list)
    complexity_hint: int = 1  # cheap cyclomatic estimate (Radon is authoritative)

    @property
    def length(self) -> int:
        if self.end_lineno is None:
            return 0
        return self.end_lineno - self.lineno + 1


class ClassInfo(BaseModel):
    """Syntactic signals for a class."""

    name: str
    lineno: int
    end_lineno: int | None = None
    bases: list[str] = Field(default_factory=list)
    methods: list[str] = Field(default_factory=list)
    num_methods: int = 0
    has_docstring: bool = False

    @property
    def length(self) -> int:
        if self.end_lineno is None:
            return 0
        return self.end_lineno - self.lineno + 1


class ImportInfo(BaseModel):
    module: str
    names: list[str] = Field(default_factory=list)
    lineno: int = 0
    is_from: bool = False
    level: int = 0  # relative import depth


class ASTRepresentation(BaseModel):
    """Structured syntactic representation of a Python module."""

    filename: str
    loc: int = 0  # physical lines of code
    num_functions: int = 0
    num_classes: int = 0
    num_imports: int = 0
    has_module_docstring: bool = False
    functions: list[FunctionInfo] = Field(default_factory=list)
    classes: list[ClassInfo] = Field(default_factory=list)
    imports: list[ImportInfo] = Field(default_factory=list)
    syntax_ok: bool = True
    syntax_error: str | None = None

    @property
    def max_loop_depth(self) -> int:
        return max((f.max_loop_depth for f in self.functions), default=0)

    @property
    def max_complexity_hint(self) -> int:
        return max((f.complexity_hint for f in self.functions), default=1)

    def prompt_summary(self) -> dict:
        """Compact, LLM-friendly view of the syntactic structure."""
        return {
            "filename": self.filename,
            "loc": self.loc,
            "has_module_docstring": self.has_module_docstring,
            "imports": [
                {"module": i.module, "names": i.names, "line": i.lineno} for i in self.imports
            ],
            "functions": [
                {
                    "name": f.qualname,
                    "line": f.lineno,
                    "length": f.length,
                    "args": f.num_args,
                    "max_nesting": f.max_nesting,
                    "max_loop_depth": f.max_loop_depth,
                    "loops": f.num_loops,
                    "branches": f.num_branches,
                    "returns": f.num_returns,
                    "complexity_hint": f.complexity_hint,
                    "has_docstring": f.has_docstring,
                }
                for f in self.functions
            ],
            "classes": [
                {
                    "name": c.name,
                    "line": c.lineno,
                    "length": c.length,
                    "bases": c.bases,
                    "num_methods": c.num_methods,
                    "has_docstring": c.has_docstring,
                }
                for c in self.classes
            ],
        }


# --------------------------------------------------------------------------- #
#  Parsing helpers
# --------------------------------------------------------------------------- #
def _own_children(node: ast.AST):
    """Iterate descendants of ``node`` without crossing into nested defs/classes."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, _DEF_NODES):
            continue
        yield child
        yield from _own_children(child)


def _max_depth(node: ast.AST, kinds: tuple[type, ...], depth: int = 0) -> int:
    best = depth
    for child in ast.iter_child_nodes(node):
        if isinstance(child, _DEF_NODES):
            continue
        inc = 1 if isinstance(child, kinds) else 0
        best = max(best, _max_depth(child, kinds, depth + inc))
    return best


def _decorator_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Call):
        return _decorator_name(node.func)
    return "?"


def _function_info(
    node: ast.FunctionDef | ast.AsyncFunctionDef, qualname: str, is_method: bool
) -> FunctionInfo:
    own = list(_own_children(node))
    loops = sum(isinstance(n, _LOOP_NODES) for n in own)
    comprehensions = sum(isinstance(n, _COMPREHENSIONS) for n in own)
    branches = sum(isinstance(n, (ast.If, ast.IfExp, ast.ExceptHandler)) for n in own)
    bool_ops = sum(
        len(n.values) - 1 for n in own if isinstance(n, ast.BoolOp)  # type: ignore[attr-defined]
    )
    returns = sum(isinstance(n, ast.Return) for n in own)
    calls = sum(isinstance(n, ast.Call) for n in own)
    statements = sum(isinstance(n, ast.stmt) for n in own)
    complexity = 1 + branches + loops + comprehensions + bool_ops

    return FunctionInfo(
        name=node.name,
        qualname=qualname,
        lineno=node.lineno,
        end_lineno=getattr(node, "end_lineno", None),
        is_method=is_method,
        is_async=isinstance(node, ast.AsyncFunctionDef),
        num_args=len(node.args.args) + len(node.args.kwonlyargs) + len(node.args.posonlyargs),
        num_statements=statements,
        max_nesting=_max_depth(node, _NESTING_NODES),
        max_loop_depth=_max_depth(node, _LOOP_NODES),
        num_loops=loops + comprehensions,
        num_branches=branches,
        num_returns=returns,
        num_calls=calls,
        has_docstring=ast.get_docstring(node) is not None,
        decorators=[_decorator_name(d) for d in node.decorator_list],
        complexity_hint=complexity,
    )


def _walk_module(tree: ast.Module, rep: ASTRepresentation) -> None:
    """Populate ``rep`` with functions, classes and imports from ``tree``."""

    def visit(node: ast.AST, prefix: str, inside_class: bool) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qualname = f"{prefix}.{child.name}" if prefix else child.name
                rep.functions.append(_function_info(child, qualname, is_method=inside_class))
                visit(child, qualname, inside_class=False)  # nested defs
            elif isinstance(child, ast.ClassDef):
                qualname = f"{prefix}.{child.name}" if prefix else child.name
                methods = [
                    n.name
                    for n in child.body
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                ]
                rep.classes.append(
                    ClassInfo(
                        name=child.name,
                        lineno=child.lineno,
                        end_lineno=getattr(child, "end_lineno", None),
                        bases=[_decorator_name(b) for b in child.bases],
                        methods=methods,
                        num_methods=len(methods),
                        has_docstring=ast.get_docstring(child) is not None,
                    )
                )
                visit(child, qualname, inside_class=True)
            elif isinstance(child, ast.Import):
                for alias in child.names:
                    rep.imports.append(
                        ImportInfo(module=alias.name, names=[], lineno=child.lineno, is_from=False)
                    )
            elif isinstance(child, ast.ImportFrom):
                rep.imports.append(
                    ImportInfo(
                        module=child.module or "",
                        names=[a.name for a in child.names],
                        lineno=child.lineno,
                        is_from=True,
                        level=child.level,
                    )
                )
            else:
                visit(child, prefix, inside_class)

    visit(tree, prefix="", inside_class=False)


def parse_code(code: str, filename: str = "<submitted>") -> ASTRepresentation:
    """Parse ``code`` into an :class:`ASTRepresentation`.

    Syntax errors are captured (never raised) so the pipeline can still report
    them through the normal channels.
    """
    loc = code.count("\n") + (0 if code.endswith("\n") else 1) if code else 0
    rep = ASTRepresentation(filename=filename, loc=loc)
    try:
        tree = ast.parse(code, filename=filename)
    except SyntaxError as exc:  # pragma: no cover - exercised via tests
        rep.syntax_ok = False
        rep.syntax_error = f"{exc.msg} (line {exc.lineno}, col {exc.offset})"
        return rep

    rep.has_module_docstring = ast.get_docstring(tree) is not None
    _walk_module(tree, rep)
    rep.num_functions = len(rep.functions)
    rep.num_classes = len(rep.classes)
    rep.num_imports = len(rep.imports)
    return rep
