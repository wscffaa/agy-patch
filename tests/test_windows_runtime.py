"""Offline regression tests for the cross-platform wrapper, relay, and statusline.

Covers the reviewed Windows runtime bugs: autonomous idle keepalive (no statusline
refresh needed), the evidenced 32k-prompt gate, no touch during turns/failure/limit/
compaction, nested Gemini upstream retention, and shared POSIX state paths.
"""

from __future__ import annotations

import contextlib
import http.client
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import unittest.mock
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

REPO = pathlib.Path(__file__).resolve().parent.parent
RUNTIME_DIR = REPO / "runtime"
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

import agy_wrapper  # noqa: E402
import cache_relay  # noqa: E402
import statusline  # noqa: E402

SID = "11111111-2222-3333-4444-555555555555"
SID2 = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
MODEL_PATH = "/v1beta/models/gemini-4-carbon-high:streamGenerateContent?alt=sse"
SSE_USAGE = (b'data: {"candidates":[],"usageMetadata":{"promptTokenCount":41000,'
             b'"candidatesTokenCount":0,"totalTokenCount":41000}}\n\n')
SSE_NO_USAGE = b'data: {"candidates":[]}\n\n'


def request_body(sid: str = SID, *, windows_path: bool = False,
                 request_id: str | None = None) -> bytes:
    separator = "\\" if windows_path else "/"
    return json.dumps({
        "model": "gemini-4-carbon-high",
        "requestId": request_id or f"agent/traj/1700000000000/{uuid.uuid4()}/1",
        "systemInstruction": {"parts": [{"text": f"C:{separator}work{separator}brain{separator}{sid}"}]},
        "contents": [{"role": "user", "parts": [{"text": "hello"}]}],
    }, separators=(",", ":")).encode()


def cloud_code_body(sid: str = SID, *, request_id: str | None = None) -> bytes:
    """ACP/v1internal shape: the generation fields live under a top-level request."""
    return json.dumps({
        "requestId": request_id or f"agent/traj/1700000000000/{uuid.uuid4()}/1",
        "request": {
            "model": "gemini-4-carbon-high",
            "systemInstruction": {"parts": [{"text": f"file:///work/brain/{sid}"}]},
            "contents": [{"role": "user", "parts": [{"text": "hello"}]}],
        },
    }, separators=(",", ":")).encode()


def wait_for(predicate, timeout: float = 5.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


class _UpstreamHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    status_code = 200
    response_body = SSE_USAGE

    def log_message(self, *_args: object) -> None:
        pass

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        with self.lock:
            self.requests.append((self.path, body, dict(self.headers.items())))
        payload = self.response_body
        self.send_response(self.status_code)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)
        self.wfile.flush()


@contextlib.contextmanager
def fake_upstream(status: int = 200, body: bytes = SSE_USAGE):
    """Loopback stand-in for the Gemini/Cloud Code upstream; records every POST."""
    handler = type("_RecordedUpstream", (_UpstreamHandler,), {
        "status_code": status,
        "response_body": body,
        "requests": [],
        "lock": threading.Lock(),
    })
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", handler
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@contextlib.contextmanager
def relay_server():
    cache_relay.Relay.upstream = None
    cache_relay.Relay.upstream_origin = ""
    server = ThreadingHTTPServer(("127.0.0.1", 0), cache_relay.Relay)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        if cache_relay.Relay.upstream is not None:
            cache_relay.Relay.upstream.close()
            cache_relay.Relay.upstream = None


def post(port: int, path: str, body: bytes) -> tuple[int, bytes]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        conn.request("POST", path, body=body, headers={"Content-Type": "application/json"})
        response = conn.getresponse()
        return response.status, response.read()
    finally:
        conn.close()


