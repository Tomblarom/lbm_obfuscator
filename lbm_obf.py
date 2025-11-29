#!/usr/bin/env python3
import sys
import re
import random
from pathlib import Path

# ------------------------------------------------------------
# Tokenizer + AST
# ------------------------------------------------------------

_token_re = re.compile(r"""
    \s+|                   # whitespace
    ;[^\n]*|               # comments
    "(?:\\.|[^"\\])*"|     # strings
    \[\||\|\]|             # [| and |]
    \(|\)|\{|\}|\[|\]|     # brackets
    ,@|['`,]|              # quote tokens
    [^\s\(\)\{\}\[\]'`,]+  # symbols
""", re.VERBOSE)

def tokenize(src: str):
    out = []
    for m in _token_re.finditer(src):
        t = m.group(0)
        if not t or t.isspace():
            continue
        if t.startswith(";"):
            continue  # strip comments
        out.append(t)
    return out

class Node: pass

class Atom(Node):
    def __init__(self, v):
        self.v = v

class List(Node):
    def __init__(self, kind, items):
        self.kind = kind  # "()", "{}", "[]"
        self.items = items

class Quote(Node):
    def __init__(self, q, expr):
        self.q = q        # "'", "`", ",", ",@"
        self.expr = expr

_open_to_close = {"(" : ")", "{" : "}", "[" : "]"}
_quote_tokens = ("'", "`", ",", ",@")

def parse_tokens(toks, i=0):
    def p_expr(i):
        t = toks[i]
        if t in _quote_tokens:
            expr, j = p_expr(i + 1)
            return Quote(t, expr), j
        if t in "([{":
            kind = t + _open_to_close[t]
            items = []
            j = i + 1
            while j < len(toks) and toks[j] != _open_to_close[t]:
                e, j = p_expr(j)
                items.append(e)
            if j >= len(toks):
                raise SyntaxError("Unbalanced brackets")
            return List(kind, items), j + 1
        return Atom(t), i + 1

    out = []
    while i < len(toks) and toks[i] not in ")]}":
        e, i = p_expr(i)
        out.append(e)
    return out, i

def parse(src: str):
    toks = tokenize(src)
    ast, pos = parse_tokens(toks, 0)
    if pos != len(toks):
        raise SyntaxError("Extra tokens at end")
    return ast

def _uses_update_vt(node):
    """
    Return True if this subtree contains a call (update-vt ...).
    Case-insensitive symbol check.
    """
    if isinstance(node, List) and node.items:
        head = node.items[0]
        if isinstance(head, Atom) and head.v.lower() == "update-vt":
            return True
        for ch in node.items:
            if _uses_update_vt(ch):
                return True
    elif isinstance(node, Quote):
        # don't look inside quoted data; 'update-vt there is just data
        return False
    return False


def filter_debug_forms(ast):
    """
    Remove *top-level* debug forms:

      - (def vt-* ...)
      - (define vt-* ...)
      - (defun update-vt ...)
      - bare top-level (update-vt ...) calls
      - any top-level (loopwhile-thd ...) whose body calls update-vt
    """
    out = []

    for form in ast:
        drop = False

        if isinstance(form, List) and form.items:
            head = form.items[0]

            if isinstance(head, Atom):
                h = head.v

                # (def vt-* ...) or (define vt-* ...)
                if h in ("def", "define") and len(form.items) >= 2:
                    name_node = form.items[1]
                    if isinstance(name_node, Atom):
                        nm = name_node.v.lower()
                        if nm.startswith("vt-"):
                            drop = True

                # (defun update-vt ...)
                if not drop and h == "defun" and len(form.items) >= 2:
                    name_node = form.items[1]
                    if isinstance(name_node, Atom):
                        nm = name_node.v.lower()
                        if nm == "update-vt":
                            drop = True

                # bare top-level (update-vt ...) call
                if not drop and h.lower() == "update-vt":
                    drop = True

                # thread that calls update-vt anywhere inside:
                # (loopwhile-thd 120 t { (update-vt) ... })
                if not drop and h == "loopwhile-thd":
                    if _uses_update_vt(form):
                        drop = True

        if not drop:
            out.append(form)

    return out

