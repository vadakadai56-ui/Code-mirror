"""Code Mirror web server.

Run:  python app.py   then open http://127.0.0.1:5000

Routes:
  GET  /                -> the single-page frontend (static/index.html)
  GET  /api/examples    -> the built-in example programs
  POST /api/visualize   -> {"code": "..."}  ->  {"graph": {...} or null, "trace": {...}}
"""

from flask import Flask, jsonify, request, send_from_directory

from mirror.examples import EXAMPLES
from mirror.graph_builder import build_graph
from mirror.runner import run_code

MAX_CODE_CHARS = 10_000

app = Flask(__name__, static_folder="static", static_url_path="/static")


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/examples")
def examples():
    return jsonify(EXAMPLES)


@app.post("/api/visualize")
def visualize():
    data = request.get_json(silent=True) or {}
    code = data.get("code")
    if not isinstance(code, str) or not code.strip():
        return jsonify({"error": "Please type or paste some Python code first."}), 400
    if len(code) > MAX_CODE_CHARS:
        return jsonify({"error": f"Code is too long (limit {MAX_CODE_CHARS} characters)."}), 400

    # 1) Read the code (never runs it) -> flowchart graph.
    try:
        graph = build_graph(code)
    except SyntaxError:
        graph = None  # the trace below reports the syntax error with its line number

    # 2) Run the code in a separate, limited process -> step-by-step trace.
    trace = run_code(code)
    return jsonify({"graph": graph, "trace": trace})


if __name__ == "__main__":
    # 127.0.0.1 means only this computer can reach the server.
    app.run(host="127.0.0.1", port=5000, debug=False)