class StatePathTests(unittest.TestCase):
    def test_posix_defaults_are_the_shared_tmp(self) -> None:
        self.assertEqual(pathlib.Path(cache_relay.default_state_dir("posix")), pathlib.Path("/tmp"))
        self.assertEqual(statusline.default_state_dir("posix"), pathlib.Path("/tmp"))

    def test_windows_defaults_are_the_native_temp(self) -> None:
        native = pathlib.Path(tempfile.gettempdir())
        self.assertEqual(pathlib.Path(cache_relay.default_state_dir("nt")), native)
        self.assertEqual(statusline.default_state_dir("nt"), native)

    def test_relay_and_statusline_consume_the_same_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with unittest.mock.patch.object(cache_relay, "STATE_DIR", tmp), \
                    unittest.mock.patch.object(statusline, "STATE_DIR", pathlib.Path(tmp)):
                self.assertEqual(pathlib.Path(cache_relay.state_path(SID)), statusline.relay_path(SID))
                self.assertEqual(cache_relay.state_path(SID),
                                 os.path.join(tmp, f"agy_cache_{SID}.dat"))

    def test_shell_statusline_uses_the_same_posix_directory(self) -> None:
        text = (RUNTIME_DIR / "statusline.sh").read_text()
        self.assertIn('local CACHE_DIR="${AGY_CACHE_RELAY_DIR:-/tmp}"', text)
        self.assertIn('local RELAY_FILE="${CACHE_DIR}/agy_cache_', text)

    def test_zsh_touch_contract_matches_relay_constants(self) -> None:
        text = (RUNTIME_DIR / "statusline.sh").read_text()
        self.assertEqual(cache_relay.MAX_TOUCHES, 4)
        self.assertEqual(cache_relay.MIN_PROMPT_TOKENS, 32000)
        self.assertEqual(cache_relay.SELF_TOUCH_AFTER, 240.0)
        self.assertEqual(statusline.CACHE_TTL, cache_relay.CACHE_TTL)
        self.assertIn("CACHE_REM > 0 && CACHE_REM <= 60", text)
        self.assertIn("TOT_PROMPT >= 32000", text)
        self.assertIn("RELAY_TOUCHES < 4", text)


class SessionIdTests(unittest.TestCase):
    def test_slash_and_backslash_brain_paths_both_resolve(self) -> None:
        for windows_path in (False, True):
            sid, _model, _shape, _compact = cache_relay.inspect_request(
                request_body(windows_path=windows_path))
            self.assertEqual(sid, SID)

    def test_non_hex_suffix_after_uuid_is_not_a_different_session(self) -> None:
        body = request_body()
        parsed = json.loads(body)
        parsed["systemInstruction"]["parts"][0]["text"] += " trailing"
        sid, _, _, _ = cache_relay.inspect_request(json.dumps(parsed).encode())
        self.assertEqual(sid, SID)

    def test_extra_hex_digit_after_uuid_is_not_a_session(self) -> None:
        body = json.dumps({
            "systemInstruction": {"parts": [{"text": f"brain/{SID}a"}]},
            "contents": [],
        }).encode()
        sid, _, _, _ = cache_relay.inspect_request(body)
        self.assertIsNone(sid)


class PromptEvidenceTests(unittest.TestCase):
    def test_split_usage_metadata_is_accumulated(self) -> None:
        entry = cache_relay.new_session()
        carry = cache_relay.note_prompt_tokens(entry, b'data: {"usageMetadata":{"promptToken', b"")
        self.assertIsNone(entry["prompt_tokens"])
        carry = cache_relay.note_prompt_tokens(entry, b'Count":41000}}', carry)
        self.assertEqual(entry["prompt_tokens"], 41000)
        self.assertIsInstance(carry, bytes)

    def test_absent_usage_metadata_stays_unknown(self) -> None:
        entry = cache_relay.new_session()
        cache_relay.note_prompt_tokens(entry, SSE_NO_USAGE)
        self.assertIsNone(entry["prompt_tokens"])

    def test_a_slow_old_response_cannot_overwrite_newer_turn_evidence(self) -> None:
        entry = cache_relay.new_session()
        entry["seq"] = 2
        cache_relay.note_prompt_tokens(entry, SSE_USAGE, seq=1)
        self.assertIsNone(entry["prompt_tokens"])


class SchedulingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for patch in (
            unittest.mock.patch.object(cache_relay, "STATE_DIR", self.tmp.name),
            unittest.mock.patch.object(cache_relay, "LOG_PATH", os.path.join(self.tmp.name, "relay.log")),
        ):
            patch.start()
            self.addCleanup(patch.stop)
        cache_relay.sessions.clear()
        self.addCleanup(cache_relay.sessions.clear)

    def entry(self, origin: str, *, anchor: int | None = None, sid: str = SID,
              prompt_tokens: int | None = 41000, status: str = "live",
              touches: int = 0, inflight: int = 0) -> dict:
        item = cache_relay.new_session()
        item.update({
            "anchor": int(time.time()) - int(cache_relay.SELF_TOUCH_AFTER) - 10
            if anchor is None else anchor,
            "touches": touches,
            "status": status,
            "body": request_body(sid),
            "origin": origin,
            "path": MODEL_PATH,
            "headers": {"Content-Type": "application/json"},
            "prompt_tokens": prompt_tokens,
            "inflight": inflight,
        })
        return item

    def test_expired_eligible_idle_sends_one_touch_and_updates_count(self) -> None:
        with fake_upstream() as (origin, handler):
            item = self.entry(origin)
            original_id = json.loads(item["body"])["requestId"]
            cache_relay.sessions[SID] = item
            now = time.time()
            self.assertEqual(cache_relay.sweep_touches(now=now), [SID])
            self.assertTrue(wait_for(lambda: item["touches"] == 1 and not item["touching"]))
            self.assertEqual(len(handler.requests), 1)
            path, body, _headers = handler.requests[0]
            self.assertEqual(path, MODEL_PATH)
            touched = json.loads(body)
            self.assertNotEqual(touched["requestId"], original_id)
            self.assertTrue(touched["requestId"].startswith("agent/traj/"))
            self.assertTrue(touched["requestId"].endswith("/1"))

            state_path = pathlib.Path(cache_relay.state_path(SID))
            state = state_path.read_text().split()
            self.assertEqual(state[0], str(item["anchor"]))
            self.assertEqual(state[1:], ["1", "live"])
            self.assertEqual(statusline.read_relay(state_path)["touches"], "1")

            # The zsh statusline may fire just after the relay; the age recheck absorbs it.
            self.assertEqual(cache_relay.sweep_touches(now=now + 1), [])
            code, text = cache_relay.touch(SID, now=now + 1)
            self.assertEqual(code, 409)
            self.assertIn("not due", text)
            self.assertEqual(item["touches"], 1)
            self.assertEqual(len(handler.requests), 1)

    def test_no_touch_before_the_keepalive_window(self) -> None:
        with fake_upstream() as (origin, handler):
            cache_relay.sessions[SID] = self.entry(origin, anchor=int(time.time()) - 100)
            self.assertEqual(cache_relay.sweep_touches(), [])
            self.assertEqual(len(handler.requests), 0)

    def test_no_touch_after_the_cache_already_expired(self) -> None:
        with fake_upstream() as (origin, handler):
            cache_relay.sessions[SID] = self.entry(
                origin, anchor=int(time.time()) - int(cache_relay.CACHE_TTL) - 100)
            self.assertEqual(cache_relay.sweep_touches(), [])
            self.assertEqual(len(handler.requests), 0)

    def test_no_touch_while_a_real_turn_is_in_flight(self) -> None:
        with fake_upstream() as (origin, handler):
            cache_relay.sessions[SID] = self.entry(origin, inflight=1)
            self.assertEqual(cache_relay.sweep_touches(), [])
            self.assertEqual(len(handler.requests), 0)

    def test_no_touch_when_prompt_size_is_unknown(self) -> None:
        with fake_upstream() as (origin, handler):
            cache_relay.sessions[SID] = self.entry(origin, prompt_tokens=None)
            self.assertEqual(cache_relay.sweep_touches(), [])
            self.assertEqual(len(handler.requests), 0)

    def test_no_touch_when_prompt_is_below_32k(self) -> None:
        with fake_upstream() as (origin, handler):
            cache_relay.sessions[SID] = self.entry(origin, prompt_tokens=31999)
            self.assertEqual(cache_relay.sweep_touches(), [])
            self.assertEqual(len(handler.requests), 0)

    def test_direct_touch_also_refuses_an_unknown_prompt_size(self) -> None:
        with fake_upstream() as (origin, handler):
            item = self.entry(origin, prompt_tokens=None)
            cache_relay.sessions[SID] = item
            code, text = cache_relay.touch(SID, now=time.time())
            self.assertEqual(code, 409)
            self.assertIn("prompt size", text)
            self.assertEqual(item["touches"], 0)
            self.assertEqual(len(handler.requests), 0)

    def test_no_touch_after_a_failed_touch(self) -> None:
        with fake_upstream() as (origin, handler):
            cache_relay.sessions[SID] = self.entry(origin, status="fail")
            self.assertEqual(cache_relay.sweep_touches(), [])
            self.assertEqual(len(handler.requests), 0)

    def test_no_touch_after_the_four_touch_limit(self) -> None:
        with fake_upstream() as (origin, handler):
            cache_relay.sessions[SID] = self.entry(origin, touches=cache_relay.MAX_TOUCHES)
            self.assertEqual(cache_relay.sweep_touches(), [])
            self.assertEqual(len(handler.requests), 0)

    def test_no_touch_after_compaction(self) -> None:
        with fake_upstream() as (origin, handler):
            cache_relay.sessions[SID] = self.entry(origin, status="off")
            self.assertEqual(cache_relay.sweep_touches(), [])
            self.assertEqual(len(handler.requests), 0)

    def test_failed_touch_marks_fail_and_stops_the_scheduler(self) -> None:
        with fake_upstream(status=500) as (origin, handler):
            item = self.entry(origin)
            cache_relay.sessions[SID] = item
            code, _text = cache_relay.touch(SID, now=time.time())
            self.assertEqual(code, 200)
            self.assertEqual(item["status"], "fail")
            self.assertEqual(item["touches"], 0)
            self.assertEqual(pathlib.Path(cache_relay.state_path(SID)).read_text().split()[1:],
                             ["0", "fail"])
            self.assertEqual(cache_relay.sweep_touches(now=time.time() + 1), [])
            self.assertEqual(len(handler.requests), 1)

    def test_multiple_sessions_are_scheduled_independently(self) -> None:
        with fake_upstream() as (origin, handler):
            first = self.entry(origin)
            second = self.entry(origin, sid=SID2)
            cache_relay.sessions[SID] = first
            cache_relay.sessions[SID2] = second
            dispatched = cache_relay.sweep_touches(now=time.time())
            self.assertCountEqual(dispatched, [SID, SID2])
            self.assertTrue(wait_for(lambda: first["touches"] == 1 and second["touches"] == 1))
            self.assertEqual(len(handler.requests), 2)

    def test_forwarded_response_evidences_prompt_size_and_allows_touch(self) -> None:
        with fake_upstream() as (upstream, handler):
            old_upstream = cache_relay.gemini_upstream
            cache_relay.gemini_upstream = upstream
            try:
                with relay_server() as port:
                    status, _data = post(port, MODEL_PATH, request_body())
                    self.assertEqual(status, 200)
                    item = cache_relay.sessions[SID]
                    self.assertTrue(wait_for(lambda: item["inflight"] == 0))
                    self.assertEqual(item["prompt_tokens"], 41000)
                    self.assertEqual(item["status"], "live")
                    self.assertEqual(len(handler.requests), 1)

                    item["anchor"] = int(time.time()) - int(cache_relay.SELF_TOUCH_AFTER) - 10
                    self.assertEqual(cache_relay.sweep_touches(now=time.time()), [SID])
                    self.assertTrue(wait_for(lambda: item["touches"] == 1))
                    self.assertEqual(len(handler.requests), 2)
            finally:
                cache_relay.gemini_upstream = old_upstream

    def test_acp_cloud_code_turn_evidences_prompt_size_and_allows_touch(self) -> None:
        with fake_upstream() as (upstream, handler):
            old_cloud = cache_relay.CLOUD_CODE
            cache_relay.CLOUD_CODE = upstream
            try:
                with relay_server() as port:
                    status, _data = post(port, "/v1internal:streamGenerateContent?alt=sse",
                                         cloud_code_body())
                    self.assertEqual(status, 200)
                    item = cache_relay.sessions[SID]
                    self.assertTrue(wait_for(lambda: item["inflight"] == 0))
                    self.assertEqual(item["status"], "live")
                    self.assertEqual(item["prompt_tokens"], 41000)
                    item["anchor"] = int(time.time()) - int(cache_relay.SELF_TOUCH_AFTER) - 10
                    self.assertEqual(cache_relay.sweep_touches(now=time.time()), [SID])
                    self.assertTrue(wait_for(lambda: item["touches"] == 1))
                    self.assertEqual(len(handler.requests), 2)
            finally:
                cache_relay.CLOUD_CODE = old_cloud

    def test_response_without_usage_metadata_never_autotouches(self) -> None:
        with fake_upstream(body=SSE_NO_USAGE) as (upstream, handler):
            old_upstream = cache_relay.gemini_upstream
            cache_relay.gemini_upstream = upstream
            try:
                with relay_server() as port:
                    status, _data = post(port, MODEL_PATH, request_body())
                    self.assertEqual(status, 200)
                    item = cache_relay.sessions[SID]
                    self.assertTrue(wait_for(lambda: item["inflight"] == 0))
                    self.assertIsNone(item["prompt_tokens"])
                    item["anchor"] = int(time.time()) - int(cache_relay.SELF_TOUCH_AFTER) - 10
                    self.assertEqual(cache_relay.sweep_touches(now=time.time()), [])
                    self.assertEqual(len(handler.requests), 1)
            finally:
                cache_relay.gemini_upstream = old_upstream


