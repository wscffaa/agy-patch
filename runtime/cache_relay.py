#!/usr/bin/env python3
"""Loopback relay that keeps an idle agy session's implicit prompt cache warm.

runtime/agy-wrapper.sh starts one relay per interactive agy process and points agy's
CLOUD_CODE_URL at it (the CLI has no --cloud_code_endpoint flag; only --hub does).
When agy runs with modelProvider "gemini", the wrapper also points
GOOGLE_GEMINI_BASE_URL here and passes the original as --gemini-upstream (CPA).
Requests then flow through unchanged: /v1internal paths to Cloud Code, the rest to
the Gemini upstream. For each main-session streamGenerateContent the relay
remembers the last body and its headers, keyed by the conversation id that agy
writes into systemInstruction (".../brain/<id>"), and records the time in
/tmp/agy_cache_<id>.dat on POSIX (the native temp directory on Windows) as
"ANCHOR_TS TOUCHES STATUS". Title and safety calls carry no brain path and are
ignored.

statusline.sh reads that file for the cache countdown and, shortly before the
5-minute implicit-cache TTL lapses, POSTs /_touch/<id>. The relay then replays
the last body with a fresh requestId, reads the first SSE event (prefill done,
cache touched), and closes the stream. It stops after MAX_TOUCHES idle replays or
any failure, until the next request upstream accepts resets it.

The relay also runs that same replay from an internal scheduler, so interactive
and ACP sessions stay warm even when the statusline never refreshes. A touch is
due once the last accepted turn is SELF_TOUCH_AFTER old, and only for a live
main-session turn whose forwarded response evidenced at least MIN_PROMPT_TOKENS
prompt tokens. Per-session locks, a due-time check and the touch count make the
internal scheduler and a statusline POST idempotent: a touch another caller just
completed is never counted twice.

The relay prints its port on stdout, then exits when the --parent process does.
"""
import argparse
import glob
import http.client
import json
import os
import re
import sys
import tempfile
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

try:
    import fcntl
except ImportError:  # Windows
    fcntl = None

CLOUD_CODE = "https://daily-cloudcode-pa.googleapis.com"
gemini_upstream: str | None = None
MAX_TOUCHES = 4
MIN_PROMPT_TOKENS = 32000  # implicit caching only pays off on prompts this large
CACHE_TTL = 300.0
SELF_TOUCH_AFTER = CACHE_TTL - 60.0  # same last-minute window statusline.sh uses
SCHEDULER_INTERVAL = 1.0
KEEPALIVE_MODELS = ("argon", "carbon", "hydrogen")  # 1M-window Gemini 4 families


def default_state_dir(platform: str = os.name) -> str:
    """Shared /tmp on POSIX (statusline.sh reads it); the native temp dir on Windows."""
    return tempfile.gettempdir() if platform == "nt" else "/tmp"


STATE_DIR = os.environ.get("AGY_CACHE_RELAY_DIR") or default_state_dir()
os.makedirs(STATE_DIR, exist_ok=True)
LOG_PATH = os.path.join(STATE_DIR, "agy_cache_relay.log")
LOG_KEEP = 200  # ~30KB
SESSION_RE = re.compile(r"brain[/\\]([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})(?![0-9a-f])")
# A compaction request, manual (/compact) or automatic, ends with a user turn that is this
# instruction, appended by CheckpointHandler after the /compact turn itself. Replaying it would
# only keep the pre-compaction prefix warm, which the next turn no longer uses. Matched at the
# start of a part: user messages begin with <USER_REQUEST>, so one quoting it is not mistaken.
COMPACT_PROMPT = "You have been working on the task described above but have not yet completed"
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
PROMPT_TOKEN_RE = re.compile(rb'"promptTokenCount"\s*:\s*(\d+)')
HOP_BY_HOP = {"connection", "keep-alive", "proxy-connection", "transfer-encoding", "te",
              "trailer", "upgrade", "host", "content-length"}

sessions: dict[str, dict] = {}
sessions_lock = threading.Lock()