def strip_update_vt_calls(ast):
    """
    Recursively remove *non-top-level* calls to (update-vt ...).

    We delete any List whose head is 'update-vt' (case-insensitive).
    Inside Quotes we do nothing (data only).
    """

    def visit(node):
        # Remove any call (update-vt ...)
        if isinstance(node, List) and node.items:
            head = node.items[0]
            if isinstance(head, Atom) and head.v.lower() == "update-vt":
                return None  # signal to parent: drop this form

            new_items = []
            for ch in node.items:
                v = visit(ch)
                if v is not None:
                    new_items.append(v)
            return List(node.kind, new_items)

        elif isinstance(node, Quote):
            # don't touch quoted data
            return node

        else:
            return node

    new_ast = []
    for expr in ast:
        v = visit(expr)
        if v is not None:
            new_ast.append(v)
    return new_ast

def strip_print_calls(ast, names=("print", "puts")):
    """
    Recursively remove calls to (print ...) and (puts ...), case-insensitive.
    - Removes both top-level and nested occurrences.
    - Preserves quoted data.
    - Keeps bracket structure; if a block becomes empty it's emitted as {} / ()
      which is syntactically valid in LispBM.
    """
    names_lc = {n.lower() for n in names}

    def visit(node):
        if isinstance(node, List) and node.items:
            head = node.items[0]
            if isinstance(head, Atom) and head.v.lower() in names_lc:
                return None  # drop this call

            new_items = []
            for ch in node.items:
                v = visit(ch)
                if v is not None:
                    new_items.append(v)
            return List(node.kind, new_items)

        elif isinstance(node, Quote):
            return node  # do not touch data in quotes

        else:
            return node

    out = []
    for expr in ast:
        v = visit(expr)
        if v is not None:
            out.append(v)
    return out

# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------

def is_string_literal(node: Node) -> bool:
    return isinstance(node, Atom) and len(node.v) >= 2 and node.v[0] == '"' and node.v[-1] == '"'

def is_symbol(node: Node) -> bool:
    return isinstance(node, Atom) and not is_string_literal(node)

def unquote_string_atom(node: Atom) -> str:
    return node.v[1:-1]

# From LispBM docs (lbmref.md), all 2-character built-ins / special forms
BUILTIN_2CHAR = { "//", "<=", ">=", "eq", "gc", "if", "ix", "or", "vt" }

class NameGen:
    """
    Generate random LispBM-valid symbol names:

      - Always at least 2 characters.
      - Start with 2-character names; only go to 3+ when 2-char space is exhausted.
      - First char from FIRST_CHAR.
      - Remaining chars from REST_CHAR.
      - Avoids collisions with:
          * all existing symbols (case-insensitive),
          * all known 2-char built-ins from docs.
      - Never looks like a numeric literal such as 42, -6, +10.
      - Never returns the same name twice.
    """

    # Valid first character set (from LispBM symbol rules)
    FIRST_CHAR = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ+-*/=<>#!"

    # Valid subsequent character set
    REST_CHAR  = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789+-*/=<>!?_"

    def __init__(self, reserved_symbols):
        """
        `reserved_symbols` should include:
          - all symbols already used in the program, and
          - all 2-char built-ins (BUILTIN_2CHAR).
        """
        # LispBM is case-insensitive: normalize everything to lower case
        self.reserved = {s.lower() for s in reserved_symbols}

        # start with 2-character names
        self.current_length = 2

    def _rand_first(self):
        return random.choice(self.FIRST_CHAR)

    def _rand_rest(self):
        return random.choice(self.REST_CHAR)

    @staticmethod
    def _looks_like_integer_literal(name: str) -> bool:
        """
        Disallow integers like "42", "-6", "+10".
        We only care about forms we could generate:
          digits, or [+/-]digits.
        """
        if name.isdigit():
            return True
        if len(name) >= 2 and name[0] in "+-" and name[1:].isdigit():
            return True
        return False

    def next(self) -> str:
        """
        Return a new, unique, valid symbol name.
        - Uses 2-char names first.
        - When 2-char space is effectively full, increases length to 3,
          then 4, etc.
        - Uniqueness is checked case-insensitively.
        """
        while True:
            # Try many random attempts at the current length
            for _ in range(50000):
                name = self._rand_first() + "".join(
                    self._rand_rest() for _ in range(self.current_length - 1)
                )

                # Reject integer-like tokens
                if self._looks_like_integer_literal(name):
                    continue

                key = name.lower()
                if key not in self.reserved:
                    # Reserve and return: guarantees uniqueness
                    self.reserved.add(key)
                    return name

            # If we get here, we failed to find a free name at this length.
            # Increase length and try again (2 -> 3 -> 4 -> ...)
            self.current_length += 1

