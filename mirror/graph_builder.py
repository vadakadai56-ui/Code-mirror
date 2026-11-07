"""Stage 1: turn Python source code into a flowchart graph.

This module only *reads* the code (with Python's `ast` module). It never runs
it. The result is a plain dict that Flask sends to the browser as JSON:

    {
      "nodes": [ {id, type, label, line, end_line, func, lane, row, col, calls}, ... ],
      "edges": [ {from, to, label, kind}, ... ],
      "lanes": [ {func, title}, ... ],          # one column of the chart per function
      "functions": { qualname: {start, end, lane} },
      "line_map": { "qualname:line": node_id }, # how a trace step finds its node
    }

Node types: start, statement, decision (if/elif/assert), loop, call, return, end.
Edge kinds: "normal" (flows down), "back" (jumps up, e.g. a loop repeating),
            "call" (from a line that calls one of your functions to that function's start).

Layout hints: `row` is the order of nodes inside a lane (top to bottom) and
`col` is the indentation depth, so the chart has the same shape as the code.
The frontend turns these hints into pixels; nothing here knows about drawing.
"""

import ast

MAX_LABEL = 42  # longer labels are shortened with "…"


def build_graph(source):
    """Parse `source` and return the graph dict. Raises SyntaxError on bad code."""
    return GraphBuilder(source).build()


def _short(text):
    """Collapse whitespace and cut long labels so boxes stay a sensible size."""
    text = " ".join(text.split())
    return text if len(text) <= MAX_LABEL else text[: MAX_LABEL - 1] + "…"


