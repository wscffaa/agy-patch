#!/usr/bin/env python3
"""Cross-platform powerline statusline for agy.

`agy` writes one JSON object per refresh to this command's stdin. The shell
version (`statusline.sh`) is a zsh/jq implementation for macOS; this file is the
Windows runtime and a portable fallback. It keeps the same telemetry contract:
context usage, per-step latency/TPS, quota, subagents/tasks, and the relay's
cache countdown (`/tmp` on POSIX, the native temp dir on Windows). The relay
schedules idle touches itself, so this statusline only renders the relay's
state; it never POSTs.

No third-party packages. Any parse failure prints a compact fallback instead of
breaking the CLI's status line.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import sys
import tempfile
import time


def default_state_dir(platform: str = os.name) -> pathlib.Path:
    """Shared /tmp on POSIX (statusline.sh reads it); the native temp dir on Windows."""
    return pathlib.Path(tempfile.gettempdir() if platform == "nt" else "/tmp")


STATE_DIR = pathlib.Path(os.environ.get("AGY_CACHE_RELAY_DIR") or default_state_dir())
try:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    pass
CACHE_TTL = 300.0
ASCII = os.environ.get("AGY_STATUSLINE_ASCII") == "1"
R = "\x1b[0m"
BOLD = "\x1b[1m"
UNBOLD = "\x1b[22m"
SEP = "|" if ASCII else "\ue0b0"

DARK = {
    "ink": (17, 17, 27),
    "mauve": (203, 166, 247),
    "lavender": (180, 190, 254),
    "sapphire": (116, 199, 236),
    "sky": (137, 220, 235),
    "teal": (148, 226, 213),
    "mint": (166, 227, 161),
    "yellow": (249, 226, 175),
    "peach": (250, 179, 135),
    "pink": (245, 194, 231),
    "flamingo": (242, 205, 205),
    "rose": (243, 139, 168),
}
LIGHT = {
    "ink": (24, 25, 38),
    "mauve": (196, 155, 248),
    "lavender": (150, 172, 255),
    "sapphire": (108, 192, 242),
    "sky": (116, 212, 238),
    "teal": (108, 218, 198),
    "mint": (132, 222, 150),
    "yellow": (246, 214, 132),
    "peach": (250, 174, 122),
    "pink": (244, 158, 206),
    "flamingo": (244, 166, 178),
    "rose": (240, 118, 142),
}
GLYPH = {
    "alert": "\uf071",
    "branch": "\ue0a0",
    "shield": "\uf132",
    "globe": "\uf0ac",
    "unlock": "\uf09c",
    "bolt": "\uf0e7",
    "clock": "\uf017",
    "chip": "\uf2db",
    "db": "\uf1c0",
    "sub": "\uf0e8",
    "gear": "\uf013",
    "file": "\uf1c9",
    "inbox": "\uf01c",
    "star": "\u2726",
}
ASCII_GLYPH = {
    "alert": "!",
    "branch": "git:",
    "shield": "sbx",
    "globe": "net",
    "unlock": "open",
    "bolt": "tps",
    "clock": "t",
    "chip": "ctx",
    "db": "cache",
    "sub": "sub",
    "gear": "task",
    "file": "art",
    "inbox": "in",
    "star": "*",
}


def glyph(name: str) -> str:
    return ASCII_GLYPH[name] if ASCII else GLYPH[name]


def clean(value: object, limit: int = 40) -> str:
    text = re.sub(r"[\x00-\x1f\x7f]", " ", str(value))
    return text[:limit]


def num(value: object, default: float = 0.0) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def tokens(value: float) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{value / 1_000:.1f}k"
    return f"{value:.0f}"


def theme() -> dict[str, tuple[int, int, int]]:
    forced = os.environ.get("AGY_THEME", "").lower()
    if forced == "light":
        return LIGHT
    if forced == "dark":
        return DARK
    if os.name == "nt":
        try:
            import winreg

            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            )
            light, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return LIGHT if light else DARK
        except OSError:
            return DARK
    return DARK


def state_path(session: str) -> pathlib.Path:
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", session)
    return STATE_DIR / f"agy_telemetry_{safe}.dat"


def relay_path(session: str) -> pathlib.Path:
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", session)
    return STATE_DIR / f"agy_cache_{safe}.dat"


def read_state(path: pathlib.Path) -> dict:
    try:
        parts = path.read_text().split()
    except OSError:
        return {}
    keys = ("prev_state", "start_time", "base_out", "last_tps", "step_lat", "last_delta", "resp_model", "model_key", "cache_ts")
    return dict(zip(keys, parts)) if parts else {}


def read_relay(path: pathlib.Path) -> dict:
    """Relay state is `ANCHOR_TS TOUCHES STATUS`, not the telemetry tuple."""
    try:
        parts = path.read_text().split()
    except OSError:
        return {}
    if len(parts) < 3:
        return {}
    return {"anchor": parts[0], "touches": parts[1], "status": parts[2]}


def write_state(path: pathlib.Path, values: dict) -> None:
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(" ".join(str(values.get(k, "")) for k in (
            "prev_state", "start_time", "base_out", "last_tps", "step_lat", "last_delta", "resp_model", "model_key", "cache_ts"
        )) + "\n")
        os.replace(tmp, path)
    except OSError:
        pass


def metrics(data: dict) -> dict:
    now = time.time()
    session = clean(data.get("session_id") or data.get("conversation_id") or "default", 80)
    state = clean(data.get("agent_state") or "idle", 24)
    model = data.get("model") or {}
    model_name = clean(model.get("display_name") or model.get("id") or "Model", 36)
    effort = clean(model.get("effort") or "", 12)
    context = data.get("context_window") or {}
    usage = context.get("current_usage") or {}
    real_in = num(usage.get("input_tokens")) + num(usage.get("cache_read_input_tokens"))
    window = num(context.get("context_window_size"))
    used_pct = real_in * 100.0 / window if real_in > 0 and window > 0 else num(context.get("used_percentage"))
    total_out = num(context.get("total_output_tokens"))
    current_out = num(usage.get("output_tokens"))
    confirm = data.get("tool_confirmation_pending") is True

    previous = read_state(state_path(session))
    prev_state = previous.get("prev_state", "idle")
    try:
        start_time = float(previous.get("start_time", now))
    except ValueError:
        start_time = now
    try:
        base_out = float(previous.get("base_out", total_out))
    except ValueError:
        base_out = total_out
    last_tps = previous.get("last_tps", "--")
    step_lat = previous.get("step_lat", "--")
    try:
        cache_ts = float(previous.get("cache_ts", 0))
    except ValueError:
        cache_ts = 0.0
    if total_out < base_out:
        base_out = total_out
    elif prev_state == "idle" and state != "idle":
        start_time, base_out = now, total_out
    elif prev_state == "idle" and state == "idle" and base_out == 0 and total_out > 0:
        base_out = total_out

    delta = total_out - base_out
    if delta > 0:
        if current_out > 0 and delta > current_out and prev_state == "idle":
            delta = current_out
        dt = max(now - start_time, 0.05)
        tps = delta / dt
        last_tps = f"{tps:.0f}" if tps >= 100 else f"{tps:.1f}"
        step_lat = f"{dt:.1f}s"
        start_time, base_out, cache_ts = now, total_out, now
    elif confirm:
        start_time = now
    elif state != "idle":
        cache_ts = now

    relay = read_relay(relay_path(session))
    if relay:
        try:
            cache_ts = float(relay.get("anchor", cache_ts))
        except ValueError:
            pass
    if cache_ts == 0 and total_out > 0:
        cache_ts = now

    write_state(state_path(session), {
        "prev_state": state,
        "start_time": int(start_time),
        "base_out": int(base_out),
        "last_tps": last_tps,
        "step_lat": step_lat,
        "last_delta": int(delta),
        "resp_model": model_name.replace(" ", "_"),
        "model_key": model_name.replace(" ", "_"),
        "cache_ts": int(cache_ts),
    })

    quota = data.get("quota")
    quota_pct = -1.0
    if isinstance(quota, dict) and quota:
        remaining = [
            num(entry.get("remaining_fraction")) * 100.0
            for entry in quota.values()
            if isinstance(entry, dict) and entry.get("disabled") is not True and entry.get("remaining_fraction") is not None
        ]
        if remaining:
            quota_pct = min(remaining)

    return {
        "session": session,
        "state": state,
        "mode": clean(data.get("execution_mode") or data.get("cycle_mode") or "", 24),
        "model": model_name,
        "effort": effort,
        "cwd": clean(data.get("cwd") or (data.get("workspace") or {}).get("current_dir") or "", 80),
        "branch": clean((data.get("vcs") or {}).get("branch") or (data.get("vcs") or {}).get("client") or "", 32),
        "dirty": (data.get("vcs") or {}).get("dirty") is True,
        "sandbox": (data.get("sandbox") or {}).get("enabled") is True,
        "network": (data.get("sandbox") or {}).get("allow_network") is True,
        "used_pct": used_pct,
        "total_in": num(context.get("total_input_tokens")),
        "total_out": total_out,
        "cache_read": num(usage.get("cache_read_input_tokens")),
        "tps": last_tps,
        "step_lat": step_lat,
        "quota": quota_pct,
        "subagents": len(data.get("subagents") or []) if isinstance(data.get("subagents"), list) else 0,
        "subagents_running": sum(
            1 for item in data.get("subagents") or []
            if isinstance(item, dict) and item.get("status") in ("running", "working", "thinking")
        ) if isinstance(data.get("subagents"), list) else 0,
        "tasks": int(num(data.get("task_count"))),
        "artifacts": int(num(data.get("artifact_count"))),
        "pending": int(num(data.get("pending_input_count"))),
        "confirm": confirm,
        "cache_ts": cache_ts,
        "relay": relay,
    }


def segments(m: dict, palette: dict[str, tuple[int, int, int]]) -> list[tuple[tuple[int, int, int], str]]:
    segs: list[tuple[tuple[int, int, int], str]] = []
    if m["confirm"]:
        segs.append((palette["rose"], f"{BOLD}{glyph('alert')} ACT{UNBOLD}"))
    mode = m["mode"].lower()
    if mode:
        if "accept" in mode or "edit" in mode:
            segs.append((palette["mint"], "edits"))
        elif "plan" in mode:
            segs.append((palette["sky"], "plan"))
        elif "auto" in mode:
            segs.append((palette["peach"], "auto"))
        elif "yolo" in mode:
            segs.append((palette["rose"], "yolo"))
        else:
            segs.append((palette["mauve"], "ask"))
    model = m["model"]
    if m["effort"]:
        model += f" · {m['effort']}"
    segs.append((palette["lavender"], f"{BOLD}{model}{UNBOLD}"))
    if m["sandbox"]:
        segs.append((palette["peach"] if m["network"] else palette["sapphire"], glyph("globe") if m["network"] else glyph("shield")))
    else:
        segs.append((palette["rose"], glyph("unlock")))
    if m["branch"]:
        segs.append((palette["sky"], f"{glyph('branch')} {m['branch']}{'*' if m['dirty'] else ''}"))
    if m["used_pct"] > 0:
        segs.append((palette["teal"], f"{glyph('chip')} {m['used_pct']:.0f}%"))
    if m["total_in"] or m["total_out"]:
        segs.append((palette["yellow"], f"{glyph('clock')} {m['step_lat']} {glyph('bolt')} {m['tps']}"))
    if m["quota"] >= 0:
        segs.append((palette["mint"] if m["quota"] >= 30 else palette["peach"] if m["quota"] >= 10 else palette["rose"], f"Q {m['quota']:.0f}%"))
    if m["relay"]:
        status = m["relay"].get("status", "")
        touches = int(num(m["relay"].get("touches"), 0))
        remaining = max(0.0, CACHE_TTL - (time.time() - m["cache_ts"]))
        mark = f"↻{touches}" if touches else "↻"
        if status == "fail":
            mark = "✗"
        elif status == "off":
            mark = "·"
        segs.append((palette["pink"], f"{glyph('db')} {mark} {int(remaining // 60)}m{int(remaining % 60):02d}s"))
    if m["subagents"]:
        segs.append((palette["flamingo"], f"{glyph('sub')} {m['subagents_running']}/{m['subagents']}"))
    if m["tasks"]:
        segs.append((palette["mauve"], f"{glyph('gear')} {m['tasks']}"))
    if m["artifacts"]:
        segs.append((palette["sapphire"], f"{glyph('file')} {m['artifacts']}"))
    if m["pending"]:
        segs.append((palette["peach"], f"{glyph('inbox')} {m['pending']}"))
    return segs


def render(segs: list[tuple[tuple[int, int, int], str]]) -> str:
    if not segs:
        return ""
    out = []
    for index, (bg, text) in enumerate(segs):
        out.append(f"\x1b[48;2;{bg[0]};{bg[1]};{bg[2]}m\x1b[38;2;{DARK['ink'][0]};{DARK['ink'][1]};{DARK['ink'][2]}m {text} ")
        if index + 1 < len(segs):
            next_bg = segs[index + 1][0]
            out.append(f"\x1b[38;2;{bg[0]};{bg[1]};{bg[2]}m\x1b[48;2;{next_bg[0]};{next_bg[1]};{next_bg[2]}m{SEP}")
        else:
            out.append(f"\x1b[0m\x1b[38;2;{bg[0]};{bg[1]};{bg[2]}m{SEP}{R}")
    return "".join(out)


def main() -> int:
    # The Windows console may default to GBK/CP1252; the bar is UTF-8 (Nerd Font glyphs).
    for stream in (sys.stdin, sys.stdout):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
        if not isinstance(data, dict):
            data = {}
        palette = theme()
        m = metrics(data)
        print(render(segments(m, palette)), flush=True)
    except Exception:
        print(f"{glyph('star')} agy", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
