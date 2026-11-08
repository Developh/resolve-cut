"""Every ffmpeg call in skills/resolve-cut/scripts/ keeps the limits in SKILL.md: it starts with nice -n 15, has
-filter_threads 2 -filter_complex_threads 2 before the first -i, -threads 2 before every -i (the input's own options,
like -ss, -t, -f or -loop, may sit between the two) and -threads 2 after the last -i, before every encoder that is not
copy. An output with no codec flag still encodes (s16le, flac, png) and needs it too; -f null and stream copy do not.
Static: reads the scripts with ast and runs nothing. It follows helpers like ff(*a), lists built with +=, extend and
append, and lists spread with *. It checks both sides of `x if c else y`, and additions made inside an if or a loop
both with and without them. A command it cannot read fails, and so does finding no ffmpeg call at all. ffmpeg named
anywhere else (a shell string, a path, a name kept in a variable, shutil.which) fails too, since this test would not
see that call.

    python3 tests/test_ffmpeg_threads.py
"""
import ast
import glob
import os
import re
import sys

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
SCRIPTS = os.path.join(ROOT, "skills", "resolve-cut", "scripts")
CODEC_FLAGS = ("-c", "-codec", "-vcodec", "-acodec")
MUTATORS = ("append", "extend", "insert", "remove", "pop", "clear", "sort", "reverse")
MAX_VARIANTS = 256
SHELL_FFMPEG = re.compile(r"(?:^|[\s/])ffmpeg\s+-")


class Unreadable(Exception):
    """A command this test cannot expand. The call fails instead of being skipped."""


def pos(node):
    return node.lineno, node.col_offset


def is_ffmpeg_list(node):
    return isinstance(node, (ast.List, ast.Tuple)) and any(isinstance(e, ast.Constant) and e.value == "ffmpeg" for e in node.elts)


def concat(parts):
    """Each part is a list of alternatives (token lists). Returns every combination, joined in order."""
    out = [[]]
    for alternatives in parts:
        out = [a + b for a in out for b in alternatives]
        if len(out) > MAX_VARIANTS:
            raise Unreadable(f"more than {MAX_VARIANTS} variants")
    return out


