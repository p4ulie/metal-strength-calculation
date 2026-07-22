"""Drive the MCP server over a real stdio transport and call every tool once.

Not part of the pytest run -- it spawns a subprocess. Run it directly:

    python tests/smoke_mcp.py
"""

from __future__ import annotations

import asyncio
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

CALLS: list[tuple[str, dict]] = [
    ("snow_load_from_depth", {"depth_m": 1.0, "state": "wet", "pitch_deg": 20.0}),
    ("snow_load_eurocode", {"zone": 2, "altitude_m": 400.0, "pitch_deg": 20.0}),
    ("list_sections", {"family": "IPE"}),
    ("list_shapes", {}),
    ("tune_roof", {"reset": True, "shape": "monopitch", "chart": False}),
    ("tune_roof", {"rafter": "IPE500", "chart": False}),
    ("tune_roof", {"profile_points": [[0, 3], [3, 5.5], [6, 6.2], [9, 5.5], [12, 3]],
                   "chart": False}),
    ("roof_report", {"language": "sk", "prices": True}),
    ("section_properties", {"name": "IPE300"}),
    ("check_beam", {"span_m": 6.0, "section": "IPE200", "udl_kn_per_m": 5.0,
                    "restrained": True}),
    ("check_rod_buckling", {"length_m": 6.0, "section": "IPE300",
                            "axial_load_kn": 200.0}),
    ("check_roof", {"span_m": 12.0, "length_m": 20.0, "pitch_deg": 20.0,
                    "snow_depth_m": 1.0, "snow_state": "wet",
                    "rafter": "IPE450", "column": "HEB240",
                    "purlin": "SHS140x140x5", "charts": True}),
    ("check_roof", {"span_m": 30.0, "length_m": 20.0, "pitch_deg": 15.0,
                    "shape": "multispan", "case": "valley_drift",
                    "snow_depth_m": 1.0, "snow_state": "wet",
                    "rafter": "IPE450", "column": "HEB240",
                    "purlin": "SHS140x140x5"}),
    ("solve_frame", {"spec": {
        "nodes": [{"x": 0, "z": 0}, {"x": 0, "z": 4}, {"x": 8, "z": 4}, {"x": 8, "z": 0}],
        "members": [{"i": 0, "j": 1, "section": "HEB200"},
                    {"i": 1, "j": 2, "section": "IPE300"},
                    {"i": 2, "j": 3, "section": "HEB200"}],
        "supports": {"0": "pinned", "3": "pinned"},
        "member_loads": [{"member": 1, "udl_z": 10.0}],
    }}),
    ("propose_construction", {"span_m": 12.0, "length_m": 20.0, "pitch_deg": 20.0,
                              "snow_depth_m": 1.0, "snow_state": "wet",
                              "include_prices": True, "country": "SK"}),
    ("material_list", {"span_m": 12.0, "length_m": 20.0, "pitch_deg": 20.0,
                       "rafter": "IPE450", "column": "HEB240",
                       "purlin": "SHS140x140x5", "include_prices": True,
                       "waste_percent": 5.0}),
    ("render_snow_cases", {"sk_kn_m2": 2.0, "pitch_deg": 25.0}),
]


async def main() -> int:
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "metal_strength.mcp_server"]
    )
    failures = 0
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = {t.name for t in (await session.list_tools()).tools}
            print(f"server exposes {len(tools)} tools: {', '.join(sorted(tools))}\n")

            for name, args in CALLS:
                try:
                    result = await session.call_tool(name, args)
                    if result.isError:
                        raise RuntimeError(result.content[0].text)
                    payload = result.structuredContent or {}
                    summary = ", ".join(
                        f"{k}={v}" for k, v in list(payload.items())[:3]
                        if not isinstance(v, (list, dict))
                    ) or result.content[0].text[:80]
                    print(f"  OK   {name:<24s} {summary}")
                except Exception as exc:  # noqa: BLE001
                    failures += 1
                    print(f"  FAIL {name:<24s} {exc}")

    print(f"\n{len(CALLS) - failures}/{len(CALLS)} tool calls succeeded over stdio")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
