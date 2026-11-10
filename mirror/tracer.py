"""Stage 2 (child side): run the user's code and record every step.

This file is started as its own Python process by runner.py:

    python -I -S mirror/tracer.py   < {"code": "...", "max_steps": 500}   > {trace JSON}

Running in a separate process means a crash, a huge loop or a memory explosion
in the user's code can't take down the Flask server, and the parent can kill
us after the time limit.

How tracing works: `sys.settrace(fn)` makes Python call `fn(frame, event, arg)`
when a function starts ("call"), before each new line ("line"), and when a
function finishes ("return"). Each call becomes one step in the trace:

    {"i": 0, "event": "line", "line": 4, "func": "fib", "depth": 1,
     "stack": ["<module>", "fib"], "locals": {"n": "8", "a": "0"},
     "stdout_len": 0, "return_value": "21" (only on "return")}

Safety layers (this is a guard rail for a local learning tool, not a sandbox
for running strangers' code):
  1. check_code() rejects imports outside ALLOWED_MODULES, names like
     __import__, attributes starting with "_", and attributes that walk up
     to Python's internals (gi_frame, f_globals, ...).
  2. The code runs with a small allowlist of builtins (no open, eval, exec...).
  3. Memory, CPU time and file-size limits are set for this process (Linux/macOS).
  4. The parent kills the process after 3 seconds and starts it with an empty
     environment.

Note: this file must stay importable without side effects, because runner.py
imports check_code() from it to report blocked code before starting a process.
"""

import ast
import builtins
import io
import json
import os
import reprlib
import sys
import types

FILENAME = "<code-mirror>"  # the user's code is compiled under this name
MAX_STDOUT = 20_000  # characters of print() output we keep

ALLOWED_MODULES = {
    "math", "random", "string", "itertools", "functools", "collections",
    "heapq", "bisect", "statistics", "fractions", "operator", "copy", "re", "time",
}

# Attributes without a leading "_" that can still reach frames, globals or code.
BLOCKED_ATTRS = {
    "gi_frame", "gi_code", "gi_yieldfrom", "cr_frame", "cr_code", "cr_await",
    "ag_frame", "ag_code", "ag_await", "f_back", "f_globals", "f_locals",
    "f_builtins", "f_code", "f_trace", "tb_frame", "tb_next",
}

# Builtins the user's code may use. Everything else simply doesn't exist for it.
SAFE_BUILTIN_NAMES = [
    "abs", "all", "any", "bin", "bool", "callable", "chr", "dict", "divmod",
    "enumerate", "filter", "float", "format", "frozenset", "hash", "hex", "id",
    "int", "isinstance", "issubclass", "iter", "len", "list", "map", "max",
    "min", "next", "object", "oct", "ord", "pow", "print", "property", "range",
    "repr", "reversed", "round", "set", "slice", "sorted", "staticmethod",
    "classmethod", "str", "sum", "super", "tuple", "zip", "__build_class__",
    # exceptions, so that try/except and raise work
    "ArithmeticError", "AssertionError", "AttributeError", "Exception",
    "IndexError", "KeyError", "LookupError", "NameError", "NotImplementedError",
    "OverflowError", "RecursionError", "RuntimeError", "StopIteration",
    "TypeError", "ValueError", "ZeroDivisionError",
]
# Builtins that exist but explain why they are switched off.
DISABLED_BUILTINS = [
    "open", "eval", "exec", "compile", "input", "getattr", "setattr", "delattr",
    "globals", "locals", "vars", "dir", "breakpoint", "help", "exit", "quit", "memoryview",
]


class BlockedCode(Exception):
    """Raised by check_code() with a student-friendly message and a line number."""

    def __init__(self, message, line=None):
        super().__init__(message)
        self.line = line