class GraphBuilder:
    def __init__(self, source):
        self.source = source
        self.lines = source.splitlines()
        self.nodes = []
        self.edges = []
        self.lanes = []
        self.functions = {}
        self.line_map = {}
        self.user_function_names = set()
        # Functions waiting to be drawn in their own lane: (qualname, def_node, child_prefix)
        self.todo = []

        # State for the scope (function or module) currently being built.
        self.scope = None  # qualname, e.g. "<module>", "fib", "Stack.push"
        self.lane = 0
        self.row = 0
        self.end_id = None  # where `return` statements go
        self.loops = []  # stack of {"header": id, "breaks": [...]} for break/continue
        self.prefix = ""  # qualname prefix for functions defined inside this scope

    # ------------------------------------------------------------------ public
    def build(self):
        tree = ast.parse(self.source)

        # First pass: remember every function name so we can spot calls to them.
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.user_function_names.add(node.name)

        # The main program gets lane 0; each function gets its own lane after it.
        self._build_scope("<module>", "Main program", tree.body, None, "")
        while self.todo:
            qualname, def_node, prefix = self.todo.pop(0)
            self._build_scope(qualname, qualname + "()", def_node.body, def_node, prefix)

        self._add_call_edges()
        self._mark_back_edges()
        return {
            "nodes": self.nodes,
            "edges": self.edges,
            "lanes": self.lanes,
            "functions": self.functions,
            "line_map": self.line_map,
        }

    # ---------------------------------------------------------------- scopes
    def _build_scope(self, qualname, title, body, def_node, prefix):
        """Build one lane: start node, the body's statements, and an end node."""
        self.scope, self.prefix = qualname, prefix
        self.lane = len(self.lanes)
        self.row = 0
        self.loops = []
        self.lanes.append({"func": qualname, "title": title})

        if def_node is None:
            start = self._add("start", "Start", None, None, col=0)
        else:
            args = ", ".join(a.arg for a in def_node.args.args)
            start = self._add("start", f"def {def_node.name}({args})", def_node.lineno, None, col=0, map_lines=False)

        # Create the end node now (so `return` can point at it); fix its row later.
        end_label = "End" if def_node is None else f"end of {def_node.name}()"
        self.end_id = self._add("end", end_label, None, None, col=0)
        end_node = self.nodes[-1]
        self.row -= 1  # don't leave an empty row where the end node was created

        preds = self._block(body, [(start, None)], col=0)
        end_node["row"] = self.row  # end goes below everything else
        self.row += 1
        self._connect(preds, self.end_id)

        self.functions[qualname] = {"start": start, "end": self.end_id, "lane": self.lane}

    # ------------------------------------------------------------ statements
    def _block(self, stmts, preds, col):
        """Build a list of statements one after another.

        `preds` is the list of dangling edges (source_id, label) that should
        point at whatever comes next. Each statement consumes them and returns
        its own dangling edges.
        """
        for stmt in stmts:
            preds = self._stmt(stmt, preds, col)
        return preds

    def _stmt(self, s, preds, col):
        if isinstance(s, ast.If):
            return self._if(s, preds, col)
        if isinstance(s, (ast.For, ast.AsyncFor)):
            label = f"for {ast.unparse(s.target)} in {ast.unparse(s.iter)}"
            return self._loop(s, preds, col, label, s.iter, ("next", "done"))
        if isinstance(s, ast.While):
            return self._loop(s, preds, col, f"while {ast.unparse(s.test)}", s.test, ("True", "False"))
        if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return self._def(s, preds, col)
        if isinstance(s, ast.ClassDef):
            return self._class(s, preds, col)
        if isinstance(s, ast.Return):
            node = self._add("return", self._source(s), s.lineno, s.end_lineno, col, calls_in=s)
            self._connect(preds, node)
            self._connect([(node, None)], self.end_id)
            return []  # nothing runs after a return
        if isinstance(s, ast.Break):
            node = self._add("statement", "break", s.lineno, s.end_lineno, col)
            self._connect(preds, node)
            if self.loops:
                self.loops[-1]["breaks"].append((node, None))
            return []
        if isinstance(s, ast.Continue):
            node = self._add("statement", "continue", s.lineno, s.end_lineno, col)
            self._connect(preds, node)
            if self.loops:
                self._connect([(node, None)], self.loops[-1]["header"])
            return []
        if isinstance(s, ast.Assert):
            return self._assert(s, preds, col)
        if isinstance(s, ast.Try):
            return self._try(s, preds, col)
        if isinstance(s, (ast.With, ast.AsyncWith)):
            items = ", ".join(ast.unparse(i) for i in s.items)
            node = self._add("statement", f"with {items}", s.lineno, s.body[0].lineno - 1, col, calls_in=s.items)
            self._connect(preds, node)
            return self._block(s.body, [(node, None)], col + 1)

        if hasattr(s, "body"):
            # Anything else with a body (e.g. `match`): one box for the whole thing.
            node = self._add("statement", self._source(s), s.lineno, s.end_lineno, col, calls_in=s)
        else:
            # A simple statement: assignment, print(...), x += 1, ...
            node = self._add("statement", self._source(s), s.lineno, s.end_lineno, col, calls_in=s)
        self._connect(preds, node)
        return [(node, None)]

    def _if(self, s, preds, col, keyword="if"):
        header_end = s.body[0].lineno - 1
        test = ast.unparse(s.test)
        node = self._add("decision", f"{keyword} {test}", s.lineno, header_end, col, calls_in=s.test)
        self._connect(preds, node)

        exits = self._block(s.body, [(node, "True")], col + 1)

        if self._is_elif(s.orelse):
            # `elif` is stored by ast as an `if` inside the `else`; draw it at the same depth.
            exits += self._if(s.orelse[0], [(node, "False")], col, keyword="elif")
        elif s.orelse:
            exits += self._block(s.orelse, [(node, "False")], col + 1)
        else:
            exits.append((node, "False"))
        return exits

    def _assert(self, s, preds, col):
        """`assert cond`: a decision. True carries on; False stops the program (AssertionError),
        so it goes straight to this lane's end node."""
        node = self._add("decision", f"assert {ast.unparse(s.test)}", s.lineno, s.end_lineno, col, calls_in=s)
        self._connect(preds, node)
        self._connect([(node, "False")], self.end_id)
        return [(node, "True")]

    def _is_elif(self, orelse):
        if len(orelse) != 1 or not isinstance(orelse[0], ast.If):
            return False
        line = self.lines[orelse[0].lineno - 1]
        return line[orelse[0].col_offset :].startswith("elif")

    def _loop(self, s, preds, col, label, header_expr, labels):
        """`for` and `while`: a loop node, the body, and an edge back up to the loop."""
        go, stop = labels
        header = self._add("loop", label, s.lineno, s.body[0].lineno - 1, col, calls_in=header_expr)
        self._connect(preds, header)

        self.loops.append({"header": header, "breaks": []})
        body_exits = self._block(s.body, [(header, go)], col + 1)
        self._connect(body_exits, header)  # the end of the body repeats the loop
        loop = self.loops.pop()

        exits = [(header, stop)]
        if s.orelse:  # for/while ... else: runs only when the loop was not broken
            exits = self._block(s.orelse, exits, col + 1)
        return exits + loop["breaks"]

    def _def(self, s, preds, col):
        """A `def` in the flow just *defines* the function; its body gets its own lane."""
        first_line = s.decorator_list[0].lineno if s.decorator_list else s.lineno
        node = self._add("statement", f"define {s.name}()", first_line, s.body[0].lineno - 1, col)
        self._connect(preds, node)
        qualname = self.prefix + s.name
        self.todo.append((qualname, s, qualname + ".<locals>."))
        return [(node, None)]

    def _class(self, s, preds, col):
        """A class is one box; each method gets its own lane (e.g. "Stack.push")."""
        node = self._add("statement", f"class {s.name}", s.lineno, s.body[0].lineno - 1, col)
        self._connect(preds, node)
        # Python runs the class body as its own little scope named after the class
        # (e.g. "Timer"). Point all of its steps at the class box so playback
        # still highlights something while the class is being set up.
        class_qualname = self.prefix + s.name
        self.functions[class_qualname] = {"start": node, "end": node, "lane": self.lane}
        for ln in range(s.lineno, s.end_lineno + 1):
            self.line_map.setdefault(f"{class_qualname}:{ln}", node)
        for item in s.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qualname = f"{self.prefix}{s.name}.{item.name}"
                self.todo.append((qualname, item, qualname + ".<locals>."))
        return [(node, None)]

    def _try(self, s, preds, col):
        node = self._add("statement", "try", s.lineno, s.body[0].lineno - 1, col)
        self._connect(preds, node)
        exits = self._block(s.body, [(node, None)], col + 1)
        if s.orelse:
            exits = self._block(s.orelse, exits, col + 1)
        for handler in s.handlers:
            name = f"except {ast.unparse(handler.type)}" if handler.type else "except"
            h = self._add("statement", name, handler.lineno, handler.body[0].lineno - 1, col)
            self._connect([(node, "error")], h)
            exits += self._block(handler.body, [(h, None)], col + 1)
        if s.finalbody:
            exits = self._block(s.finalbody, exits, col + 1)
        return exits

    # --------------------------------------------------------------- helpers
    def _add(self, type_, label, line, end_line, col, calls_in=None, map_lines=True):
        """Create a node, give it the next row, and record which lines it covers."""
        node_id = f"n{len(self.nodes)}"
        calls = self._calls(calls_in) if calls_in is not None else []
        if type_ == "statement" and calls:
            type_ = "call"
        self.nodes.append(
            {
                "id": node_id,
                "type": type_,
                "label": _short(label),
                "line": line,
                "end_line": end_line if end_line is not None else line,
                "func": self.scope,
                "lane": self.lane,
                "row": self.row,
                "col": col,
                "calls": calls,
            }
        )
        self.row += 1
        if map_lines and line is not None:
            for ln in range(line, (end_line or line) + 1):
                # The trace says "function X is on line N"; this table finds the node.
                self.line_map.setdefault(f"{self.scope}:{ln}", node_id)
        return node_id

    def _connect(self, preds, target):
        for source, label in preds:
            self.edges.append({"from": source, "to": target, "label": label, "kind": "normal"})

    def _calls(self, tree):
        """Names of *your* functions called inside an expression or statement."""
        trees = tree if isinstance(tree, list) else [tree]
        found = set()
        for t in trees:
            for n in ast.walk(t):
                if isinstance(n, ast.Call):
                    f = n.func
                    name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None
                    if name in self.user_function_names:
                        found.add(name)
        return sorted(found)

    def _source(self, s):
        """The statement's own source text (first line if it is long)."""
        text = ast.get_source_segment(self.source, s) or ast.unparse(s)
        return text.splitlines()[0] if "\n" in text and len(text) > MAX_LABEL else text

    def _add_call_edges(self):
        """Dashed edges from a calling line to the start of the called function."""
        for node in self.nodes:
            for name in node["calls"]:
                for qualname, info in self.functions.items():
                    if qualname.split(".")[-1] == name:
                        self.edges.append({"from": node["id"], "to": info["start"], "label": None, "kind": "call"})

    def _mark_back_edges(self):
        """An edge that goes to an earlier (or the same) row is drawn as a loop-back."""
        by_id = {n["id"]: n for n in self.nodes}
        for e in self.edges:
            if e["kind"] == "normal" and by_id[e["to"]]["row"] <= by_id[e["from"]]["row"]:
                e["kind"] = "back"
