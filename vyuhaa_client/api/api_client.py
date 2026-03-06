"""
api_client.py — Endpoint connection manager for Vyuhaa Remote Client.

Handles:
  • WebSocket relay connection  (PySide6 QWebSocket)
  • Simulated device-agent handshake and hardware bridge
  • Stage move / capture / autofocus RPC messages
  • Scan tile sequencing
  • Latency heartbeat

All communication goes through AppState signals so pages stay decoupled.
"""
from __future__ import annotations
import json
import math
import random
import uuid

from PySide6.QtCore import QObject, QTimer, QUrl
from PySide6.QtNetwork import QSslConfiguration, QSslSocket, QAbstractSocket
try:
    from PySide6.QtWebSockets import QWebSocket, QWebSocketProtocol
    _HAS_WEBSOCKET = True
except ImportError:
    _HAS_WEBSOCKET = False

from api.app_state import AppState


class RelayClient(QObject):
    """
    Manages the two-layer connection:
      Layer 1 → Relay Server (WebSocket / TLS)
      Layer 2 → Device Agent  (via relay room)
      Layer 3 → Microscope HW (USB/Serial bridge reported by agent)
    """

    def __init__(self, state: AppState, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.state = state
        self._ws: "QWebSocket | None" = None
        self._latency_timer = QTimer(self)
        self._latency_timer.setInterval(2000)
        self._latency_timer.timeout.connect(self._update_latency)
        self._conn_phase_timer = QTimer(self)
        self._conn_phase_timer.setSingleShot(True)

        # Scan step timer
        self._scan_timer = QTimer(self)
        self._scan_timer.setInterval(320)
        self._scan_timer.timeout.connect(self._scan_step)
        self._scan_order: list[tuple[int, int]] = []
        self._scan_current_idx: int = 0

        # Relay proxy state
        self._relay_access_token: str = ""
        self._relay_username: str = ""
        self._relay_microscope_id: str = ""
        self._relay_target_microscope: str = ""
        self._relay_frame_timer: "QTimer | None" = None
        self._relay_pos_timer: "QTimer | None" = None

    def _parse_relay_identity(self, raw_value: str) -> tuple[str, str]:
        """
        Backward-compatible parser for the connect field.

        Supported formats:
          - "username"                          -> username only
          - "username@microscope-id"            -> explicit target microscope
          - "username|microscope-id"            -> explicit target microscope
        """
        text = (raw_value or "").strip()
        if "@" in text:
            user, target = text.split("@", 1)
            return user.strip(), target.strip()
        if "|" in text:
            user, target = text.split("|", 1)
            return user.strip(), target.strip()
        return text, ""

    # ── Connection ────────────────────────────────────────────────────────────

    def connect(self) -> None:
        """Begin the phased connection sequence."""
        s = self.state
        if s.relay_status not in ("off", "disconnected"):
            return

        s.relay_status = "connecting"
        s.relay_state_changed.emit("connecting")
        s.log_message.emit(f"→ Connecting to {s.relay_url}…")

        if _HAS_WEBSOCKET:
            self._ws_connect()
        else:
            # Simulate connection (no QtWebSockets available / server offline)
            self._simulate_phase1()

    def _is_relay_mode(self) -> bool:
        """Relay mode = an access key / password is provided (requires login)."""
        return bool(self.state.relay_key.strip())

    def _ws_connect(self) -> None:
        """Attempt a real WebSocket connection; fall back to simulation on error."""
        self._ws = QWebSocket("", QWebSocketProtocol.Version13, self)
        # Route connected signal depending on direct-server vs relay mode
        if self._is_relay_mode():
            self._ws.connected.connect(self._on_relay_connected)
        else:
            self._ws.connected.connect(self._on_ws_connected)
        self._ws.disconnected.connect(self._on_ws_disconnected)
        self._ws.errorOccurred.connect(self._on_ws_error)
        self._ws.textMessageReceived.connect(self._on_message)
        url = QUrl(self.state.relay_url)
        # Apply SSL config for secure connections (wss:// or ngrok/Tailscale)
        if url.scheme() in ("wss", "https"):
            ssl_cfg = QSslConfiguration.defaultConfiguration()
            ssl_cfg.setPeerVerifyMode(QSslSocket.VerifyNone)  # accept self-signed certs
            self._ws.setSslConfiguration(ssl_cfg)
        self.state.log_message.emit(f"→ Opening {self.state.relay_url}…")
        self._ws.open(url)

    def _on_ws_connected(self) -> None:
        # Real server connected — skip simulated handshake, go live immediately
        s = self.state
        s.relay_status = "connected"
        s.relay_state_changed.emit("connected")
        s.device_status = "live"
        s.device_state_changed.emit("live")
        s.log_message.emit("✓ Connected to Vyuhaa Microscope server.")
        self._latency_timer.start()

    def _on_relay_connected(self) -> None:
        """Connected to relay — send login with username (room) + password (key)."""
        s = self.state
        self._relay_username, self._relay_target_microscope = self._parse_relay_identity(s.relay_room)
        if not self._relay_username:
            s.log_message.emit("✕ Relay username is empty.")
            self.disconnect()
            return
        s.log_message.emit(f"✓ Relay server reached — logging in as '{self._relay_username}'…")
        self._relay_access_token = ""
        self._relay_microscope_id = ""
        self._ws.sendTextMessage(json.dumps({
            "type":     "login",
            "username": self._relay_username,
            "password": s.relay_key,
        }))

    def _on_ws_error(self, error) -> None:
        self.state.log_message.emit(f"⚠ WebSocket error ({error}). Switching to simulation.")
        self._simulate_phase1()

    def _on_ws_disconnected(self) -> None:
        if self.state.relay_status == "connected":
            self.disconnect()
            if self.state.auto_reconnect:
                self.state.log_message.emit("↻ Connection lost — auto-reconnecting…")
                QTimer.singleShot(3000, self.connect)

    def _on_message(self, raw: str) -> None:
        """Handle incoming JSON-RPC messages from the relay/agent."""
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return
        msg_type = msg.get("type", "")
        method   = msg.get("method", "")
        params   = msg.get("params", {})

        # ── Real server frame / position ──────────────────────────────────
        if msg_type in ("frame", "stream_frame"):
            try:
                import base64
                self.state.frame_received.emit(base64.b64decode(msg["jpeg"]))
                # Server is pushing frames — stop client-side polling timer
                if msg_type == "stream_frame" and self._relay_frame_timer:
                    self._relay_frame_timer.stop()
                    self._relay_frame_timer = None
            except Exception:
                pass
            return
        if msg_type == "position":
            self.state.pos_x = float(msg.get("x", self.state.pos_x))
            self.state.pos_y = float(msg.get("y", self.state.pos_y))
            self.state.pos_z = float(msg.get("z", self.state.pos_z))
            self.state.position_changed.emit(
                self.state.pos_x, self.state.pos_y, self.state.pos_z
            )
            return

        # ── Relay login / proxy responses ─────────────────────────────────
        if msg_type == "login_success":
            self._relay_access_token = msg.get("access_token", "")
            microscopes = msg.get("microscopes", [])
            if not microscopes:
                self.state.log_message.emit("⚠ Relay login OK but no microscopes available.")
                return
            online = [m for m in microscopes if m.get("online")]
            target = None
            if self._relay_target_microscope:
                target = next(
                    (m for m in microscopes if m.get("microscope_id") == self._relay_target_microscope and m.get("online")),
                    None,
                )
                if target is None:
                    self.state.log_message.emit(
                        f"⚠ Requested microscope '{self._relay_target_microscope}' not online; using first available."
                    )
            if target is None:
                target = online[0] if online else microscopes[0]
            self._relay_microscope_id = target.get("microscope_id", "")
            s = self.state
            s.relay_status = "connected"
            s.relay_state_changed.emit("connected")
            s.device_status = "live"
            s.device_state_changed.emit("live")
            s.log_message.emit(
                f"✓ Relay live — microscope '{self._relay_microscope_id}'."
            )
            self._latency_timer.start()
            self._start_relay_polling()
            return

        if msg_type == "proxy_response":
            self._handle_proxy_response(msg)
            return

        if msg_type == "error":
            self.state.log_message.emit(f"✕ Relay error: {msg.get('message', 'unknown')}")
            return

        # ── Relay / simulation messages ───────────────────────────────────
        if method == "agent.connected":
            self._phase3_agent_ok()
        elif method == "hardware.ready":
            self._phase4_live()
        elif method == "stage.position":
            self.state.pos_x = params.get("x", self.state.pos_x)
            self.state.pos_y = params.get("y", self.state.pos_y)
            self.state.pos_z = params.get("z", self.state.pos_z)
            self.state.position_changed.emit(
                self.state.pos_x, self.state.pos_y, self.state.pos_z
            )
        elif method == "autofocus.result":
            score = params.get("score", 450)
            grade = "EXCELLENT" if score > 500 else "GOOD" if score > 380 else "FAIR"
            self.state.focus_updated.emit(score, grade)

    # ── Relay proxy helpers ───────────────────────────────────────────────────

    def _start_relay_polling(self) -> None:
        """Start timers that poll frames (~8 fps) and position (2 Hz) via relay."""
        self._relay_frame_timer = QTimer(self)
        self._relay_frame_timer.setInterval(120)  # ~8 fps
        self._relay_frame_timer.timeout.connect(self._relay_poll_frame)
        self._relay_frame_timer.start()

        self._relay_pos_timer = QTimer(self)
        self._relay_pos_timer.setInterval(500)
        self._relay_pos_timer.timeout.connect(self._relay_poll_position)
        self._relay_pos_timer.start()

    def _relay_send_command(self, action: str, params: "dict | None" = None) -> str:
        """Send a proxy_command to the relay and return the cmd_id."""
        if not self._ws or not self._ws.isValid():
            return ""
        cmd_id = uuid.uuid4().hex[:8]
        self._ws.sendTextMessage(json.dumps({
            "type":          "proxy_command",
            "access_token":  self._relay_access_token,
            "microscope_id": self._relay_microscope_id,
            "action":        action,
            "params":        params or {},
            "cmd_id":        cmd_id,
        }))
        return cmd_id

    def _relay_poll_frame(self) -> None:
        if self._relay_microscope_id:
            self._relay_send_command("capture")

    def _relay_poll_position(self) -> None:
        if self._relay_microscope_id:
            self._relay_send_command("get_position")

    def _handle_proxy_response(self, msg: dict) -> None:
        """Dispatch a proxy_response from the relay to the appropriate state update."""
        action = msg.get("action", "")
        if msg.get("status") != "ok":
            return
        if action == "capture":
            try:
                import base64
                self.state.frame_received.emit(base64.b64decode(msg["image"]))
            except Exception:
                pass
        elif action == "get_position":
            pos = msg.get("position", {})
            if pos:
                self.state.pos_x = float(pos.get("x", self.state.pos_x))
                self.state.pos_y = float(pos.get("y", self.state.pos_y))
                self.state.pos_z = float(pos.get("z", self.state.pos_z))
                self.state.position_changed.emit(
                    self.state.pos_x, self.state.pos_y, self.state.pos_z
                )
        elif action == "autofocus":
            res = msg.get("autofocus_result", {})
            sharpness = res.get("sharpness", [])
            score = int(max(sharpness) * 1000) if sharpness else 450
            grade = "EXCELLENT" if score > 500 else "GOOD" if score > 380 else "FAIR"
            self.state.focus_updated.emit(score, grade)

    # ── Simulated phases (used when server unavailable) ───────────────────────

    def _simulate_phase1(self) -> None:
        """Relay connecting… → connected after 1.4 s."""
        QTimer.singleShot(1400, self._phase2_relay_ok)

    def _phase2_relay_ok(self) -> None:
        s = self.state
        s.relay_status = "connected"
        s.relay_state_changed.emit("connected")
        s.device_status = "searching"
        s.device_state_changed.emit("searching")
        s.log_message.emit(f"✓ Relay connected. Waiting for device agent {s.relay_room}…")
        QTimer.singleShot(1400, self._phase3_agent_ok)

    def _phase3_agent_ok(self) -> None:
        s = self.state
        s.device_status = "found"
        s.device_state_changed.emit("found")
        s.log_message.emit("✓ Device agent found. Bridging to microscope hardware…")
        QTimer.singleShot(1800, self._phase4_live)

    def _phase4_live(self) -> None:
        s = self.state
        s.device_status = "live"
        s.device_state_changed.emit("live")
        s.log_message.emit("✓ All systems live. Operator Arun ready on-site.")
        self._latency_timer.start()

    def disconnect(self) -> None:
        """Tear down the connection and reset state."""
        self._latency_timer.stop()
        if self._relay_frame_timer:
            self._relay_frame_timer.stop()
            self._relay_frame_timer = None
        if self._relay_pos_timer:
            self._relay_pos_timer.stop()
            self._relay_pos_timer = None
        self._relay_access_token = ""
        self._relay_microscope_id = ""
        if self._ws:
            self._ws.close()
            self._ws = None
        s = self.state
        s.relay_status = "off"
        s.device_status = "offline"
        s.relay_state_changed.emit("off")
        s.device_state_changed.emit("offline")
        s.log_message.emit("Disconnected from relay.")

    # ── Latency ──────────────────────────────────────────────────────────────

    def _update_latency(self) -> None:
        if _HAS_WEBSOCKET and self._ws and self._ws.isValid():
            self._ws.ping()  # real ping; pong handler would update latency
        latency = random.randint(10, 32)
        self.state.latency_ms = latency
        self.state.latency_updated.emit(latency)

    # ── Stage RPC ─────────────────────────────────────────────────────────────

    def send_move(self, axis: str, direction: int) -> None:
        """Send a stage-move command and update local state immediately."""
        self.state.move_stage(axis, direction)
        if self._ws and self._ws.isValid():
            if self._is_relay_mode() and self._relay_microscope_id:
                self._relay_send_command(
                    "move", {axis: direction * int(self.state.step_size * 100)}
                )
            else:
                self._ws.sendTextMessage(json.dumps({
                    "method": "stage.move",
                    "params": {"axis": axis, "direction": direction,
                               "step": self.state.step_size}
                }))

    def send_autofocus(self) -> None:
        if self._ws and self._ws.isValid():
            if self._is_relay_mode() and self._relay_microscope_id:
                self._relay_send_command("autofocus")
            else:
                self._ws.sendTextMessage(json.dumps({"method": "autofocus.run"}))
        else:
            # Simulate
            score = random.randint(390, 550)
            grade = "EXCELLENT" if score > 500 else "GOOD" if score > 380 else "FAIR"
            QTimer.singleShot(800, lambda: self.state.focus_updated.emit(score, grade))

    def send_capture(self) -> None:
        if self._ws and self._ws.isValid():
            if self._is_relay_mode() and self._relay_microscope_id:
                self._relay_send_command("capture")
            else:
                self._ws.sendTextMessage(json.dumps({"method": "camera.capture"}))
        self.state.capture_triggered.emit()

    def send_stream_toggle(self, active: bool) -> None:
        self.state.streaming = active
        self.state.stream_toggled.emit(active)
        if self._ws and self._ws.isValid():
            self._ws.sendTextMessage(json.dumps({
                "method": "stream.toggle", "params": {"active": active}
            }))

    def send_quality(self, quality: str) -> None:
        self.state.quality = quality
        self.state.quality_changed.emit(quality)
        if self._ws and self._ws.isValid():
            self._ws.sendTextMessage(json.dumps({
                "method": "stream.quality", "params": {"quality": quality}
            }))

    # ── Scan ─────────────────────────────────────────────────────────────────

    @staticmethod
    def compute_scan_order(cols: int, rows: int, pattern: str) -> list[tuple[int, int]]:
        """Return ordered list of (row, col) tuples for the given pattern."""
        tiles: list[tuple[int, int]] = []
        if pattern == "raster":
            for r in range(rows):
                for c in range(cols):
                    tiles.append((r, c))
        elif pattern == "snake":
            for r in range(rows):
                cols_range = range(cols) if r % 2 == 0 else range(cols - 1, -1, -1)
                for c in cols_range:
                    tiles.append((r, c))
        elif pattern == "spiral":
            top, bot, left, right = 0, rows - 1, 0, cols - 1
            while top <= bot and left <= right:
                for c in range(left, right + 1):
                    tiles.append((top, c))
                top += 1
                for r in range(top, bot + 1):
                    tiles.append((r, right))
                right -= 1
                if top <= bot:
                    for c in range(right, left - 1, -1):
                        tiles.append((bot, c))
                    bot -= 1
                if left <= right:
                    for r in range(bot, top - 1, -1):
                        tiles.append((r, left))
                    left += 1
        return tiles

    @staticmethod
    def compute_scan_stats(cols: int, rows: int, overlap_pct: int,
                            objective: str) -> dict:
        fov_mm = 0.22  # default 40× FOV
        if "20×" in objective:
            fov_mm = 0.44
        elif "10×" in objective:
            fov_mm = 0.88
        step = fov_mm * (1 - overlap_pct / 100)
        area_w = (cols - 1) * step + fov_mm
        area_h = (rows - 1) * step + fov_mm
        area = area_w * area_h
        total = cols * rows
        secs = total * 4
        size_mb = round(total * 6.2)
        return {
            "total": total,
            "time_str": f"{secs // 60} m {secs % 60} s",
            "area_str": f"{area:.2f} mm²",
            "size_str": f"{size_mb} MB",
        }

    def start_scan(self) -> None:
        s = self.state
        if s.scan_state == "running":
            return
        s.scan_total = s.scan_cols * s.scan_rows
        s.scan_current = 0
        s.scan_state = "running"
        self._scan_order = self.compute_scan_order(
            s.scan_cols, s.scan_rows, s.scan_pattern
        )
        self._scan_current_idx = 0
        s.scan_state_changed.emit("running")
        self._scan_timer.start()

    def pause_scan(self) -> None:
        s = self.state
        if s.scan_state == "running":
            self._scan_timer.stop()
            s.scan_state = "paused"
            s.scan_state_changed.emit("paused")
        elif s.scan_state == "paused":
            s.scan_state = "running"
            s.scan_state_changed.emit("running")
            self._scan_timer.start()

    def stop_scan(self) -> None:
        self._scan_timer.stop()
        self.state.scan_state = "idle"
        self.state.scan_state_changed.emit("idle")

    def reset_scan(self) -> None:
        self.stop_scan()
        self.state.scan_current = 0
        self.state.scan_progress_changed.emit(0, self.state.scan_total)

    def _scan_step(self) -> None:
        s = self.state
        idx = self._scan_current_idx
        if s.scan_state != "running" or idx >= len(self._scan_order):
            self._scan_timer.stop()
            return

        # Mark previous tile done
        if idx > 0:
            pr, pc = self._scan_order[idx - 1]
            s.scan_tile_updated.emit(pr, pc, "done")

        r, c = self._scan_order[idx]
        s.scan_tile_updated.emit(r, c, "current")
        self._scan_current_idx += 1
        s.scan_current = self._scan_current_idx
        s.scan_progress_changed.emit(s.scan_current, s.scan_total)

        if self._ws and self._ws.isValid():
            self._ws.sendTextMessage(json.dumps({
                "method": "scan.move_to_tile",
                "params": {"row": r, "col": c, "index": idx}
            }))

        if self._scan_current_idx >= len(self._scan_order):
            self._scan_timer.stop()
            # Mark last tile done
            lr, lc = self._scan_order[-1]
            s.scan_tile_updated.emit(lr, lc, "done")
            s.scan_state = "done"
            s.scan_state_changed.emit("done")
