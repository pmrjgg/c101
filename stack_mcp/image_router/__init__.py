"""image-router v2: the ``image`` MCP stdio server.

One tool per kind of image operation (GEN, REF, EDIT, MASK, RGBA, UPSCALE, VECTOR, TRACE and,
optionally, VECTOR_MANIPULATION), each bound to exactly the endpoint, key and model tag the
user sets for that operation in ``~/.claude/stack.env`` (``IMAGE_<OP>_URL / _KEY / _MODEL``;
OpenRouter, Opper or any OpenAI-compatible router; read at call time, no fallbacks), plus local
tools for masks, SVG inspection/rendering, layers and layered PDF export. The operation table is
documented in config/image-ops.json.
"""

__version__ = "2.0.0"
