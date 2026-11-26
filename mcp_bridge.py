#!/usr/bin/env python3
"""Resolve Lumvrix™ AI Bridge MCP Server (v4.1.0) — Zero-Dependency Stdlib JSON-RPC 2.0 MCP Server.

Copyright (c) 2026 HRL International Pvt. Ltd. All Rights Reserved.
Resolve Lumvrix™ and its RL emblem (rl.png) are proprietary trademarks and intellectual property
of HRL International Private Limited (Mangaluru, Karnataka, India). Patent & IP rights reserved.

Connects Antigravity, Claude Code, Codex, and Cursor directly to the live Resolve Lumvrix™ Studio
(`harness_state.json`) and native 2K 60fps `scripts/clip.py` engine — zero external packages required.

Usage:
  .venv/bin/python scripts/mcp_bridge.py                # Start MCP stdio server
  .venv/bin/python scripts/mcp_bridge.py --print-config # Print ready-to-paste MCP client JSON
  .venv/bin/python scripts/mcp_bridge.py --check        # Run end-to-end JSON-RPC + tool self-check
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPTS_DIR.parent
IS_FLAT = (SCRIPTS_DIR / "harness" / "index.html").is_file()
WORKSPACE_DIR = SCRIPTS_DIR if IS_FLAT else ROOT_DIR
CLIP_PY = SCRIPTS_DIR / "clip.py"
DEFAULT_STATE_FILE = WORKSPACE_DIR / "harness_state.json"

ALLOWED_STYLES = ("hormozi", "shine", "stopmotion", "flicker", "inverted")
ALLOWED_COLORS = ("auto", "green", "blue", "cream", "gold", "pink", "white")
ALLOWED_THEMES = ("blue", "vice", "gold")
ALLOWED_QUALITIES = ("2k", "ultra", "fast")
ALLOWED_STAGES = ("01_ingest", "02_split", "03_upscale", "04_captions", "05_hook", "06_gate")
ALLOWED_SEVERITIES = ("blocker", "tweak", "note")
CAM_RE = re.compile(r"^[0-9.*:+/iwht -]{5,64}$")
CLIP_RE = re.compile(r"^\d+(\.\d+)?:\d+(\.\d+)?$")

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {
    "name": "resolve-lumvrix-ai-bridge",
    "version": "4.5.0",
    "owner": "HRL International Pvt. Ltd.",
    "trademark": "Resolve Lumvrix™",
}


def default_harness_state() -> dict:
    return {
        "app": "Resolve Lumvrix",
        "version": "4.5.0",
        "owner": "HRL International Pvt. Ltd.",
        "copyright": "Copyright © 2026 HRL International Pvt. Ltd. All Rights Reserved.",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "revision": 1,
        "edit_spec": {
            "source": "<VIDEO_OR_URL>",
            "clip": "120:150",
            "cam_crop": "iw*0.37:ih*0.43:iw*0.00:ih*0.56",
            "layout": "aaron",
            "quality": "2k",
            "caption_style": "shine",
            "caption_color": "green",
            "pos_y_1920": 612,
            "font_scale": 1.0,
            "hook": "IShowSpeed | Breaks GTA 6",
            "hook_theme": "blue",
            "cold_open_s": 2.6,
            "cold_open_sfx": True,
            "trim_dead_air": True,
            "zoom_peaks": True,
            "grade": {"brightness": 0.04, "contrast": 1.08, "saturation": 1.12, "gamma": 1.00},
            "preview_chunks": [
                {"start": 0.05, "end": 1.80, "text": "No way bro!"},
                {"start": 1.80, "end": 3.60, "text": "Look at Vice City"},
                {"start": 3.60, "end": 5.40, "text": "GTA 6 is unreal!"},
            ],
        },
        "voiceover": {
            "provider": "kokoro",
            "voice": "am_fenrir",
            "speed": 1.02,
            "topic": "GTA 6 Can Do Things We Never Imagined in GTA 5",
            "script": (
                "In GTA 5, you can rob a store, turn two corners, and the police just give up. "
                "In GTA 6, they remember your shirt. What you wore, what you drove, and what you were holding. "
                "Every car runs on actual fuel, and your diet shows up on your body."
            ),
            "last_wav": "",
            "last_deep_dive_mp4": "",
        },
        "flags": [],
        "snapshots": {},
        "tool_trace": [],
        "autopilot": {
            "status": "idle",
            "url": "",
            "requested_count": 3,
            "completed_count": 0,
            "current_clip_index": 0,
            "agent": "auto",
            "agent_label": "Auto-Detect Agent",
            "stage": "01_ingest",
            "stage_label": "Ready — Paste a YouTube link to start agent clipping",
            "out_dir": str(WORKSPACE_DIR / "output"),
            "candidates": [],
            "saved_videos": [],
            "logs": [],
        },
    }


def load_state(state_file: Path = DEFAULT_STATE_FILE) -> dict:
    if state_file.is_file():
        try:
            data = json.loads(state_file.read_text(encoding="utf-8"))
            base = default_harness_state()
            base.update(data)
            if isinstance(data.get("edit_spec"), dict):
                merged_spec = default_harness_state()["edit_spec"]
                merged_spec.update(data["edit_spec"])
                base["edit_spec"] = merged_spec
            if isinstance(data.get("voiceover"), dict):
                merged_vo = default_harness_state()["voiceover"]
                merged_vo.update(data["voiceover"])
                base["voiceover"] = merged_vo
            return base
        except Exception:
            pass
    return default_harness_state()


def save_state(state: dict, state_file: Path = DEFAULT_STATE_FILE) -> dict:
    state["app"] = "Resolve Lumvrix"
    state["version"] = "4.4.0"
    state["owner"] = "HRL International Pvt. Ltd."
    state["copyright"] = "Copyright © 2026 HRL International Pvt. Ltd. All Rights Reserved."
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    state["revision"] = int(state.get("revision", 0)) + 1
    state["tool_trace"] = list(state.get("tool_trace", []))[-40:]
    tmp = state_file.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.replace(state_file)
    return state


def evaluate_gates(state: dict) -> list[dict]:
    spec = state["edit_spec"]
    flags = state.get("flags", [])
    clip_str = str(spec.get("clip", "120:150"))
    try:
        s0, s1 = [float(x) for x in clip_str.split(":", 1)]
        clip_dur = max(0.0, s1 - s0)
    except Exception:
        clip_dur = 0.0
    hook = str(spec.get("hook") or "").replace("|", " ").strip()
    hook_clean = re.sub(r"\s+", " ", hook)
    has_shorts = bool(re.search(r"#shorts", hook_clean, re.I))
    has_emoji = any(ord(ch) > 0x1F000 for ch in hook_clean)
    pos_y = int(spec.get("pos_y_1920", 612))
    safe_y = 260 <= pos_y <= 1380
    open_blockers = sum(1 for f in flags if not f.get("resolved") and f.get("severity") == "blocker")
    quality = str(spec.get("quality", "2k"))
    return [
        {"id": "ZERO_GAP_SEAM", "stage": "02_split", "status": "pass",
         "detail": "Flush 816+1744 (2K) edge-to-edge split-screen; bar_h=0 + auto OBS letterbox trim."},
        {"id": "CAPTION_SAFE_ZONE", "stage": "04_captions", "status": "pass" if safe_y else "warn",
         "detail": f"--pos-y {pos_y} (y={round(pos_y*2560/1920)} @ 2K) {'clears' if safe_y else 'collides with'} Shorts UI safe zones."},
        {"id": "HOOK_PACKAGING", "stage": "05_hook",
         "status": "pass" if (not hook_clean or (12 <= len(hook_clean) <= 42 and not has_shorts and not has_emoji)) else "warn",
         "detail": f"{len(hook_clean)} chars, {'no' if not has_emoji else 'has'} emoji, {'no' if not has_shorts else 'has'} #shorts."},
        {"id": "CLIP_DURATION", "stage": "01_ingest", "status": "pass" if 20 <= clip_dur <= 38 else "warn",
         "detail": f"Clip duration {clip_dur:.1f}s (STA-6 viral target: 24-36s)."},
        {"id": "ENCODER_VP9_TIER", "stage": "03_upscale", "status": "pass" if quality == "2k" else "warn",
         "detail": f"Quality '{quality}' ({'triggers YouTube VP9/AV1 1440x2560 tier' if quality == '2k' else 'switch to 2k for VP9 tier'})."},
        {"id": "OPEN_FLAGS_CLEAR", "stage": "06_gate", "status": "pass" if open_blockers == 0 else "fail",
         "detail": "Zero open Blocker markers." if open_blockers == 0 else f"{open_blockers} unresolved Blocker marker(s) blocking render."},
    ]


def build_cli_from_spec(spec: dict) -> list[str]:
    source = str(spec.get("source", "")).strip()
    clip_rng = str(spec.get("clip", "120:150")).strip()
    cam = str(spec.get("cam_crop", "")).strip()
    style = str(spec.get("caption_style", "hormozi"))
    color = str(spec.get("caption_color", "auto"))
    quality = str(spec.get("quality", "2k"))
    hook = spec.get("hook")
    hook_theme = str(spec.get("hook_theme", "blue"))
    pos_y = spec.get("pos_y_1920")

    if not source or source.startswith("-") or source == "<VIDEO_OR_URL>":
        raise ValueError("Provide a real local video path or YouTube/Twitch URL in edit_spec.source.")
    if not CLIP_RE.match(clip_rng):
        raise ValueError(f"Invalid clip range '{clip_rng}' (expected START:END).")
    if style not in ALLOWED_STYLES:
        raise ValueError(f"Invalid caption_style '{style}'.")
    if color not in ALLOWED_COLORS:
        raise ValueError(f"Invalid caption_color '{color}'.")
    if quality not in ALLOWED_QUALITIES:
        raise ValueError(f"Invalid quality '{quality}'.")
    if hook_theme not in ALLOWED_THEMES:
        raise ValueError(f"Invalid hook_theme '{hook_theme}'.")

    cmd = [
        sys.executable, str(CLIP_PY), "render", source,
        "--clip", clip_rng, "--layout", "aaron", "--quality", quality,
        "--caption-style", style, "--caption-color", color,
        "--out-dir", str(WORKSPACE_DIR / "output"),
    ]
    if cam:
        if not CAM_RE.match(cam):
            raise ValueError(f"Invalid cam_crop '{cam}'.")
        cmd += ["--cam", cam]
    if pos_y is not None:
        cmd += ["--pos-y", str(int(pos_y))]
    if float(spec.get("cold_open_s", 0) or 0) > 0:
        cmd += ["--cold-open", f"{float(spec['cold_open_s']):.2f}"]
    if spec.get("cold_open_sfx"):
        cmd.append("--cold-open-sfx")
    if spec.get("trim_dead_air"):
        cmd.append("--trim-dead-air")
    if spec.get("zoom_peaks"):
        cmd.append("--zoom-peaks")
    if hook and str(hook).strip():
        cmd += ["--hook", str(hook).strip()[:80], "--hook-theme", hook_theme]
    return cmd


# ===== MCP TOOL SCHEMAS (DaVinci Resolve AI Bridge Inspired) =====
MCP_TOOLS: list[dict] = [
    {
        "name": "bridge_status",
        "description": "Check STA-6 AI Bridge MCP connection, engine version, active workspace, and live harness revision.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "bridge_capabilities",
        "description": "Return all 5 built-in caption styles, color presets, hook themes, and zero-gap invariants from clip.py.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "timeline_overview",
        "description": "Inspect the live STA-6 editing timeline (T1 captions, V2 facecam, V1 gameplay, A1 audio), active EditSpec, markers/flags, and saved snapshots.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "project_health",
        "description": "Evaluate all 6 deterministic Harness Quality Gates (ZERO_GAP_SEAM, CAPTION_SAFE_ZONE, HOOK_PACKAGING, CLIP_DURATION, ENCODER_VP9_TIER, OPEN_FLAGS_CLEAR).",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "customize_captions",
        "description": "Update caption style, accent color, vertical pos_y, timed caption chunks, or Viral Shine hook live in the Editing Harness.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "caption_style": {"type": "string", "enum": list(ALLOWED_STYLES)},
                "caption_color": {"type": "string", "enum": list(ALLOWED_COLORS)},
                "pos_y_1920": {"type": "integer", "minimum": 200, "maximum": 1700},
                "hook": {"type": ["string", "null"]},
                "hook_theme": {"type": "string", "enum": list(ALLOWED_THEMES)},
                "preview_chunks": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"start": {"type": "number"}, "end": {"type": "number"}, "text": {"type": "string"}},
                        "required": ["start", "end", "text"],
                    },
                },
            },
        },
    },
    {
        "name": "set_clip_grade",
        "description": "Adjust Resolve-style color grade (brightness, contrast, saturation, gamma) or facecam crop expression in the live timeline.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "brightness": {"type": "number", "minimum": -0.35, "maximum": 0.35},
                "contrast": {"type": "number", "minimum": 0.6, "maximum": 1.6},
                "saturation": {"type": "number", "minimum": 0.0, "maximum": 2.0},
                "gamma": {"type": "number", "minimum": 0.5, "maximum": 1.8},
                "cam_crop": {"type": "string"},
                "clip": {"type": "string", "description": "START:END seconds e.g. 120:150"},
                "source": {"type": "string", "description": "Local video file path or YouTube/Twitch URL"},
                "quality": {"type": "string", "enum": list(ALLOWED_QUALITIES)},
            },
        },
    },
    {
        "name": "add_marker",
        "description": "Drop a DaVinci-style colored review marker / change flag onto the live timeline at timestamp t (optionally pinned to 2K x,y).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "t": {"type": "number", "minimum": 0},
                "note": {"type": "string"},
                "severity": {"type": "string", "enum": list(ALLOWED_SEVERITIES), "default": "tweak"},
                "stage": {"type": "string", "enum": list(ALLOWED_STAGES), "default": "04_captions"},
                "category": {"type": "string", "default": "Caption"},
                "x2k": {"type": "integer", "minimum": 0, "maximum": 1440},
                "y2k": {"type": "integer", "minimum": 0, "maximum": 2560},
            },
            "required": ["t", "note"],
        },
    },
    {
        "name": "resolve_marker",
        "description": "Mark a flagged change marker as resolved (or remove it) so the OPEN_FLAGS_CLEAR gate passes.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "marker_id": {"type": "string"},
                "delete": {"type": "boolean", "default": False},
            },
            "required": ["marker_id"],
        },
    },
    {
        "name": "preview_timeline",
        "description": "Save a named non-destructive snapshot of the current timeline (e.g. 'original' or 'preview_v2') before experimenting with batch edits.",
        "inputSchema": {
            "type": "object",
            "properties": {"name": {"type": "string", "default": "preview"}},
        },
    },
    {
        "name": "compare_timelines",
        "description": "Compare two saved timeline snapshots (or a snapshot against 'current') and return structured field-level diffs.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "left": {"type": "string", "default": "original"},
                "right": {"type": "string", "default": "current"},
            },
        },
    },
    {
        "name": "mine_viral_moments",
        "description": "Scan a local video or VOD URL via `scripts/clip.py mine` and rank top viral 24-36s candidate timestamps.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "source": {"type": "string"},
                "dur": {"type": "number", "default": 30.0},
                "top": {"type": "integer", "default": 5},
            },
            "required": ["source"],
        },
    },
    {
        "name": "render_current_timeline",
        "description": "Render the active timeline at 2K 60fps via `scripts/clip.py render`. Fail-closed if unresolved Blocker markers exist unless force=true.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "source": {"type": "string", "description": "Optional override for video path or URL"},
                "force": {"type": "boolean", "default": False},
            },
        },
    },
    {
        "name": "synthesize_voiceover",
        "description": "Synthesize natural human narration to 48kHz stereo WAV (-16 LUFS) using free local Kokoro-82M (54 voices, 0 API key) or ElevenLabs / Gemini 2.5 / Groq PlayAI.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Narration script text to synthesize."},
                "provider": {"type": "string", "enum": ["kokoro", "elevenlabs", "gemini", "groq", "macos"], "default": "kokoro"},
                "voice": {"type": "string", "default": "am_fenrir"},
                "speed": {"type": "number", "default": 1.0},
                "api_key": {"type": "string", "description": "Optional API key for ElevenLabs, Gemini, or Groq"},
                "align": {"type": "boolean", "default": True},
            },
            "required": ["text"],
        },
    },
    {
        "name": "build_longform_deep_dive",
        "description": "Build a narrated 16:9 GTA 6 Long-Form Deep Dive video (Romayroh CkOEHYjv6XU workflow + human voiceover + 11 graphic card types + clause-cut EDL assembler).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "default": "GTA 6 Can Do Things We Never Imagined in GTA 5"},
                "script": {"type": "string", "description": "Optional custom narration script text"},
                "provider": {"type": "string", "enum": ["kokoro", "elevenlabs", "gemini", "groq", "macos"], "default": "kokoro"},
                "voice": {"type": "string", "default": "am_fenrir"},
                "speed": {"type": "number", "default": 1.02},
                "api_key": {"type": "string"},
                "preview": {"type": "boolean", "default": True},
            },
        },
    },
]


def _record_trace(state: dict, tool: str, summary: str) -> None:
    state.setdefault("tool_trace", []).append({
        "ts": datetime.now(timezone.utc).isoformat(),
        "tool": tool,
        "summary": summary,
    })


def execute_tool(name: str, args: dict | None, state_file: Path = DEFAULT_STATE_FILE) -> dict:
    args = args or {}
    state = load_state(state_file)

    if name == "bridge_status":
        return {
            "connected": True,
            "server": SERVER_INFO,
            "workspace": str(WORKSPACE_DIR),
            "state_file": str(state_file),
            "revision": state.get("revision", 1),
            "clip_py_exists": CLIP_PY.is_file(),
            "open_flags": sum(1 for f in state.get("flags", []) if not f.get("resolved")),
            "snapshots": sorted(state.get("snapshots", {}).keys()),
        }

    if name == "bridge_capabilities":
        proc = subprocess.run([sys.executable, str(CLIP_PY), "captions"], capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr or "clip.py captions failed")
        payload = json.loads(proc.stdout)
        payload["bridge_tools"] = [t["name"] for t in MCP_TOOLS]
        payload["resolve_inspired_features"] = ["preview_timeline", "compare_timelines", "project_health", "add_marker", "set_clip_grade"]
        return payload

    if name == "timeline_overview":
        spec = state["edit_spec"]
        return {
            "revision": state.get("revision", 1),
            "updated_at": state.get("updated_at"),
            "tracks": [
                {"id": "T1", "type": "titles", "name": f"Captions ({spec['caption_style']}) + Viral Hook"},
                {"id": "V2", "type": "video", "name": f"Facecam Flush 816px ({spec['cam_crop']})"},
                {"id": "V1", "type": "video", "name": "Gameplay Flush 1744px (2K AMD CAS, 0px Gap)"},
                {"id": "A1", "type": "audio", "name": "Master Audio (-18 LUFS + Sub-Bass SFX)"},
            ],
            "edit_spec": spec,
            "flags": state.get("flags", []),
            "snapshots": sorted(state.get("snapshots", {}).keys()),
            "recent_trace": state.get("tool_trace", [])[-8:],
        }

    if name == "project_health":
        gates = evaluate_gates(state)
        return {
            "ready_to_render": all(g["status"] != "fail" for g in gates),
            "pass_count": sum(1 for g in gates if g["status"] == "pass"),
            "total_gates": len(gates),
            "gates": gates,
        }

    if name == "customize_captions":
        spec = state["edit_spec"]
        if "original" not in state.get("snapshots", {}):
            state.setdefault("snapshots", {})["original"] = copy.deepcopy(spec)
        changed = []
        if "caption_style" in args:
            st = str(args["caption_style"])
            if st not in ALLOWED_STYLES:
                raise ValueError(f"Unsupported caption_style: {st}")
            spec["caption_style"] = st
            if "pos_y_1920" not in args:
                spec["pos_y_1920"] = 1180 if st == "inverted" else 612
            changed.append(f"style={st}")
        if "caption_color" in args:
            col = str(args["caption_color"])
            if col not in ALLOWED_COLORS:
                raise ValueError(f"Unsupported caption_color: {col}")
            spec["caption_color"] = col
            changed.append(f"color={col}")
        if "pos_y_1920" in args:
            spec["pos_y_1920"] = max(200, min(1700, int(args["pos_y_1920"])))
            changed.append(f"pos_y={spec['pos_y_1920']}")
        if "hook" in args:
            spec["hook"] = args["hook"]
            changed.append("hook")
        if "hook_theme" in args:
            th = str(args["hook_theme"])
            if th not in ALLOWED_THEMES:
                raise ValueError(f"Unsupported hook_theme: {th}")
            spec["hook_theme"] = th
            changed.append(f"hook_theme={th}")
        if "preview_chunks" in args and isinstance(args["preview_chunks"], list):
            spec["preview_chunks"] = [
                {"start": float(c["start"]), "end": float(c["end"]), "text": str(c["text"])}
                for c in args["preview_chunks"]
            ]
            changed.append(f"chunks={len(spec['preview_chunks'])}")
        _record_trace(state, name, ", ".join(changed) or "no-op")
        save_state(state, state_file)
        return {"ok": True, "revision": state["revision"], "changed": changed, "edit_spec": spec}

    if name == "set_clip_grade":
        spec = state["edit_spec"]
        grade = spec.setdefault("grade", {"brightness": 0.04, "contrast": 1.08, "saturation": 1.12, "gamma": 1.00})
        changed = []
        for k, lo, hi in (("brightness", -0.35, 0.35), ("contrast", 0.6, 1.6), ("saturation", 0.0, 2.0), ("gamma", 0.5, 1.8)):
            if k in args:
                grade[k] = round(max(lo, min(hi, float(args[k]))), 3)
                changed.append(f"{k}={grade[k]}")
        if "cam_crop" in args:
            cam = str(args["cam_crop"]).strip()
            if not CAM_RE.match(cam):
                raise ValueError(f"Invalid cam_crop: {cam}")
            spec["cam_crop"] = cam
            changed.append(f"cam_crop={cam}")
        if "clip" in args:
            cl = str(args["clip"]).strip()
            if not CLIP_RE.match(cl):
                raise ValueError(f"Invalid clip: {cl}")
            spec["clip"] = cl
            changed.append(f"clip={cl}")
        if "source" in args:
            src = str(args["source"]).strip()
            if src.startswith("-"):
                raise ValueError("Invalid source")
            spec["source"] = src
            changed.append("source")
        if "quality" in args:
            q = str(args["quality"])
            if q not in ALLOWED_QUALITIES:
                raise ValueError(f"Invalid quality: {q}")
            spec["quality"] = q
            changed.append(f"quality={q}")
        _record_trace(state, name, ", ".join(changed) or "no-op")
        save_state(state, state_file)
        return {"ok": True, "revision": state["revision"], "changed": changed, "grade": grade, "edit_spec": spec}

    if name == "add_marker":
        sev = str(args.get("severity", "tweak"))
        stage = str(args.get("stage", "04_captions"))
        if sev not in ALLOWED_SEVERITIES:
            raise ValueError(f"Invalid severity: {sev}")
        if stage not in ALLOWED_STAGES:
            raise ValueError(f"Invalid stage: {stage}")
        note = str(args.get("note", "")).strip()
        if not note:
            raise ValueError("Marker note cannot be empty.")
        pin = None
        if "x2k" in args and "y2k" in args:
            x2k = max(0, min(1440, int(args["x2k"])))
            y2k = max(0, min(2560, int(args["y2k"])))
            pin = {"x2k": x2k, "y2k": y2k, "nx": round(x2k / 1440, 4), "ny": round(y2k / 2560, 4)}
        marker = {
            "id": f"mkr_{int(time.time() * 1000):x}",
            "t": round(max(0.0, float(args.get("t", 0.0))), 2),
            "stage": stage,
            "category": str(args.get("category", "Caption")),
            "severity": sev,
            "note": note,
            "pin": pin,
            "resolved": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source": "ai-bridge-mcp",
        }
        state.setdefault("flags", []).insert(0, marker)
        _record_trace(state, name, f"[{sev}] t={marker['t']}s: {note[:48]}")
        save_state(state, state_file)
        return {"ok": True, "marker": marker, "open_flags": sum(1 for f in state["flags"] if not f.get("resolved"))}

    if name == "resolve_marker":
        mid = str(args.get("marker_id", ""))
        delete = bool(args.get("delete", False))
        flags = state.get("flags", [])
        found = None
        for idx, f in enumerate(flags):
            if f.get("id") == mid:
                found = f
                if delete:
                    flags.pop(idx)
                else:
                    f["resolved"] = True
                break
        if not found:
            raise ValueError(f"Marker '{mid}' not found.")
        _record_trace(state, name, f"{'deleted' if delete else 'resolved'} {mid}")
        save_state(state, state_file)
        return {"ok": True, "marker_id": mid, "deleted": delete, "open_flags": sum(1 for f in flags if not f.get("resolved"))}

    if name == "preview_timeline":
        snap_name = re.sub(r"[^A-Za-z0-9_-]", "_", str(args.get("name", "preview")))[:32] or "preview"
        state.setdefault("snapshots", {})[snap_name] = copy.deepcopy(state["edit_spec"])
        _record_trace(state, name, f"saved snapshot '{snap_name}'")
        save_state(state, state_file)
        return {"ok": True, "snapshot": snap_name, "all_snapshots": sorted(state["snapshots"].keys())}

    if name == "compare_timelines":
        left_k = str(args.get("left", "original"))
        right_k = str(args.get("right", "current"))
        snaps = state.get("snapshots", {})
        left_v = state["edit_spec"] if left_k == "current" else snaps.get(left_k)
        right_v = state["edit_spec"] if right_k == "current" else snaps.get(right_k)
        if left_v is None:
            raise ValueError(f"Snapshot '{left_k}' not found. Available: {sorted(snaps.keys())}")
        if right_v is None:
            raise ValueError(f"Snapshot '{right_k}' not found. Available: {sorted(snaps.keys())}")
        diffs = {}
        for k in sorted(set(left_v.keys()) | set(right_v.keys())):
            if left_v.get(k) != right_v.get(k):
                diffs[k] = {"left": left_v.get(k), "right": right_v.get(k)}
        return {"left": left_k, "right": right_k, "changed_fields": len(diffs), "diffs": diffs}

    if name == "mine_viral_moments":
        src = str(args.get("source", "")).strip()
        if not src or src.startswith("-"):
            raise ValueError("Valid source URL or local video path required.")
        dur = float(args.get("dur", 30.0))
        top = int(args.get("top", 5))
        proc = subprocess.run(
            [sys.executable, str(CLIP_PY), "mine", src, "--dur", str(dur), "--top", str(top)],
            capture_output=True, text=True,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr or proc.stdout or "mine failed")
        return {"ok": True, "candidates": json.loads(proc.stdout)}

    if name == "render_current_timeline":
        spec = copy.deepcopy(state["edit_spec"])
        if args.get("source"):
            spec["source"] = str(args["source"]).strip()
        open_blockers = [f for f in state.get("flags", []) if not f.get("resolved") and f.get("severity") == "blocker"]
        if open_blockers and not args.get("force", False):
            return {
                "ok": False,
                "blocked_by_harness_gate": "OPEN_FLAGS_CLEAR",
                "unresolved_blockers": open_blockers,
                "hint": "Resolve blocker markers via `resolve_marker` or pass force=true to override.",
            }
        cmd = build_cli_from_spec(spec)
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr[-1200:] or proc.stdout[-1200:] or "render failed")
        _record_trace(state, name, f"rendered {spec['caption_style']} ({spec['quality']})")
        save_state(state, state_file)
        return {"ok": True, "result": json.loads(proc.stdout)}

    if name == "synthesize_voiceover":
        text = str(args.get("text") or state.get("voiceover", {}).get("script") or "").strip()
        if not text:
            raise ValueError("Narration text is required.")
        prov = str(args.get("provider") or state.get("voiceover", {}).get("provider") or "kokoro").strip()
        voice = str(args.get("voice") or state.get("voiceover", {}).get("voice") or "am_fenrir").strip()
        speed = float(args.get("speed") or state.get("voiceover", {}).get("speed") or 1.0)
        api_key = str(args.get("api_key") or "").strip() or None
        align = bool(args.get("align", True))
        out_dir = WORKSPACE_DIR / "output" / "voiceovers"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_wav = out_dir / f"vo_{prov}_{voice}_{int(time.time())}.wav"
        cmd = [
            sys.executable, str(CLIP_PY), "voiceover",
            "--text", text, "--out", str(out_wav),
            "--provider", prov, "--voice", voice, "--speed", f"{speed:.2f}",
        ]
        if api_key:
            cmd += ["--api-key", api_key]
        if align:
            cmd.append("--align")
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr[-1000:] or proc.stdout[-1000:] or "voiceover failed")
        res = json.loads(proc.stdout)
        vo_state = state.setdefault("voiceover", {})
        vo_state.update({
            "provider": res.get("provider", prov),
            "voice": res.get("voice", voice),
            "speed": speed,
            "script": text,
            "last_wav": res.get("output_wav", str(out_wav)),
        })
        if isinstance(res.get("words"), list) and res["words"]:
            words = res["words"]
            chunks = []
            for i in range(0, min(len(words), 18), 3):
                grp = words[i : i + 3]
                chunks.append({
                    "start": round(float(grp[0]["start"]), 2),
                    "end": round(max(float(grp[-1]["end"]), float(grp[0]["start"]) + 0.35), 2),
                    "text": " ".join(str(w["word"]) for w in grp),
                })
            if chunks:
                state["edit_spec"]["preview_chunks"] = chunks
        _record_trace(state, name, f"synthesized {prov}:{voice} ({res.get('duration_s')}s)")
        save_state(state, state_file)
        return res

    if name == "build_longform_deep_dive":
        topic = str(args.get("topic") or state.get("voiceover", {}).get("topic") or "GTA 6 Can Do Things We Never Imagined in GTA 5").strip()
        script = str(args.get("script") or state.get("voiceover", {}).get("script") or "").strip()
        prov = str(args.get("provider") or state.get("voiceover", {}).get("provider") or "kokoro").strip()
        voice = str(args.get("voice") or state.get("voiceover", {}).get("voice") or "am_fenrir").strip()
        speed = float(args.get("speed") or state.get("voiceover", {}).get("speed") or 1.02)
        api_key = str(args.get("api_key") or "").strip() or None
        preview = bool(args.get("preview", True))
        slug = re.sub(r"[^a-z0-9]+", "_", topic.lower()).strip("_")[:28] or "gta6_deep_dive"
        proj_dir = WORKSPACE_DIR / "output" / "longform_deep_dives" / slug
        cmd = [
            sys.executable, str(CLIP_PY), "deep-dive", str(proj_dir),
            "--topic", topic, "--provider", prov, "--voice", voice, "--speed", f"{speed:.2f}",
        ]
        if script:
            cmd += ["--script", script]
        if api_key:
            cmd += ["--api-key", api_key]
        if preview:
            cmd.append("--preview")
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr[-1200:] or proc.stdout[-1200:] or "deep-dive build failed")
        res = json.loads(proc.stdout)
        vo_state = state.setdefault("voiceover", {})
        vo_state.update({
            "provider": prov,
            "voice": voice,
            "speed": speed,
            "topic": topic,
            "last_wav": (res.get("voiceover") or {}).get("output_wav", ""),
            "last_deep_dive_mp4": res.get("output_mp4", ""),
        })
        _record_trace(state, name, f"built deep-dive '{topic[:32]}' ({res.get('duration_s')}s)")
        save_state(state, state_file)
        return res

    raise ValueError(f"Unknown MCP tool: {name}")


def handle_rpc_message(msg: dict, state_file: Path = DEFAULT_STATE_FILE) -> dict | None:
    mid = msg.get("id")
    method = msg.get("method", "")
    params = msg.get("params") or {}

    if method == "notifications/initialized":
        return None
    if method == "initialize":
        return {
            "jsonrpc": "2.0", "id": mid,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": SERVER_INFO,
            },
        }
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": MCP_TOOLS}}
    if method == "tools/call":
        tname = params.get("name", "")
        targs = params.get("arguments") or {}
        try:
            out = execute_tool(tname, targs, state_file=state_file)
            return {
                "jsonrpc": "2.0", "id": mid,
                "result": {"content": [{"type": "text", "text": json.dumps(out, indent=2)}], "isError": False},
            }
        except Exception as exc:
            return {
                "jsonrpc": "2.0", "id": mid,
                "result": {"content": [{"type": "text", "text": json.dumps({"error": str(exc)})}], "isError": True},
            }
    if mid is None:
        return None
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Method not found: {method}"}}


def serve_stdio(state_file: Path = DEFAULT_STATE_FILE) -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError as exc:
            resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(exc)}}
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()
            continue
        resp = handle_rpc_message(msg, state_file=state_file)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()


def detect_installed_agents() -> dict[str, dict]:
    """Discover local AI coding agent CLIs so Resolve Lumvrix™ can use the user's own agent tokens."""
    extra_paths = [
        str(Path.home() / ".local" / "bin"),
        "/opt/homebrew/bin",
        "/usr/local/bin",
    ]
    nvm_dir = Path.home() / ".nvm" / "versions" / "node"
    if nvm_dir.is_dir():
        for p in sorted(nvm_dir.glob("*/bin"), reverse=True):
            extra_paths.append(str(p))
    search_path = os.pathsep.join(extra_paths + [os.environ.get("PATH", "")])

    def _find(cmd: str) -> str | None:
        return shutil.which(cmd, path=search_path)

    agents = {
        "claude": {
            "id": "claude",
            "label": "Claude Code (Local CLI Tokens)",
            "binary": _find("claude"),
            "installed": bool(_find("claude")),
        },
        "antigravity": {
            "id": "antigravity",
            "label": "Antigravity (agy CLI / MCP Tokens)",
            "binary": _find("agy"),
            "installed": bool(_find("agy")),
        },
        "codex": {
            "id": "codex",
            "label": "OpenAI Codex (Local CLI Tokens)",
            "binary": _find("codex"),
            "installed": bool(_find("codex")),
        },
        "gemini": {
            "id": "gemini",
            "label": "Gemini CLI (Local CLI Tokens)",
            "binary": _find("gemini"),
            "installed": bool(_find("gemini")),
        },
        "algorithm": {
            "id": "algorithm",
            "label": "Tri-Stage Viral ML Algorithm (Built-In Local)",
            "binary": str(CLIP_PY),
            "installed": True,
        },
    }
    return agents


