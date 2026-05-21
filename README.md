# codex-chats-mcp

[![PyPI version](https://img.shields.io/pypi/v/codex-chats-mcp.svg)](https://pypi.org/project/codex-chats-mcp/)
[![Python versions](https://img.shields.io/pypi/pyversions/codex-chats-mcp.svg)](https://pypi.org/project/codex-chats-mcp/)
[![License: MIT](https://img.shields.io/pypi/l/codex-chats-mcp.svg)](https://github.com/shoyu-ramen/codex-chats-mcp/blob/main/LICENSE)
[![Publish to PyPI](https://github.com/shoyu-ramen/codex-chats-mcp/actions/workflows/publish.yml/badge.svg)](https://github.com/shoyu-ramen/codex-chats-mcp/actions/workflows/publish.yml)

An MCP server for managing ChatGPT conversations and Codex Cloud tasks (chats) from any MCP-compatible client — Claude Code, Codex, Cline, etc.

ChatGPT's web UI lets you archive chats but the "Delete all" button only wipes visible ones, and Codex Cloud has no per-task delete at all. This server wraps the internal `chatgpt.com/backend-api` endpoints so you can list, search, rename, archive, export, and **permanently delete** both kinds of chats from your agent.

> **Unofficial.** This uses undocumented internal endpoints (`/conversations/*`, `/wham/tasks/*`). They can change without notice and require a valid ChatGPT session. Use at your own risk.

## Install

```bash
pip install codex-chats-mcp
```

Or with `uv`:

```bash
uv tool install codex-chats-mcp
```

This installs a `codex-chats-mcp` executable.

## Authentication

The server reads `~/.codex/auth.json` — the same file the Codex CLI maintains after `codex login`. If you don't have Codex installed, log in once with `npx @openai/codex login` (or sign in via the Codex desktop app) to produce the file.

The token has full access to your ChatGPT account. Treat the auth file as a secret.

## Wire it up

### Codex CLI (`~/.codex/config.toml`)

```toml
[mcp_servers.codex-chats]
command = "codex-chats-mcp"
```

### Claude Code

```bash
claude mcp add codex-chats codex-chats-mcp
```

### Anything else

Point your MCP client at the `codex-chats-mcp` executable. It speaks MCP over stdio.

## Tools

### ChatGPT conversations (the "Recents" list)

| Tool | What it does |
|---|---|
| `list_conversations` | Paginates through your conversations. Filters out archived by default. |
| `get_conversation` | Full payload for one conversation, including the message tree. |
| `search_conversations` | Substring match on titles (client-side). |
| `rename_conversation` | Change a conversation's title. |
| `archive_conversation` / `unarchive_conversation` | Toggle the archive flag. |
| `delete_conversation` | Permanently delete one chat (`is_visible=false`). No undo. |
| `delete_conversations_matching` | Delete every chat whose title matches a substring. Requires `confirm=True`. |
| `delete_all_conversations` | Nuke every visible chat — same as ChatGPT's "Delete all chats" button. Requires `confirm=True`. |
| `export_conversations` | Dump titles/IDs (and optionally full message trees) to a JSON file. |

### Codex Cloud tasks

| Tool | What it does |
|---|---|
| `list_chats` | Paginate Codex tasks, filterable by `all` / `current` / `archived`. |
| `get_chat` | Summary of one task. |
| `get_chat_raw` | Full raw task payload. |
| `archive_chat` / `unarchive_chat` | Toggle archive state. |
| `delete_chat` | Permanently delete a task. Works on active OR archived. |
| `delete_all_archived` | Bulk-delete every archived task. Requires `confirm=True`. |

## Safety

Every destructive bulk action (`delete_all_conversations`, `delete_all_archived`, `delete_conversations_matching`) requires `confirm=True`. Without it the tool returns a preview of what *would* be deleted. There is no undo on the ChatGPT side.

## Development

```bash
git clone https://github.com/shoyu-ramen/codex-chats-mcp
cd codex-chats-mcp
python3 codex_chats_mcp.py
```

## License

MIT