# --------------------------------------------------------------------- checks
def check_code(tree):
    """Look through the parsed code for things Code Mirror doesn't allow."""
    for node in ast.walk(tree):
        line = getattr(node, "lineno", None)
        if isinstance(node, ast.Import):
            for alias in node.names:
                _check_module(alias.name, line)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                raise BlockedCode("Relative imports are not allowed in Code Mirror.", line)
            _check_module(node.module or "", line)
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("_"):
                raise BlockedCode(
                    f"'.{node.attr}' is blocked: attribute names starting with '_' can reach "
                    "Python's internals. Please rename it (for example without the underscore).",
                    line,
                )
            if node.attr in BLOCKED_ATTRS:
                raise BlockedCode(f"'.{node.attr}' is blocked in Code Mirror.", line)
        elif isinstance(node, ast.Name) and node.id.startswith("__") and node.id != "__name__":
            raise BlockedCode(f"The name '{node.id}' is blocked in Code Mirror.", line)


def _check_module(name, line):
    if name.split(".")[0] not in ALLOWED_MODULES:
        allowed = ", ".join(sorted(ALLOWED_MODULES))
        raise BlockedCode(f"Importing '{name}' is not allowed. You can import: {allowed}.", line)


class ModuleProxy(types.SimpleNamespace):
    """A filtered copy of a module, handed to the user's code instead of the real one.

    Some allowed modules carry other modules as public attributes (for example
    `fractions.sys`), which would be a back door to `sys.modules["os"]`. The
    proxy only copies public attributes that are not modules, plus submodules
    that are themselves allowed (like `collections.abc`).
    """

    def __repr__(self):
        return f"<module {self.module_name_}>"

    def __getattr__(self, name):  # only called when the attribute is missing
        raise AttributeError(f"module '{self.module_name_}' has no attribute '{name}' (in Code Mirror)")


def module_proxy(module, cache):
    if id(module) in cache:
        return cache[id(module)]
    proxy = ModuleProxy(module_name_=module.__name__)
    cache[id(module)] = proxy
    for name in dir(module):
        if name.startswith("_"):
            continue
        value = getattr(module, name)
        if isinstance(value, types.ModuleType):
            if value.__name__.split(".")[0] in ALLOWED_MODULES:
                setattr(proxy, name, module_proxy(value, cache))
            continue  # any other module is left out
        setattr(proxy, name, value)
    return proxy


def make_builtins():
    """The tiny builtins dict the user's code sees instead of the real one."""
    safe = {name: getattr(builtins, name) for name in SAFE_BUILTIN_NAMES}
    real_import = builtins.__import__
    cache = {}

    def safe_import(name, globals=None, locals=None, fromlist=(), level=0):
        _check_module(name, None)  # second check at run time, in case the AST check is bypassed
        if level:
            raise ImportError("Relative imports are not allowed in Code Mirror.")
        return module_proxy(real_import(name, globals, locals, fromlist, level), cache)

    def disabled(name):
        def blocked(*args, **kwargs):
            raise PermissionError(f"{name}() is disabled in Code Mirror.")
        return blocked

    safe["__import__"] = safe_import
    for name in DISABLED_BUILTINS:
        safe[name] = disabled(name)
    return safe


def limit_resources():
    """Cap memory, CPU time and file writes for this process (not available on Windows)."""
    try:
        import resource
    except ImportError:
        return
    limits = [
        ("RLIMIT_AS", 512 * 1024 * 1024),  # 512 MB of memory
        ("RLIMIT_CPU", 5),  # seconds of CPU time (the parent's 3 s wall clock usually fires first)
        ("RLIMIT_FSIZE", 0),  # may not write files
    ]
    for name, value in limits:
        if hasattr(resource, name):
            try:
                resource.setrlimit(getattr(resource, name), (value, value))
            except (ValueError, OSError):
                pass  # some systems (e.g. macOS for RLIMIT_AS) refuse; the other layers still apply


# ------------------------------------------------------------------ recording
class LimitedOutput(io.StringIO):
    """Stands in for sys.stdout so print() output is captured (up to MAX_STDOUT chars)."""

    def write(self, text):
        room = MAX_STDOUT - self.tell()
        if room > 0:
            super().write(text[:room])
        return len(text)


