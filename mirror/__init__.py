"""Code Mirror backend: graph building (graph_builder) and tracing (runner + tracer).

The two halves never import each other: the graph is built from the source
text alone, and the trace comes from actually running the code. The frontend
joins them using the graph's `line_map` and `functions` tables.
"""