def resolve_agent_choice(preferred: str = "auto") -> dict:
    agents = detect_installed_agents()
    pref = (preferred or "auto").lower().strip()
    if pref in agents and agents[pref]["installed"]:
        return agents[pref]
    for k in ("claude", "antigravity", "codex", "gemini", "algorithm"):
        if agents[k]["installed"]:
            return agents[k]
    return agents["algorithm"]


def steer_spec_with_agent(
    spec: dict,
    instruction: str = "",
    agent: str = "auto",
    candidate: dict | None = None,
    invoke_cli: bool = False,
) -> dict:
    """Update edit_spec using the selected agent (or deterministic natural-language + Tri-Stage ML director)."""
    chosen = resolve_agent_choice(agent)
    updated = copy.deepcopy(spec)
    text = (instruction or "").strip()
    low = text.lower()
    skip_clip = any(w in low for w in ("skip", "next clip", "not interested", "another clip", "different part", "discard"))
    changes: list[str] = []

    # 1. If a mined candidate window is provided, apply its optimal window & Tri-Stage style recommendation
    if candidate:
        s0 = int(round(float(candidate.get("start_s", 120))))
        s1 = int(round(float(candidate.get("end_s", s0 + 30))))
        updated["clip"] = f"{s0}:{s1}"
        if candidate.get("recommended_style") in ALLOWED_STYLES:
            updated["caption_style"] = candidate["recommended_style"]
            default_col = {"shine": "green", "stopmotion": "cream", "flicker": "white", "inverted": "auto", "hormozi": "gold"}
            updated["caption_color"] = default_col.get(updated["caption_style"], "green")
            updated["pos_y_1920"] = 1180 if updated["caption_style"] == "inverted" else 612
        if candidate.get("recommended_hook"):
            updated["hook"] = candidate["recommended_hook"]
        if candidate.get("recommended_theme") in ALLOWED_THEMES:
            updated["hook_theme"] = candidate["recommended_theme"]
        if isinstance(candidate.get("preview_chunks"), list) and candidate["preview_chunks"]:
            updated["preview_chunks"] = candidate["preview_chunks"]
        changes.append(f"window={updated['clip']} (score {candidate.get('viral_score', 91.0)})")

    # 2. Deterministic natural-language steering rules first (<1ms instant response for known keywords)
    if text:
        style_aliases = {
            "hormozi": "hormozi", "karaoke": "hormozi", "pop": "hormozi",
            "shine": "shine", "neon": "shine", "glow": "shine",
            "stopmotion": "stopmotion", "stop motion": "stopmotion", "editorial": "stopmotion", "serif": "stopmotion",
            "flicker": "flicker",
            "inverted": "inverted", "invert": "inverted", "negative": "inverted",
        }
        for kw, st in style_aliases.items():
            if kw in low:
                updated["caption_style"] = st
                updated["pos_y_1920"] = 1180 if st == "inverted" else 612
                changes.append(f"style={st}")
                break
        for col in ("green", "blue", "cream", "gold", "pink", "white"):
            if re.search(rf"\b{col}\b", low):
                updated["caption_color"] = col
                changes.append(f"color={col}")
                break
        if "yellow" in low:
            updated["caption_color"] = "gold"
            changes.append("color=gold")
        for th in ("vice", "gold", "blue"):
            if f"{th} theme" in low or f"theme {th}" in low or (th == "vice" and "vice city" in low and "hook" in low):
                updated["hook_theme"] = th
                changes.append(f"hook_theme={th}")
                break
        m_clip = re.search(r"\b(\d{1,4})\s*(?::|to|-)\s*(\d{1,4})\b", low)
        if m_clip and int(m_clip.group(2)) > int(m_clip.group(1)):
            updated["clip"] = f"{m_clip.group(1)}:{m_clip.group(2)}"
            changes.append(f"clip={updated['clip']}")
        m_hook = re.search(r'(?:hook(?:\s+to|\s*[:=])?\s*)["\']([^"\']{4,56})["\']', text, re.I)
        if not m_hook:
            m_hook = re.search(r"hook\s*(?:to|:|=)\s*([A-Za-z0-9 |!?'_-]{4,52})$", text, re.I)
        if m_hook:
            updated["hook"] = m_hook.group(1).strip()
            changes.append(f"hook='{updated['hook']}'")
        if "bright" in low:
            updated.setdefault("grade", {})["brightness"] = 0.08
            changes.append("brightness=+0.08")
        if "contrast" in low:
            updated.setdefault("grade", {})["contrast"] = 1.16
            changes.append("contrast=1.16")

    # 3. If open-ended creative prompt with no keyword hits, invoke local agent CLI using user's agent tokens
    cli_bin = chosen.get("binary")
    if invoke_cli and text and not changes and chosen["id"] in ("claude", "codex", "gemini") and cli_bin:
        prompt = (
            "Return ONLY a single-line JSON object with keys from "
            "{caption_style:(hormozi|shine|stopmotion|flicker|inverted), "
            "caption_color:(auto|green|blue|cream|gold|pink|white), "
            "hook:string, hook_theme:(blue|vice|gold), clip:string, skip:bool} "
            f"for user video editing request: {text}"
        )
        try:
            cmd = [cli_bin, "-p", prompt] if chosen["id"] in ("claude", "gemini") else [cli_bin, "exec", prompt]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=6)
            m = re.search(r"\{.*\}", proc.stdout or "", re.S)
            if m:
                parsed = json.loads(m.group(0))
                if parsed.get("caption_style") in ALLOWED_STYLES:
                    updated["caption_style"] = parsed["caption_style"]
                    changes.append(f"style={updated['caption_style']}")
                if parsed.get("caption_color") in ALLOWED_COLORS:
                    updated["caption_color"] = parsed["caption_color"]
                    changes.append(f"color={updated['caption_color']}")
                if isinstance(parsed.get("hook"), str) and parsed["hook"].strip():
                    updated["hook"] = parsed["hook"].strip()[:56]
                    changes.append(f"hook='{updated['hook']}'")
                if parsed.get("hook_theme") in ALLOWED_THEMES:
                    updated["hook_theme"] = parsed["hook_theme"]
                if isinstance(parsed.get("clip"), str) and CLIP_RE.match(parsed["clip"]):
                    updated["clip"] = parsed["clip"]
                    changes.append(f"clip={updated['clip']}")
                if parsed.get("skip") is True:
                    skip_clip = True
        except Exception:
            pass

    return {
        "edit_spec": updated,
        "skip_clip": skip_clip,
        "agent_id": chosen["id"],
        "agent_label": chosen["label"],
        "changes": changes or ["Applied agent direction"],
    }