def log(message: str) -> None:
    """Append to the shared log, keeping only its last LOG_KEEP lines across all relays."""
    line = f"{time.strftime('%m-%d %H:%M:%S')} {message}"
    try:
        with open(LOG_PATH, "a+") as f:
            if fcntl is not None:
                fcntl.flock(f, fcntl.LOCK_EX)
            f.seek(0)
            lines = f.read().splitlines()[-(LOG_KEEP - 1):] + [line]
            f.truncate(0)
            f.write("\n".join(lines) + "\n")
    except OSError:
        print(line, file=sys.stderr, flush=True)


def sweep_state(max_age: float = 86400) -> None:
    """Drop state files of conversations untouched for a day; each conversation leaves one."""
    cutoff = time.time() - max_age
    for path in glob.glob(os.path.join(STATE_DIR, "agy_cache_*.dat")):
        try:
            if os.path.getmtime(path) < cutoff:
                os.remove(path)
        except OSError:
            pass


def route(path: str) -> tuple[str, str]:
    """(origin, upstream path) for a request path received by the relay."""
    base = CLOUD_CODE if path.startswith("/v1internal") or not gemini_upstream else gemini_upstream
    parts = urlsplit(base)
    return f"{parts.scheme}://{parts.netloc}", parts.path.rstrip("/") + path


def connect(origin: str, timeout: float) -> http.client.HTTPConnection:
    parts = urlsplit(origin)
    host = "127.0.0.1" if parts.hostname == "localhost" else parts.hostname  # CPA binds IPv4 only
    cls = http.client.HTTPSConnection if parts.scheme == "https" else http.client.HTTPConnection
    return cls(host, parts.port, timeout=timeout)


def state_path(sid: str) -> str:
    return os.path.join(STATE_DIR, f"agy_cache_{sid}.dat")


def write_state(sid: str, anchor: int, touches: int, status: str) -> None:
    path = state_path(sid)
    tmp = f"{path}.{os.getpid()}"
    with open(tmp, "w") as f:
        f.write(f"{anchor} {touches} {status}\n")
    os.replace(tmp, path)


def inspect_request(body: bytes) -> tuple[str | None, str, str, bool]:
    """The main session's id, the body's model field, a one-line shape, and whether it is /compact.

    The id is read from systemInstruction only, since contents may quote other paths.
    The shape (model, tool count, turn count, last turn) tells request kinds apart in the
    log, e.g. a compaction call from an ordinary agent step.
    """
    try:
        root = json.loads(body)
    except ValueError:
        return None, "", "", False
    request = root.get("request", root)
    sid = None
    for part in (request.get("systemInstruction") or {}).get("parts") or []:
        if match := SESSION_RE.search(part.get("text", "")):
            sid = match.group(1)
            break
    contents = request.get("contents") or []
    last = contents[-1] if contents else {}
    kinds = ",".join(sorted({key for part in last.get("parts") or [] for key in part if key != "thoughtSignature"}))
    tools = sum(len(t.get("functionDeclarations") or [1]) for t in request.get("tools") or [])
    model = str(root.get("model") or request.get("model") or "")
    compact = last.get("role") == "user" and any(
        part.get("text", "").startswith(COMPACT_PROMPT) for part in last.get("parts") or [])
    shape = (f"model={model or '-'} tools={tools} turns={len(contents)} "
             f"last={last.get('role', '-')}:{kinds or '-'} {len(body) // 1024}KB{' compact' if compact else ''}")
    return sid, model, shape, compact


def with_fresh_request_id(body: bytes) -> bytes:
    """Swap the per-request UUID in the top-level requestId; every other byte stays identical.

    agy formats it as agent/<trajectoryId>/<epochMs>/<requestUuid>/<n>, so only the last
    UUID changes and the trajectory id survives.
    """
    request_id = json.loads(body).get("requestId")
    if not isinstance(request_id, str):
        return body
    matches = list(UUID_RE.finditer(request_id))
    if not matches:
        return body
    last = matches[-1]
    fresh = request_id[:last.start()] + str(uuid.uuid4()) + request_id[last.end():]
    old = json.dumps({"requestId": request_id}, separators=(",", ":"))[1:-1].encode()
    new = json.dumps({"requestId": fresh}, separators=(",", ":"))[1:-1].encode()
    return body.replace(old, new, 1)