class WrapperUpstreamTests(unittest.TestCase):
    def test_nested_relay_uses_the_recorded_original_upstream(self) -> None:
        env = {
            "AGY_CACHE_RELAY": "http://127.0.0.1:4100",
            "GOOGLE_GEMINI_BASE_URL": "http://127.0.0.1:4100",
            "AGY_GEMINI_UPSTREAM": "http://127.0.0.1:5233",
        }
        self.assertEqual(agy_wrapper.gemini_upstream(env), "http://127.0.0.1:5233")
        command = agy_wrapper.relay_command(pathlib.Path("cache_relay.py"), env, parent=4242)
        self.assertEqual(command[command.index("--parent") + 1], "4242")
        self.assertEqual(command[command.index("--gemini-upstream") + 1], "http://127.0.0.1:5233")
        child = agy_wrapper.relay_environment(env, "http://127.0.0.1:4101")
        self.assertEqual(child["GOOGLE_GEMINI_BASE_URL"], "http://127.0.0.1:4101")
        self.assertEqual(child["AGY_GEMINI_UPSTREAM"], "http://127.0.0.1:5233")
        self.assertEqual(child["CLOUD_CODE_URL"], "http://127.0.0.1:4101")
        self.assertEqual(child["AGY_CACHE_RELAY"], "http://127.0.0.1:4101")

    def test_nested_relay_without_an_original_is_not_pointed_at_cloud_code(self) -> None:
        env = {
            "AGY_CACHE_RELAY": "http://127.0.0.1:4100",
            "GOOGLE_GEMINI_BASE_URL": "http://127.0.0.1:4100",
        }
        self.assertEqual(agy_wrapper.gemini_upstream(env), "")
        command = agy_wrapper.relay_command(pathlib.Path("cache_relay.py"), env, parent=7)
        self.assertNotIn("--gemini-upstream", command)
        child = agy_wrapper.relay_environment(env, "http://127.0.0.1:4101")
        self.assertNotIn("GOOGLE_GEMINI_BASE_URL", child)
        self.assertNotIn("AGY_GEMINI_UPSTREAM", child)
        self.assertEqual(child["CLOUD_CODE_URL"], "http://127.0.0.1:4101")

    def test_external_gemini_upstream_is_preserved(self) -> None:
        env = {
            "AGY_CACHE_RELAY": "http://127.0.0.1:4100",
            "GOOGLE_GEMINI_BASE_URL": "http://127.0.0.1:5233",
            "AGY_GEMINI_UPSTREAM": "http://127.0.0.1:9999",
        }
        self.assertEqual(agy_wrapper.gemini_upstream(env), "http://127.0.0.1:5233")
        child = agy_wrapper.relay_environment(env, "http://127.0.0.1:4101")
        self.assertEqual(child["GOOGLE_GEMINI_BASE_URL"], "http://127.0.0.1:4101")
        self.assertEqual(child["AGY_GEMINI_UPSTREAM"], "http://127.0.0.1:5233")

    def test_relay_routes_gemini_paths_to_the_configured_upstream(self) -> None:
        old_upstream = cache_relay.gemini_upstream
        cache_relay.gemini_upstream = "http://127.0.0.1:5233"
        try:
            self.assertEqual(cache_relay.route(MODEL_PATH)[0], "http://127.0.0.1:5233")
            self.assertEqual(cache_relay.route("/v1internal:generateContent")[0],
                             cache_relay.CLOUD_CODE)
        finally:
            cache_relay.gemini_upstream = old_upstream

    def test_shell_wrapper_matches_the_python_nested_rule(self) -> None:
        text = (RUNTIME_DIR / "agy-wrapper.sh").read_text()
        self.assertIn('[[ -n $gemini_upstream && $gemini_upstream == "$relay_parent" ]]', text)
        self.assertIn("unset GOOGLE_GEMINI_BASE_URL", text)


class WindowsProcessTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Windows kernel32 handle signatures")
    def test_current_process_is_alive(self) -> None:
        self.assertTrue(cache_relay.process_alive(os.getpid()))

    @unittest.skipUnless(os.name == "nt", "Windows kernel32 handle signatures")
    def test_invalid_pid_is_not_alive(self) -> None:
        self.assertFalse(cache_relay.process_alive(0x7FFFFFFF))


class InstalledCopyTests(unittest.TestCase):
    def test_runtime_scripts_run_from_a_bare_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            relay_copy = pathlib.Path(tmp) / "cache_relay.py"
            status_copy = pathlib.Path(tmp) / "statusline.py"
            shutil.copy2(RUNTIME_DIR / "cache_relay.py", relay_copy)
            shutil.copy2(RUNTIME_DIR / "statusline.py", status_copy)
            env = os.environ.copy()
            env["AGY_CACHE_RELAY_DIR"] = tmp
            env["AGY_STATUSLINE_ASCII"] = "1"

            relay = subprocess.run(
                [sys.executable, "-I", str(relay_copy), "--help"],
                cwd=tmp, env=env, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(relay.returncode, 0, relay.stderr)
            self.assertIn("--gemini-upstream", relay.stdout)

            bar = subprocess.run(
                [sys.executable, "-I", str(status_copy)],
                cwd=tmp, env=env, input='{"session_id":"bare"}',
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(bar.returncode, 0, bar.stderr)
            self.assertTrue(bar.stdout.strip())


if __name__ == "__main__":
    unittest.main()