class Script:
    def __init__(self, path):
        self.rel = os.path.relpath(path, ROOT)
        self.tree = ast.parse(open(path, encoding="utf-8").read(), path)
        self.parent = {}
        for node in ast.walk(self.tree):
            for field, value in ast.iter_fields(node):
                for child in value if isinstance(value, list) else [value]:
                    if isinstance(child, ast.AST):
                        self.parent[child] = (node, field)
        self.helpers = {}  # function name -> (its ffmpeg list, index of *vararg in it)
        for fn in ast.walk(self.tree):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and fn.args.vararg:
                for node in ast.walk(fn):
                    if is_ffmpeg_list(node):
                        star = [k for k, e in enumerate(node.elts) if isinstance(e, ast.Starred)
                                and isinstance(e.value, ast.Name) and e.value.id == fn.args.vararg.arg]
                        if star:
                            self.helpers[fn.name] = (node, star[0])
        self.scope_nodes = {}

    def scope(self, node):
        while not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Module)):
            node = self.parent[node][0]
        return node

    def stmt(self, node):
        while not isinstance(node, ast.stmt):
            node = self.parent[node][0]
        return node

    def nodes(self, scope):
        """Nodes of a function (or of the module), without the functions nested in it."""
        if id(scope) not in self.scope_nodes:
            out, todo = [], list(ast.iter_child_nodes(scope))
            while todo:
                n = todo.pop()
                if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    out.append(n)
                    todo.extend(ast.iter_child_nodes(n))
            self.scope_nodes[id(scope)] = out
        return self.scope_nodes[id(scope)]

    def statements(self, scope):
        return sorted((n for n in self.nodes(scope) if isinstance(n, ast.stmt)), key=pos)

    def change(self, s, name):
        """What statement s does to the list `name`: ("set", value), ("add", list), ("add1", element),
        ("other", None) for anything this test does not follow, or None."""
        is_name = lambda n: isinstance(n, ast.Name) and n.id == name
        if isinstance(s, ast.Expr) and isinstance(s.value, ast.Call) and isinstance(s.value.func, ast.Attribute) \
                and is_name(s.value.func.value) and s.value.func.attr in ("extend", "append") and len(s.value.args) == 1:
            return ("add" if s.value.func.attr == "extend" else "add1"), s.value.args[0]
        if isinstance(s, (ast.Assign, ast.AnnAssign)) and s.value is not None \
                and any(is_name(t) for t in (s.targets if isinstance(s, ast.Assign) else [s.target])):
            v = s.value
            if isinstance(v, ast.BinOp) and isinstance(v.op, ast.Add) and is_name(v.left) \
                    and not any(is_name(n) for n in ast.walk(v.right)):
                return "add", v.right
            return ("other", None) if any(is_name(n) for n in ast.walk(v)) else ("set", v)
        if isinstance(s, ast.AugAssign) and is_name(s.target):
            return ("add", s.value) if isinstance(s.op, ast.Add) else ("other", None)
        targets = {ast.Assign: lambda: s.targets, ast.AnnAssign: lambda: [s.target], ast.AugAssign: lambda: [s.target],
                   ast.For: lambda: [s.target], ast.AsyncFor: lambda: [s.target], ast.Delete: lambda: s.targets,
                   ast.With: lambda: [i.optional_vars for i in s.items if i.optional_vars],
                   ast.AsyncWith: lambda: [i.optional_vars for i in s.items if i.optional_vars]}.get(type(s), list)()
        own = [n for c in ast.iter_child_nodes(s) if not isinstance(c, ast.stmt) for n in ast.walk(c)]
        if any(is_name(n) or isinstance(n, ast.Subscript) and is_name(n.value) for t in targets for n in ast.walk(t)) \
                or any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and is_name(n.func.value)
                       and n.func.attr in MUTATORS for n in own):
            return "other", None
        return None

    def value_at(self, name, at):
        """Variants of the list `name` holds at node `at`: its last assignment in the same function, then the +=,
        extend and append after it. An addition inside an if, a loop or a try counts both with and without."""
        changes = []
        for s in reversed([s for s in self.statements(self.scope(at)) if pos(s) < pos(at)]):
            c = self.change(s, name)
            if c is None:
                continue
            how, expr = c
            if how == "other":
                raise Unreadable(f"line {s.lineno} changes {name} in a way this test does not follow")
            if how == "set":
                variants = self.alternatives(expr)
                for s2, how2, e2 in reversed(changes):
                    extra = self.alternatives(e2) if how2 == "add" else [[self.token(e2)]]
                    if self.parent[s2] != self.parent[s]:
                        extra = extra + [[]]
                    variants = concat([variants, extra])
                return variants
            changes.append((s, how, expr))
        raise Unreadable(f"no list is assigned to {name} before line {at.lineno}")

    def alternatives(self, e):
        """Variants (token lists) of an expression that gives a list of arguments."""
        if isinstance(e, (ast.List, ast.Tuple)):
            return self.elements(e.elts)
        if isinstance(e, ast.IfExp):
            return self.alternatives(e.body) + self.alternatives(e.orelse)
        if isinstance(e, ast.BinOp) and isinstance(e.op, ast.Add):
            return concat([self.alternatives(e.left), self.alternatives(e.right)])
        if isinstance(e, ast.Name):
            return self.value_at(e.id, e)
        if isinstance(e, ast.Call) and isinstance(e.func, ast.Name) and e.func.id in self.helpers:
            return self.helper_call(e)
        raise Unreadable(f"cannot expand {ast.unparse(e)}")

    def elements(self, elts):
        return concat([self.alternatives(e.value) if isinstance(e, ast.Starred) else [[self.token(e)]] for e in elts])

    def token(self, e):
        """A string argument as is; anything computed as <its source>, which never matches a flag."""
        return e.value if isinstance(e, ast.Constant) and isinstance(e.value, str) else f"<{ast.unparse(e)}>"

    def helper_call(self, call):
        lst, k = self.helpers[call.func.id]
        return concat([self.elements(lst.elts[:k]), self.elements(call.args), self.elements(lst.elts[k + 1:])])

    def uses(self, name, s):
        """Where the list that statement s assigns to `name` is read: every load of `name` after s and before its next
        assignment, outside the statements that add to it."""
        later = [x for x in self.statements(self.scope(s)) if pos(x) > pos(s)]
        kinds = {id(x): (self.change(x, name) or (None,))[0] for x in later}
        stop = next((pos(x) for x in later if kinds[id(x)] == "set"), None)
        return [n for n in self.nodes(self.scope(s)) if isinstance(n, ast.Name) and n.id == name and isinstance(n.ctx, ast.Load)
                and pos(n) > pos(s) and (stop is None or pos(n) < stop) and kinds.get(id(self.stmt(n))) not in ("add", "add1")]

    def calls(self):
        """(line, build) for every ffmpeg call: build() returns its variants as token lists."""
        helper_lists = {id(lst) for lst, _ in self.helpers.values()}
        done = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in self.helpers:
                yield node.lineno, lambda node=node: self.helper_call(node)
            elif is_ffmpeg_list(node) and id(node) not in helper_lists:
                top = node
                while isinstance(self.parent[top][0], ast.BinOp) and isinstance(self.parent[top][0].op, ast.Add) \
                        or isinstance(self.parent[top][0], ast.IfExp) and self.parent[top][1] != "test":
                    top = self.parent[top][0]
                if id(top) in done:
                    continue
                done.add(id(top))
                p = self.parent[top][0]
                names = [t.id for t in (p.targets if isinstance(p, ast.Assign) else [p.target] if isinstance(p, ast.AnnAssign) else [])
                         if isinstance(t, ast.Name)]
                uses = [(name, use) for name in names for use in self.uses(name, p)]
                for name, use in uses:
                    yield p.lineno, lambda name=name, use=use: self.value_at(name, use)
                if not uses:
                    yield top.lineno, lambda top=top: self.alternatives(top)

    def strays(self):
        """(line, text) for ffmpeg named outside a list that calls() reads: "ffmpeg" or a path to it on its own, or a
        string that runs it ("ffmpeg -i ..."). Docstrings do not count."""
        docs = {id(n.body[0].value) for n in ast.walk(self.tree)
                if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.body
                and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
        for n in ast.walk(self.tree):
            if not (isinstance(n, ast.Constant) and isinstance(n.value, str)) or id(n) in docs:
                continue
            v = n.value
            if v == "ffmpeg" and is_ffmpeg_list(self.parent[n][0]):
                continue
            if v == "ffmpeg" or v.endswith("/ffmpeg") or SHELL_FFMPEG.search(v):
                yield n.lineno, v


def last_value(t, flag, lo, hi):
    """Value of the last `flag` in t[lo:hi] (flag and value both inside), or None."""
    found = None
    for k in range(lo, hi - 1):
        if t[k] == flag:
            found = t[k + 1]
    return found


def missing(t, flag, lo, hi):
    """How `flag 2` is missing from t[lo:hi], or None if the last `flag` there is 2."""
    value = last_value(t, flag, lo, hi)
    return None if value == "2" else f"no {flag} 2" if value is None else f"{flag} {value} instead of {flag} 2"


def stream(flag):
    if flag in ("-c", "-codec"):
        return "all"
    if flag == "-vcodec" or flag.startswith(("-c:v", "-codec:v")):
        return "v"
    if flag == "-acodec" or flag.startswith(("-c:a", "-codec:a")):
        return "a"
    return flag


def check(t):
    """What one ffmpeg command (as tokens) is missing."""
    problems = []
    if t[:4] != ["nice", "-n", "15", "ffmpeg"]:
        problems.append("does not start with nice -n 15 ffmpeg")
    start = t.index("ffmpeg") + 1
    inputs = [k for k in range(start, len(t) - 1) if t[k] == "-i"]
    if not inputs:
        return problems + ["has no -i, so the per-input -threads 2 cannot be checked"]
    for flag in ("-filter_threads", "-filter_complex_threads"):
        if gap := missing(t, flag, start, inputs[0]):
            problems.append(f"{gap} before the first -i")
    lo = start
    for n, k in enumerate(inputs, 1):
        if gap := missing(t, "-threads", lo, k):
            where = "since ffmpeg" if n == 1 else "since the previous -i"
            problems.append(f"input {n} (-i {t[k + 1]}): {gap} before it ({where})")
        lo = k + 2
    codecs = [(k, t[k], t[k + 1]) for k in range(lo, len(t) - 1) if t[k] in CODEC_FLAGS or t[k].startswith(("-c:", "-codec:"))]
    encoders = [c for c in codecs if c[2] != "copy"]
    for k, flag, codec in encoders:
        if gap := missing(t, "-threads", lo, k):
            problems.append(f"encoder {flag} {codec}: {gap} between the last -i and it")
    if not encoders:
        out = t[lo:]
        copied = {stream(flag) for _, flag, _ in codecs}
        all_copy = "all" in copied or ("v" in copied or "-vn" in out) and ("a" in copied or "-an" in out)
        null = any(out[k:k + 2] == ["-f", "null"] for k in range(len(out)))
        gap = missing(t, "-threads", lo, len(t))
        if gap and not null and not all_copy:
            problems.append(f"the output encodes with the default encoder (no -c:v/-c:a): {gap} after the last -i")
    return problems


def main():
    paths = sorted(glob.glob(os.path.join(SCRIPTS, "**", "*.py"), recursive=True))
    total, errors = 0, []
    for path in paths:
        script = Script(path)
        for line, build in script.calls():
            total += 1
            where = f"{script.rel}:{line}"
            try:
                variants = build()
            except Unreadable as e:
                errors.append(f"{where}: cannot read this ffmpeg command ({e}): write it as a list, or teach this test the new form")
                continue
            seen = set()
            for tokens in variants:
                if "ffmpeg" not in tokens:
                    continue
                for problem in check(tokens):
                    if problem not in seen:
                        seen.add(problem)
                        errors.append(f"{where}: {problem}\n    {' '.join(tokens)}")
        for line, text in script.strays():
            errors.append(f"{script.rel}:{line}: ffmpeg outside a command list this test reads ({text!r}): write the call as "
                          f"a list starting with \"nice\", \"-n\", \"15\", \"ffmpeg\", or teach this test the new form")
    if not total:
        sys.exit(f"no ffmpeg call found in {os.path.relpath(SCRIPTS, ROOT)}: this test no longer sees the commands it guards")
    if errors:
        sys.exit(f"{len(errors)} problem(s) in {total} ffmpeg calls (the rule is in skills/resolve-cut/SKILL.md):\n" + "\n".join(errors))
    print(f"ok: nice and 2 threads in {total} ffmpeg calls")


if __name__ == "__main__":
    main()