def collect_all_symbols(ast):
    syms = set()

    def visit(node):
        if isinstance(node, Atom):
            # strings are not symbols
            if not (len(node.v) >= 2 and node.v[0] == '"' and node.v[-1] == '"'):
                syms.add(node.v)
        elif isinstance(node, Quote):
            visit(node.expr)
        elif isinstance(node, List):
            for ch in node.items:
                visit(ch)

    for expr in ast:
        visit(expr)

    return syms

# ------------------------------------------------------------
# Pass 0: inline (import "x.lbm" 'sym) + (read-eval-program sym)
# ------------------------------------------------------------

def load_with_inlines(path: Path, stack=None):
    """
    Load `path`, parse it, and inline any top-level pattern:

      (import "file.lbm" 'sym)
      (read-eval-program sym)

    by replacing those two forms with the full content of file.lbm
    (recursively processed the same way).
    """
    if stack is None:
        stack = set()
    path = Path(path).resolve()
    if path in stack:
        # cycle: just parse as-is
        text = path.read_text(encoding="utf-8")
        return parse(text)

    stack.add(path)
    text = path.read_text(encoding="utf-8")
    ast = parse(text)
    base_dir = path.parent

    new_ast = []
    i = 0
    while i < len(ast):
        expr = ast[i]
        inlined = False

        if isinstance(expr, List) and expr.items:
            head = expr.items[0]
            if isinstance(head, Atom) and head.v == "import" and len(expr.items) >= 3:
                path_node = expr.items[1]
                sym_expr  = expr.items[2]

                sym_name = None
                if isinstance(sym_expr, Quote) and isinstance(sym_expr.expr, Atom):
                    sym_name = sym_expr.expr.v
                elif isinstance(sym_expr, Atom):
                    sym_name = sym_expr.v

                if sym_name is not None and i + 1 < len(ast):
                    next_expr = ast[i + 1]
                    if isinstance(next_expr, List) and next_expr.items:
                        head2 = next_expr.items[0]
                        if isinstance(head2, Atom) and head2.v == "read-eval-program" and len(next_expr.items) >= 2:
                            arg = next_expr.items[1]
                            arg_name = arg.v if isinstance(arg, Atom) else None

                            if arg_name == sym_name and isinstance(path_node, Atom) and is_string_literal(path_node):
                                rel = unquote_string_atom(path_node)
                                imp_path = Path(rel)
                                if not imp_path.is_absolute():
                                    imp_path = (base_dir / imp_path).resolve()
                                try:
                                    imported_ast = load_with_inlines(imp_path, stack)
                                except FileNotFoundError:
                                    imported_ast = None

                                if imported_ast is not None:
                                    new_ast.extend(imported_ast)
                                    i += 2
                                    inlined = True

        if not inlined:
            new_ast.append(expr)
            i += 1

    stack.remove(path)
    return new_ast

# ------------------------------------------------------------
# Pass 1: collect user functions, global vars, thread names
# ------------------------------------------------------------

def collect_symbols(ast):
    user_funcs = set()
    global_defs = set()
    thread_names = set()

    def visit(node: Node):
        if isinstance(node, List) and node.items:
            head = node.items[0]
            if isinstance(head, Atom):
                h = head.v

                # (defun name (args) ...)
                if h == "defun" and len(node.items) >= 2:
                    name_node = node.items[1]
                    if isinstance(name_node, Atom):
                        name = name_node.v
                        if name not in ("main", "image-save"):
                            user_funcs.add(name)
                            global_defs.add(name)

                # (def / define name value...)
                elif h in ("def", "define") and len(node.items) >= 2:
                    name_node = node.items[1]
                    if isinstance(name_node, Atom):
                        name = name_node.v
                        if name not in ("main", "image-save"):
                            global_defs.add(name)
                    if len(node.items) >= 3:
                        value_node = node.items[2]
                        if isinstance(value_node, List) and value_node.items:
                            vhead = value_node.items[0]
                            if isinstance(vhead, Atom) and vhead.v in ("lambda", "fn"):
                                if isinstance(name_node, Atom):
                                    n = name_node.v
                                    if n not in ("main", "image-save"):
                                        user_funcs.add(n)

                # loopwhile-thd: thread name strings
                if h == "loopwhile-thd" and len(node.items) >= 2:
                    stack_expr = node.items[1]
                    if isinstance(stack_expr, Atom) and is_string_literal(stack_expr):
                        thread_names.add(stack_expr.v)
                    elif isinstance(stack_expr, List) and stack_expr.items:
                        first = stack_expr.items[0]
                        if isinstance(first, Atom) and is_string_literal(first):
                            thread_names.add(first.v)

            for ch in node.items:
                visit(ch)

        elif isinstance(node, Quote):
            # we do not care about defs in quoted data here
            return

    for expr in ast:
        visit(expr)

    global_vars = set(
        n for n in global_defs
        if n not in user_funcs and n not in ("main", "image-save")
    )
    return user_funcs, global_vars, thread_names

