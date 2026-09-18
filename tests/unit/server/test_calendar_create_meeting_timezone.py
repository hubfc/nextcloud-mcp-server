"""Unit tests for the timezone ``nc_calendar_create_meeting`` forwards.

The tool builds ``start_datetime`` as ``f"{date}T{time}:00"`` — always naive, by
construction. Until this test's fix it also forwarded no ``timezone``, so every
meeting was stored as RFC 5545 floating time and moved for anyone viewing the
calendar from another zone.

Testing at the client layer would miss it: ``_create_ical_event`` binds a naive
DTSTART correctly once a timezone is present, and it is only absent because the
*tool* leaves it out. ``nc_calendar_create_event`` has accepted ``timezone``
all along, which is what makes the gap easy to overlook — the capability exists,
it just was not reachable from the convenience tool.
"""

from __future__ import annotations

import pytest
from mcp.server.mcpserver import MCPServer

from nextcloud_mcp_server.server.calendar import configure_calendar_tools

pytestmark = pytest.mark.unit


@pytest.fixture
def create_meeting_tool():
    mcp = MCPServer("test")
    configure_calendar_tools(mcp)
    return mcp._tool_manager.get_tool("nc_calendar_create_meeting")


async def _captured_event_data(tool, mocker, **kwargs):
    """Call the tool with a stubbed client and return the dict it forwarded."""
    client = mocker.MagicMock()
    client.calendar.create_event = mocker.AsyncMock(return_value={"uid": "u"})
    mocker.patch(
        "nextcloud_mcp_server.server.calendar.get_client",
        mocker.AsyncMock(return_value=client),
    )
    # Pin the deployment mode. @require_scopes denies a request that carries a
    # context but no verified token *only* under login-flow, so leaving this to
    # the ambient environment makes the test pass locally and fail in CI.
    mocker.patch(
        "nextcloud_mcp_server.auth.scope_authorization.get_settings",
        return_value=mocker.MagicMock(enable_login_flow=False),
    )

    await tool.fn(
        title="Quick Meeting",
        date="2026-09-21",
        time="14:00",
        ctx=mocker.MagicMock(),
        **kwargs,
    )

    return client.calendar.create_event.call_args.args[1]


async def test_timezone_reaches_the_client(create_meeting_tool, mocker):
    """The caller's zone must be forwarded, not dropped."""
    event_data = await _captured_event_data(
        create_meeting_tool, mocker, timezone="Europe/Berlin"
    )

    assert event_data["timezone"] == "Europe/Berlin"


async def test_start_and_end_stay_naive_so_the_timezone_can_bind(
    create_meeting_tool, mocker
):
    """``timezone`` only applies to naive input, so the tool must keep it naive.

    Were the tool to grow an offset or a ``Z`` suffix, ``create_event`` would
    ignore the zone — with a warning — and the meeting would silently land in
    UTC instead.
    """
    event_data = await _captured_event_data(
        create_meeting_tool, mocker, timezone="Europe/Berlin"
    )

    assert event_data["start_datetime"] == "2026-09-21T14:00:00"
    assert event_data["end_datetime"] == "2026-09-21T15:00:00"


async def test_duration_is_honoured_alongside_the_timezone(
    create_meeting_tool, mocker
):
    """The end time is derived locally; a zone must not disturb that."""
    event_data = await _captured_event_data(
        create_meeting_tool, mocker, duration_minutes=30, timezone="Europe/Berlin"
    )

    assert event_data["end_datetime"] == "2026-09-21T14:30:00"