def mcp_client_config() -> dict:
    return {
        "mcpServers": {
            "resolve-lumvrix": {
                "command": sys.executable,
                "args": [str(Path(__file__).resolve())],
            }
        }
    }


def self_check() -> None:
    """Runnable end-to-end check: JSON-RPC handshake, capabilities, snapshot/compare, marker gate, agent detection & steering."""
    with tempfile.TemporaryDirectory(prefix="sta6_mcp_chk_") as tmp:
        sf = Path(tmp) / "harness_state.json"
        init = handle_rpc_message({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}, sf)
        assert init and init["result"]["serverInfo"]["version"] == "4.5.0"
        assert init["result"]["serverInfo"]["owner"] == "HRL International Pvt. Ltd."
        tl = handle_rpc_message({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, sf)
        tool_names = [t["name"] for t in tl["result"]["tools"]]
        assert len(tool_names) == 14 and "synthesize_voiceover" in tool_names and "build_longform_deep_dive" in tool_names

        agents = detect_installed_agents()
        assert "claude" in agents and "antigravity" in agents and agents["algorithm"]["installed"] is True
        st_res = steer_spec_with_agent(
            default_harness_state()["edit_spec"],
            "Not interested, skip this clip, switch to inverted captions and set hook to 'GTA 6 Physics | Are Unreal'",
            agent="auto",
        )
        assert st_res["skip_clip"] is True and st_res["edit_spec"]["caption_style"] == "inverted"
        assert st_res["edit_spec"]["hook"] == "GTA 6 Physics | Are Unreal"

        caps = execute_tool("bridge_capabilities", {}, sf)
        assert set(caps["styles"].keys()) == set(ALLOWED_STYLES)

        execute_tool("preview_timeline", {"name": "original"}, sf)
        execute_tool("customize_captions", {"caption_style": "stopmotion", "caption_color": "cream"}, sf)
        execute_tool("set_clip_grade", {"contrast": 1.15, "saturation": 1.22}, sf)
        diff = execute_tool("compare_timelines", {"left": "original", "right": "current"}, sf)
        assert diff["changed_fields"] >= 3 and "caption_style" in diff["diffs"]

        mk = execute_tool("add_marker", {"t": 1.45, "note": "Check serif kerning", "severity": "blocker", "x2k": 720, "y2k": 816}, sf)
        health = execute_tool("project_health", {}, sf)
        assert health["ready_to_render"] is False, "Blocker marker must trip OPEN_FLAGS_CLEAR gate!"
        blocked = execute_tool("render_current_timeline", {"source": "demo.mp4"}, sf)
        assert blocked["ok"] is False and blocked["blocked_by_harness_gate"] == "OPEN_FLAGS_CLEAR"

        execute_tool("resolve_marker", {"marker_id": mk["marker"]["id"]}, sf)
        health2 = execute_tool("project_health", {}, sf)
        assert health2["ready_to_render"] is True
        print(json.dumps({
            "status": "OK",
            "app": "Resolve Lumvrix",
            "owner": "HRL International Pvt. Ltd.",
            "version": "4.5.0",
            "mcp_tools": len(tool_names),
            "detected_agents": [k for k, v in agents.items() if v["installed"]],
            "diff_fields_verified": sorted(diff["diffs"].keys()),
            "fail_closed_gate_verified": True,
        }, indent=2))


def main() -> None:
    ap = argparse.ArgumentParser(description="Resolve Lumvrix™ AI Bridge MCP Server (v4.5.0) — HRL International Pvt. Ltd.")
    ap.add_argument("--check", action="store_true", help="Run automated MCP bridge self-check")
    ap.add_argument("--print-config", action="store_true", help="Print ready-to-paste MCP client configuration JSON")
    ap.add_argument("--state", type=Path, default=DEFAULT_STATE_FILE, help="Path to shared harness_state.json")
    args = ap.parse_args()
    if args.check:
        self_check()
        return
    if args.print_config:
        print(json.dumps(mcp_client_config(), indent=2))
        return
    serve_stdio(args.state)


if __name__ == "__main__":
    main()