# ------------------------------------------------------------
# Pass 2: obfuscation
# ------------------------------------------------------------

def rename_atom(atom: Atom, env_stack, func_rename, global_var_rename):
    if not is_symbol(atom):
        return atom
    name = atom.v

    # local lexical envs
    for env in reversed(env_stack):
        if name in env:
            return Atom(env[name])

    # project-wide globals
    if name in global_var_rename:
        return Atom(global_var_rename[name])

    # project-wide functions
    if name in func_rename:
        return Atom(func_rename[name])

    # everything else (builtins, config keys, etc.) stays as-is
    return atom

def obfuscate_node(node: Node,
                   env_stack,
                   func_rename,
                   global_var_rename,
                   name_gen,
                   thread_name_map):

    # Atoms
    if isinstance(node, Atom):
        return rename_atom(node, env_stack, func_rename, global_var_rename)

    # Quotes: do NOT rename inside at all
    if isinstance(node, Quote):
        return Quote(node.q, node.expr)

    # Lists
    if isinstance(node, List):
        # Brace block { ... }
        if node.kind == "{}":
            block_env = {}
            env_stack.append(block_env)
            new_items = []
            for it in node.items:
                if isinstance(it, List) and it.items:
                    head_it = it.items[0]
                    if isinstance(head_it, Atom) and head_it.v == "var" and len(it.items) >= 2:
                        name_atom = it.items[1]
                        if is_symbol(name_atom) and name_atom.v not in block_env:
                            block_env[name_atom.v] = name_gen.next()
                new_items.append(
                    obfuscate_node(it, env_stack, func_rename, global_var_rename,
                                   name_gen, thread_name_map)
                )
            env_stack.pop()
            return List(node.kind, new_items)

        items = node.items
        if not items:
            return List(node.kind, [])

        head = items[0]
        h = head.v if isinstance(head, Atom) else None

        # (lambda (args) ...)
        if isinstance(head, Atom) and h in ("lambda", "fn") and len(items) >= 2:
            params_expr = items[1]
            param_env = {}
            new_params_expr = params_expr
            if isinstance(params_expr, List) and params_expr.kind == "()":
                new_params = []
                for p in params_expr.items:
                    if is_symbol(p):
                        new_name = name_gen.next()
                        param_env[p.v] = new_name
                        new_params.append(Atom(new_name))
                    else:
                        new_params.append(p)
                new_params_expr = List("()", new_params)
            env_stack.append(param_env)
            new_body = [
                obfuscate_node(e, env_stack, func_rename, global_var_rename,
                               name_gen, thread_name_map)
                for e in items[2:]
            ]
            env_stack.pop()
            return List(node.kind, [head, new_params_expr] + new_body)

        # (defun name (args) ...)
        if isinstance(head, Atom) and h == "defun" and len(items) >= 3:
            fname_atom = items[1]
            params_expr = items[2]
            if isinstance(fname_atom, Atom):
                if fname_atom.v in ("main", "image-save"):
                    new_fname = fname_atom.v
                else:
                    new_fname = func_rename.get(fname_atom.v, fname_atom.v)
            else:
                new_fname = fname_atom

            param_env = {}
            new_params_expr = params_expr
            if isinstance(params_expr, List) and params_expr.kind == "()":
                new_params = []
                for p in params_expr.items:
                    if is_symbol(p):
                        new_name = name_gen.next()
                        param_env[p.v] = new_name
                        new_params.append(Atom(new_name))
                    else:
                        new_params.append(p)
                new_params_expr = List("()", new_params)

            env_stack.append(param_env)
            new_body = [
                obfuscate_node(e, env_stack, func_rename, global_var_rename,
                               name_gen, thread_name_map)
                for e in items[3:]
            ]
            env_stack.pop()
            return List(node.kind, [head, Atom(new_fname), new_params_expr] + new_body)

        # (def name value...) / (define ...)
        if isinstance(head, Atom) and h in ("def", "define") and len(items) >= 2:
            name_atom = items[1]
            rest_exprs = items[2:]
            new_name_atom = name_atom

            if isinstance(name_atom, Atom) and is_symbol(name_atom):
                nm = name_atom.v
                if nm in ("main", "image-save"):
                    new_name_atom = name_atom
                elif nm in func_rename:
                    new_name_atom = Atom(func_rename[nm])
                elif nm in global_var_rename:
                    new_name_atom = Atom(global_var_rename[nm])

            new_rest = [
                obfuscate_node(e, env_stack, func_rename, global_var_rename,
                               name_gen, thread_name_map)
                for e in rest_exprs
            ]
            return List(node.kind, [head, new_name_atom] + new_rest)

        # (let ((x e1) (y e2) ...) body...)
        if isinstance(head, Atom) and h == "let" and len(items) >= 2:
            bindings_expr = items[1]
            new_bindings_expr = bindings_expr
            new_env = {}

            if isinstance(bindings_expr, List) and bindings_expr.kind == "()":
                new_bindings = []
                for b in bindings_expr.items:
                    if isinstance(b, List) and b.kind == "()" and b.items:
                        b_name = b.items[0]
                        b_val = b.items[1] if len(b.items) > 1 else Atom("nil")
                        new_b_val = obfuscate_node(
                            b_val, env_stack, func_rename, global_var_rename,
                            name_gen, thread_name_map
                        )
                        if is_symbol(b_name):
                            new_name = name_gen.next()
                            new_env[b_name.v] = new_name
                            new_b_name = Atom(new_name)
                        else:
                            new_b_name = b_name
                        new_bindings.append(List("()", [new_b_name, new_b_val]))
                    else:
                        new_bindings.append(
                            obfuscate_node(b, env_stack, func_rename, global_var_rename,
                                           name_gen, thread_name_map)
                        )
                new_bindings_expr = List("()", new_bindings)

            env_stack.append(new_env)
            new_body = [
                obfuscate_node(e, env_stack, func_rename, global_var_rename,
                               name_gen, thread_name_map)
                for e in items[2:]
            ]
            env_stack.pop()
            return List(node.kind, [head, new_bindings_expr] + new_body)

        # (var x expr ...)
        if isinstance(head, Atom) and h == "var" and len(items) >= 2:
            name_atom = items[1]
            rest_exprs = items[2:]
            new_name_atom = name_atom

            if is_symbol(name_atom):
                curr_env = env_stack[-1]
                if name_atom.v not in curr_env:
                    curr_env[name_atom.v] = name_gen.next()
                new_name_atom = Atom(curr_env[name_atom.v])

            new_rest = [
                obfuscate_node(e, env_stack, func_rename, global_var_rename,
                               name_gen, thread_name_map)
                for e in rest_exprs
            ]
            return List(node.kind, [head, new_name_atom] + new_rest)

        # (loopwhile-thd ...) : obfuscate thread name strings
        if isinstance(head, Atom) and h == "loopwhile-thd" and len(items) >= 2:
            stack_expr = items[1]
            new_stack_expr = stack_expr

            # "Name"
            if isinstance(stack_expr, Atom) and is_string_literal(stack_expr):
                new_stack_expr = Atom(thread_name_map.get(stack_expr.v, stack_expr.v))

            # ("Name" 100)
            elif isinstance(stack_expr, List) and stack_expr.items:
                inner_items = list(stack_expr.items)
                first = inner_items[0]
                if isinstance(first, Atom) and is_string_literal(first):
                    inner_items[0] = Atom(thread_name_map.get(first.v, first.v))
                new_stack_expr = List(stack_expr.kind, inner_items)

            new_rest = [
                obfuscate_node(e, env_stack, func_rename, global_var_rename,
                               name_gen, thread_name_map)
                for e in items[2:]
            ]
            return List(node.kind, [head, new_stack_expr] + new_rest)

        # (import ...) that survived inlining: only rename imported symbol if user-owned
        if isinstance(head, Atom) and h == "import" and len(items) >= 3:
            path_expr = items[1]
            sym_expr  = items[2]
            new_sym_expr = sym_expr

            if isinstance(sym_expr, Quote) and isinstance(sym_expr.expr, Atom):
                sname = sym_expr.expr.v
                if sname in func_rename:
                    new_sym_expr = Quote(sym_expr.q, Atom(func_rename[sname]))
                elif sname in global_var_rename:
                    new_sym_expr = Quote(sym_expr.q, Atom(global_var_rename[sname]))
            elif isinstance(sym_expr, Atom):
                sname = sym_expr.v
                if sname in func_rename:
                    new_sym_expr = Atom(func_rename[sname])
                elif sname in global_var_rename:
                    new_sym_expr = Atom(global_var_rename[sname])

            new_rest = [
                obfuscate_node(e, env_stack, func_rename, global_var_rename,
                               name_gen, thread_name_map)
                for e in items[3:]
            ]
            return List(node.kind, [head, path_expr, new_sym_expr] + new_rest)

        # Generic list (function calls, etc.)
        new_items = []
        new_head = obfuscate_node(head, env_stack, func_rename, global_var_rename,
                                  name_gen, thread_name_map)
        new_items.append(new_head)
        for arg in items[1:]:
            new_items.append(
                obfuscate_node(arg, env_stack, func_rename, global_var_rename,
                               name_gen, thread_name_map)
            )
        return List(node.kind, new_items)

    raise TypeError("Unknown node type in obfuscate_node")