def new_session() -> dict:
    """One main conversation's captured turn plus its keepalive bookkeeping."""
    return {
        "lock": threading.Lock(),
        "inflight": 0,
        "seq": 0,
        "body": None,
        "anchor": 0,
        "touches": 0,
        "status": "",
        "origin": "",
        "path": "",
        "headers": {},
        # Evidenced only: usageMetadata.promptTokenCount from a forwarded response.
        "prompt_tokens": None,
        "touching": False,
    }


def note_prompt_tokens(entry: dict, chunk: bytes, carry: bytes = b"",
                       seq: int | None = None) -> bytes:
    """Record an upstream promptTokenCount from a response chunk; return the split tail.

    chunk may end mid-field, so the last 64 bytes are carried into the next call. A seq,
    when given, keeps a slow old response from overwriting a newer turn's evidence.
    """
    window = carry + chunk
    matches = list(PROMPT_TOKEN_RE.finditer(window))
    if matches:
        with sessions_lock:
            if seq is None or entry["seq"] == seq:
                entry["prompt_tokens"] = int(matches[-1].group(1))
    return window[-64:]


def eligible(entry: dict, now: float, after: float = SELF_TOUCH_AFTER) -> bool:
    """An idle, warm, evidenced-large main session whose implicit cache is about to lapse."""
    prompt = entry["prompt_tokens"]
    return (
        entry["status"] == "live"
        and entry["body"] is not None
        and entry["inflight"] == 0
        and not entry["touching"]
        and entry["touches"] < MAX_TOUCHES
        and prompt is not None
        and prompt >= MIN_PROMPT_TOKENS
        and entry["anchor"] > 0
        and after <= now - entry["anchor"] < CACHE_TTL
    )


def _self_touch(sid: str, now: float, after: float) -> None:
    try:
        code, text = touch(sid, now=now, min_age=after, require_prompt=True)
        if code != 200:
            log(f"self-touch {sid[:8]} skipped: {text}")
    except Exception as err:  # keep the scheduler alive; touch already logs transport failures
        log(f"self-touch {sid[:8]} error: {err!r}")
    finally:
        with sessions_lock:
            entry = sessions.get(sid)
            if entry is not None:
                entry["touching"] = False


def sweep_touches(now: float | None = None, after: float = SELF_TOUCH_AFTER) -> list[str]:
    """Dispatch one self-touch per due session; multiple sessions never block each other."""
    current = time.time() if now is None else now
    due: list[str] = []
    with sessions_lock:
        for sid, entry in sessions.items():
            if eligible(entry, current, after):
                entry["touching"] = True  # claimed before dispatch: one touch per idle stretch
                due.append(sid)
    for sid in due:
        worker = threading.Thread(target=_self_touch, args=(sid, current, after),
                                  name=f"agy-touch-{sid[:8]}", daemon=True)
        try:
            worker.start()
        except RuntimeError as err:
            with sessions_lock:
                entry = sessions.get(sid)
                if entry is not None:
                    entry["touching"] = False
            log(f"self-touch {sid[:8]} could not start: {err!r}")
    return due


def scheduler_loop(interval: float = SCHEDULER_INTERVAL) -> None:
    while True:
        time.sleep(interval)
        try:
            sweep_touches()
        except Exception as err:  # a scheduler bug must not kill the keepalive thread
            log(f"scheduler error: {err!r}")


