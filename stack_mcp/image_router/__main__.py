"""``python -m stack_mcp.image_router`` (``--mode`` is accepted and ignored; ``--check`` prints status)."""

from .server import main

raise SystemExit(main())
