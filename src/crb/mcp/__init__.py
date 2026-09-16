"""``crb.mcp`` — the instrument as Model Context Protocol tools.

Navigation
----------
What it is:   The MCP surface: ``build_server`` (the tools over ``/api/v1``), ``CrbApi``
              (the authenticated HTTP client), ``main`` (``crb mcp`` on stdio).
What it does: Lets Claude Code — or any MCP client — read a crb deployment and start
              measurements under the deployment's own RBAC, so an assistant can answer
              "what does the map say about this repo?" from the ledger instead of from
              memory. Sign-offs and reviews are deliberately not tools (human attestations).
How:          A client of the HTTP API (never an importer of ``crb.server``); optional extra
              ``[mcp]`` (``mcp>=2``, ``httpx``).
Layer:        mcp — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0008-stdlib-core-and-downward-layers.md
Works with:   src/crb/mcp/server.py, src/crb/mcp/client.py, src/crb/cli/commands/service.py
              (``crb mcp``), docs/MCP.md
Tested by:    tests/test_mcp_server.py
Touch when:   a route is added that an assistant should reach (see server.py).
"""

from crb.mcp.client import CrbApi, CrbApiError
from crb.mcp.server import INSTRUCTIONS, build_server, main, tool_names

__all__ = ["INSTRUCTIONS", "CrbApi", "CrbApiError", "build_server", "main", "tool_names"]