class Recorder:
    def __init__(self, max_steps, out, real_stdout):
        self.max_steps = max_steps
        self.out = out
        self.real_stdout = real_stdout
        self.steps = []
        self.repr = reprlib.Repr()
        self.repr.maxstring = 60
        self.repr.maxother = 60
        self.repr.maxlist = self.repr.maxtuple = self.repr.maxset = self.repr.maxdict = 12

    def trace(self, frame, event, arg):
        """Called by Python for every call / line / return in any frame."""
        code = frame.f_code
        if code.co_filename != FILENAME:
            return None  # library code (e.g. inside `random`): don't trace it
        if code.co_name.startswith("<") and code.co_name != "<module>":
            return None  # lambdas and generator expressions: too fine-grained to show
        if event in ("call", "line", "return"):
            self.record(frame, event, arg)
        return self.trace  # keep receiving line events for this frame

    def record(self, frame, event, arg):
        if len(self.steps) >= self.max_steps:
            # Stop right here, even if the user's code is inside a try/except.
            self.finish(truncated=True, error=None)
        stack = []
        f = frame
        while f is not None:
            if f.f_code.co_filename == FILENAME:
                stack.append(f.f_code.co_qualname)
            f = f.f_back
        stack.reverse()
        step = {
            "i": len(self.steps),
            "event": event,
            "line": frame.f_lineno,
            "func": frame.f_code.co_qualname,
            "depth": len(stack) - 1,
            "stack": stack,
            "locals": self.snapshot(frame),
            "stdout_len": self.out.tell(),
        }
        if event == "return":
            step["return_value"] = self.safe_repr(arg)
        self.steps.append(step)

    def snapshot(self, frame):
        """Current variables as short strings. Functions, classes and modules are left out."""
        result = {}
        for name, value in list(frame.f_locals.items()):
            if name.startswith("__") or callable(value) or isinstance(value, (types.ModuleType, ModuleProxy)):
                continue
            result[name] = self.safe_repr(value)
        return result

    def safe_repr(self, value):
        try:
            return self.repr.repr(value)
        except Exception:  # a user-defined __repr__ could fail
            return "<unprintable>"

    def finish(self, truncated, error):
        """Write the trace JSON to the real stdout and end the process immediately."""
        sys.settrace(None)
        result = {
            "steps": self.steps,
            "stdout": self.out.getvalue(),
            "truncated": truncated,
            "error": error,
        }
        self.real_stdout.write(json.dumps(result))
        self.real_stdout.flush()
        os._exit(0)  # skip any user `finally:` blocks and atexit handlers


def error_line(exc):
    """The last line of the *user's* code in an exception's traceback."""
    line = None
    tb = exc.__traceback__
    while tb is not None:
        if tb.tb_frame.f_code.co_filename == FILENAME:
            line = tb.tb_lineno
        tb = tb.tb_next
    return line


# ----------------------------------------------------------------------- main
def main():
    request = json.loads(sys.stdin.read())
    source = request["code"]
    max_steps = int(request.get("max_steps", 500))
    real_stdout = sys.stdout
    out = LimitedOutput()
    recorder = Recorder(max_steps, out, real_stdout)

    try:
        tree = ast.parse(source, FILENAME)
        check_code(tree)
        code_obj = compile(tree, FILENAME, "exec")
    except SyntaxError as e:
        recorder.finish(False, {"kind": "syntax", "message": e.msg, "line": e.lineno})
    except BlockedCode as e:
        recorder.finish(False, {"kind": "blocked", "message": str(e), "line": e.line})

    user_globals = {"__builtins__": make_builtins(), "__name__": "__main__"}
    limit_resources()
    sys.stdout = sys.stderr = out  # print() goes into our buffer
    sys.setrecursionlimit(400)

    error = None
    sys.settrace(recorder.trace)
    try:
        exec(code_obj, user_globals)
    except BaseException as e:  # noqa: BLE001 - we report every kind of failure to the student
        sys.settrace(None)
        kind = "blocked" if isinstance(e, PermissionError) else "runtime"
        error = {"kind": kind, "message": f"{type(e).__name__}: {e}", "line": error_line(e)}
    sys.settrace(None)
    recorder.finish(False, error)


if __name__ == "__main__":
    main()