def touch(sid: str, *, now: float | None = None, min_age: float = SELF_TOUCH_AFTER,
          require_prompt: bool = True) -> tuple[int, str]:
    with sessions_lock:
        entry = sessions.get(sid)
    if entry is None or entry["body"] is None:
        return 404, "no captured request"
    if not entry["lock"].acquire(blocking=False):
        return 409, "touch in flight"
    try:
        checked = time.time() if now is None else now
        with sessions_lock:
            if entry["inflight"]:
                return 409, "turn in flight"
            if entry["status"] != "live" or entry["touches"] >= MAX_TOUCHES:
                return 429, f"{entry['status']} after {entry['touches']} touches"
            if require_prompt and (entry["prompt_tokens"] is None or entry["prompt_tokens"] < MIN_PROMPT_TOKENS):
                return 409, "prompt size unknown or below keepalive threshold"
            # Recheck under the per-session lock: a statusline POST may have just replayed it.
            age = checked - entry["anchor"]
            if entry["anchor"] <= 0 or age < min_age or age >= CACHE_TTL:
                return 409, "not due"
            entry["touching"] = True
            seq, origin, path, body = entry["seq"], entry["origin"], entry["path"], entry["body"]
            # Plain text, so the first SSE event is visible without decompressing.
            headers = {k: v for k, v in entry["headers"].items() if k.lower() != "accept-encoding"}
        headers["Accept-Encoding"] = "identity"
        conn = connect(origin, timeout=120)
        sent, status, events = int(time.time()), 0, 0
        try:
            conn.request("POST", path, body=with_fresh_request_id(body), headers=headers)
            resp = conn.getresponse()
            status = resp.status
            # The first event proves prefill ran. Streams report cachedContentTokenCount only
            # in the final event, so a hit cannot be confirmed without paying for the whole
            # generation; a miss still re-writes the cache, which is what a touch is for.
            while status == 200 and not events and (chunk := resp.read1(65536)):
                events = chunk.count(b"data:")
        except (OSError, http.client.HTTPException) as err:
            log(f"touch {sid[:8]} error: {err}")
        finally:
            conn.close()  # abort generation after the first event
        with sessions_lock:
            # A real turn that began meanwhile owns the state now, whatever this touch's outcome.
            superseded = entry["seq"] != seq
            if not superseded:
                if status == 200 and events:
                    entry["touches"] += 1
                    entry["anchor"] = sent
                else:
                    entry["status"] = "fail"
                write_state(sid, entry["anchor"], entry["touches"], entry["status"])
        outcome = "superseded by a turn" if superseded else f"-> {entry['status']}"
        log(f"touch {sid[:8]} #{entry['touches']} http={status} {outcome}")
        return 200, json.dumps({"status": entry["status"], "touches": entry["touches"]})
    finally:
        with sessions_lock:
            entry["touching"] = False
        entry["lock"].release()