# ------------------------------------------------------------
# Emit + driver
# ------------------------------------------------------------

def emit(node: Node) -> str:
    if isinstance(node, Atom):
        return node.v
    if isinstance(node, Quote):
        return node.q + emit(node.expr)
    if isinstance(node, List):
        op, cl = node.kind[0], node.kind[1]
        return op + " ".join(emit(x) for x in node.items) + cl
    raise TypeError("Unknown node type in emit")

def obfuscate_file(root_path: Path):
    # 0) Merge all imports
    combined_ast = load_with_inlines(root_path)
    combined_ast = filter_debug_forms(combined_ast)
    combined_ast = strip_update_vt_calls(combined_ast)
    combined_ast = strip_print_calls(combined_ast)

    # 1) Collect project-wide symbols
    user_funcs, global_vars, thread_names = collect_symbols(combined_ast)

    # 1b) Collect all existing symbol names (builtins + user + quoted)
    existing_syms = collect_all_symbols(combined_ast)
    reserved_symbols = existing_syms | BUILTIN_2CHAR

    # 2) Build rename maps, using NameGen that avoids ALL existing symbols
    name_gen = NameGen(reserved_symbols)
    func_rename = {}
    for fname in sorted(user_funcs):
        func_rename[fname] = name_gen.next()
    global_var_rename = {}
    for vname in sorted(global_vars):
        global_var_rename[vname] = name_gen.next()

    thread_gen = NameGen(set())  # thread names are strings; no need to avoid symbols
    thread_name_map = {name: '"' + thread_gen.next() + '"' for name in sorted(thread_names)}

    # 3) Obfuscate
    env_stack = [{}]
    obf_ast = [
        obfuscate_node(expr, env_stack, func_rename, global_var_rename,
                       name_gen, thread_name_map)
        for expr in combined_ast
    ]

    # 4) One top-level form per line, no empty lines, compact spaces
    lines = [emit(expr) for expr in obf_ast]
    lines = [ln for ln in lines if ln.strip() != ""]

    compacted = []
    for ln in lines:
        ln = re.sub(r"\(\s+", "(", ln)
        ln = re.sub(r"\s+\)", ")", ln)
        ln = re.sub(r"\[\s+", "[", ln)
        ln = re.sub(r"\s+\]", "]", ln)
        ln = re.sub(r"\{\s+", "{", ln)
        ln = re.sub(r"\s+\}", "}", ln)
        compacted.append(ln)

    return "\n".join(compacted) + "\n"

def main():
    if len(sys.argv) < 2:
        print("Usage: obfuscate_lbm.py <main.lbm>", file=sys.stderr)
        sys.exit(1)

    root = Path(sys.argv[1]).resolve()
    code = obfuscate_file(root)

    out_path = root.with_name(root.stem + "_obf.lbm")
    out_path.write_text(code, encoding="utf-8")

    # Also print to stdout for piping / inspection
    #sys.stdout.write(code)

if __name__ == "__main__":
    main()
