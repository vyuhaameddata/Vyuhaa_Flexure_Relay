"""
Vyuhaa Relay Server
====================
Bridges Vyuhaa Microscope servers (Jetson) with remote clients over the internet.

Protocol
--------
MICROSCOPE SIDE:
  → { type: "register_microscope", microscope_id: "clinic-001", api_key: "..." }
  ← { type: "registered" }
  ← { type: "incoming_offer", session_id, from_user, sdp }
  ← { type: "ice", session_id, candidate }
  ← { type: "proxy_command", cmd_id, action, params, ... }
  → { type: "answer", session_id, sdp }
  → { type: "ice", session_id, candidate }
  → { type: "proxy_response", cmd_id, ... }
  → { type: "end_session", session_id }

CLIENT SIDE:
  → { type: "login", username: "john", password: "..." }
  ← { type: "login_success", access_token, refresh_token, microscopes: [...] }
  → { type: "offer", access_token, microscope_id, sdp }
  ← { type: "answer", session_id, sdp }
  → { type: "ice", session_id, candidate }
  ← { type: "ice", session_id, candidate }
  → { type: "proxy_command", access_token, microscope_id, action, params, cmd_id }
  ← { type: "proxy_response", cmd_id, ... }

Run
---
  python relay_server.py

  Env vars:
    PORT          WebSocket port (default 8765)
    RELAY_USERS   Path to users JSON  (default relay_users.json same dir)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import time
from typing import Dict, Optional, Set

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("relay")

# ── Config ────────────────────────────────────────────────────────────────────

PORT       = int(os.environ.get("PORT", 8765))
USERS_FILE = os.environ.get(
    "RELAY_USERS",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "relay_users.json")
)


def _load_users() -> dict:
    if not os.path.exists(USERS_FILE):
        log.warning(f"relay_users.json not found at {USERS_FILE} — using defaults")
        return {
            "users": {"admin": "vyuhaa2026"},
            "microscopes": {"clinic-001": "mk-vyuhaa-2026"}
        }
    with open(USERS_FILE) as f:
        return json.load(f)


# ── State ─────────────────────────────────────────────────────────────────────

# microscope_id → websocket
_microscopes: Dict[str, object] = {}

# access_token → {"username": ..., "expires": float}
_tokens: Dict[str, dict] = {}

# session_id → {"microscope_ws": ws, "client_ws": ws, "microscope_id": str}
_sessions: Dict[str, dict] = {}

# microscope_id → set of client websockets currently streaming
_streaming_clients: Dict[str, set] = {}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_token(username: str) -> str:
    tok = secrets.token_hex(24)
    _tokens[tok] = {"username": username, "expires": time.time() + 86400 * 30}
    return tok


def _verify_token(token: str) -> Optional[str]:
    entry = _tokens.get(token)
    if not entry:
        return None
    if time.time() > entry["expires"]:
        del _tokens[token]
        return None
    return entry["username"]


async def _send(ws, msg: dict) -> None:
    try:
        await ws.send(json.dumps(msg))
    except Exception:
        pass


# ── Connection handler ────────────────────────────────────────────────────────

async def _handle(ws) -> None:
    role    = None   # "microscope" | "client"
    mid     = None   # microscope_id for microscope connections
    session_ids: Set[str] = set()

    try:
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except Exception:
                continue

            mtype = msg.get("type", "")

            # ── Heartbeat ─────────────────────────────────────────────────
            if mtype == "ping":
                await _send(ws, {"type": "pong"})
                continue

            # ─────────────────────────────────────────────────────────────
            # MICROSCOPE: register
            # ─────────────────────────────────────────────────────────────
            if mtype == "register_microscope":
                cfg = _load_users()
                m_id  = msg.get("microscope_id", "")
                a_key = msg.get("api_key", "")
                expected = cfg["microscopes"].get(m_id)
                if not expected or expected != a_key:
                    await _send(ws, {"type": "error", "message": "Invalid microscope_id or api_key"})
                    continue
                _microscopes[m_id] = ws
                mid  = m_id
                role = "microscope"
                await _send(ws, {"type": "registered"})
                log.info(f"Microscope registered: '{m_id}'")
                continue

            # ─────────────────────────────────────────────────────────────
            # CLIENT: login
            # ─────────────────────────────────────────────────────────────
            if mtype == "login":
                cfg  = _load_users()
                user = msg.get("username", "")
                pw   = msg.get("password", "")
                is_user_login = cfg["users"].get(user) == pw
                is_scope_login = cfg["microscopes"].get(user) == pw
                if not (is_user_login or is_scope_login):
                    await _send(ws, {"type": "error", "message": "Invalid username/password (or microscope_id/api_key)"})
                    continue
                access  = _make_token(user)
                refresh = _make_token(user)
                role = "client"
                if is_scope_login:
                    microscopes = [{
                        "microscope_id":  user,
                        "display_name":   user,
                        "online":         user in _microscopes,
                        "busy":           False,
                    }]
                else:
                    microscopes = [
                        {
                            "microscope_id":  m,
                            "display_name":   m,
                            "online":         m in _microscopes,
                            "busy":           False,
                        }
                        for m in cfg["microscopes"]
                    ]
                await _send(ws, {
                    "type":          "login_success",
                    "access_token":  access,
                    "refresh_token": refresh,
                    "microscopes":   microscopes,
                })
                mode = "microscope-credential" if is_scope_login else "user-credential"
                log.info(f"Client login: '{user}' ({mode}) — {len(microscopes)} microscope(s)")
                continue

            # ─────────────────────────────────────────────────────────────
            # CLIENT: refresh token
            # ─────────────────────────────────────────────────────────────
            if mtype == "refresh":
                old = msg.get("refresh_token", "")
                entry = _tokens.get(old)
                if not entry:
                    await _send(ws, {"type": "error", "message": "Invalid refresh token"})
                    continue
                username = entry["username"]
                del _tokens[old]
                new_access  = _make_token(username)
                new_refresh = _make_token(username)
                await _send(ws, {
                    "type":          "login_success",
                    "access_token":  new_access,
                    "refresh_token": new_refresh,
                })
                continue

            # ─────────────────────────────────────────────────────────────
            # CLIENT: WebRTC offer → forward to microscope
            # ─────────────────────────────────────────────────────────────
            if mtype == "offer":
                token  = msg.get("access_token", "")
                m_id   = msg.get("microscope_id", "")
                sdp    = msg.get("sdp", "")
                user   = _verify_token(token)
                if not user:
                    await _send(ws, {"type": "error", "message": "Invalid or expired token"})
                    continue
                m_ws = _microscopes.get(m_id)
                if not m_ws:
                    await _send(ws, {"type": "error", "message": f"Microscope '{m_id}' not online"})
                    continue
                sid = secrets.token_hex(16)
                _sessions[sid] = {"microscope_ws": m_ws, "client_ws": ws, "microscope_id": m_id}
                session_ids.add(sid)
                await _send(m_ws, {
                    "type":       "incoming_offer",
                    "session_id": sid,
                    "from_user":  user,
                    "sdp":        sdp,
                })
                log.info(f"Offer forwarded: {user} → {m_id} [{sid[:8]}]")
                continue

            # ─────────────────────────────────────────────────────────────
            # MICROSCOPE: WebRTC answer → forward to client
            # ─────────────────────────────────────────────────────────────
            if mtype == "answer":
                sid  = msg.get("session_id", "")
                sess = _sessions.get(sid)
                if sess:
                    await _send(sess["client_ws"], {
                        "type":       "answer",
                        "session_id": sid,
                        "sdp":        msg.get("sdp", ""),
                    })
                continue

            # ─────────────────────────────────────────────────────────────
            # ICE candidates — forward in both directions
            # ─────────────────────────────────────────────────────────────
            if mtype == "ice":
                sid  = msg.get("session_id", "")
                sess = _sessions.get(sid)
                if not sess:
                    continue
                if role == "microscope":
                    target = sess["client_ws"]
                else:
                    target = sess["microscope_ws"]
                await _send(target, {
                    "type":       "ice",
                    "session_id": sid,
                    "candidate":  msg.get("candidate"),
                })
                continue

            # ─────────────────────────────────────────────────────────────            # MICROSCOPE: stream_frame → push to all streaming clients
            # ───────────────────────────────────────────────────────────────
            if mtype == "stream_frame" and role == "microscope" and mid:
                clients = _streaming_clients.get(mid, set())
                dead = set()
                for c_ws in clients:
                    try:
                        await c_ws.send(json.dumps({"type": "stream_frame", "jpeg": msg.get("jpeg", "")}))
                    except Exception:
                        dead.add(c_ws)
                clients -= dead
                continue

            # ───────────────────────────────────────────────────────────────            # CLIENT: proxy_command (fallback — no WebRTC)
            # ─────────────────────────────────────────────────────────────
            if mtype == "proxy_command":
                token  = msg.get("access_token", "")
                m_id   = msg.get("microscope_id", "")
                user   = _verify_token(token)
                if not user:
                    await _send(ws, {"type": "error", "message": "Invalid or expired token"})
                    continue
                # Register this client as a streaming receiver for this microscope
                if m_id not in _streaming_clients:
                    _streaming_clients[m_id] = set()
                _was_empty = len(_streaming_clients[m_id]) == 0
                _streaming_clients[m_id].add(ws)
                # Tell microscope to start pushing frames when first viewer connects
                if _was_empty:
                    m_ws_notify = _microscopes.get(m_id)
                    if m_ws_notify:
                        await _send(m_ws_notify, {"type": "viewer_joined"})
                m_ws = _microscopes.get(m_id)
                if not m_ws:
                    await _send(ws, {"type": "error", "message": f"Microscope '{m_id}' not online"})
                    continue
                # Tag the client ws so the microscope response can be routed back
                cmd_id = msg.get("cmd_id", "")
                await _send(m_ws, {
                    "type":       "proxy_command",
                    "cmd_id":     cmd_id,
                    "action":     msg.get("action", ""),
                    "params":     msg.get("params", {}),
                    "from_user":  user,
                    "_client_ws": id(ws),   # internal routing tag (stripped before send)
                })
                # Store pending so response can be routed back
                _sessions[f"proxy_{cmd_id}"] = {"client_ws": ws}
                continue

            # ─────────────────────────────────────────────────────────────
            # MICROSCOPE: proxy_response → route back to client
            # ─────────────────────────────────────────────────────────────
            if mtype == "proxy_response":
                cmd_id = msg.get("cmd_id", "")
                key    = f"proxy_{cmd_id}"
                sess   = _sessions.pop(key, None)
                if sess:
                    await _send(sess["client_ws"], msg)
                continue

            # ─────────────────────────────────────────────────────────────
            # End session
            # ─────────────────────────────────────────────────────────────
            if mtype in ("end_session", "session_ended"):
                sid  = msg.get("session_id", "")
                sess = _sessions.pop(sid, None)
                session_ids.discard(sid)
                if sess:
                    if role == "microscope":
                        await _send(sess["client_ws"], {"type": "session_ended", "session_id": sid, "reason": "microscope"})
                    else:
                        await _send(sess["microscope_ws"], {"type": "session_ended", "session_id": sid})
                continue

            log.debug(f"Unhandled message type: {mtype}")

    except Exception as exc:
        log.debug(f"Connection handler error: {exc}")
    finally:
        # Clean up on disconnect
        if role == "microscope" and mid and _microscopes.get(mid) is ws:
            del _microscopes[mid]
            log.info(f"Microscope disconnected: '{mid}'")
        # Remove client from all streaming sets — notify microscope if last viewer left
        if role == "client":
            for m_id_key, clients_set in list(_streaming_clients.items()):
                if ws in clients_set:
                    clients_set.discard(ws)
                    if not clients_set:
                        m_ws_notify = _microscopes.get(m_id_key)
                        if m_ws_notify:
                            await _send(m_ws_notify, {"type": "viewer_left"})
        # Close any open sessions for this connection
        for sid in list(session_ids):
            sess = _sessions.pop(sid, None)
            if sess:
                other = sess["client_ws"] if role == "microscope" else sess.get("microscope_ws")
                if other:
                    await _send(other, {"type": "session_ended", "session_id": sid, "reason": "peer_disconnected"})


# ── Entry point ───────────────────────────────────────────────────────────────

async def _main() -> None:
    try:
        import websockets
    except ImportError:
        print("ERROR: websockets not installed. Run:  pip install websockets")
        return

    import socket
    try:
        lan_ip = socket.gethostbyname(socket.gethostname())
    except Exception:
        lan_ip = "0.0.0.0"

    # TCP_NODELAY: disable Nagle's algorithm to avoid ~200 ms batching delay
    raw = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    raw.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    raw.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    raw.bind(("0.0.0.0", PORT))
    raw.setblocking(False)

    async with websockets.serve(_handle, sock=raw, max_size=20 * 1024 * 1024,
                                 ping_interval=None, ping_timeout=None):
        log.info("=" * 55)
        log.info(f"  Vyuhaa Relay Server running on port {PORT}")
        log.info(f"  Local :  ws://localhost:{PORT}")
        log.info(f"  LAN   :  ws://{lan_ip}:{PORT}")
        log.info(f"  Users :  {USERS_FILE}")
        log.info("=" * 55)
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(_main())