class Relay(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    upstream: http.client.HTTPConnection | None = None
    upstream_origin = ""

    def log_message(self, *_):
        pass

    def read_body(self) -> bytes:
        if length := self.headers.get("Content-Length"):
            return self.rfile.read(int(length))
        if "chunked" in self.headers.get("Transfer-Encoding", "").lower():
            chunks = []
            while size := int(self.rfile.readline().split(b";")[0], 16):
                chunks.append(self.rfile.read(size))
                self.rfile.readline()
            self.rfile.readline()
            return b"".join(chunks)
        return b""

    def reply(self, status: int, text: str) -> None:
        data = text.encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def relay(self) -> None:
        body = self.read_body()
        if self.command == "POST" and self.path.startswith("/_touch/"):
            return self.reply(*touch(self.path.rsplit("/", 1)[-1]))

        started = int(time.time())
        headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP_BY_HOP}
        if ":streamGenerateContent" in self.path:
            # Plain text lets the relay read usageMetadata.promptTokenCount while forwarding.
            # The CLI accepts identity; this only changes the wire encoding.
            headers["Accept-Encoding"] = "identity"
        origin, path = route(self.path)
        if self.upstream is not None and self.upstream_origin != origin:
            self.upstream.close()
            self.upstream = None
        entry, entry_seq, sid, parsed = None, None, None, False
        try:
            for _ in range(2):
                reused = self.upstream is not None
                if not reused:
                    self.upstream, self.upstream_origin = connect(origin, timeout=600), origin
                try:
                    self.upstream.request(self.command, path, body=body or None, headers=headers)
                    if not parsed:  # parse while upstream prefills, so the hot path pays nothing
                        parsed = True
                        if ":streamGenerateContent" in self.path:
                            sid, model, shape, compact = inspect_request(body)
                            if sid:
                                log(f"turn {sid[:8]} {self.path.split('?')[0].rsplit('/', 1)[-1]} {shape}")
                        if sid:
                            # Only KEEPALIVE_MODELS are worth keeping warm. The genai path names
                            # the model; Cloud Code bodies carry it in "model".
                            target = f"{self.path} {model}"
                            warm = any(m in target for m in KEEPALIVE_MODELS)
                            status = "live" if warm and not compact else "off"
                            # Register the turn: touches wait for it, and one already
                            # waiting on its first event will not commit over it.
                            with sessions_lock:
                                entry = sessions.setdefault(sid, new_session())
                                entry["inflight"] += 1
                                entry["seq"] += 1
                                entry_seq = entry["seq"]
                    resp = self.upstream.getresponse()
                    break
                except ConnectionError:
                    # Upstreams close idle keep-alive connections; retry once on a fresh one.
                    self.upstream.close()
                    self.upstream = None
                    if not reused:
                        raise
            if entry is not None and resp.status == 200:
                # Commit before streaming: the request is accepted and prefill writes the
                # cache, so even a turn the user interrupts (Esc) is the freshest prefix.
                # A rejected one (4xx/5xx) wrote nothing and leaves the previous state.
                with sessions_lock:
                    entry.update(anchor=started, touches=0, status=status, origin=origin, path=path,
                                 headers=headers, body=body if status == "live" else None,
                                 # Size evidence belongs to this turn; only its response can
                                 # confirm that the prompt is large enough to keep warm.
                                 prompt_tokens=None)
                    write_state(sid, started, 0, status)
            self.forward(resp, entry, entry_seq)
        except (OSError, http.client.HTTPException) as err:
            self.upstream = None
            log(f"relay error {self.path}: {err!r}")
            if not self.close_connection:
                self.reply(502, json.dumps({"error": str(err)}))
        finally:
            if entry is not None:
                with sessions_lock:
                    entry["inflight"] -= 1
        if os.environ.get("AGY_CACHE_RELAY_DEBUG"):
            log(f"{self.command} {self.path} {len(body)}B session={sid}")

    def forward(self, resp: http.client.HTTPResponse, entry: dict | None = None,
                seq: int | None = None) -> None:
        self.send_response(resp.status, resp.reason)
        for key, value in resp.getheaders():
            if key.lower() not in HOP_BY_HOP:
                self.send_header(key, value)
        bodiless = self.command == "HEAD" or resp.status in (204, 304)
        if not bodiless:
            self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        carry = b""
        try:
            while not bodiless and (chunk := resp.read1(65536)):
                if entry is not None and entry["seq"] == seq:
                    carry = note_prompt_tokens(entry, chunk, carry, seq)
                self.wfile.write(b"%x\r\n%s\r\n" % (len(chunk), chunk))
                self.wfile.flush()
            if not bodiless:
                self.wfile.write(b"0\r\n\r\n")
        except (OSError, http.client.HTTPException):
            # Headers are already out, so no 502: drop both sides. Closing upstream also
            # stops generation when the client went away (Esc in the TUI).
            self.upstream.close()
            self.close_connection = True
            raise
        if resp.will_close:
            self.upstream = None

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = relay


def process_alive(pid: int) -> bool:
    """True while the wrapper process is still running (POSIX and Windows)."""
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        synchronize = 0x00100000
        wait_timeout = 0x00000102
        error_access_denied = 5
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.OpenProcess(synchronize, False, pid)
        if not handle:
            # A live but protected process is still a live parent.
            return ctypes.get_last_error() == error_access_denied
        try:
            return kernel32.WaitForSingleObject(handle, 0) == wait_timeout
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def watch_parent(pid: int) -> None:
    while True:
        time.sleep(2)
        if not process_alive(pid):
            os._exit(0)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--parent", type=int, required=True, help="exit when this pid exits")
    ap.add_argument("--gemini-upstream", help="original GOOGLE_GEMINI_BASE_URL, for non-/v1internal paths")
    args = ap.parse_args()
    global gemini_upstream
    gemini_upstream = args.gemini_upstream
    sweep_state()
    server = ThreadingHTTPServer(("127.0.0.1", 0), Relay)
    server.daemon_threads = True
    threading.Thread(target=watch_parent, args=(args.parent,), daemon=True).start()
    threading.Thread(target=scheduler_loop, name="agy-cache-scheduler", daemon=True).start()
    print(server.server_port, flush=True)
    log(f"relay :{server.server_port} for pid {args.parent} gemini={gemini_upstream}")
    server.serve_forever()


if __name__ == "__main__":
    main()
