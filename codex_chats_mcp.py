#!/usr/bin/env python3
"""MCP server: list and delete Codex Cloud chats (tasks) and regular ChatGPT conversations.

Codex itself only exposes archive/unarchive in the UI. This wraps the
internal ChatGPT `/backend-api/wham/tasks/*` endpoints so archived tasks
can actually be deleted (`DELETE /wham/tasks/{id}`), and also wraps
`/backend-api/conversations/*` so the regular ChatGPT chat list can be
managed the same way.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Literal

from mcp.server.fastmcp import FastMCP

AUTH_PATH = Path.home() / ".codex" / "auth.json"
BASE_URL = "https://chatgpt.com/backend-api"
USER_AGENT = "codex-chats-mcp/0.1"

mcp = FastMCP("codex-chats")


def _auth_headers() -> dict[str, str]:
    data = json.loads(AUTH_PATH.read_text())
    tokens = data["tokens"]
    return {
        "Authorization": f"Bearer {tokens['access_token']}",
        "ChatGPT-Account-ID": tokens["account_id"],
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }


def _request(method: str, path: str, body: dict | None = None) -> tuple[int, dict | str]:
    url = f"{BASE_URL}{path}"
    data = json.dumps(body).encode() if body is not None else None
    headers = _auth_headers()
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode(errors="replace")
            try:
                return resp.status, json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                return resp.status, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        try:
            return e.code, json.loads(raw) if raw else {"detail": str(e)}
        except json.JSONDecodeError:
            return e.code, raw


PAGE_LIMIT = 20  # server-side cap on /wham/tasks/list


def _summarize(item: dict) -> dict:
    return {
        "id": item.get("id"),
        "title": item.get("title"),
        "archived": item.get("archived"),
        "created_at": item.get("created_at"),
        "updated_at": item.get("updated_at"),
        "environment_label": (item.get("task_status_display") or {}).get("environment_label"),
    }


def _list_page(task_filter: str, cursor: str | None) -> tuple[int, dict | str]:
    qs = f"limit={PAGE_LIMIT}&task_filter={task_filter}"
    if cursor:
        qs += f"&cursor={urllib.parse.quote(cursor)}"
    return _request("GET", f"/wham/tasks/list?{qs}")


@mcp.tool()
def list_chats(
    task_filter: Literal["all", "current", "archived"] = "all",
    max_results: int = 100,
) -> dict:
    """List Codex Cloud chats.

    Args:
        task_filter: 'archived' to see archived chats, 'current' for active,
            'all' for everything.
        max_results: stop after collecting this many items (paginates internally;
            server caps each page at 20).
    """
    items: list[dict] = []
    cursor: str | None = None
    while len(items) < max_results:
        status, payload = _list_page(task_filter, cursor)
        if status != 200 or not isinstance(payload, dict):
            return {"ok": False, "status": status, "error": payload, "items": items}
        page = payload.get("items") or []
        items.extend(_summarize(i) for i in page)
        cursor = payload.get("cursor")
        if not cursor or not page:
            break
    return {"ok": True, "count": len(items), "items": items[:max_results]}


@mcp.tool()
def get_chat(chat_id: str) -> dict:
    """Fetch a single Codex Cloud chat by ID (e.g. task_e_...)."""
    status, payload = _request("GET", f"/wham/tasks/{chat_id}")
    if status != 200:
        return {"ok": False, "status": status, "error": payload}
    task = payload.get("task", {}) if isinstance(payload, dict) else {}
    return {
        "ok": True,
        "id": task.get("id"),
        "title": task.get("title"),
        "archived": task.get("archived"),
        "task_status_display": task.get("task_status_display"),
    }


@mcp.tool()
def get_chat_raw(chat_id: str) -> dict:
    """Fetch the full raw Codex Cloud task payload (includes turns/messages if any)."""
    status, payload = _request("GET", f"/wham/tasks/{chat_id}")
    return {"ok": status == 200, "status": status, "task": payload}


@mcp.tool()
def delete_chat(chat_id: str) -> dict:
    """Permanently delete a Codex Cloud chat by ID.

    Works on archived OR active chats. There is no undo.
    """
    status, payload = _request("DELETE", f"/wham/tasks/{chat_id}")
    return {"ok": status == 200, "status": status, "response": payload}


@mcp.tool()
def archive_chat(chat_id: str) -> dict:
    """Archive a Codex Cloud chat (move it out of the active list)."""
    status, payload = _request("POST", f"/wham/tasks/{chat_id}/archive", body={})
    return {"ok": status == 200, "status": status, "response": payload}


@mcp.tool()
def unarchive_chat(chat_id: str) -> dict:
    """Unarchive a Codex Cloud chat (return it to the active list)."""
    status, payload = _request("POST", f"/wham/tasks/{chat_id}/unarchive", body={})
    return {"ok": status == 200, "status": status, "response": payload}


@mcp.tool()
def delete_all_archived(confirm: bool = False) -> dict:
    """Delete every archived Codex Cloud chat. Requires confirm=True.

    Repeatedly fetches the first page of archived tasks and DELETEs each.
    The next page is fetched only after the current one is gone — so we don't
    need cursor handling and we won't get stuck if a delete fails (a failed
    item stays on the page and we'd loop on it, so we bail in that case).
    """
    if not confirm:
        return {
            "ok": False,
            "error": "Pass confirm=true to actually delete. Call list_chats(task_filter='archived') first to preview.",
        }

    deleted: list[dict] = []
    failed: list[dict] = []
    while True:
        status, payload = _list_page("archived", cursor=None)
        if status != 200 or not isinstance(payload, dict):
            return {"ok": False, "status": status, "error": payload,
                    "deleted": deleted, "failed": failed}
        items = payload.get("items") or []
        if not items:
            break
        page_success = 0
        for item in items:
            cid = item.get("id")
            if not cid:
                continue
            ds, _ = _request("DELETE", f"/wham/tasks/{cid}")
            entry = {"id": cid, "title": item.get("title"), "status": ds}
            if ds == 200:
                deleted.append(entry); page_success += 1
            else:
                failed.append(entry)
        if page_success == 0:
            break  # nothing progressed; avoid infinite loop
    return {"ok": not failed, "deleted_count": len(deleted),
            "failed_count": len(failed), "deleted": deleted, "failed": failed}


CONVERSATIONS_PAGE_LIMIT = 28  # ChatGPT web default for /conversations


def _summarize_conversation(item: dict) -> dict:
    return {
        "id": item.get("id"),
        "title": item.get("title"),
        "create_time": item.get("create_time"),
        "update_time": item.get("update_time"),
        "is_archived": item.get("is_archived"),
    }


@mcp.tool()
def list_conversations(max_results: int = 100, include_archived: bool = False) -> dict:
    """List regular ChatGPT conversations (the 'Recents' list, not Codex tasks).

    Args:
        max_results: stop after collecting this many items (paginates internally).
        include_archived: if False (default), filter out archived conversations.
    """
    items: list[dict] = []
    offset = 0
    while len(items) < max_results:
        qs = f"offset={offset}&limit={CONVERSATIONS_PAGE_LIMIT}&order=updated"
        status, payload = _request("GET", f"/conversations?{qs}")
        if status != 200 or not isinstance(payload, dict):
            return {"ok": False, "status": status, "error": payload, "items": items}
        page = payload.get("items") or []
        if not page:
            break
        for c in page:
            if not include_archived and c.get("is_archived"):
                continue
            items.append(_summarize_conversation(c))
        offset += len(page)
        total = payload.get("total")
        if isinstance(total, int) and offset >= total:
            break
    return {"ok": True, "count": len(items), "items": items[:max_results]}


@mcp.tool()
def delete_conversation(conversation_id: str) -> dict:
    """Permanently delete a regular ChatGPT conversation by ID.

    Uses PATCH /conversations/{id} with is_visible=false, which is what the
    web UI's 'Delete chat' action does. There is no undo.
    """
    status, payload = _request(
        "PATCH", f"/conversations/{conversation_id}", body={"is_visible": False}
    )
    return {"ok": status == 200, "status": status, "response": payload}


@mcp.tool()
def delete_all_conversations(confirm: bool = False) -> dict:
    """Permanently delete EVERY regular ChatGPT conversation. Requires confirm=True.

    Mirrors the 'Delete all chats' button in ChatGPT settings: a single
    PATCH /conversations with is_visible=false flips every chat at once.
    There is no undo. Call list_conversations() first to preview.
    """
    if not confirm:
        return {
            "ok": False,
            "error": "Pass confirm=true to actually delete every conversation. Call list_conversations() first to preview.",
        }
    status, payload = _request("PATCH", "/conversations", body={"is_visible": False})
    return {"ok": status == 200, "status": status, "response": payload}


@mcp.tool()
def get_conversation(conversation_id: str) -> dict:
    """Fetch the full payload for a regular ChatGPT conversation, including its message tree."""
    status, payload = _request("GET", f"/conversation/{conversation_id}")
    return {"ok": status == 200, "status": status, "conversation": payload}


@mcp.tool()
def archive_conversation(conversation_id: str) -> dict:
    """Archive a regular ChatGPT conversation (hide from Recents, keep around)."""
    status, payload = _request(
        "PATCH", f"/conversations/{conversation_id}", body={"is_archived": True}
    )
    return {"ok": status == 200, "status": status, "response": payload}


@mcp.tool()
def unarchive_conversation(conversation_id: str) -> dict:
    """Unarchive a regular ChatGPT conversation (return to Recents)."""
    status, payload = _request(
        "PATCH", f"/conversations/{conversation_id}", body={"is_archived": False}
    )
    return {"ok": status == 200, "status": status, "response": payload}


@mcp.tool()
def rename_conversation(conversation_id: str, title: str) -> dict:
    """Rename a regular ChatGPT conversation."""
    status, payload = _request(
        "PATCH", f"/conversations/{conversation_id}", body={"title": title}
    )
    return {"ok": status == 200, "status": status, "response": payload}


@mcp.tool()
def search_conversations(
    query: str,
    max_results: int = 100,
    case_sensitive: bool = False,
    include_archived: bool = False,
) -> dict:
    """Find ChatGPT conversations whose title contains `query` (substring match).

    Client-side filter over list_conversations — no dedicated search endpoint
    is used, so this is exact-substring only (no semantic search).
    """
    listing = list_conversations(max_results=max_results, include_archived=include_archived)
    if not listing.get("ok"):
        return listing
    needle = query if case_sensitive else query.lower()
    matches = []
    for item in listing["items"]:
        title = item.get("title") or ""
        hay = title if case_sensitive else title.lower()
        if needle in hay:
            matches.append(item)
    return {"ok": True, "count": len(matches), "query": query, "items": matches}


@mcp.tool()
def delete_conversations_matching(
    query: str,
    confirm: bool = False,
    case_sensitive: bool = False,
    max_scan: int = 500,
) -> dict:
    """Delete every conversation whose title contains `query`. Requires confirm=True.

    Always call search_conversations(query) first to preview the hit list.
    `max_scan` caps how many conversations we scan before deleting.
    """
    matches = search_conversations(
        query=query, max_results=max_scan, case_sensitive=case_sensitive
    )
    if not matches.get("ok"):
        return matches
    items = matches["items"]
    if not confirm:
        return {
            "ok": False,
            "would_delete_count": len(items),
            "items": items,
            "error": "Pass confirm=true to actually delete. Above is the preview.",
        }
    deleted: list[dict] = []
    failed: list[dict] = []
    for item in items:
        cid = item.get("id")
        if not cid:
            continue
        ds, _ = _request("PATCH", f"/conversations/{cid}", body={"is_visible": False})
        entry = {"id": cid, "title": item.get("title"), "status": ds}
        (deleted if ds == 200 else failed).append(entry)
    return {
        "ok": not failed,
        "deleted_count": len(deleted),
        "failed_count": len(failed),
        "deleted": deleted,
        "failed": failed,
    }


@mcp.tool()
def export_conversations(
    output_path: str,
    max_results: int = 1000,
    include_archived: bool = True,
    include_messages: bool = False,
) -> dict:
    """Dump conversations to a JSON file at `output_path`.

    `include_messages=True` fetches the full message tree for each conversation
    (one API call per chat — slow for large accounts but produces a complete backup).
    `include_messages=False` (default) writes only titles/timestamps/IDs.
    """
    listing = list_conversations(max_results=max_results, include_archived=include_archived)
    if not listing.get("ok"):
        return listing
    items = listing["items"]
    if include_messages:
        for item in items:
            cid = item.get("id")
            if not cid:
                continue
            full = get_conversation(cid)
            if full.get("ok"):
                item["full"] = full["conversation"]
    out = Path(output_path).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"count": len(items), "items": items}, indent=2))
    return {"ok": True, "count": len(items), "path": str(out), "with_messages": include_messages}


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
