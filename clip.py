#!/usr/bin/env python3
"""Resolve Lumvrix™ (v4.5.0) — HRL Studio Update (1:1 Neural Flow-Matching Voice Cloner 'This is HRL' + Native Neural ONNX + 8:05+ Long-Form Engine).
Copyright (c) 2026 HRL International Pvt. Ltd. All Rights Reserved. Trademark, Copyright & Patent Rights Reserved.

Enforces:
  Rule A: Zero AV drift + dynamic compression + -18 LUFS mastering (steady crest ~2.3-2.5)
  Rule B: Flush zero-gap Aaron Rheins 1440x2560 (2k VP9 default: 816 cam + 1744 game) / 1080x1920 (612 cam + 1308 game) @60fps,
          auto OBS/letterbox header trim (zero accidental black gaps), single-pass lanczos+accurate_rnd+full_chroma_int upscale,
          deblock + hqdn3d + AMD CAS sharpening, zero double-encoding, libx264 High Profile CRF 13 BT.709 master, 2.6s climax cold-open
  Rule C: Seamless seam-locked captions (zero black bar) with 5 built-in styles (hormozi, shine, stopmotion, flicker, inverted)
          + soft glyph-hugging contact shadow + 60fps animated Viral Shine Text 2.6s hook (zero boxes/borders)
  Rule D: Strict cleanup (all intermediates live in TemporaryDirectory; output dir gets only .mp4)
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ARCHIVE_LOG = BASE_DIR / "archive_manifest.json"
FONTS_DIR = Path("/System/Library/Fonts/Supplemental")
IMPACT_TTF = FONTS_DIR / "Impact.ttf"
HELVETICA_NEUE_TTC = Path("/System/Library/Fonts/HelveticaNeue.ttc")
BASKERVILLE_TTC = FONTS_DIR / "Baskerville.ttc"
GEORGIA_BOLD_ITALIC_TTF = FONTS_DIR / "Georgia Bold Italic.ttf"


def next_short_number(out_dir: Path) -> int:
    """Return next sequential short index across local output/ and Drive archive_manifest.json."""
    highest = 0
    pat = re.compile(r"^short_(\d+)")
    if out_dir.exists():
        for p in out_dir.glob("short_*.mp4"):
            m = pat.match(p.name)
            if m:
                highest = max(highest, int(m.group(1)))
    if ARCHIVE_LOG.exists():
        try:
            for item in json.loads(ARCHIVE_LOG.read_text(encoding="utf-8")):
                m = pat.match(str(item.get("file", "")))
                if m:
                    highest = max(highest, int(m.group(1)))
        except Exception:
            pass
    return highest + 1


def find_ffmpeg() -> str:
    """Prefer an FFmpeg binary compiled with libass (for .ass karaoke burn-in)."""
    candidates = [
        os.environ.get("FFMPEG_BIN"),
        shutil.which("ffmpeg"),
        "/Users/pavankumars/.gemini/antigravity/bin/ffmpeg",
        "/opt/homebrew/bin/ffmpeg",
        "/usr/local/bin/ffmpeg",
    ]
    fallback = None
    for path in candidates:
        if not path or not os.path.isfile(path):
            continue
        fallback = fallback or path
        out = subprocess.run(
            [path, "-hide_banner", "-filters"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout
        if " ass " in out:
            return path
    if fallback:
        raise RuntimeError(
            f"FFmpeg at {fallback} lacks libass (required for .ass subtitles). "
            "Install ffmpeg with libass or set FFMPEG_BIN."
        )
    raise RuntimeError("ffmpeg not found in PATH.")


def find_ffprobe() -> str:
    for path in (shutil.which("ffprobe"), "/opt/homebrew/bin/ffprobe", "/usr/local/bin/ffprobe"):
        if path and os.path.isfile(path):
            return path
    raise RuntimeError("ffprobe not found in PATH.")


def has_videotoolbox(ffmpeg_bin: str) -> bool:
    out = subprocess.run(
        [ffmpeg_bin, "-hide_banner", "-encoders"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    return "h264_videotoolbox" in out


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"Command failed ({proc.returncode}): {' '.join(cmd)}\n{proc.stderr[-1500:]}")
    return proc


def download_vod(url: str, work_dir: Path, max_height: int = 2160, section: tuple[float, float] | None = None) -> Path:
    """Fetch ONLY the requested clip window via direct stream URLs (yt-dlp -g + ffmpeg -ss) or --download-sections.

    Excludes slow HLS .m3u8 manifests on VOD/was_live streams so FFmpeg performs an instant HTTP Range seek (<2s)
    instead of walking thousands of HLS segments or downloading multi-GB livestreams.
    """
    yt_dlp = Path(sys.executable).parent / "yt-dlp"
    yt_cmd = str(yt_dlp) if yt_dlp.exists() else (shutil.which("yt-dlp") or "yt-dlp")
    ffmpeg_bin = find_ffmpeg()
    out_mp4 = work_dir / "source.mp4"

    # Prefer direct HTTPS byte-range streams (non-m3u8) first for instant <2s HTTP Range seeking; fallback to any protocol for active live streams
    direct_fmt = (
        f"bestvideo[height<={max_height}][protocol!*=m3u8]+bestaudio[protocol!*=m3u8]/"
        f"best[height<={max_height}][protocol!*=m3u8]/"
        f"bestvideo[height<={max_height}]+bestaudio/best[height<={max_height}]/best"
    )
    if section is not None:
        s0, s1 = max(0.0, float(section[0])), max(1.0, float(section[1]))
        dur = max(1.0, s1 - s0)
        try:
            g_proc = subprocess.run(
                [yt_cmd, "-f", direct_fmt, "-S", f"res:{max_height},fps,vbr", "-g", url],
                capture_output=True, text=True, timeout=25,
            )
            urls = [u.strip() for u in (g_proc.stdout or "").splitlines() if u.strip().startswith("http")]
            if len(urls) >= 2:
                run([
                    ffmpeg_bin, "-y",
                    "-ss", f"{s0:.2f}", "-t", f"{dur:.2f}", "-i", urls[0],
                    "-ss", f"{s0:.2f}", "-t", f"{dur:.2f}", "-i", urls[1],
                    "-map", "0:v:0", "-map", "1:a:0",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                    str(out_mp4),
                ])
                if out_mp4.is_file() and out_mp4.stat().st_size > 10_000:
                    return out_mp4
            elif len(urls) == 1:
                run([
                    ffmpeg_bin, "-y",
                    "-ss", f"{s0:.2f}", "-t", f"{dur:.2f}", "-i", urls[0],
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                    str(out_mp4),
                ])
                if out_mp4.is_file() and out_mp4.stat().st_size > 10_000:
                    return out_mp4
        except Exception:
            pass

    out_tpl = str(work_dir / "source.%(ext)s")
    cmd = [
        yt_cmd,
        "-f", direct_fmt,
        "-S", f"res:{max_height},fps,vbr",
        "--merge-output-format", "mp4",
    ]
    if section is not None:
        s0, s1 = max(0.0, float(section[0])), max(1.0, float(section[1]))
        cmd.extend(["--ffmpeg-location", ffmpeg_bin, "--download-sections", f"*{s0:.1f}-{s1:.1f}"])
    cmd.extend(["-o", out_tpl, url])
    run(cmd)
    matches = sorted(work_dir.glob("source.*"))
    if not matches:
        raise RuntimeError("yt-dlp finished without producing a source file.")
    return matches[0]


def video_encoder_args(ffmpeg_bin: str, quality: str = "2k", canvas_h: int = 2560) -> list[str]:
    """v4.0.2 Zero-Quality-Loss Master encoder profiles (replaces low-bitrate 6.5M VideoToolbox)."""
    color_tags = ["-color_range", "tv", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709"]
    if quality == "fast" and has_videotoolbox(ffmpeg_bin):
        br = "28000k" if canvas_h >= 2560 else "20000k"
        mr = "40000k" if canvas_h >= 2560 else "28000k"
        return ["-c:v", "h264_videotoolbox", "-profile:v", "high", "-b:v", br, "-maxrate", mr, "-allow_sw", "1", *color_tags]
    # Default '2k' and 'ultra': visually lossless libx264 High Profile CRF 13 with aq-mode=3 (protects dark facecams),
    # psy-rd=1.0,0.15 & deblock=-1,-1 (preserves crisp facial/hair/HUD edges with zero compression softness).
    mr = "45M" if canvas_h >= 2560 else "30M"
    bs = "90M" if canvas_h >= 2560 else "60M"
    lvl = "5.1" if canvas_h >= 2560 else "4.2"
    return [
        "-c:v", "libx264", "-profile:v", "high", "-level:v", lvl,
        "-preset", "medium", "-crf", "13",
        "-maxrate", mr, "-bufsize", bs,
        "-x264-params", "aq-mode=3:deblock=-1,-1:psy-rd=1.0,0.15",
        *color_tags,
    ]


def detect_scream_peaks(wav_path: Path, max_windows: int = 8) -> list[tuple[float, float]]:
    """Detect high-energy reaction/scream windows (seconds) from a 16kHz mono WAV."""
    import numpy as np

    with wave.open(str(wav_path), "rb") as wf:
        sr = wf.getframerate()
        pcm = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    if len(pcm) < sr:
        return []
    step = int(sr * 0.5)
    rms = np.array([float(np.sqrt(np.mean(pcm[i : i + step] ** 2))) for i in range(0, len(pcm) - step + 1, step)])
    if len(rms) == 0:
        return []
    thresh = max(0.16, float(np.median(rms)) * 2.1)
    windows: list[tuple[float, float]] = []
    i = 0
    while i < len(rms):
        if rms[i] >= thresh:
            t0 = max(0.0, i * 0.5 - 0.15)
            j = i
            while j < len(rms) and rms[j] >= thresh * 0.85:
                j += 1
            t1 = min(len(pcm) / sr, j * 0.5 + 0.35)
            if windows and t0 <= windows[-1][1] + 0.6:
                windows[-1] = (windows[-1][0], t1)
            else:
                windows.append((round(t0, 2), round(t1, 2)))
            i = j
        else:
            i += 1
    # Keep strongest/longest bursts up to max_windows to keep filtergraph compact
    return windows[:max_windows]


def find_climax_window(wav_path: Path, cold_dur: float = 2.6) -> tuple[float, float] | None:
    """Locate the peak-energy climax burst in the back 60% of a clip for Aaron's cold-open flashforward."""
    import numpy as np

    with wave.open(str(wav_path), "rb") as wf:
        sr = wf.getframerate()
        pcm = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    total_s = len(pcm) / max(sr, 1)
    if total_s < cold_dur * 2.5:
        return None
    win = int(sr * cold_dur)
    step = int(sr * 0.25)
    start_i = int(sr * total_s * 0.35)
    end_i = len(pcm) - win
    if end_i <= start_i:
        return None
    best_i = start_i
    best_rms = -1.0
    for i in range(start_i, end_i + 1, step):
        seg = pcm[i : i + win]
        r = float(np.sqrt(np.mean(seg * seg)))
        if r > best_rms:
            best_rms = r
            best_i = i
    t0 = round(best_i / sr, 2)
    return (t0, round(min(total_s, t0 + cold_dur), 2))


def build_cold_open_source(
    source_path: Path,
    start: float,
    end: float,
    peak_rel_start: float,
    cold_dur: float,
    work_dir: Path,
    ffmpeg_bin: str,
) -> Path:
    """Splice [start+peak_rel_start .. +cold_dur] directly onto t=0.00s ahead of [start .. end].

    Recreates Aaron Rheins' rwS2r7cs52s climax flashforward so opening 1.5s RMS >= 1.15x overall RMS.
    """
    out_src = work_dir / f"cold_open_{int(start)}_{int(end)}.mp4"
    dur = end - start
    # v4.0.2: Near-lossless intermediate (CRF 8) guarantees zero quality drop on cold-open splices
    v_enc = ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "8"]
    fade_out_st = max(0.0, cold_dur - 0.05)
    fc = (
        "[0:v]setpts=PTS-STARTPTS[v0];"
        f"[0:a]asetpts=PTS-STARTPTS,aresample=48000:async=1:first_pts=0,afade=t=out:st={fade_out_st:.3f}:d=0.05[a0];"
        "[1:v]setpts=PTS-STARTPTS[v1];"
        "[1:a]asetpts=PTS-STARTPTS,aresample=48000:async=1:first_pts=0,afade=t=in:st=0:d=0.04[a1];"
        "[v0][a0][v1][a1]concat=n=2:v=1:a=1[v][a]"
    )
    run([
        ffmpeg_bin, "-y",
        "-ss", f"{start + peak_rel_start:.3f}", "-t", f"{cold_dur:.3f}", "-i", str(source_path),
        "-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", str(source_path),
        "-filter_complex", fc,
        "-map", "[v]", "-map", "[a]",
        *v_enc, "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "256k",
        str(out_src),
    ])
    return out_src


def shift_words_for_cold_open(
    words: list[dict],
    clip_start: float,
    clip_end: float,
    peak_rel_start: float,
    cold_dur: float,
) -> list[dict]:
    """Build aligned word timestamps for [cold_open (0..cold_dur)] + [main clip (cold_dur..)]."""
    peak_abs_start = clip_start + peak_rel_start
    peak_abs_end = peak_abs_start + cold_dur
    shifted: list[dict] = []
    for w in words:
        if w["end"] > peak_abs_start and w["start"] < peak_abs_end:
            shifted.append({
                "word": w["word"],
                "start": max(0.0, w["start"] - peak_abs_start),
                "end": min(cold_dur, w["end"] - peak_abs_start),
            })
    for w in words:
        if w["end"] > clip_start and w["start"] < clip_end:
            shifted.append({
                "word": w["word"],
                "start": cold_dur + max(0.0, w["start"] - clip_start),
                "end": cold_dur + min(clip_end - clip_start, w["end"] - clip_start),
            })
    return shifted


def transcribe_words(
    media_path: Path,
    work_dir: Path,
    ffmpeg_bin: str,
    model_size: str = "base.en",
) -> list[dict]:
    import numpy as np
    from faster_whisper import WhisperModel

    wav_path = work_dir / "audio.wav"
    run([
        ffmpeg_bin, "-y", "-i", str(media_path),
        "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
        str(wav_path),
    ])
    with wave.open(str(wav_path), "rb") as wf:
        pcm = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segments, _ = model.transcribe(pcm, word_timestamps=True, vad_filter=True)
    words: list[dict] = []
    for seg in segments:
        for w in seg.words or []:
            text = w.word.strip()
            if text:
                words.append({"word": text, "start": float(w.start), "end": float(w.end)})
    return words


def fmt_ass_time(seconds: float) -> str:
    cs = max(0, int(round(seconds * 100)))
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, c = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{c:02d}"


def _wrap_hook_lines(text: str, max_line: int = 19) -> str:
    """Wrap hook card cleanly onto max 2 balanced lines (keeping 'GTA 6'/'GTA VI' glued together)."""
    glued = re.sub(r"\b(GTA)\s+(6|VI)\b", lambda m: f"{m.group(1)}\u00A0{m.group(2)}", text, flags=re.I)
    words = glued.split(" ")
    if len(text) <= max_line or len(words) < 2:
        return text
    best_split = len(words) // 2
    best_diff = 999
    for k in range(1, len(words)):
        l1 = " ".join(words[:k])
        l2 = " ".join(words[k:])
        diff = abs(len(l1) - len(l2))
        if diff < best_diff:
            best_diff = diff
            best_split = k
    return (" ".join(words[:best_split]) + r"\N" + " ".join(words[best_split:])).replace("\u00A0", " ")


HOOK_SHINE_THEMES: dict[str, dict] = {
    # Exact Hexa Visual (Aln55a2X4GM) 4-color electric blue gradient + cyan ambient bloom
    "blue": {
        "colors_4": ((40, 218, 255), (18, 158, 255), (0, 84, 218), (26, 60, 245)),
        "glow_rgb": (36, 192, 255),
    },
    # GTA 6 Vice City sunset magenta-gold gradient + neon pink bloom
    "vice": {
        "colors_4": ((255, 190, 64), (255, 86, 168), (230, 42, 138), (138, 46, 255)),
        "glow_rgb": (255, 92, 178),
    },
    # Luxury metallic gold gradient + warm amber bloom
    "gold": {
        "colors_4": ((255, 240, 128), (255, 196, 36), (222, 132, 0), (255, 168, 24)),
        "glow_rgb": (255, 196, 48),
    },
}


def _split_shine_hook_lines(text: str) -> tuple[str, str]:
    """Split hook into a punchy 2-tier (Main Title, Subtitle) lockup preserving clean casing."""
    clean = re.sub(r"\s+", " ", text.strip().replace("{", "").replace("}", ""))
    if "|" in clean:
        a, b = clean.split("|", 1)
        return a.strip(), b.strip()
    # Keep acronyms / mixed-case brand handles (IShowSpeed, GTA 6) intact; normalize ALL-CAPS titles cleanly
    if clean.isupper() and len(clean) > 6:
        acronyms = {"GTA", "VI", "AI", "VIP", "FPS", "VOD", "NPC", "RP", "IRL", "W", "L"}
        words = [w if w in acronyms else w.capitalize() for w in clean.split(" ")]
        clean = " ".join(words)
    glued = re.sub(r"\b(GTA)\s+(6|VI)\b", lambda m: f"{m.group(1)}\u00A0{m.group(2)}", clean, flags=re.I)
    parts = glued.split(" ")
    if len(parts) <= 1:
        return clean, ""
    if len(parts) == 2:
        return parts[0].replace("\u00A0", " "), parts[1].replace("\u00A0", " ")
    # Prefer 1 punchy subject word (e.g. 'IShowSpeed') if long enough, else balanced 2-line split
    if len(parts[0]) >= 7 and len(" ".join(parts[1:])) <= 22:
        l1, l2 = parts[0], " ".join(parts[1:])
    else:
        best_k, best_diff = 1, 999
        for k in range(1, len(parts)):
            d = abs(len(" ".join(parts[:k])) - len(" ".join(parts[k:])))
            if d < best_diff:
                best_diff, best_k = d, k
        l1, l2 = " ".join(parts[:best_k]), " ".join(parts[best_k:])
    return l1.replace("\u00A0", " "), l2.replace("\u00A0", " ")


def build_viral_shine_hook_mov(
    hook_text: str,
    out_mov: Path,
    ffmpeg_bin: str,
    duration: float = 2.6,
    canvas_w: int = 1440,
    theme: str = "blue",
    fps: int = 60,
) -> Path:
    """v4.0.4: Render 60fps transparent RGBA Viral Shine Text animation (Hexa Visual Aln55a2X4GM recipe).

    Two-tier tight Coolvetica-style lockup (Helvetica Neue Bold), 4-color bilinear gradient,
    animated -28 deg feathered diagonal Brightness+100 shine sweep, bottom-stack ambient bloom glow,
    staggered pop-in entrance, and clean fade-out — zero boxes and zero borderlines.
    """
    import numpy as np
    from PIL import Image, ImageDraw, ImageFilter, ImageFont

    line1, line2 = _split_shine_hook_lines(hook_text)
    spec = HOOK_SHINE_THEMES.get(theme, HOOK_SHINE_THEMES["blue"])
    scale = canvas_w / 1080.0
    font1_px = int(round(92 * scale))
    font2_px = int(round(62 * scale))
    pad = int(round(96 * scale))

    def load_bold(sz: int):
        if HELVETICA_NEUE_TTC.exists():
            return ImageFont.truetype(str(HELVETICA_NEUE_TTC), sz, index=1)
        return ImageFont.truetype(str(IMPACT_TTF), sz) if IMPACT_TTF.exists() else ImageFont.load_default()

    def ease_out_cubic(t: float) -> float:
        t = max(0.0, min(1.0, t))
        return 1.0 - (1.0 - t) ** 3

    def ease_out_back(t: float, s: float = 1.15) -> float:
        t = max(0.0, min(1.0, t)) - 1.0
        return t * t * ((s + 1.0) * t + s) + 1.0

    def ease_in_out_cubic(t: float) -> float:
        t = max(0.0, min(1.0, t))
        return 4 * t * t * t if t < 0.5 else 1 - ((-2 * t + 2) ** 3) / 2

    def draw_tracked_mask(txt: str, fpx: int, tr: float):
        max_w = int(round(canvas_w * 0.86))
        for _ in range(4):
            fnt = load_bold(fpx)
            probe = ImageDraw.Draw(Image.new("L", (16, 16), 0))
            cap_bb = probe.textbbox((0, 0), "H", font=fnt)
            xs, cx = [], 0.0
            min_y, max_y = 10**9, -10**9
            for idx, ch in enumerate(txt):
                adv = probe.textlength(ch, font=fnt)
                bb = probe.textbbox((cx, 0), ch, font=fnt)
                xs.append((ch, cx, bb))
                min_y, max_y = min(min_y, bb[1]), max(max_y, bb[3])
                cx += adv + (fpx * tr if idx < len(txt) - 1 else 0.0)
            min_x = min(b[0] for _, _, b in xs)
            max_x = max(b[2] for _, _, b in xs)
            iw = int(math.ceil(max_x - min_x))
            if iw <= max_w or fpx <= 28:
                ih = int(math.ceil(max_y - min_y))
                cap_h = int(math.ceil(cap_bb[3] - min_y))
                w, h = iw + 2 * pad, ih + 2 * pad
                mask = Image.new("L", (w, h), 0)
                d = ImageDraw.Draw(mask)
                for ch, x0, _ in xs:
                    d.text((pad + x0 - min_x, pad - min_y), ch, font=fnt, fill=255)
                return mask, iw, ih, cap_h, fpx
            fpx = max(28, int(round(fpx * (max_w / iw))))
        raise RuntimeError("Unreachable")

    def prep_layer(txt: str, fpx: int, tr: float, colors_4: tuple, glow_rgb: tuple, glow_r: float, glow_op: float):
        mask, iw, ih, cap_h, eff_fpx = draw_tracked_mask(txt, fpx, tr)
        w, h = mask.size
        m_arr = np.asarray(mask, dtype=np.float32) / 255.0
        gx = np.linspace(0.0, 1.0, max(1, iw), dtype=np.float32)[None, :, None]
        gy = np.linspace(0.0, 1.0, max(1, ih), dtype=np.float32)[:, None, None]
        tl, trc, bl, br = [np.array(c, dtype=np.float32) for c in colors_4]
        g_ink = (tl * (1 - gx) + trc * gx) * (1 - gy) + (bl * (1 - gx) + br * gx) * gy
        grad = np.zeros((h, w, 3), dtype=np.float32)
        grad[pad : pad + ih, pad : pad + iw] = g_ink
        grad[:pad, pad : pad + iw] = g_ink[0:1, :]
        grad[pad + ih :, pad : pad + iw] = g_ink[-1:, :]
        grad[:, :pad] = grad[:, pad : pad + 1]
        grad[:, pad + iw :] = grad[:, pad + iw - 1 : pad + iw]

        ob = np.asarray(mask.filter(ImageFilter.GaussianBlur(radius=glow_r)), dtype=np.float32) / 255.0
        mb = np.asarray(mask.filter(ImageFilter.GaussianBlur(radius=glow_r * 0.40)), dtype=np.float32) / 255.0
        ib = np.asarray(mask.filter(ImageFilter.GaussianBlur(radius=glow_r * 0.15)), dtype=np.float32) / 255.0
        sh = max(2, int(round(eff_fpx * 0.035)))
        ob = np.roll(np.roll(ob, sh, axis=0), sh, axis=1)
        glow_a = np.clip(ob * glow_op + mb * (glow_op * 0.62) + ib * (glow_op * 0.42), 0.0, 1.0)

        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        rad = math.radians(-28.0)
        u = (xx - pad) * math.cos(rad) - (yy - (pad + ih * 0.5)) * math.sin(rad)
        return {
            "w": w, "h": h, "iw": iw, "ih": ih, "cap_h": cap_h, "pad": pad,
            "m_arr": m_arr, "grad": grad, "glow_a": glow_a,
            "glow_rgb": np.array(glow_rgb, dtype=np.float32), "u": u,
        }

    def render_layer(L: dict, shine_pos: float, boost: float, glow_mult: float) -> Image.Image:
        sigma = max(20.0, L["iw"] * 0.11)
        shine = np.exp(-0.5 * ((L["u"] - shine_pos * L["iw"]) / sigma) ** 2).astype(np.float32)
        rgb = np.clip(L["grad"] + shine[:, :, None] * boost, 0, 255)
        ga = np.clip(L["glow_a"] * glow_mult, 0.0, 1.0)
        ta = L["m_arr"]
        out_a = ta + ga * (1.0 - ta)
        safe_a = np.where(out_a > 1e-4, out_a, 1.0)
        out_rgb = (rgb * ta[:, :, None] + L["glow_rgb"][None, None, :] * (ga * (1.0 - ta))[:, :, None]) / safe_a[:, :, None]
        rgba = np.zeros((L["h"], L["w"], 4), dtype=np.uint8)
        rgba[:, :, :3] = np.clip(out_rgb, 0, 255).astype(np.uint8)
        rgba[:, :, 3] = np.clip(out_a * 255.0, 0, 255).astype(np.uint8)
        return Image.fromarray(rgba, "RGBA")

    white_4 = ((255, 255, 255), (252, 254, 255), (232, 240, 250), (240, 246, 255))
    L1 = prep_layer(line1, font1_px, -0.046, spec["colors_4"], spec["glow_rgb"], 38.0 * scale, 0.78)
    L2 = prep_layer(line2, font2_px, -0.042, white_4, (255, 255, 255), 32.0 * scale, 0.66) if line2 else None

    gap = int(round(13 * scale))
    stack_h = (L1["cap_h"] + gap + L2["ih"]) if L2 else L1["ih"]
    box_w = max(L1["w"], L2["w"] if L2 else 0) + int(round(40 * scale))
    box_h = stack_h + 2 * pad + int(round(40 * scale))
    box_w = (box_w // 2) * 2
    box_h = (box_h // 2) * 2

    # Invisible-edge soft radial contrast scrim so glow stays legible on bright daytime gameplay (zero border!)
    scrim = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
    sd = ImageDraw.Draw(scrim, "RGBA")
    rx = int(max(L1["iw"], L2["iw"] if L2 else 0) * 0.60)
    ry = int(stack_h * 0.74)
    sd.ellipse([(box_w // 2 - rx, box_h // 2 - ry), (box_w // 2 + rx, box_h // 2 + ry)], fill=(0, 0, 0, 120))
    scrim = scrim.filter(ImageFilter.GaussianBlur(radius=50.0 * scale))

    n_frames = max(12, int(round(duration * fps)))
    exit_start = max(0.6, duration - 0.36)
    top_y = (box_h - stack_h) / 2.0

    def paste_tx(canvas: Image.Image, im: Image.Image, cx: float, cy: float, sc: float, al: float) -> Image.Image:
        if al <= 0.005:
            return canvas
        if abs(sc - 1.0) > 0.002:
            im = im.resize((max(2, int(round(im.width * sc))), max(2, int(round(im.height * sc)))), Image.Resampling.BILINEAR)
        if al < 0.995:
            im = im.copy()
            im.putalpha(im.getchannel("A").point(lambda p: int(p * al)))
        tmp_l = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        tmp_l.paste(im, (int(round(cx - im.width / 2)), int(round(cy - im.height / 2))))
        return Image.alpha_composite(canvas, tmp_l)

    proc = subprocess.Popen(
        [
            ffmpeg_bin, "-y", "-f", "rawvideo", "-vcodec", "rawvideo", "-pix_fmt", "rgba",
            "-s", f"{box_w}x{box_h}", "-r", str(fps), "-i", "-",
            "-c:v", "qtrle", "-pix_fmt", "argb", str(out_mov),
        ],
        stdin=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert proc.stdin is not None
    for f in range(n_frames):
        t = f / fps
        out_p = ease_in_out_cubic((t - exit_start) / max(0.12, duration - exit_start)) if t > exit_start else 0.0
        out_a = 1.0 - out_p
        out_sc = 1.0 - 0.05 * out_p

        in1 = ease_out_cubic(t / 0.30)
        sc1 = (0.88 + 0.12 * ease_out_back(t / 0.34)) * out_sc
        al1 = in1 * out_a
        dy1 = (1.0 - in1) * (24.0 * scale)
        sh1 = -0.45 + 1.90 * ease_in_out_cubic((t - 0.30) / 1.25)
        pulse1 = 1.0 + 0.22 * math.exp(-((sh1 - 0.5) / 0.35) ** 2)

        frame = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
        if al1 > 0.01:
            sc_l = scrim.copy()
            sc_l.putalpha(sc_l.getchannel("A").point(lambda p: int(p * al1)))
            frame = Image.alpha_composite(frame, sc_l)

        if L2:
            in2 = ease_out_cubic((t - 0.09) / 0.30)
            sc2 = (0.90 + 0.10 * ease_out_back((t - 0.09) / 0.34)) * out_sc
            al2 = in2 * out_a
            dy2 = (1.0 - in2) * (18.0 * scale)
            sh2 = -0.45 + 1.90 * ease_in_out_cubic((t - 0.46) / 1.25)
            pulse2 = 1.0 + 0.18 * math.exp(-((sh2 - 0.5) / 0.35) ** 2)
            cy2 = top_y + L1["cap_h"] + gap - pad + L2["h"] / 2.0 + dy2
            frame = paste_tx(frame, render_layer(L2, sh2, 75.0, pulse2), box_w / 2.0, cy2, sc2, al2)

        cy1 = top_y - pad + L1["h"] / 2.0 + dy1
        frame = paste_tx(frame, render_layer(L1, sh1, 145.0, pulse1), box_w / 2.0, cy1, sc1, al1)
        proc.stdin.write(frame.tobytes())

    proc.stdin.close()
    err = proc.stderr.read().decode("utf-8", errors="ignore") if proc.stderr else ""
    if proc.wait() != 0:
        raise RuntimeError(f"Viral Shine hook animation failed:\n{err[-800:]}")
    return out_mov


CAPTION_COLORS: dict[str, dict] = {
    "green": {"fill": (94, 255, 36), "glow": (84, 255, 32), "hi": (218, 255, 185), "hex": "#5EFF24"},
    "blue":  {"fill": (46, 206, 255), "glow": (30, 172, 255), "hi": (214, 246, 255), "hex": "#2ECEFF"},
    "cream": {"fill": (244, 237, 210), "glow": (244, 237, 210), "hi": (255, 252, 240), "hex": "#F4EDD2"},
    "gold":  {"fill": (255, 216, 48), "glow": (255, 184, 24), "hi": (255, 248, 204), "hex": "#FFD830"},
    "pink":  {"fill": (255, 76, 172), "glow": (255, 52, 158), "hi": (255, 214, 236), "hex": "#FF4CAC"},
    "white": {"fill": (255, 255, 255), "glow": (235, 244, 255), "hi": (255, 255, 255), "hex": "#FFFFFF"},
}

CAPTION_STYLES: dict[str, dict] = {
    "hormozi": {
        "name": "Hormozi Karaoke",
        "source_recipe": "Built-in STA-6 Classic (Rule C)",
        "font": "Impact Bold Italic",
        "default_color": "gold",
        "supports_color": False,
        "visual_signature": "High-contrast ALL-CAPS word-by-word karaoke with crisp outline & drop shadow; active spoken word pops Electric Yellow (#FFE500) at 108% -> 100% cleanly across the zero-gap split-screen seam.",
        "best_for": "Fast-paced gaming reactions, streamer clips, hype montages, loud comedy moments.",
        "alignment": "Pixel-centered on the flush zero-gap split-screen seam (y=816 @ 2K / y=612 @ 1080p) with zero black bar.",
    },
    "shine": {
        "name": "The Shine",
        "source_recipe": "Victor Grubbe (TWIZ2_FlIB0) — Effect 1",
        "font": "Helvetica Neue Bold (-4.2% tracking)",
        "default_color": "green",
        "supports_color": True,
        "visual_signature": "Vibrant colored typography (default neon green #5EFF24) with 3 parallel -28 deg diagonal light sweeps, 3-layer pulsing optical bloom, and soft glyph-hugging contact shadow over flush footage.",
        "best_for": "High-retention creator hooks, tech/gaming breakdowns, energetic viral clips wanting neon glow polish.",
        "alignment": "Exact ink_bb pixel-centered (+/-1px) directly on the flush zero-gap seam (y=816 @ 2K) with zero black bar.",
    },
    "stopmotion": {
        "name": "The Stop Motion",
        "source_recipe": "Victor Grubbe (TWIZ2_FlIB0) — Effect 2",
        "font": "Baskerville Bold Italic (Playfair editorial twin)",
        "default_color": "cream",
        "supports_color": True,
        "visual_signature": "Editorial serif italic in warm cream (#F4EDD2) with circular morphological erode-dilate dissolve quantized to tactile 15 fps stop-motion cadence + soft glyph shadow over flush footage.",
        "best_for": "Storytelling, cinematic lore, commentary, luxury/aesthetic edits, documentary-style Shorts.",
        "alignment": "Exact ink_bb pixel-centered (+/-1px) directly on the flush zero-gap seam (y=816 @ 2K) with zero black bar.",
    },
    "flicker": {
        "name": "The Flicker",
        "source_recipe": "Victor Grubbe (TWIZ2_FlIB0) — Effect 3",
        "font": "Helvetica Neue Bold (-4.2% tracking)",
        "default_color": "white",
        "supports_color": True,
        "visual_signature": "Crisp cinema white typography with smooth bloom, soft glyph shadow, and exact spline neon-tube opacity flicker sequence (0->50->25->75->50->100% over 233ms).",
        "best_for": "Dramatic reveals, suspense/plot twists, GTA 6 leaks, punchy talking-head emphasis.",
        "alignment": "Exact ink_bb pixel-centered (+/-1px) directly on the flush zero-gap seam (y=816 @ 2K) with zero black bar.",
    },
    "inverted": {
        "name": "The Inverted (Color-Corrected)",
        "source_recipe": "Victor Grubbe (TWIZ2_FlIB0) — Effect 4 (Secret Method)",
        "font": "Helvetica Neue Bold (-4.2% tracking)",
        "default_color": "auto",
        "supports_color": False,
        "visual_signature": "4:4:4 RGB anti-aliased alpha mask composited via negate + color-corrected contrast/gamma boost + maskedmerge over live moving footage — zero white edge artifacts.",
        "best_for": "Aesthetic full-bleed B-roll, trailers, cinematics, gameplay showcases where letters dynamically invert live video colors.",
        "alignment": "Flush zero-gap split-screen, dead-center X over upper-middle live gameplay well above Shorts/Reels UI safe zone.",
    },
}

_FLICKER_KEYFRAMES: tuple[tuple[float, float], ...] = (
    (0.000, 0.00),
    (0.033, 0.50),
    (0.067, 0.25),
    (0.100, 0.75),
    (0.167, 0.50),
    (0.233, 1.00),
)


def caption_catalog_payload() -> dict:
    """Machine-readable caption style catalog so coding agents (Claude Code, Antigravity, Cursor, Codex) can pick the right style automatically."""
    styles_out = {}
    for key, meta in CAPTION_STYLES.items():
        color_flag = f" --caption-color {meta['default_color']}" if meta["supports_color"] else ""
        styles_out[key] = {
            **meta,
            "cli_flag": f"--caption-style {key}",
            "command_template": (
                f'.venv/bin/python scripts/clip.py render "<VIDEO_OR_URL>" '
                f'--clip 120:150 --cam "iw*0.37:ih*0.43:0:ih*0.56" --layout aaron --quality 2k '
                f'--caption-style {key}{color_flag} --hook "Your Viral Hook" --out-dir output'
            ),
        }
    return {
        "version": "4.0.6",
        "zero_black_gap": True,
        "zero_external_editors": True,
        "default_style": "hormozi",
        "styles": styles_out,
        "caption_colors": {k: v["hex"] for k, v in CAPTION_COLORS.items()},
        "hook_themes": list(HOOK_SHINE_THEMES.keys()),
        "agent_instructions": (
            "Run `scripts/clip.py captions` to inspect styles, then pass `--caption-style <style>` "
            "(and optionally `--caption-color <color>`) to `scripts/clip.py render`. "
            "Flush zero-gap split-screen with +/-1px auto-alignment; zero external editors needed."
        ),
    }


def _normalize_caption_text(raw: str) -> str:
    """Keep clean natural mixed casing for editorial styles; normalize ALL-CAPS Whisper/mock tokens cleanly."""
    clean = re.sub(r"\s+", " ", raw.strip().replace("{", "").replace("}", ""))
    if not clean:
        return ""
    if clean.isupper() and len(clean) > 4:
        acronyms = {"GTA", "VI", "AI", "VIP", "FPS", "VOD", "NPC", "RP", "IRL", "W", "L", "OK", "WTF", "OMG", "USA", "NYC"}
        tokens = []
        for idx, tok in enumerate(clean.split(" ")):
            bare = re.sub(r"[^A-Z0-9]", "", tok)
            if bare in acronyms or bare == "I":
                tokens.append(tok)
            elif idx == 0:
                tokens.append(tok.capitalize())
            else:
                tokens.append(tok.lower())
        clean = " ".join(tokens)
    return clean


def _chunk_caption_words(
    words: list[dict],
    clip_start: float,
    clip_end: float,
    max_words: int = 3,
    max_chars: int = 20,
) -> list[dict]:
    """Group word timestamps into punchy single-line phrases with zero overlap."""
    dur = max(0.0, clip_end - clip_start)
    rel = []
    for w in words:
        if w["end"] > clip_start and w["start"] < clip_end:
            txt = str(w["word"]).strip().replace("{", "").replace("}", "")
            if txt:
                rel.append({
                    "word": txt,
                    "start": max(0.0, float(w["start"]) - clip_start),
                    "end": min(dur, float(w["end"]) - clip_start),
                })
    if not rel:
        return []

    chunks: list[dict] = []
    cur: list[dict] = []
    for w in rel:
        cand_txt = " ".join(x["word"] for x in cur + [w])
        pause = (w["start"] - cur[-1]["end"]) if cur else 0.0
        if cur and (len(cur) >= max_words or len(cand_txt) > max_chars or pause > 0.45):
            chunks.append({
                "text": _normalize_caption_text(" ".join(x["word"] for x in cur)),
                "start": cur[0]["start"],
                "end": max(cur[-1]["end"], cur[0]["start"] + 0.14),
            })
            cur = [w]
        else:
            cur.append(w)
    if cur:
        chunks.append({
            "text": _normalize_caption_text(" ".join(x["word"] for x in cur)),
            "start": cur[0]["start"],
            "end": max(cur[-1]["end"], cur[0]["start"] + 0.14),
        })
    for i in range(len(chunks) - 1):
        # Smooth tiny gaps (<0.12s) and prevent any overlap between adjacent phrases
        gap = chunks[i + 1]["start"] - chunks[i]["end"]
        if gap < 0.0:
            chunks[i]["end"] = chunks[i + 1]["start"]
        elif gap < 0.10:
            chunks[i]["end"] = chunks[i + 1]["start"]
    return [c for c in chunks if c["text"] and c["end"] > c["start"]]


def build_pro_captions_mov(
    words: list[dict],
    clip_start: float,
    clip_end: float,
    out_mov: Path,
    ffmpeg_bin: str,
    style: str = "shine",
    color: str = "auto",
    canvas_w: int = 1440,
    fps: int = 60,
) -> tuple[Path, int]:
    """v4.0.6: Render 60fps lossless pro caption strip (shine, stopmotion, flicker -> RGBA with soft glyph shadow; inverted -> full-range gray mask).

    Returns (mov_path, strip_h) where text ink is mathematically centered to +/-1px vertically at strip_h/2
    and horizontally at canvas_w/2, ready for flush zero-gap overlay or 4:4:4 RGB maskedmerge.
    """
    import numpy as np
    from PIL import Image, ImageDraw, ImageFilter, ImageFont

    if style not in ("shine", "stopmotion", "flicker", "inverted"):
        raise ValueError(f"Unsupported pro caption style: {style}")

    duration = max(0.2, clip_end - clip_start)
    scale = canvas_w / 1080.0
    strip_h = (int(round(216 * scale)) // 2) * 2
    chunks = _chunk_caption_words(words, clip_start, clip_end, max_words=3, max_chars=19 if style == "inverted" else 22)

    eff_color = CAPTION_STYLES[style]["default_color"] if color == "auto" else color
    col_spec = CAPTION_COLORS.get(eff_color, CAPTION_COLORS["green"])
    fill_rgb = np.array(col_spec["fill"], dtype=np.float32)
    glow_rgb = np.array(col_spec["glow"], dtype=np.float32)
    hi_rgb = np.array(col_spec["hi"], dtype=np.float32)

    def ease_out_cubic(t: float) -> float:
        t = max(0.0, min(1.0, t))
        return 1.0 - (1.0 - t) ** 3

    def ease_in_out_cubic(t: float) -> float:
        t = max(0.0, min(1.0, t))
        return 4.0 * t * t * t if t < 0.5 else 1.0 - ((-2.0 * t + 2.0) ** 3) / 2.0

    def flicker_opacity(dt: float) -> float:
        if dt <= 0.0:
            return 0.0
        if dt >= _FLICKER_KEYFRAMES[-1][0]:
            return 1.0
        for i in range(len(_FLICKER_KEYFRAMES) - 1):
            t0, v0 = _FLICKER_KEYFRAMES[i]
            t1, v1 = _FLICKER_KEYFRAMES[i + 1]
            if t0 <= dt <= t1:
                p = ease_in_out_cubic((dt - t0) / max(1e-5, t1 - t0))
                return v0 + (v1 - v0) * p
        return 1.0

    def load_caption_font(sz: int):
        if style == "stopmotion":
            if BASKERVILLE_TTC.exists():
                return ImageFont.truetype(str(BASKERVILLE_TTC), sz, index=3)
            if GEORGIA_BOLD_ITALIC_TTF.exists():
                return ImageFont.truetype(str(GEORGIA_BOLD_ITALIC_TTF), sz, index=0)
        if HELVETICA_NEUE_TTC.exists():
            return ImageFont.truetype(str(HELVETICA_NEUE_TTC), sz, index=1)
        return ImageFont.truetype(str(IMPACT_TTF), sz) if IMPACT_TTF.exists() else ImageFont.load_default()

    # v4.0.6: Bold cinema sizing directly over flush zero-gap footage (no cramped black bar!)
    if style == "inverted":
        base_fpx = int(round(68 * scale))
        tracking = -0.042
    elif style == "stopmotion":
        base_fpx = int(round(62 * scale))
        tracking = -0.015
    else:
        base_fpx = int(round(58 * scale))
        tracking = -0.042

    pad = int(round(62 * scale))
    max_w = int(round(canvas_w * 0.86))
    strip_cy = strip_h / 2.0

    def prep_chunk(text: str) -> dict:
        fpx = base_fpx
        for _ in range(5):
            fnt = load_caption_font(fpx)
            probe = ImageDraw.Draw(Image.new("L", (16, 16), 0))
            cap_bb = probe.textbbox((0, 0), "H", font=fnt)
            xs, cx = [], 0.0
            min_y, max_y = 10**9, -10**9
            for idx, ch in enumerate(text):
                adv = probe.textlength(ch, font=fnt)
                bb = probe.textbbox((cx, 0), ch, font=fnt)
                xs.append((ch, cx, bb))
                min_y, max_y = min(min_y, bb[1]), max(max_y, bb[3])
                cx += adv + (fpx * tracking if idx < len(text) - 1 else 0.0)
            min_x = min(b[0] for _, _, b in xs)
            max_x = max(b[2] for _, _, b in xs)
            iw = max(2, int(math.ceil(max_x - min_x)))
            if iw <= max_w or fpx <= 24:
                ih = max(2, int(math.ceil(max_y - min_y)))
                w, h = iw + 2 * pad, ih + 2 * pad
                mask = Image.new("L", (w, h), 0)
                d = ImageDraw.Draw(mask)
                for ch, x0, _ in xs:
                    d.text((pad + x0 - min_x, pad - min_y), ch, font=fnt, fill=255)
                # Measure actual rendered ink pixel bounds (fixes italic slant/serif overhang to +/-1px)
                ink_bb = mask.point(lambda v: 255 if v >= 32 else 0).getbbox() or (pad, pad, pad + iw, pad + ih)
                ax0, ay0, ax1, ay1 = ink_bb
                ink_cx = (ax0 + ax1) * 0.5
                ink_cy = (ay0 + ay1) * 0.5
                # Anchor visually on cap-height midpoint (steady baseline across phrases)
                cap_mid_in_mask = pad + ((cap_bb[1] + cap_bb[3]) * 0.5) - min_y
                has_descender = (max_y - cap_bb[3]) > (3.0 * scale)
                anchor_y_in_mask = cap_mid_in_mask if has_descender else ink_cy
                paste_x = int(round(canvas_w * 0.5 - ink_cx))
                paste_y = int(round(strip_cy - anchor_y_in_mask))
                m_arr = np.asarray(mask, dtype=np.float32) / 255.0

                info: dict = {
                    "mask": mask, "m_arr": m_arr, "w": w, "h": h, "iw": iw, "ih": ih,
                    "paste_x": paste_x, "paste_y": paste_y,
                }
                if style == "inverted":
                    return info

                # Rich subtle vertical depth gradient on glyph fill (avoids flat look while preserving exact hue)
                gy = np.linspace(0.0, 1.0, max(1, ih), dtype=np.float32)[:, None, None]
                c_top = np.clip(fill_rgb * 0.78 + hi_rgb * 0.22, 0, 255)
                c_bot = np.clip(fill_rgb * 0.84, 0, 255)
                g_ink = c_top * (1.0 - gy) + c_bot * gy
                grad = np.zeros((h, w, 3), dtype=np.float32)
                grad[pad : pad + ih, :] = g_ink
                grad[:pad, :] = c_top
                grad[pad + ih :, :] = c_bot
                info["grad"] = grad

                # Soft invisible-edge glyph-hugging drop shadow (zero bar/box!) so glow stays crisp over bright flush footage
                sh_tight = np.asarray(mask.filter(ImageFilter.GaussianBlur(radius=7.5 * scale)), dtype=np.float32) / 255.0
                sh_wide = np.asarray(mask.filter(ImageFilter.GaussianBlur(radius=18.0 * scale)), dtype=np.float32) / 255.0
                sh_dy = max(2, int(round(3.0 * scale)))
                sh_tight = np.roll(sh_tight, sh_dy, axis=0)
                sh_wide = np.roll(sh_wide, sh_dy, axis=0)
                info["shadow_a"] = np.clip(sh_tight * 0.78 + sh_wide * 0.36, 0.0, 0.90)

                if style == "shine":
                    g1 = np.asarray(mask.filter(ImageFilter.GaussianBlur(radius=3.8 * scale)), dtype=np.float32) / 255.0
                    g2 = np.asarray(mask.filter(ImageFilter.GaussianBlur(radius=11.0 * scale)), dtype=np.float32) / 255.0
                    g3 = np.asarray(mask.filter(ImageFilter.GaussianBlur(radius=23.0 * scale)), dtype=np.float32) / 255.0
                    info["glow_a"] = np.clip(g1 * 0.62 + g2 * 0.48 + g3 * 0.34, 0.0, 1.0)
                    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
                    rad = math.radians(-28.0)
                    info["u"] = (xx - pad) * math.cos(rad) - (yy - (pad + ih * 0.5)) * math.sin(rad)
                elif style == "flicker":
                    g1 = np.asarray(mask.filter(ImageFilter.GaussianBlur(radius=3.8 * scale)), dtype=np.float32) / 255.0
                    g2 = np.asarray(mask.filter(ImageFilter.GaussianBlur(radius=12.5 * scale)), dtype=np.float32) / 255.0
                    g3 = np.asarray(mask.filter(ImageFilter.GaussianBlur(radius=22.0 * scale)), dtype=np.float32) / 255.0
                    info["glow_a"] = np.clip(g1 * 0.44 + g2 * 0.36 + g3 * 0.22, 0.0, 1.0)
                elif style == "stopmotion":
                    g1 = np.asarray(mask.filter(ImageFilter.GaussianBlur(radius=2.8 * scale)), dtype=np.float32) / 255.0
                    g2 = np.asarray(mask.filter(ImageFilter.GaussianBlur(radius=9.0 * scale)), dtype=np.float32) / 255.0
                    info["glow_a"] = np.clip(g1 * 0.28 + g2 * 0.26, 0.0, 1.0)
                return info
            fpx = max(24, int(round(fpx * (max_w / iw))))
        raise RuntimeError("Unreachable caption layout loop")

    def composite_rgba_patch(
        rgb: np.ndarray,
        ta: np.ndarray,
        ga: np.ndarray,
        sa: np.ndarray,
        alpha_mult: float = 1.0,
    ) -> Image.Image:
        # Porter-Duff source-over: Text over Optical Bloom over Soft Glyph-Hugging Drop Shadow (rgb=0)
        ta_e = np.clip(ta * alpha_mult, 0.0, 1.0)
        ga_e = np.clip(ga * alpha_mult, 0.0, 1.0)
        sa_e = np.clip(sa * alpha_mult, 0.0, 1.0)
        bg_a = ga_e + sa_e * (1.0 - ga_e)
        bg_rgb_pre = glow_rgb[None, None, :] * ga_e[:, :, None]
        out_a = ta_e + bg_a * (1.0 - ta_e)
        out_rgb_pre = rgb * ta_e[:, :, None] + bg_rgb_pre * (1.0 - ta_e)[:, :, None]
        safe_a = np.where(out_a > 1e-4, out_a, 1.0)
        out_rgb = out_rgb_pre / safe_a[:, :, None]
        rgba = np.zeros((rgb.shape[0], rgb.shape[1], 4), dtype=np.uint8)
        rgba[:, :, :3] = np.clip(out_rgb, 0, 255).astype(np.uint8)
        rgba[:, :, 3] = np.clip(out_a * 255.0, 0, 255).astype(np.uint8)
        return Image.fromarray(rgba, "RGBA")

    def place_on_strip(patch: Image.Image, info: dict, sc: float = 1.0, dx: int = 0, dy: int = 0) -> bytes:
        mode = "L" if style == "inverted" else "RGBA"
        bg = 0 if mode == "L" else (0, 0, 0, 0)
        im = patch
        px = info["paste_x"] + dx
        py = info["paste_y"] + dy
        if abs(sc - 1.0) > 0.002:
            nw = max(2, int(round(im.width * sc)))
            nh = max(2, int(round(im.height * sc)))
            im = im.resize((nw, nh), Image.Resampling.BILINEAR)
            px = int(round(px + (info["w"] - nw) * 0.5))
            py = int(round(py + (info["h"] - nh) * 0.5))
        strip = Image.new(mode, (canvas_w, strip_h), bg)
        strip.paste(im, (px, py))
        return strip.tobytes()

    prepped: list[dict] = []
    for c in chunks:
        info = prep_chunk(c["text"])
        info["start"] = c["start"]
        info["end"] = c["end"]
        info["dur"] = max(0.14, c["end"] - c["start"])
        # Precompute steady settled frame bytes for fast O(1) reuse once entrance finishes
        if style == "inverted":
            info["steady_bytes"] = place_on_strip(info["mask"], info)
        elif style in ("flicker", "stopmotion"):
            patch = composite_rgba_patch(info["grad"], info["m_arr"], info["glow_a"], info["shadow_a"], 1.0)
            info["steady_bytes"] = place_on_strip(patch, info)
        prepped.append(info)

    is_mask = style == "inverted"
    pix_in = "gray" if is_mask else "rgba"
    pix_out = "gray" if is_mask else "argb"
    blank_bytes = bytes(canvas_w * strip_h * (1 if is_mask else 4))
    n_frames = max(12, int(math.ceil(duration * fps)) + 4)

    proc = subprocess.Popen(
        [
            ffmpeg_bin, "-y", "-f", "rawvideo", "-vcodec", "rawvideo", "-pix_fmt", pix_in,
            "-s", f"{canvas_w}x{strip_h}", "-r", str(fps), "-i", "-",
            "-c:v", "qtrle", "-pix_fmt", pix_out, str(out_mov),
        ],
        stdin=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert proc.stdin is not None

    c_idx = 0
    sm_cache: dict[tuple[int, int], bytes] = {}
    for f in range(n_frames):
        t = f / fps
        while c_idx < len(prepped) and t >= prepped[c_idx]["end"]:
            c_idx += 1
        if c_idx >= len(prepped) or t < prepped[c_idx]["start"]:
            proc.stdin.write(blank_bytes)
            continue

        info = prepped[c_idx]
        dt = t - info["start"]

        if style == "inverted":
            if dt >= 0.12:
                proc.stdin.write(info["steady_bytes"])
            else:
                p = ease_out_cubic(dt / 0.12)
                sc = 0.92 + 0.08 * p
                m_patch = info["mask"].point(lambda v, a=p: int(v * a))
                proc.stdin.write(place_on_strip(m_patch, info, sc=sc))
        elif style == "flicker":
            if dt >= 0.24:
                proc.stdin.write(info["steady_bytes"])
            else:
                op = flicker_opacity(dt)
                if op <= 0.01:
                    proc.stdin.write(blank_bytes)
                else:
                    ga = info["glow_a"] * (0.65 + 0.55 * (op ** 1.2))
                    patch = composite_rgba_patch(info["grad"], info["m_arr"], ga, info["shadow_a"], op)
                    proc.stdin.write(place_on_strip(patch, info))
        elif style == "stopmotion":
            # Quantize to 15 fps (frame_repeat = 4 at 60fps) for authentic tactile stop-motion cadence
            q_step = int((dt * fps) // 4)
            q_dt = (q_step * 4) / fps
            if q_dt >= 0.42:
                proc.stdin.write(info["steady_bytes"])
            else:
                cache_key = (c_idx, q_step)
                if cache_key not in sm_cache:
                    p = ease_out_cubic(q_dt / 0.42)
                    # Circular morphological erode-dilate dissolve via Gaussian level-set bounded strictly inside m_arr
                    erode_r = max(0.6, (1.0 - p) * 6.5 * scale)
                    blurred = np.asarray(
                        info["mask"].filter(ImageFilter.GaussianBlur(radius=erode_r)),
                        dtype=np.float32,
                    ) / 255.0
                    thr = 0.06 + 0.80 * (1.0 - p)
                    feather = 0.10 + 0.16 * (1.0 - p)
                    eroded = np.clip((blurred - thr) / feather, 0.0, 1.0) * info["m_arr"]
                    vis_a = ease_out_cubic(min(1.0, p * 1.45))
                    # Subtle tactile 1px stop-motion step during dissolve only; settles to exact (0, 0) center
                    jx = ((q_step * 7 + c_idx) % 3 - 1) if p < 0.96 else 0
                    jy = ((q_step * 5 + c_idx) % 3 - 1) if p < 0.96 else 0
                    ga = info["glow_a"] * (0.35 + 0.65 * p)
                    sa = info["shadow_a"] * (0.35 + 0.65 * p)
                    patch = composite_rgba_patch(info["grad"], eroded, ga, sa, vis_a)
                    sm_cache[cache_key] = place_on_strip(patch, info, dx=jx, dy=jy)
                proc.stdin.write(sm_cache[cache_key])
        else:
            # style == "shine": 3 parallel diagonal -28 deg light sweeps + 3-layer pulsing optical bloom
            in_p = ease_out_cubic(dt / 0.12) if dt < 0.12 else 1.0
            sc = 0.94 + 0.06 * in_p
            sweep_dur = max(0.85, min(1.35, info["dur"]))
            sweep_p = ease_in_out_cubic((dt % sweep_dur) / sweep_dur)
            pos = -0.35 + 1.70 * sweep_p
            iw = max(12.0, float(info["iw"]))
            u = info["u"]
            b1 = 0.48 * np.exp(-0.5 * ((u - (pos - 0.16) * iw) / max(10.0, iw * 0.045)) ** 2)
            b2 = 1.00 * np.exp(-0.5 * ((u - pos * iw) / max(16.0, iw * 0.095)) ** 2)
            b3 = 0.40 * np.exp(-0.5 * ((u - (pos + 0.17) * iw) / max(10.0, iw * 0.042)) ** 2)
            shine = np.clip(b1 + b2 + b3, 0.0, 1.15).astype(np.float32)
            # Blend smoothly toward bright specular white-tinted highlight along the 3 diagonal beams
            spec_rgb = np.clip(info["grad"] + shine[:, :, None] * (255.0 - info["grad"] * 0.55), 0, 255)
            pulse = 1.0 + 0.30 * math.exp(-((pos - 0.5) / 0.36) ** 2)
            patch = composite_rgba_patch(spec_rgb, info["m_arr"], info["glow_a"] * pulse, info["shadow_a"], in_p)
            proc.stdin.write(place_on_strip(patch, info, sc=sc))

    proc.stdin.close()
    err = proc.stderr.read().decode("utf-8", errors="ignore") if proc.stderr else ""
    if proc.wait() != 0:
        raise RuntimeError(f"Pro caption render ({style}) failed:\n{err[-800:]}")
    return out_mov, strip_h


def build_hormozi_ass(
    words: list[dict],
    clip_start: float,
    clip_end: float,
    ass_path: Path,
    font_name: str = "Impact",
    font_size: int = 72,
    pos_y: int = 612,
    chunk_size: int = 3,
    hook_text: str | None = None,
    layout: str = "aaron",
    embed_hook_in_ass: bool = False,
) -> Path:
    """Rule C (v4.0.6): Bold italic karaoke with crisp stroke + drop shadow cleanly straddling the flush zero-gap seam."""
    clip_words = [
        {
            "word": w["word"].upper().replace("{", "").replace("}", ""),
            "start": max(0.0, w["start"] - clip_start),
            "end": min(clip_end - clip_start, w["end"] - clip_start),
        }
        for w in words
        if w["end"] > clip_start and w["start"] < clip_end
    ]

    italic_flag = 1 if layout == "aaron" else 0
    hook_style = (
        f"Style: Hook,{font_name},60,&H00FFFFFF,&H00FFFFFF,&H00000000,&H90000000,1,1,0,0,100,100,1,0,1,4,2,5,60,60,40,1"
        if layout == "aaron"
        else f"Style: Hook,{font_name},56,&H0000FFFF,&H00FFFFFF,&H00000000,&HC0000000,1,0,0,0,100,100,1,0,1,4,2,5,40,40,40,1"
    )
    hook_y = 850 if layout == "aaron" else 445

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font_name},{font_size},&H00FFFFFF,&H0000FFFF,&H00000000,&H90000000,1,{italic_flag},0,0,100,100,1,0,1,5,2,5,40,40,40,1
{hook_style}

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    if hook_text and embed_hook_in_ass:
        clean_hook = _wrap_hook_lines(hook_text.strip().upper().replace("{", "").replace("}", ""))
        hook_end = min(2.6, max(1.0, clip_end - clip_start))
        lines.append(
            f"Dialogue: 2,0:00:00.00,{fmt_ass_time(hook_end)},Hook,,0,0,0,,"
            rf"{{\an5\pos(540,{hook_y})\fad(60,260)\fscx105\fscy105\t(0,110,\fscx100\fscy100)}}{clean_hook}" + "\n"
        )

    for i in range(0, len(clip_words), chunk_size):
        chunk = clip_words[i : i + chunk_size]
        for active_idx, active_w in enumerate(chunk):
            t0 = active_w["start"]
            t1 = chunk[active_idx + 1]["start"] if active_idx + 1 < len(chunk) else active_w["end"]
            t1 = max(t1, t0 + 0.08)
            rendered = []
            for j, w in enumerate(chunk):
                if j == active_idx:
                    rendered.append(
                        r"{\c&H0000FFFF&\fscx108\fscy108\t(0,80,\fscx100\fscy100)}"
                        + w["word"]
                        + r"{\r}"
                    )
                else:
                    rendered.append(w["word"])
            text = rf"{{\an5\pos(540,{pos_y})}}" + " ".join(rendered)
            lines.append(
                f"Dialogue: 0,{fmt_ass_time(t0)},{fmt_ass_time(t1)},Default,,0,0,0,,{text}\n"
            )

    ass_path.write_text("".join(lines), encoding="utf-8")
    return ass_path


def escape_filter_path(path: Path) -> str:
    return str(path).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def detect_top_black_bar(source_path: Path, sample_t: float, work_dir: Path, ffmpeg_bin: str) -> int:
    """v4.0.3: Detect solid black OBS/letterbox header strip at top of source frame (px) so caption lane stays dead-center."""
    import numpy as np
    from PIL import Image

    probe_png = work_dir / "letterbox_probe.png"
    try:
        run([ffmpeg_bin, "-y", "-ss", f"{max(0.0, sample_t):.2f}", "-i", str(source_path), "-frames:v", "1", str(probe_png)])
        if not probe_png.is_file():
            return 0
        arr = np.asarray(Image.open(probe_png).convert("RGB"))
        h, w, _ = arr.shape
        # Check central 50% width (avoids corner overlays/viewer counters) up to 14% of height
        mid = arr[: int(h * 0.14), int(w * 0.25) : int(w * 0.75), :]
        row_p90 = np.percentile(mid.max(axis=2), 90, axis=1)
        bar = 0
        for v in row_p90:
            if v < 18:
                bar += 1
            else:
                break
        return (bar // 2) * 2 if bar >= 8 else 0
    except Exception:
        return 0


def build_filtergraph(
    ass_path: Path | None,
    cam_crop: str | None,
    zoom_peaks: list[tuple[float, float]] | None = None,
    layout: str = "aaron",
    canvas_w: int = 1080,
    canvas_h: int = 1920,
    sharpen: bool = True,
    game_top_crop: int = 0,
) -> str:
    """Rule A + Rule B + Rule C composite filtergraph (v4.0.6 Zero-Gap Flush Split-Screen + Anti-Blur 2K).

    Zero black divider gap between facecam & gameplay:
      - 2K (1440x2560): 816 cam + 1744 game = 2560 flush edge-to-edge (exact seam y=816)
      - 1080p (1080x1920): 612 cam + 1308 game = 1920 flush edge-to-edge (exact seam y=612)
      - Pre-upscale macroblock + noise cleanup (`deblock` + light `hqdn3d`)
      - Single-pass `lanczos+accurate_rnd+full_chroma_int` scaling on both base and zoom branches
      - Post-upscale AMD FidelityFX CAS (`cas`) + luma-only fine edge recovery (`unsharp`)
    """
    ass_escaped = escape_filter_path(ass_path) if ass_path else ""
    fonts_dir = escape_filter_path(FONTS_DIR)
    hq_flags = "flags=lanczos+accurate_rnd+full_chroma_int"
    cam_pre = "deblock=filter=weak:block=8:alpha=0.06:beta=0.04,hqdn3d=1.0:0.8:2.0:1.5," if sharpen else ""
    cam_post = ",cas=strength=0.60,unsharp=3:3:0.50:3:3:0.0" if sharpen else ""
    game_post = ",cas=strength=0.35" if sharpen else ""
    full_post = ",cas=strength=0.45,unsharp=3:3:0.35:3:3:0.0" if sharpen else ""

    if cam_crop and layout == "aaron":
        cam_w = canvas_w
        # v4.0.6: Flush zero-gap edge-to-edge split-screen (ZERO black bar between facecam & gameplay!)
        # 2K (1440x2560): 816 cam + 1744 game = 2560 (seam y=816 = exact 612 in 1920-space)
        # 1080p (1080x1920): 612 cam + 1308 game = 1920 (seam y=612)
        cam_h = 816 if canvas_h >= 2560 else 612
        game_w = canvas_w
        game_h = canvas_h - cam_h
        # Tightened 1.10x punch (even dimensions) avoids over-stretching small streamer facecams
        zw = (int(round(cam_w * 1.10)) // 2) * 2
        zh = (int(round(cam_h * 1.10)) // 2) * 2
        grade = ",eq=brightness=0.04:contrast=1.08:saturation=1.12"
        if zoom_peaks:
            cond = "+".join(f"between(t\\,{t0:.2f}\\,{t1:.2f})" for t0, t1 in zoom_peaks)
            cam_chain = (
                f"[cam_src]crop={cam_crop},{cam_pre}split=2[cam_z0][cam_z1];"
                f"[cam_z0]scale={cam_w}:{cam_h}:force_original_aspect_ratio=increase:{hq_flags},"
                f"crop={cam_w}:{cam_h}{cam_post}[cam_base];"
                f"[cam_z1]scale={zw}:{zh}:force_original_aspect_ratio=increase:{hq_flags},"
                f"crop={cam_w}:{cam_h}:(iw-{cam_w})/2:(ih-{cam_h})/2{cam_post}[cam_zoom];"
                f"[cam_base][cam_zoom]overlay=0:0:enable='gt({cond},0)'{grade}[cam];"
            )
        else:
            cam_chain = (
                f"[cam_src]crop={cam_crop},{cam_pre}"
                f"scale={cam_w}:{cam_h}:force_original_aspect_ratio=increase:{hq_flags},"
                f"crop={cam_w}:{cam_h}{cam_post}{grade}[cam];"
            )
        top_trim = f"crop=iw:ih-{game_top_crop}:0:{game_top_crop}," if game_top_crop > 0 else ""
        tail = (
            f"[cam][game]vstack=inputs=2[stacked];[stacked]ass='{ass_escaped}':fontsdir='{fonts_dir}'[vout]"
            if ass_path
            else "[cam][game]vstack=inputs=2[vout]"
        )
        return (
            "[0:v]setpts=PTS-STARTPTS,fps=60,split=2[cam_src][game_src];"
            + cam_chain
            + f"[game_src]{top_trim}crop='min(iw,ih*{game_w}/{game_h})':ih:(iw-'min(iw,ih*{game_w}/{game_h})')/2:0,"
            f"scale={game_w}:{game_h}:{hq_flags}{game_post}{grade}[game];"
            + tail
        )

    if cam_crop:
        scale_f = canvas_w / 1080.0
        cw = (int(round(620 * scale_f)) // 2) * 2
        ch = (int(round(400 * scale_f)) // 2) * 2
        zw = (int(round(cw * 1.10)) // 2) * 2
        zh = (int(round(ch * 1.10)) // 2) * 2
        gh = (int(round(1440 * scale_f)) // 2) * 2
        gy = (int(round(440 * scale_f)) // 2) * 2
        if zoom_peaks:
            cond = "+".join(f"between(t\\,{t0:.2f}\\,{t1:.2f})" for t0, t1 in zoom_peaks)
            cam_chain = (
                f"[cam_src]crop={cam_crop},{cam_pre}split=2[cam_z0][cam_z1];"
                f"[cam_z0]scale={cw}:{ch}:force_original_aspect_ratio=increase:{hq_flags},"
                f"crop={cw}:{ch}{cam_post}[cam_base];"
                f"[cam_z1]scale={zw}:{zh}:force_original_aspect_ratio=increase:{hq_flags},"
                f"crop={cw}:{ch}:(iw-{cw})/2:(ih-{ch})/2{cam_post}[cam_zoom];"
                f"[cam_base][cam_zoom]overlay=0:0:enable='gt({cond},0)'[cam];"
            )
        else:
            cam_chain = (
                f"[cam_src]crop={cam_crop},{cam_pre}"
                f"scale={cw}:{ch}:force_original_aspect_ratio=increase:{hq_flags},"
                f"crop={cw}:{ch}{cam_post}[cam];"
            )
        tail = (
            f"[s1][game]overlay=0:{gy}[s2];[s2]ass='{ass_escaped}':fontsdir='{fonts_dir}'[vout]"
            if ass_path
            else f"[s1][game]overlay=0:{gy}[vout]"
        )
        return (
            "[0:v]setpts=PTS-STARTPTS,fps=60,split=3[bg_src][cam_src][game_src];"
            f"[bg_src]scale={canvas_w}:{canvas_h}:force_original_aspect_ratio=increase:{hq_flags},"
            f"crop={canvas_w}:{canvas_h},boxblur=25:2,eq=brightness=-0.15[bg];"
            + cam_chain
            + "[game_src]crop='min(iw,ih*3/4)':ih:(iw-'min(iw,ih*3/4)')/2:0,"
            f"scale={canvas_w}:{gh}:{hq_flags}{game_post}[game];"
            "[bg][cam]overlay=(W-w)/2:0[s1];"
            + tail
        )

    if layout == "aaron":
        ass_tail = f",ass='{ass_escaped}':fontsdir='{fonts_dir}'" if ass_path else ""
        return (
            f"[0:v]setpts=PTS-STARTPTS,fps=60,{cam_pre}"
            "crop='min(iw,ih*9/16)':ih:(iw-'min(iw,ih*9/16)')/2:0,"
            f"scale={canvas_w}:{canvas_h}:{hq_flags}{full_post},"
            f"eq=brightness=0.04:contrast=1.08:saturation=1.12{ass_tail}[vout]"
        )
    gh = (int(round(1440 * (canvas_w / 1080.0))) // 2) * 2
    gy = (int(round(240 * (canvas_w / 1080.0))) // 2) * 2
    tail = (
        f"[bg][game]overlay=0:{gy}[s1];[s1]ass='{ass_escaped}':fontsdir='{fonts_dir}'[vout]"
        if ass_path
        else f"[bg][game]overlay=0:{gy}[vout]"
    )
    return (
        "[0:v]setpts=PTS-STARTPTS,fps=60,split=2[bg_src][game_src];"
        f"[bg_src]scale={canvas_w}:{canvas_h}:force_original_aspect_ratio=increase:{hq_flags},"
        f"crop={canvas_w}:{canvas_h},boxblur=25:2,eq=brightness=-0.15[bg];"
        "[game_src]crop='min(iw,ih*3/4)':ih:(iw-'min(iw,ih*3/4)')/2:0,"
        f"scale={canvas_w}:{gh}:{hq_flags}{game_post}[game];"
        + tail
    )


def verify_zero_drift(output_mp4: Path, ffprobe_bin: str, expected_w: int = 1080, expected_h: int = 1920) -> dict[str, float]:
    """Rule A: Verify via ffprobe that video & audio start_time == 0.000000 and dimensions match."""
    proc = run([
        ffprobe_bin, "-v", "error",
        "-show_entries", "stream=codec_type,start_time,width,height,duration",
        "-of", "json",
        str(output_mp4),
    ])
    streams = json.loads(proc.stdout).get("streams", [])
    starts: dict[str, float] = {}
    for s in streams:
        ctype = s.get("codec_type")
        if ctype in ("video", "audio"):
            st = float(s.get("start_time", "0"))
            starts[ctype] = st
            if abs(st) > 0.001:
                raise RuntimeError(f"DASH sync violation: {ctype} start_time={st:.6f} != 0.000000")
            if ctype == "video" and (s.get("width") != expected_w or s.get("height") != expected_h):
                raise RuntimeError(f"Canvas violation: {s.get('width')}x{s.get('height')} != {expected_w}x{expected_h}")
    if "video" not in starts or "audio" not in starts:
        raise RuntimeError(f"Expected both video and audio streams, got: {starts}")
    return starts


def render_clip(
    source_path: Path,
    start: float,
    end: float,
    output_mp4: Path,
    words: list[dict],
    work_dir: Path,
    ffmpeg_bin: str,
    ffprobe_bin: str,
    cam_crop: str | None = None,
    pos_y: int | None = None,
    hook_text: str | None = None,
    zoom_peaks: list[tuple[float, float]] | None = None,
    layout: str = "aaron",
    normalize_lufs: bool = True,
    cold_open_sfx: bool = False,
    quality: str = "2k",
    sharpen: bool = True,
    hook_theme: str = "blue",
    caption_style: str = "hormozi",
    caption_color: str = "auto",
) -> dict:
    """Steps 3-5: Slice with PTS zeroing, v4.0.6 flush zero-gap split-screen + pro motion captions + animated Viral Shine hook + -18 LUFS, verify."""
    duration = end - start
    if duration <= 0:
        raise ValueError(f"Invalid clip range: {start}..{end}")
    if caption_style not in CAPTION_STYLES:
        raise ValueError(f"Unknown caption_style '{caption_style}'. Choose from: {list(CAPTION_STYLES)}")

    canvas_w, canvas_h = (1440, 2560) if quality == "2k" else (1080, 1920)

    if pos_y is not None:
        eff_pos_y = pos_y
    elif caption_style == "hormozi":
        # v4.0.6: Centered directly on the flush zero-gap split-screen seam (y=612 -> 816px @ 2K)
        eff_pos_y = 612 if (layout == "aaron" and cam_crop) else 825
    elif caption_style == "inverted":
        # v4.0.6: Centered cleanly over live upper-middle gameplay well above Shorts/Reels bottom UI
        eff_pos_y = 1180 if (layout == "aaron" and cam_crop) else 1120
    else:
        # v4.0.6: Exact flush zero-gap seam midpoint (y=612 -> 816px @ 2K) with glyph-hugging contact shadow
        eff_pos_y = 612 if (layout == "aaron" and cam_crop) else 1120

    ass_path = (
        build_hormozi_ass(
            words, start, end, work_dir / f"{output_mp4.stem}.ass",
            pos_y=eff_pos_y, hook_text=hook_text, layout=layout, embed_hook_in_ass=False,
        )
        if caption_style == "hormozi"
        else None
    )
    game_top_crop = (
        detect_top_black_bar(source_path, start + min(0.5, duration * 0.25), work_dir, ffmpeg_bin)
        if (cam_crop and layout == "aaron")
        else 0
    )
    filter_complex = build_filtergraph(
        ass_path, cam_crop, zoom_peaks=zoom_peaks, layout=layout,
        canvas_w=canvas_w, canvas_h=canvas_h, sharpen=sharpen,
        game_top_crop=game_top_crop,
    )
    v_enc = video_encoder_args(ffmpeg_bin, quality=quality, canvas_h=canvas_h)
    af = "asetpts=PTS-STARTPTS,aresample=48000:async=1:first_pts=0"
    if normalize_lufs:
        # v4.0.1 Model B + Gold-Standard (139 pairs + 18 Gold): target crest ~2.3-2.5 + -18 LUFS
        # Guard: FFmpeg single-pass loudnorm requires >=3s of audio buffer to emit frames reliably
        af += ",acompressor=threshold=-20dB:ratio=3.0:attack=8:release=110"
        if duration >= 3.0:
            af += ",loudnorm=I=-18:TP=-1.5:LRA=8"
    output_mp4.parent.mkdir(parents=True, exist_ok=True)

    inputs = ["-ss", f"{start:.3f}", "-t", f"{duration:.3f}", "-i", str(source_path)]
    next_idx = 1
    fc_parts = [filter_complex]
    v_map = "[vout]"

    if caption_style != "hormozi" and words:
        cap_mov, strip_h = build_pro_captions_mov(
            words, start, end, work_dir / f"{output_mp4.stem}_cap_{caption_style}.mov",
            ffmpeg_bin=ffmpeg_bin, style=caption_style, color=caption_color,
            canvas_w=canvas_w,
        )
        inputs += ["-i", str(cap_mov)]
        cap_idx = next_idx
        next_idx += 1
        cap_cy = int(round(eff_pos_y * (canvas_h / 1920.0)))
        cap_top = max(0, min(canvas_h - strip_h, cap_cy - strip_h // 2))
        if caption_style == "inverted":
            fc_parts.append(
                f"[{cap_idx}:v]trim=duration={duration:.3f},setpts=PTS-STARTPTS,"
                f"pad={canvas_w}:{canvas_h}:0:{cap_top}:black,format=gbrp[cap_mask];"
                f"{v_map}split=2[v_inv_a][v_inv_b];"
                "[v_inv_a]format=gbrp[v_orig_rgb];"
                "[v_inv_b]format=gbrp,negate,eq=contrast=1.18:gamma=0.62:brightness=0.05:saturation=1.25,format=gbrp[v_inv_rgb];"
                "[v_orig_rgb][v_inv_rgb][cap_mask]maskedmerge,format=yuv420p[vcap]"
            )
        else:
            fc_parts.append(
                f"[{cap_idx}:v]format=rgba[cap_ovl];"
                f"{v_map}[cap_ovl]overlay=0:{cap_top}:eof_action=pass[vcap]"
            )
        v_map = "[vcap]"

    if hook_text:
        hook_end = min(2.6, max(1.0, duration))
        hook_mov = build_viral_shine_hook_mov(
            hook_text, work_dir / f"{output_mp4.stem}_hook.mov",
            ffmpeg_bin=ffmpeg_bin, duration=hook_end, canvas_w=canvas_w, theme=hook_theme,
        )
        inputs += ["-i", str(hook_mov)]
        hook_idx = next_idx
        next_idx += 1
        # Position cleanly floating in upper gameplay area with crisp breathing room below the flush seam
        hook_y_px = int(round((885 if layout == "aaron" else 445) * (canvas_h / 1920.0)))
        fc_parts.append(
            f"[{hook_idx}:v]format=rgba[hook_card];"
            f"{v_map}[hook_card]overlay=(W-w)/2:{hook_y_px}-h/2:eof_action=pass[vfinal]"
        )
        v_map = "[vfinal]"

    out_dur_args = ["-t", f"{duration:.3f}"] if caption_style == "inverted" else []
    if cold_open_sfx:
        inputs += ["-f", "lavfi", "-t", "0.26", "-i", "sine=frequency=62:sample_rate=48000"]
        sfx_idx = next_idx
        next_idx += 1
        fc_parts.append(
            f"[0:a:0]{af}[main_a];"
            f"[{sfx_idx}:a]aformat=sample_rates=48000:channel_layouts=stereo,afade=t=in:st=0:d=0.01,afade=t=out:st=0.04:d=0.22,volume=0.22[sfx];"
            "[main_a][sfx]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,asetpts=PTS-STARTPTS[aout]"
        )
        cmd = [
            ffmpeg_bin, "-y",
            *inputs,
            "-filter_complex", ";".join(fc_parts),
            "-map", v_map, "-map", "[aout]",
            *out_dur_args,
            *v_enc,
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "320k",
            "-movflags", "+faststart",
            str(output_mp4),
        ]
    else:
        cmd = [
            ffmpeg_bin, "-y",
            *inputs,
            "-filter_complex", ";".join(fc_parts),
            "-map", v_map, "-map", "0:a:0",
            "-af", af,
            *out_dur_args,
            *v_enc,
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "320k",
            "-movflags", "+faststart",
            str(output_mp4),
        ]
    run(cmd)
    starts = verify_zero_drift(output_mp4, ffprobe_bin, canvas_w, canvas_h)
    eff_color = CAPTION_STYLES[caption_style]["default_color"] if caption_color == "auto" else caption_color
    return {
        "output": str(output_mp4),
        "start": start,
        "end": end,
        "duration": round(duration, 3),
        "resolution": f"{canvas_w}x{canvas_h}",
        "quality": quality,
        "sharpen": sharpen,
        "layout": layout,
        "encoder": v_enc[1],
        "caption_style": caption_style,
        "caption_color": eff_color,
        "hook": hook_text,
        "hook_theme": hook_theme if hook_text else None,
        "zoom_windows": len(zoom_peaks or []),
        "lufs_normalized": normalize_lufs,
        "cold_open_sfx": cold_open_sfx,
        "stream_start_times": starts,
    }


def generate_thumbnail(frame_path: Path, out_jpg: Path, headline: str, badge: str = "TOP 15") -> Path:
    """Generate a high-CTR 1280x720 YouTube long-form thumbnail locally with Pillow + Impact."""
    from PIL import Image, ImageDraw, ImageEnhance, ImageFont

    img = Image.open(frame_path).convert("RGB").resize((1280, 720), Image.Resampling.LANCZOS)
    img = ImageEnhance.Contrast(img).enhance(1.18)
    img = ImageEnhance.Color(img).enhance(1.22)
    draw = ImageDraw.Draw(img, "RGBA")

    # Subtle bottom dark gradient bar for headline readability
    for y in range(470, 720):
        alpha = int(210 * (y - 470) / 250)
        draw.line([(0, y), (1280, y)], fill=(0, 0, 0, alpha))

    font_big = ImageFont.truetype(str(IMPACT_TTF), 92) if IMPACT_TTF.exists() else ImageFont.load_default()
    font_badge = ImageFont.truetype(str(IMPACT_TTF), 56) if IMPACT_TTF.exists() else ImageFont.load_default()

    # Top-left bright red badge
    badge_txt = badge.upper()
    draw.rounded_rectangle([(32, 28), (300, 112)], radius=14, fill=(225, 20, 20, 245), outline=(255, 255, 255, 255), width=4)
    draw.text((166, 70), badge_txt, font=font_badge, fill=(255, 255, 255, 255), anchor="mm", stroke_width=4, stroke_fill=(0, 0, 0, 255))

    # Bottom Electric Yellow + White centered headline
    draw.text(
        (640, 625),
        headline.upper()[:34],
        font=font_big,
        fill=(255, 229, 0, 255),
        anchor="mm",
        stroke_width=8,
        stroke_fill=(0, 0, 0, 255),
    )
    out_jpg.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_jpg, "JPEG", quality=93)
    return out_jpg


def compile_longform(
    manifest_json: Path,
    output_mp4: Path,
    thumbnail_out: Path | None = None,
    thumb_headline: str = "WILDEST GTA 6 MOMENTS!",
    quality: str = "ultra",
) -> dict:
    """Build a 1920x1080 @ 60fps ranked long-form compilation (v4.0.2: single-pass encode + lossless concat)."""
    ffmpeg_bin = find_ffmpeg()
    ffprobe_bin = find_ffprobe()
    items = json.loads(manifest_json.read_text(encoding="utf-8"))
    if not items:
        raise ValueError("Compilation manifest is empty.")

    v_enc = video_encoder_args(ffmpeg_bin, quality=quality, canvas_h=1080)
    with tempfile.TemporaryDirectory(prefix="longform_comp_") as tmp:
        work = Path(tmp)
        seg_files: list[Path] = []
        chapters: list[dict] = []
        cursor = 0.0

        for idx, item in enumerate(items):
            rank = item.get("rank", len(items) - idx)
            title = str(item["title"]).upper()
            src = Path(item["file"])
            start = float(item.get("start", 0.0))
            end = float(item["end"]) if "end" in item else None
            if end is None:
                dur_str = run([ffprobe_bin, "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(src)]).stdout.strip()
                dur = float(dur_str) - start
            else:
                dur = end - start

            ass_p = work / f"rank_{idx:02d}.ass"
            banner_end = min(3.6, dur)
            ass_p.write_text(
                f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Banner,Impact,72,&H00FFFFFF,&H0000FFFF,&H00000000,&H90000000,1,0,0,0,100,100,1,0,1,6,3,8,40,40,54,1
Style: Corner,Impact,52,&H0000FFFF,&H00FFFFFF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,5,2,7,36,36,28,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 1,0:00:00.00,{fmt_ass_time(banner_end)},Banner,,0,0,0,,{{\\an8\\pos(960,55)\\fad(120,350)\\fscx112\\fscy112\\t(0,140,\\fscx100\\fscy100)}}{{\\c&H0000FFFF&}}#{rank}{{\\c&H00FFFFFF&}}  {title}
Dialogue: 0,0:00:00.00,{fmt_ass_time(dur)},Corner,,0,0,0,,{{\\an7\\pos(36,28)}}#{rank}
""",
                encoding="utf-8",
            )
            clip_mkv = work / f"seg_{idx:02d}.mkv"
            vf = (
                "setpts=PTS-STARTPTS,fps=60,"
                "scale=1920:1080:force_original_aspect_ratio=decrease:flags=lanczos+accurate_rnd+full_chroma_int,"
                "pad=1920:1080:(ow-iw)/2:(oh-ih)/2,cas=strength=0.30,"
                f"ass='{escape_filter_path(ass_p)}':fontsdir='{escape_filter_path(FONTS_DIR)}'"
            )
            af = f"asetpts=PTS-STARTPTS,aresample=48000:async=1:first_pts=0,afade=t=in:st=0:d=0.12,afade=t=out:st={max(0.1, dur-0.12):.3f}:d=0.12"
            run([
                ffmpeg_bin, "-y",
                "-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", str(src),
                "-map", "0:v:0", "-map", "0:a:0",
                "-vf", vf, "-af", af,
                *v_enc, "-bf", "0", "-pix_fmt", "yuv420p", "-g", "120",
                "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2",
                str(clip_mkv),
            ])
            seg_files.append(clip_mkv)
            cm, cs = divmod(int(round(cursor)), 60)
            chapters.append({"rank": rank, "timestamp": f"{cm}:{cs:02d}", "title": title, "duration_s": round(dur, 2)})
            cursor += dur

        concat_txt = work / "concat.txt"
        concat_txt.write_text("\n".join(f"file '{p}'" for p in seg_files) + "\n", encoding="utf-8")
        output_mp4.parent.mkdir(parents=True, exist_ok=True)
        # v4.0.2: Lossless video stream-copy concat + single-pass AAC audio (zero double-encode, exact 0.000s sync)
        run([
            ffmpeg_bin, "-y",
            "-f", "concat", "-safe", "0", "-i", str(concat_txt),
            "-c:v", "copy",
            "-af", "asetpts=PTS-STARTPTS,aresample=48000:async=1:first_pts=0",
            "-c:a", "aac", "-b:a", "256k", "-ar", "48000", "-ac", "2",
            "-movflags", "+faststart", str(output_mp4),
        ])
        starts = verify_zero_drift(output_mp4, ffprobe_bin, 1920, 1080)
        thumb_path = None
        if thumbnail_out:
            thumb_src = work / "thumb_src.png"
            run([ffmpeg_bin, "-y", "-ss", f"{min(1.5, cursor * 0.25):.2f}", "-i", str(output_mp4), "-frames:v", "1", str(thumb_src)])
            if thumb_src.is_file():
                thumb_path = str(generate_thumbnail(thumb_src, thumbnail_out, thumb_headline, badge=f"TOP {len(items)}"))

    return {
        "output": str(output_mp4),
        "duration_s": round(cursor, 2),
        "midroll_eligible_8min": cursor >= 480.0,
        "size_mb": round(output_mp4.stat().st_size / 1e6, 2),
        "thumbnail": thumb_path,
        "stream_start_times": starts,
        "chapters": chapters,
    }


# ===== v4.4.0 HUMAN VOICEOVER STUDIO + LONG-FORM DEEP DIVE ENGINE (CkOEHYjv6XU) =====
VOICE_PROVIDERS: dict[str, dict] = {
    "kokoro": {
        "id": "kokoro",
        "name": "Kokoro-82M Neural ONNX (Local · 100% Free · 0 API Key)",
        "free": True,
        "needs_api_key": False,
        "default_voice": "am_fenrir",
        "voices": {
            "hrl_navya": "HRL Navya — Expressive, Smiling Cheerful Female RJ & Gamer (10/10 Flow-Matched Clone · 'This is HRL Navya')",
            "hrl": "HRL Tech & Gaming Narrator — Deadpan, Rapid Sarcastic Explainer (1:1 Flow-Matched Clone · 'This is HRL')",
            "hrl_clone": "HRL Studio Clone (F5-TTS Neural Flow-Matching Engine)",
            "hybrid": "Hybrid Blend (60% Michael + 40% Fenrir) — Natural Conversational Reality & Streamer Breakdown",
            "am_fenrir": "American Male — Deep Documentary Narrator (GTA Deep Dive Default)",
            "am_michael": "American Male — Warm Conversational Storyteller",
            "am_adam": "American Male — Crisp Tech & Gaming Analyst",
            "am_puck": "American Male — Energetic Fast-Paced Explainer",
            "am_onyx": "American Male — Cinema Trailer Bass",
            "af_heart": "American Female — Natural Warm Studio Narrator (Kokoro Flagship)",
            "af_bella": "American Female — Bright All-American Storyteller (Hannah Twin)",
            "af_nicole": "American Female — Calm Authority Essayist",
            "bm_george": "British Male — BBC-Style Documentary Narrator",
            "bf_emma": "British Female — Crisp Editorial Narrator",
        },
        "where_to_get_key": "No API key needed! 100% free & offline on Apple Silicon via models/kokoro/kokoro-v1.0.int8.onnx.",
    },
    "elevenlabs": {
        "id": "elevenlabs",
        "name": "ElevenLabs Multilingual v2 (Cloud API Key · Free 10K Chars/Mo Tier)",
        "free": False,
        "needs_api_key": True,
        "env_key": "ELEVENLABS_API_KEY",
        "default_voice": "EXAVITQu4vr4xnSDxMaL",
        "voices": {
            "EXAVITQu4vr4xnSDxMaL": "Hannah / Bella — Bright, Natural All-American (Romayroh CkOEHYjv6XU Choice)",
            "pNInz6obpgDQGcFmaJgB": "Adam — Deep Documentary & Gaming Essay Narrator",
            "JBFqnCBsd6RMkjVDRZzb": "George — Warm British Storyteller",
            "21m00Tcm4TlvDq8ikWAM": "Rachel — Crisp Calm Explainer",
        },
        "where_to_get_key": "https://elevenlabs.io -> Bottom-Left 'Developers' -> 'API Keys' -> '+ Create Key' (Free tier includes 10,000 chars/mo).",
    },
    "gemini": {
        "id": "gemini",
        "name": "Google Gemini 2.5 Flash Native Audio TTS (Free API Key Tier)",
        "free": True,
        "needs_api_key": True,
        "env_key": "GEMINI_API_KEY",
        "default_voice": "Puck",
        "voices": {
            "Puck": "Upbeat Natural Conversational Narrator",
            "Charon": "Deep Informative Documentary Voice",
            "Kore": "Firm Clear Studio Voice",
            "Fenrir": "Excitable Dynamic Gaming Narrator",
            "Aoede": "Breezy Warm Storyteller",
        },
        "where_to_get_key": "https://aistudio.google.com/apikey -> 'Create API Key' (100% Free tier, no credit card required).",
    },
    "groq": {
        "id": "groq",
        "name": "Groq PlayAI Dialog TTS (Free Developer API Key Tier)",
        "free": True,
        "needs_api_key": True,
        "env_key": "GROQ_API_KEY",
        "default_voice": "Angelo-PlayAI",
        "voices": {
            "Angelo-PlayAI": "Natural American Male Narrator",
            "Arista-PlayAI": "Natural American Female Narrator",
            "Atlas-PlayAI": "Deep Authoritative Storyteller",
        },
        "where_to_get_key": "https://console.groq.com/keys -> 'Create API Key' (Free tier).",
    },
    "macos": {
        "id": "macos",
        "name": "macOS Apple Neural Speech (Built-In Offline Fallback · 0 API Key)",
        "free": True,
        "needs_api_key": False,
        "default_voice": "Daniel",
        "voices": {
            "Daniel": "British Male Studio Narrator",
            "Samantha": "American Female Assistant Narrator",
            "Eddy (English (US))": "American Male Conversational",
            "Flo (English (US))": "American Female Warm",
        },
        "where_to_get_key": "Built into macOS (/usr/bin/say) — zero key or download needed.",
    },
}


def find_kokoro_paths() -> tuple[Path, Path] | None:
    candidates = [
        BASE_DIR / "models" / "kokoro",
        BASE_DIR.parent / "models" / "kokoro",
        Path("/Users/pavankumars/.gemini/antigravity/scratch/shorts-clipper/models/kokoro"),
    ]
    for d in candidates:
        m = d / "kokoro-v1.0.int8.onnx"
        v = d / "voices-v1.0.bin"
        if m.is_file() and v.is_file():
            return m, v
    return None


def list_voice_catalog() -> dict:
    kokoro_paths = find_kokoro_paths()
    all_kokoro_voices: list[str] = []
    if kokoro_paths:
        try:
            from kokoro_onnx import Kokoro
            k = Kokoro(str(kokoro_paths[0]), str(kokoro_paths[1]))
            all_kokoro_voices = sorted(k.get_voices())
        except Exception:
            all_kokoro_voices = sorted(VOICE_PROVIDERS["kokoro"]["voices"].keys())
    return {
        "version": "4.4.0",
        "default_free_human_provider": "kokoro",
        "kokoro_installed_locally": kokoro_paths is not None,
        "kokoro_model_path": str(kokoro_paths[0]) if kokoro_paths else None,
        "kokoro_total_voices": len(all_kokoro_voices),
        "kokoro_all_voices": all_kokoro_voices,
        "providers": VOICE_PROVIDERS,
        "longform_deep_dive_skill": str(BASE_DIR / "gta_deep_dive" / "SKILL.md"),
    }


def synthesize_human_voice(
    text: str,
    out_wav: Path,
    provider: str = "kokoro",
    voice: str = "am_fenrir",
    speed: float = 1.0,
    api_key: str | None = None,
    align_words: bool = False,
) -> dict:
    """Synthesize natural human narration to 48kHz stereo broadcast WAV (-16 LUFS) with optional Whisper word timestamps."""
    import urllib.request
    import numpy as np

    clean_text = re.sub(r"\s+", " ", (text or "").strip())
    if not clean_text:
        raise ValueError("Narration text cannot be empty.")

    ffmpeg_bin = find_ffmpeg()
    prov = (provider or "kokoro").lower().strip()
    if prov not in VOICE_PROVIDERS:
        prov = "kokoro"

    out_wav = Path(out_wav).resolve()
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    used_provider = prov
    used_voice = voice or VOICE_PROVIDERS[prov]["default_voice"]

    with tempfile.TemporaryDirectory(prefix="lumvrix_vo_") as td:
        work = Path(td)
        raw_audio = work / "raw_vo.wav"

        if prov == "elevenlabs":
            key = (api_key or os.environ.get("ELEVENLABS_API_KEY") or "").strip()
            if not key:
                raise ValueError("ElevenLabs requires an API key (pass --api-key or set ELEVENLABS_API_KEY, or use free --provider kokoro).")
            vid = used_voice if len(used_voice) >= 15 else "EXAVITQu4vr4xnSDxMaL"
            url = f"https://api.elevenlabs.io/v1/text-to-speech/{vid}"
            assert urllib.parse.urlparse(url).hostname == "api.elevenlabs.io", "Invalid ElevenLabs API host"
            payload = json.dumps({
                "text": clean_text,
                "model_id": "eleven_multilingual_v2",
                "voice_settings": {"stability": 0.48, "similarity_boost": 0.82, "style": 0.18, "use_speaker_boost": True},
            }).encode("utf-8")
            req = urllib.request.Request(
                url, data=payload,
                headers={"xi-api-key": key, "Content-Type": "application/json", "Accept": "audio/mpeg", "User-Agent": "Resolve-Lumvrix/4.5.0"},
                method="POST",
            )
            mp3_p = work / "el.mp3"
            with urllib.request.urlopen(req, timeout=45) as resp:
                mp3_p.write_bytes(resp.read())
            raw_audio = mp3_p

        elif prov == "gemini":
            key = (api_key or os.environ.get("GEMINI_API_KEY") or "").strip()
            if not key:
                raise ValueError("Gemini TTS requires GEMINI_API_KEY from https://aistudio.google.com/apikey (or use free --provider kokoro).")
            g_voice = used_voice if used_voice in VOICE_PROVIDERS["gemini"]["voices"] else "Puck"
            url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-tts:generateContent"
            assert urllib.parse.urlparse(url).hostname == "generativelanguage.googleapis.com", "Invalid Google Generative Language API host"
            payload = json.dumps({
                "contents": [{"parts": [{"text": clean_text}]}],
                "generationConfig": {
                    "responseModalities": ["AUDIO"],
                    "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": g_voice}}},
                },
            }).encode("utf-8")
            req = urllib.request.Request(url, data=payload, headers={"x-goog-api-key": key, "Content-Type": "application/json", "User-Agent": "Resolve-Lumvrix/4.5.0"}, method="POST")
            import base64
            with urllib.request.urlopen(req, timeout=45) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            b64 = data["candidates"][0]["content"]["parts"][0]["inlineData"]["data"]
            pcm_bytes = base64.b64decode(b64)
            with wave.open(str(raw_audio), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(24000)
                wf.writeframes(pcm_bytes)
            used_voice = g_voice

        elif prov == "groq":
            key = (api_key or os.environ.get("GROQ_API_KEY") or "").strip()
            if not key:
                raise ValueError("Groq PlayAI TTS requires GROQ_API_KEY from https://console.groq.com/keys (or use free --provider kokoro).")
            gr_voice = used_voice if used_voice in VOICE_PROVIDERS["groq"]["voices"] else "Angelo-PlayAI"
            url = "https://api.groq.com/openai/v1/audio/speech"
            assert urllib.parse.urlparse(url).hostname == "api.groq.com", "Invalid Groq API host"
            req = urllib.request.Request(
                url,
                data=json.dumps({"model": "playai-tts", "input": clean_text, "voice": gr_voice, "response_format": "wav"}).encode("utf-8"),
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json", "User-Agent": "Resolve-Lumvrix/4.4.0"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=45) as resp:
                raw_audio.write_bytes(resp.read())
            used_voice = gr_voice

        elif prov == "kokoro":
            k_paths = find_kokoro_paths()
            if k_paths:
                from kokoro_onnx import Kokoro
                k = Kokoro(str(k_paths[0]), str(k_paths[1]))
                avail = set(k.get_voices())
                if used_voice.lower() in ("hybrid", "hybrid_blend", "blend", "hybrid_reality"):
                    voice_arg = 0.60 * k.get_voice_style("am_michael") + 0.40 * k.get_voice_style("am_fenrir")
                    lang = "en-us"
                else:
                    if used_voice not in avail:
                        used_voice = "am_fenrir" if "am_fenrir" in avail else "af_heart"
                    voice_arg = used_voice
                    lang = "en-gb" if used_voice.startswith("b") else "en-us"
                samples, sr = k.create(clean_text, voice=voice_arg, speed=max(0.65, min(1.45, float(speed))), lang=lang)
                pcm16 = np.clip(samples * 32767.0, -32768, 32767).astype(np.int16)
                with wave.open(str(raw_audio), "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(int(sr))
                    wf.writeframes(pcm16.tobytes())
            else:
                prov = "macos"
                used_provider = "macos"

        if prov == "macos":
            aiff = work / "mac.aiff"
            mac_voice = used_voice if used_voice in ("Daniel", "Samantha", "Fred") else "Daniel"
            wpm = str(int(round(175 * max(0.7, min(1.4, float(speed))))))
            run(["/usr/bin/say", "-v", mac_voice, "-r", wpm, "-o", str(aiff), clean_text])
            raw_audio = aiff
            used_voice = mac_voice

        # Master narration to 48kHz stereo PCM WAV with gentle compression & -16 LUFS broadcast leveling (matches assemble.py)
        probe_dur_str = run([
            find_ffprobe(), "-v", "error", "-show_entries", "format=duration",
            "-of", "default=nw=1:nk=1", str(raw_audio),
        ]).stdout.strip()
        raw_dur = float(probe_dur_str or 0.0)
        af = "asetpts=PTS-STARTPTS,aresample=48000,aformat=channel_layouts=stereo,acompressor=threshold=-20dB:ratio=2.5:attack=10:release=120"
        if raw_dur >= 3.0:
            af += ",loudnorm=I=-16:TP=-1.5:LRA=9"
        run([
            ffmpeg_bin, "-y", "-i", str(raw_audio),
            "-af", af, "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le",
            str(out_wav),
        ])

        final_dur = float(run([
            find_ffprobe(), "-v", "error", "-show_entries", "format=duration",
            "-of", "default=nw=1:nk=1", str(out_wav),
        ]).stdout.strip() or raw_dur)

        words_out = []
        if align_words:
            words_out = transcribe_words(out_wav, work, ffmpeg_bin, model_size="base.en")

    return {
        "ok": True,
        "provider": used_provider,
        "voice": used_voice,
        "speed": round(float(speed), 2),
        "text_chars": len(clean_text),
        "word_count": len(clean_text.split()),
        "duration_s": round(final_dur, 3),
        "output_wav": str(out_wav),
        "size_kb": round(out_wav.stat().st_size / 1024.0, 1),
        "words": words_out if align_words else None,
    }


def build_longform_deep_dive_demo(
    project_dir: Path,
    topic: str = "GTA 6 Can Do Things We Never Imagined in GTA 5",
    narration_text: str | None = None,
    provider: str = "kokoro",
    voice: str = "am_fenrir",
    speed: float = 1.02,
    api_key: str | None = None,
    source_video: Path | None = None,
    preview_only: bool = False,
) -> dict:
    """End-to-end GTA Deep Dive Long-Form Builder (Romayroh CkOEHYjv6XU workflow + 100% Free Local Kokoro Voice):
    1. Initializes project folders + procedural SFX (`hit.wav`, `whoosh.wav`, `tick.wav`, `riser.wav`)
    2. Synthesizes human voiceover (`audio/vo.wav`) using free local Kokoro-82M (or ElevenLabs / Gemini / Groq)
    3. Word-times narration (`audio/vo.json`) and generates 11 graphic card types (`cards/out/*.png`)
    4. Builds clause-cut EDL (`edit/edit.json` with -26dB game audio, -20dB music bed, music drop on reveal, credit pills)
    5. Assembles final 16:9 1080p MP4 + `credits.txt` via `gta_deep_dive/scripts/assemble.py`
    """
    skill_dir = BASE_DIR / "gta_deep_dive"
    if not (skill_dir / "scripts" / "assemble.py").is_file():
        raise FileNotFoundError(f"Missing gta_deep_dive scripts in {skill_dir}")

    project_dir = Path(project_dir).resolve()
    for sub_name in ("research", "script", "sources", "scans", "audio", "music", "sfx", "cards", "edit", "renders"):
        (project_dir / sub_name).mkdir(parents=True, exist_ok=True)

    default_script = (
        "In GTA 5, you can rob a store, turn two corners, and the police just give up. "
        "In GTA 6, they remember your shirt. "
        "What you wore, what you drove, and what you were holding. "
        "Every car runs on actual fuel, and your diet shows up on your body. "
        "Dazed put it best: the days of moving through the city without consequences are over. "
        "And there is one thing GTA 5 lets you do that GTA 6 took away completely."
    )
    script_txt = (narration_text or default_script).strip()
    (project_dir / "script" / "script.md").write_text(f"# {topic}\n\n{script_txt}\n", encoding="utf-8")

    # 1. Generate procedural YPP-safe SFX (hit, whoosh, tick, riser)
    run([sys.executable, str(skill_dir / "scripts" / "make_sfx.py"), str(project_dir / "sfx")])

    # 2. Synthesize natural human voiceover (`audio/vo.wav`) + word timestamps
    vo_wav = project_dir / "audio" / "vo.wav"
    vo_res = synthesize_human_voice(
        text=script_txt, out_wav=vo_wav, provider=provider, voice=voice,
        speed=speed, api_key=api_key, align_words=True,
    )
    vo_dur = max(12.0, float(vo_res["duration_s"]) + 0.8)
    (project_dir / "audio" / "vo.json").write_text(json.dumps(vo_res, indent=2), encoding="utf-8")

    # 3. Render Deep-Dive graphic overlay cards (`cards.py`)
    cards_spec = {
        "width": 1920,
        "height": 1080,
        "theme": {"accent": "#D1002D", "accent2": "#FFC24B", "paper": "#F6F3EE", "ink": "#141414", "night": "#120F1C"},
        "cards": [
            {"name": "stars_shirt", "kind": "stars", "total": 6, "filled": 3, "tag": "WITNESS ID", "icons": ["Shirt", "Plate", "Weapon"]},
            {"name": "stat_anims", "kind": "stat", "before": "55,000", "after": "600,000+", "label_before": "GTA V", "label_after": "GTA VI", "caption": "NPC & Police Response Animations"},
            {"name": "quote_dazed", "kind": "quote", "source": "DAZED · HANDS-ON REPORT",
             "text": "The world is more grounded and reactive than before, and the days of moving through the city without consequences are over.",
             "states": [["grounded and reactive"], ["grounded and reactive", "without consequences are over"]]},
            {"name": "ch_map_cops", "kind": "chapter", "nodes": ["Cops", "Body", "Duo", "Guns", "Cars", "Money", "People", "World"], "active": 0, "part": "PART 01", "title": "THE COPS"},
            {"name": "stamp_reveal", "kind": "stamp", "text": "6-STAR LOCKDOWN"},
            {"name": "label_gta5", "kind": "label", "text": "GTA V (2013)"},
            {"name": "label_gta6", "kind": "label", "text": "GTA VI · LEONIDA"},
        ],
    }
    cards_json = project_dir / "cards" / "cards.json"
    cards_out = project_dir / "cards" / "out"
    cards_json.write_text(json.dumps(cards_spec, indent=2), encoding="utf-8")
    run([sys.executable, str(skill_dir / "scripts" / "cards.py"), str(cards_json), str(cards_out)])

    # 4. Prepare 16:9 gameplay source & royalty-free ambient synth bed
    ffmpeg_bin = find_ffmpeg()
    src_mp4 = project_dir / "sources" / "gameplay_master.mp4"
    existing_day3 = sorted((BASE_DIR / "output" / "DAY3").glob("short_*.mp4"))
    pick_src = source_video if (source_video and Path(source_video).is_file()) else (existing_day3[0] if existing_day3 else None)
    need_dur = vo_dur + 4.0
    if pick_src:
        run([
            ffmpeg_bin, "-y", "-stream_loop", "-1", "-i", str(pick_src),
            "-t", f"{need_dur:.2f}",
            "-vf", "crop=iw:ih*0.56:0:ih*0.38,scale=1920:1080:flags=lanczos,format=yuv420p",
            "-r", "30", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
            "-c:a", "aac", "-b:a", "160k", str(src_mp4),
        ])
    else:
        run([
            ffmpeg_bin, "-y",
            "-f", "lavfi", "-i", f"testsrc2=size=1920x1080:rate=30:duration={need_dur:.2f}",
            "-f", "lavfi", "-i", f"sine=frequency=110:sample_rate=48000:duration={need_dur:.2f}",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", str(src_mp4),
        ])

    bed_wav = project_dir / "music" / "bed_synth.wav"
    run([
        ffmpeg_bin, "-y", "-f", "lavfi",
        "-i", f"aevalsrc='0.18*sin(2*PI*110*t)+0.12*sin(2*PI*164.81*t)+0.08*sin(2*PI*220*t)':s=48000:d={need_dur:.2f}",
        "-af", "lowpass=f=1200,aformat=channel_layouts=stereo", "-ar", "48000", str(bed_wav),
    ])

    # 5. Build clause-by-clause EDL (edit/edit.json) matching reference-breakdown.md
    s1 = round(vo_dur * 0.18, 2)
    s2 = round(vo_dur * 0.36, 2)
    s3 = round(vo_dur * 0.56, 2)
    s4 = round(vo_dur * 0.78, 2)
    s5 = round(vo_dur, 2)
    edl = {
        "width": 1920,
        "height": 1080,
        "fps": 30,
        "voice": {"source": "../audio/vo.wav", "start": 0.4, "gain_db": 0},
        "game_audio_db": -26,
        "shots": [
            {"start": 0.0, "end": s1, "source": "../sources/gameplay_master.mp4", "in": 0.0, "credit": "Rockstar Games", "game_db": -10, "note": "Cold open: GTA 5 contrast"},
            {"start": s1, "end": s2, "source": "../sources/gameplay_master.mp4", "in": 2.5, "credit": "Rockstar Games", "blur": 18, "dim": 0.45, "note": "GTA 6 6-star shirt witness card"},
            {"start": s2, "end": s3, "source": "../sources/gameplay_master.mp4", "in": 5.5, "credit": "HRL SPEED! GTA6", "zoom": 1.15, "focus": [0.5, 0.45], "note": "Fuel & body physics proof"},
            {"start": s3, "end": s4, "source": "../sources/gameplay_master.mp4", "in": 8.0, "credit": "Rockstar Games", "blur": 18, "dim": 0.45, "note": "Dazed press quote card"},
            {"start": s4, "end": s5, "source": "../sources/gameplay_master.mp4", "in": 11.0, "credit": "HRL SPEED! GTA6", "zoom": 1.12, "note": "Open-loop reveal with music drop"},
        ],
        "overlays": [
            {"image": "../cards/out/label_gta5.png", "start": 0.0, "end": s1, "fade_in": 0, "fade_out": 0},
            {"image": "../cards/out/stars_shirt.png", "start": s1 + 0.1, "end": s2, "fade_in": 0.12, "fade_out": 0.12},
            {"image": "../cards/out/label_gta6.png", "start": s2, "end": s3, "fade_in": 0, "fade_out": 0},
            {"image": "../cards/out/quote_dazed_2.png", "start": s3 + 0.1, "end": s4, "fade_in": 0.12, "fade_out": 0.12},
            {"image": "../cards/out/stamp_reveal.png", "start": s4 + 0.2, "end": s5 - 0.1, "fade_in": 0.06, "fade_out": 0.12},
        ],
        "music": [
            {"source": "../music/bed_synth.wav", "start": 0.4, "end": s5, "in": 0, "gain_db": -20, "fade_in": 0.8, "fade_out": 1.2},
        ],
        "music_drops": [
            {"start": max(0.5, s1 - 0.15), "end": s1 + 0.15},
            {"start": s4, "end": max(s4 + 0.5, s5 - 0.2)},
        ],
        "sfx": [
            {"source": "../sfx/hit.wav", "start": s1 + 0.08, "gain_db": -8},
            {"source": "../sfx/whoosh.wav", "start": s3 + 0.08, "gain_db": -9},
            {"source": "../sfx/hit.wav", "start": s4 + 0.18, "gain_db": -6},
        ],
    }
    edl_path = project_dir / "edit" / "edit.json"
    edl_path.write_text(json.dumps(edl, indent=2), encoding="utf-8")

    out_mp4 = project_dir / "renders" / f"deep_dive_{int(time.time())}.mp4"
    cmd = [sys.executable, str(skill_dir / "scripts" / "assemble.py"), str(edl_path), str(out_mp4)]
    if preview_only:
        cmd.append("--preview")
    run(cmd)
    credits_file = out_mp4.with_name(out_mp4.stem + "_credits.txt")
    return {
        "ok": True,
        "topic": topic,
        "project_dir": str(project_dir),
        "voiceover": vo_res,
        "cards_rendered": sorted(p.name for p in cards_out.glob("*.png")),
        "edl_path": str(edl_path),
        "output_mp4": str(out_mp4),
        "credits_file": str(credits_file) if credits_file.is_file() else None,
        "duration_s": round(s5, 2),
        "size_kb": round(out_mp4.stat().st_size / 1024.0, 1) if out_mp4.is_file() else 0.0,
    }


def trim_dead_air_bounds(wav_path: Path, start: float, end: float, max_trim_s: float = 2.0) -> tuple[float, float]:
    """v4.0 Model B dead-air trimmer: strips leading/trailing silence (flops average 2.0s dead air)."""
    import numpy as np

    with wave.open(str(wav_path), "rb") as wf:
        sr = wf.getframerate()
        pcm = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    if len(pcm) < sr * 2:
        return start, end
    step = int(sr * 0.05)
    frms = np.array([float(np.sqrt(np.mean(pcm[i : i + step] ** 2))) for i in range(0, len(pcm) - step + 1, step)])
    rms_all = float(np.sqrt(np.mean(pcm**2)))
    thr = max(0.008, rms_all * 0.14)
    lead = 0.0
    for v in frms:
        if v < thr and lead < max_trim_s:
            lead += 0.05
        else:
            break
    trail = 0.0
    for v in reversed(frms):
        if v < thr and trail < max_trim_s:
            trail += 0.05
        else:
            break
    ns = round(start + max(0.0, lead - 0.08), 2)
    ne = round(end - max(0.0, trail - 0.08), 2)
    return (ns, ne) if ne - ns >= 6.0 else (start, end)


def mine_viral_moments(
    wav_path: Path,
    words: list[dict],
    clip_dur: float = 30.0,
    top_n: int = 5,
    step_s: float = 4.0,
) -> list[dict]:
    """v4.5 VOD Moment Miner: snaps starts to clean phrase boundaries, guards 0-3s profanity,
    and scores candidate windows with the trained Model B Pairwise RankNet + hook coherence."""
    import numpy as np

    hook_re = re.compile(r"\?|no way|wait|what happens|can you|insane|crazy|bro|oh my|secret|never|actually|died|ending|real|betray", re.I)
    profanity_3s_re = re.compile(r"\b(fuck|fucker|fucking|motherfucker|bitch|nigga|cunt)\b", re.I)
    try:
        import viral_algorithm as va
        va_model = va.load_model()
    except Exception:
        va = None  # type: ignore[assignment]
        va_model = None

    with wave.open(str(wav_path), "rb") as wf:
        sr = wf.getframerate()
        pcm = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    total_s = len(pcm) / max(sr, 1)
    if total_s <= clip_dur:
        return [{"start": 0.0, "end": round(total_s, 2), "mine_score": 50.0, "opening_3s": " ".join(w["word"] for w in words if w["start"] < 3.0)}]

    # Candidate start times: step grid snapped to clean phrase starts (pause >=0.22s before word) when available
    phrase_starts = [
        float(w["start"])
        for i, w in enumerate(words)
        if float(w["start"]) + clip_dur <= total_s and (i == 0 or float(w["start"]) - float(words[i - 1]["end"]) >= 0.22)
    ]
    cands = []
    raw_t = 0.0
    seen_starts: set[int] = set()
    while raw_t + clip_dur <= total_s:
        near = [ps for ps in phrase_starts if abs(ps - raw_t) <= step_s * 0.6]
        t = min(near, key=lambda ps: abs(ps - raw_t)) if near else raw_t
        raw_t += step_s
        key_ms = int(round(t * 10))
        if key_ms in seen_starts or t + clip_dur > total_s:
            continue
        seen_starts.add(key_ms)

        seg = pcm[int(t * sr) : int((t + clip_dur) * sr)]
        rms_all = float(np.sqrt(np.mean(seg**2))) + 1e-6
        rms_15 = float(np.sqrt(np.mean(seg[: int(1.5 * sr)] ** 2)))
        open_ratio = rms_15 / rms_all
        st = int(sr * 0.05)
        frms = np.array([float(np.sqrt(np.mean(seg[i : i + st] ** 2))) for i in range(0, len(seg) - st + 1, st)])
        thresh = max(0.008, rms_all * 0.14)
        sil_frac = float((frms < thresh).mean()) if len(frms) else 0.5
        crest = float(np.percentile(frms, 95) / max(float(np.median(frms)), 1e-4)) if len(frms) else 3.0
        lead_sil = 0.0
        for v in frms:
            if v < thresh:
                lead_sil += 0.05
            else:
                break
        trail_sil = 0.0
        for v in reversed(frms):
            if v < thresh:
                trail_sil += 0.05
            else:
                break

        w3 = [w["word"] for w in words if t <= w["start"] < t + 3.0]
        w_all = [w["word"] for w in words if t <= w["start"] < t + clip_dur]
        w3_txt = " ".join(w3)
        hook_hit = 1.0 if hook_re.search(w3_txt) else 0.0
        early_profanity = bool(profanity_3s_re.search(w3_txt))
        wpm = len(w_all) / max(clip_dur / 60.0, 0.1)
        pace_bonus = 1.0 if 100.0 <= wpm <= 195.0 else (0.5 if wpm >= 65.0 else 0.0)

        mm_prob = 0.5
        if va is not None and va_model is not None:
            mm_res = va.predict_multimodal_prob({
                "motion_first_3s": 0.10,
                "motion_overall": 0.10,
                "brightness_t0": 0.34,
                "silence_frac": sil_frac,
                "leading_silence_s": lead_sil,
                "peak_crest_factor": crest,
                "has_disbelief_hook_3s": hook_hit,
                "duration_s": clip_dur,
                "trailing_silence_s": trail_sil,
                "opening_1_5s_rms_ratio": open_ratio,
            }, va_model)
            if mm_res:
                mm_prob = mm_res["multimodal_prob"]

        score = (
            36.0 * mm_prob
            + 22.0 * min(open_ratio, 1.45)
            + 14.0 * min(len(w3) / 8.0, 1.2)
            + 10.0 * (1.0 - min(sil_frac, 0.5) * 2.0)
            + 10.0 * hook_hit
            + 8.0 * pace_bonus
            - (18.0 if early_profanity else 0.0)
        )
        cands.append({
            "start": round(t, 2),
            "end": round(t + clip_dur, 2),
            "mine_score": round(max(1.0, score), 1),
            "ranknet_prob": round(mm_prob, 3),
            "opening_rms_ratio": round(open_ratio, 2),
            "opening_3s_words": len(w3),
            "total_words": len(w_all),
            "wpm": round(wpm, 1),
            "crest_factor": round(crest, 2),
            "silence_frac": round(sil_frac, 2),
            "clean_0_3s": not early_profanity,
            "opening_3s": w3_txt[:100],
        })

    cands.sort(key=lambda x: x["mine_score"], reverse=True)
    picked: list[dict] = []
    for c in cands:
        if all(abs(c["start"] - p["start"]) >= clip_dur * 0.85 for p in picked):
            picked.append(c)
            if len(picked) >= top_n:
                break
    return picked


def self_check() -> None:
    """Runnable v4.0 end-to-end check: VOD moment miner + full-bleed Aaron split-screen +
    climax cold-open + dynamic compression + -18 LUFS + v4.0 Dual-Stage audit + compilation + thumb."""
    ffmpeg_bin = find_ffmpeg()
    ffprobe_bin = find_ffprobe()
    import faster_whisper  # noqa: F401
    import PIL  # noqa: F401
    import yt_dlp  # noqa: F401

    with tempfile.TemporaryDirectory(prefix="shorts_check_") as tmp:
        work = Path(tmp)
        src = work / "synthetic_1080p.mp4"
        out_dir = work / "deliverables"
        out_mp4 = out_dir / "check_short.mp4"
        run([
            ffmpeg_bin, "-y",
            "-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=30:duration=7",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=7",
            "-af", "volume='if(between(t,4.5,6.8),0.95,0.18)':eval=frame",
            "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
            str(src),
        ])
        wav = work / "check.wav"
        run([ffmpeg_bin, "-y", "-i", str(src), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav)])
        peak = find_climax_window(wav, cold_dur=2.0)
        assert peak is not None and peak[0] >= 3.5, f"Climax detector missed loud window: {peak}"
        cold_src = build_cold_open_source(src, 0.0, 7.0, peak[0], 2.0, work, ffmpeg_bin)

        mock_words = [
            {"word": "AIRPORTS", "start": 0.1, "end": 0.6},
            {"word": "IN", "start": 0.6, "end": 0.9},
            {"word": "GTA", "start": 0.9, "end": 1.3},
            {"word": "SIX", "start": 1.3, "end": 1.8},
            {"word": "ARE", "start": 4.7, "end": 5.2},
            {"word": "INSANE!", "start": 5.2, "end": 6.4},
        ]
        mined = mine_viral_moments(wav, mock_words, clip_dur=3.0, top_n=2, step_s=1.0)
        assert len(mined) >= 1 and mined[0]["mine_score"] > 0, f"Miner check failed: {mined}"

        shifted = shift_words_for_cold_open(mock_words, 0.0, 7.0, peak[0], 2.0)
        # v4.0.2 default: 2K (1440x2560 @ 60fps, libx264 High Profile CRF 13 BT.709) — zero quality loss!
        result = render_clip(
            source_path=cold_src,
            start=0.0,
            end=9.0,
            output_mp4=out_mp4,
            words=shifted,
            work_dir=work,
            ffmpeg_bin=ffmpeg_bin,
            ffprobe_bin=ffprobe_bin,
            cam_crop="420:270:1480:790",
            hook_text="AIRPORTS IN GTA 6 ARE INSANE",
            zoom_peaks=[(0.2, 1.8), (6.5, 8.4)],
            layout="aaron",
            normalize_lufs=True,
            cold_open_sfx=True,
        )
        assert [p.name for p in out_dir.iterdir()] == ["check_short.mp4"], "Rule D cleanup violation"
        assert result["encoder"] == "libx264", f"Expected libx264 master encoder, got: {result['encoder']}"
        assert result["resolution"] == "1440x2560", f"Expected default 2K canvas 1440x2560, got: {result['resolution']}"

        probe_color = json.loads(run([
            ffprobe_bin, "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=color_space,profile,bit_rate", "-of", "json", str(out_mp4),
        ]).stdout)["streams"][0]
        assert probe_color.get("color_space") == "bt709", f"Expected bt709 color_space: {probe_color}"

        # Compare Laplacian edge sharpness (sharpen=True vs raw sharpen=False) on upscaled 2K facecam crop
        import numpy as np
        from PIL import Image
        out_raw = work / "check_nosharp.mp4"
        render_clip(
            source_path=src, start=0.0, end=1.0, output_mp4=out_raw,
            words=[], work_dir=work, ffmpeg_bin=ffmpeg_bin, ffprobe_bin=ffprobe_bin,
            cam_crop="420:270:1480:790", layout="aaron", quality="2k", sharpen=False,
        )
        sharp_scores = {}
        for tag, vid in (("v403_sharp", out_mp4), ("no_sharpen", out_raw)):
            fp = work / f"{tag}.png"
            run([ffmpeg_bin, "-y", "-ss", "0.5", "-i", str(vid), "-frames:v", "1", str(fp)])
            g = np.asarray(Image.open(fp).convert("L"), dtype=np.float32)[:816, :]
            lap = -4 * g[1:-1, 1:-1] + g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:]
            sharp_scores[tag] = round(float(lap.var()), 1)
        assert sharp_scores["v403_sharp"] > sharp_scores["no_sharpen"], f"Anti-blur sharpness check failed: {sharp_scores}"

        # v4.0.6: Verify ZERO black divider gap at flush split-screen seam (y=816 @ 2K)
        seam_frame = np.asarray(Image.open(work / "no_sharpen.png").convert("L"), dtype=np.float32)
        seam_row_means = seam_frame[800:832, :].mean(axis=1)
        assert float(seam_row_means.min()) > 15.0, f"Black gap detected near seam y=816: min_row_luma={seam_row_means.min():.1f}"

        forensics = None
        v4_score = None
        try:
            import viral_algorithm as va
            forensics = va.audit_video_forensics(out_mp4, opening_3s_words=8.0, has_disbelief_hook_3s=1.0)
            assert forensics["opening_1_5s_rms_ratio"] >= 1.05, f"Cold-open energy too low: {forensics}"
            assert forensics["fps"] >= 59.0, f"Expected 60fps: {forensics}"
            assert forensics["peak_crest_factor"] <= 3.1, f"Crest too high: {forensics}"
            assert forensics["brightness_t0"] > 0.25, f"Brightness check failed: {forensics}"
            v4_score = va.score_short(
                title="Airports in GTA 6 are Insane",
                duration_s=28.0,
                description="",
                tags=[],
                pub_hour_utc=21,
                video_path=out_mp4,
                opening_3s_words=8.0,
            )
            assert v4_score["model_b_multimodal"] is not None, "Model B multimodal score missing"
            assert v4_score["model_c_gold_centroid"] is not None, "Model C Gold Centroid missing"
            assert any("1440x2560" in p for p in v4_score["passes"]), f"Expected 1440x2560 pass in viral_algorithm: {v4_score['passes']}"
        except ImportError:
            pass

        # v4.0.6: Verify all 4 pro motion caption styles on flush zero-gap split-screen + pixel-exact seam centering
        style_words = [
            {"word": "GTA", "start": 0.05, "end": 0.45},
            {"word": "SIX", "start": 0.45, "end": 1.15},
        ]
        caption_checks: dict[str, dict] = {}
        for st in ("shine", "stopmotion", "flicker", "inverted"):
            st_mp4 = work / f"check_{st}.mp4"
            st_res = render_clip(
                source_path=src, start=0.0, end=1.2, output_mp4=st_mp4,
                words=style_words, work_dir=work, ffmpeg_bin=ffmpeg_bin, ffprobe_bin=ffprobe_bin,
                cam_crop="420:270:1480:790", layout="aaron", quality="2k",
                caption_style=st, normalize_lufs=False,
            )
            assert st_res["caption_style"] == st
            if st != "inverted":
                # Verify exact (+/-1px) centering of glyph ink inside the RGBA overlay strip anchored at seam y=816
                cap_mov = work / f"check_{st}_cap_{st}.mov"
                cap_png = work / f"check_{st}_strip.png"
                run([ffmpeg_bin, "-y", "-ss", "0.65", "-i", str(cap_mov), "-frames:v", "1", str(cap_png)])
                rgba = np.asarray(Image.open(cap_png).convert("RGBA"))
                # High-opacity core glyph ink (alpha > 235 separates solid glyphs from soft glow/shadow)
                ys, xs = np.where(rgba[:, :, 3] > 235)
                assert len(ys) > 200, f"Caption style '{st}' rendered empty!"
                sh_h, sh_w = rgba.shape[:2]
                top_pad, bot_pad = int(ys.min()), int(sh_h - 1 - ys.max())
                left_pad, right_pad = int(xs.min()), int(sh_w - 1 - xs.max())
                assert abs(top_pad - bot_pad) <= 3, f"Vertical alignment off for '{st}': top={top_pad}, bot={bot_pad}"
                assert abs(left_pad - right_pad) <= 3, f"Horizontal alignment off for '{st}': left={left_pad}, right={right_pad}"
                caption_checks[st] = {
                    "resolution": st_res["resolution"],
                    "seam_y": 816,
                    "v_diff_px": abs(top_pad - bot_pad),
                    "h_diff_px": abs(left_pad - right_pad),
                }
            else:
                st_png = work / f"check_{st}.png"
                run([ffmpeg_bin, "-y", "-ss", "0.65", "-i", str(st_mp4), "-frames:v", "1", str(st_png)])
                arr = np.asarray(Image.open(st_png).convert("RGB"))
                inv_band = arr[1470:1670, 300:1140, :].astype(np.float32)
                assert inv_band.std() > 25.0, "Inverted text band lacks live contrast!"
                caption_checks[st] = {"resolution": st_res["resolution"], "live_band_std": round(float(inv_band.std()), 1)}

        comp_manifest = work / "comp.json"
        comp_manifest.write_text(json.dumps([
            {"rank": 2, "title": "MOMENT TWO", "file": str(src), "start": 0.0, "end": 1.5},
            {"rank": 1, "title": "MOMENT ONE", "file": str(src), "start": 1.5, "end": 3.0},
        ]))
        comp_res = compile_longform(comp_manifest, work / "comp.mp4", work / "thumb.jpg", "TOP GTA 6 MOMENTS!")
        assert Path(comp_res["thumbnail"]).is_file(), "Thumbnail not created"

        print(json.dumps({
            "status": "OK",
            "version": "4.0.6",
            "ffmpeg": ffmpeg_bin,
            "ffprobe": ffprobe_bin,
            "climax_cold_open_window": peak,
            "miner_top_candidate": mined[0],
            "short_check": result,
            "v406_zero_gap_seam_check": {
                "seam_y_2k": 816,
                "min_row_luma_across_seam": round(float(seam_row_means.min()), 1),
                "zero_black_bar": True,
            },
            "v406_caption_styles_check": caption_checks,
            "v402_quality_check": {
                "default_resolution": result["resolution"],
                "color_space": probe_color.get("color_space"),
                "profile": probe_color.get("profile"),
                "bit_rate_kbps": round(int(probe_color.get("bit_rate", 0)) / 1000),
                "facecam_laplacian_sharpness": sharp_scores,
            },
            "v401_forensics": forensics,
            "v401_tri_stage_score": v4_score["viral_score_v4"] if v4_score else None,
            "v401_gold_similarity_pct": v4_score["model_c_gold_centroid"]["gold_similarity_pct"] if v4_score else None,
            "longform_check": {
                "duration_s": comp_res["duration_s"],
                "stream_start_times": comp_res["stream_start_times"],
                "thumbnail_ok": True,
            },
        }, indent=2))


def main() -> None:
    p = argparse.ArgumentParser(description="Native Apple Silicon 9:16 Viral Shorts (v4.0.6 Zero-Gap Flush Split-Screen + 5 Pro Captions + 2K Engine) + 8:05+ Compiler.")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("check", help="Run v4.0.6 end-to-end verification (zero-gap seam + all 5 caption styles + pixel alignment + 2K VP9 + miner + compile).")
    sub.add_parser("captions", help="Output machine-readable JSON catalog of all 5 built-in caption styles, colors & CLI templates for coding agents.")

    tc = sub.add_parser("transcribe", help="Download URL (or read local file) and dump word timestamps.")
    tc.add_argument("source", help="YouTube/Twitch URL or local video path.")
    tc.add_argument("--model", default="base.en")
    tc.add_argument("--max-height", type=int, default=2160, help="Max source VOD download height (default 2160 / 4K).")

    mn = sub.add_parser("mine", help="Scan a VOD and rank top viral 24-36s candidate timestamps using v4.0 multimodal signals.")
    mn.add_argument("source", help="YouTube/Twitch URL or local video path.")
    mn.add_argument("--dur", type=float, default=30.0, help="Target Short window length in seconds (default 30s).")
    mn.add_argument("--top", type=int, default=5, help="Number of top non-overlapping moments to return.")
    mn.add_argument("--model", default="base.en")
    mn.add_argument("--max-height", type=int, default=2160, help="Max source VOD download height (default 2160 / 4K).")

    rc = sub.add_parser("render", help="Render Short(s) using v4.0.6 zero-gap flush split-screen, 5 pro motion caption styles, Viral Shine hook & -18 LUFS.")
    rc.add_argument("source", help="YouTube/Twitch URL or local video path.")
    rc.add_argument("--clip", action="append", required=True, help="START:END in seconds (repeatable; target 24–36s).")
    rc.add_argument("--out-dir", required=True, help="Output directory (will contain ONLY final .mp4 files).")
    rc.add_argument("--cam", default=None, help="Optional facecam crop W:H:X:Y (or proportional e.g. iw*0.20:ih*0.20:0:ih*0.40).")
    rc.add_argument("--caption-style", choices=list(CAPTION_STYLES), default="hormozi", help="Caption animation style: hormozi (default), shine, stopmotion, flicker, inverted.")
    rc.add_argument("--caption-color", choices=["auto", *CAPTION_COLORS.keys()], default="auto", help="Caption color accent for shine/stopmotion/flicker (default: auto per style).")
    rc.add_argument("--hook", default=None, help="2.6s animated Viral Shine Text hook title (use 'Line 1 | Line 2' or auto-split).")
    rc.add_argument("--hook-theme", choices=["blue", "vice", "gold"], default="blue", help="Viral Shine 4-color gradient theme (default: blue).")
    rc.add_argument("--layout", choices=["aaron", "legacy"], default="aaron", help="Full-bleed Aaron split-screen (default) or legacy blurred.")
    rc.add_argument("--quality", choices=["2k", "ultra", "fast"], default="2k", help="2k=1440x2560 libx264 CRF 13 YouTube VP9/AV1 zero-loss master (default), ultra=1080x1920 CRF 13 master, fast=20Mbps VideoToolbox.")
    rc.add_argument("--max-height", type=int, default=2160, help="Max source VOD download height (default 2160 / 4K for sharpest facecams).")
    rc.add_argument("--no-sharpen", action="store_true", help="Disable v4.0.2 deblock + hqdn3d + AMD CAS anti-blur restoration.")
    rc.add_argument("--cold-open", type=float, default=0.0, help="Splice N seconds (e.g. 2.6) of climax audio/video onto t=0.00s.")
    rc.add_argument("--cold-open-sfx", action="store_true", help="Add procedural YPP-safe 260ms sub-bass hit at t=0.00s.")
    rc.add_argument("--trim-dead-air", action="store_true", help="Auto-trim leading/trailing silence (<=0.2s) for seamless loops.")
    rc.add_argument("--zoom-peaks", action="store_true", help="Enable crisp 1.10x facecam zoom-punch on scream/hype audio peaks.")
    rc.add_argument("--no-loudnorm", action="store_true", help="Disable v4.0 dynamic compression + -18 LUFS mastering.")
    rc.add_argument("--model", default="small.en")
    rc.add_argument("--pos-y", type=int, default=None, help="Caption Y coordinate in 1920-space (auto-calibrated per style & layout).")

    cp = sub.add_parser("compile", help="Stitch a ranked 1920x1080@60fps long-form compilation + 1280x720 thumbnail.")
    cp.add_argument("manifest", help="Path to JSON list of {rank, title, file, start, end} entries.")
    cp.add_argument("--out", required=True, help="Output .mp4 path.")
    cp.add_argument("--thumb", default=None, help="Optional output 1280x720 .jpg thumbnail path.")
    cp.add_argument("--headline", default="WILDEST GTA 6 MOMENTS!", help="Thumbnail headline.")
    cp.add_argument("--quality", choices=["ultra", "fast"], default="ultra", help="ultra=libx264 CRF 15 master (default), fast=18Mbps VideoToolbox.")

    sub.add_parser("voices", help="List all free & API human voiceover providers (Kokoro-82M 54 local voices, ElevenLabs, Gemini 2.5, Groq PlayAI, macOS).")

    vo = sub.add_parser("voiceover", help="Synthesize natural human narration to 48kHz stereo WAV (-16 LUFS) with optional Whisper word alignment.")
    vo.add_argument("--text", required=True, help="Narration text to synthesize.")
    vo.add_argument("--out", required=True, help="Output .wav path.")
    vo.add_argument("--provider", choices=list(VOICE_PROVIDERS), default="kokoro", help="Voice engine (default: kokoro — 100% free local ONNX).")
    vo.add_argument("--voice", default="am_fenrir", help="Voice ID (e.g. am_fenrir, af_heart, af_bella, am_michael, bm_george, EXAVITQu4vr4xnSDxMaL).")
    vo.add_argument("--speed", type=float, default=1.0, help="Speech speed multiplier (0.7 to 1.4).")
    vo.add_argument("--api-key", default=None, help="Optional API key for ElevenLabs, Gemini, or Groq.")
    vo.add_argument("--align", action="store_true", help="Run faster-whisper word timestamp alignment on the generated voiceover.")

    dd = sub.add_parser("deep-dive", help="Build a narrated 16:9 GTA 6 Long-Form Deep Dive video (Romayroh CkOEHYjv6XU workflow + Kokoro/ElevenLabs VO + 11 Card Types + EDL Assembler).")
    dd.add_argument("project_dir", help="Target project directory (creates research/, script/, sources/, audio/, cards/, edit/, renders/).")
    dd.add_argument("--topic", default="GTA 6 Can Do Things We Never Imagined in GTA 5", help="Long-form video title / thesis topic.")
    dd.add_argument("--script", default=None, help="Custom narration text or path to a .md/.txt script file.")
    dd.add_argument("--provider", choices=list(VOICE_PROVIDERS), default="kokoro", help="Voice provider (default: kokoro free local ONNX).")
    dd.add_argument("--voice", default="am_fenrir", help="Voice ID (default: am_fenrir).")
    dd.add_argument("--speed", type=float, default=1.02, help="Voice speed multiplier (default: 1.02).")
    dd.add_argument("--api-key", default=None, help="Optional API key for ElevenLabs / Gemini / Groq.")
    dd.add_argument("--source-video", default=None, help="Optional local gameplay .mp4 source.")
    dd.add_argument("--preview", action="store_true", help="Render fast 960x540 preview MP4.")

    args = p.parse_args()
    if args.cmd == "check":
        self_check()
        return
    if args.cmd == "captions":
        print(json.dumps(caption_catalog_payload(), indent=2))
        return
    if args.cmd == "voices":
        print(json.dumps(list_voice_catalog(), indent=2))
        return
    if args.cmd == "voiceover":
        print(json.dumps(synthesize_human_voice(
            text=args.text, out_wav=Path(args.out), provider=args.provider,
            voice=args.voice, speed=args.speed, api_key=args.api_key, align_words=args.align,
        ), indent=2))
        return
    if args.cmd == "deep-dive":
        script_val = args.script
        if script_val and Path(script_val).is_file():
            script_val = Path(script_val).read_text(encoding="utf-8")
        print(json.dumps(build_longform_deep_dive_demo(
            project_dir=Path(args.project_dir), topic=args.topic, narration_text=script_val,
            provider=args.provider, voice=args.voice, speed=args.speed, api_key=args.api_key,
            source_video=Path(args.source_video) if args.source_video else None,
            preview_only=args.preview,
        ), indent=2))
        return
    if args.cmd == "compile":
        print(json.dumps(compile_longform(Path(args.manifest), Path(args.out), Path(args.thumb) if args.thumb else None, args.headline, quality=args.quality), indent=2))
        return

    ffmpeg_bin = find_ffmpeg()
    ffprobe_bin = find_ffprobe()
    with tempfile.TemporaryDirectory(prefix="shorts_pipe_") as tmp:
        work = Path(tmp)
        if Path(args.source).exists():
            src = Path(args.source)
        else:
            dl_section = None
            if args.cmd == "render" and getattr(args, "clip", None):
                bounds = [[float(x) for x in sp.split(":")] for sp in args.clip]
                min_s = max(0.0, min(b[0] for b in bounds) - 1.0)
                max_e = max(b[1] for b in bounds) + 1.0
                dl_section = (min_s, max_e)
                args.clip = [f"{max(0.0, b[0] - min_s):.2f}:{max(1.0, b[1] - min_s):.2f}" for b in bounds]
            src = download_vod(args.source, work, max_height=args.max_height, section=dl_section)
        words = transcribe_words(src, work, ffmpeg_bin, model_size=args.model)
        if args.cmd == "transcribe":
            print(json.dumps(words, indent=2))
            return
        if args.cmd == "mine":
            print(json.dumps(mine_viral_moments(work / "audio.wav", words, clip_dur=args.dur, top_n=args.top), indent=2))
            return

        out_dir = Path(args.out_dir)
        start_idx = next_short_number(out_dir)
        results = []
        for offset, spec in enumerate(args.clip):
            idx = start_idx + offset
            s_str, e_str = spec.split(":")
            s_val, e_val = float(s_str), float(e_str)

            clip_wav = None
            if args.zoom_peaks or args.cold_open > 0 or args.trim_dead_air:
                clip_wav = work / f"peaks_{idx:02d}.wav"
                run([
                    ffmpeg_bin, "-y", "-ss", f"{s_val:.3f}", "-t", f"{e_val - s_val:.3f}", "-i", str(src),
                    "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(clip_wav),
                ])
                if args.trim_dead_air:
                    s_val, e_val = trim_dead_air_bounds(clip_wav, s_val, e_val)
                    run([
                        ffmpeg_bin, "-y", "-ss", f"{s_val:.3f}", "-t", f"{e_val - s_val:.3f}", "-i", str(src),
                        "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(clip_wav),
                    ])

            peaks = detect_scream_peaks(clip_wav) if (args.zoom_peaks and clip_wav) else None
            render_src = src
            render_s, render_e = s_val, e_val
            render_words = words
            cold_meta = None
            if args.cold_open > 0 and clip_wav:
                climax = find_climax_window(clip_wav, cold_dur=args.cold_open)
                if climax:
                    cold_dur = climax[1] - climax[0]
                    render_src = build_cold_open_source(src, s_val, e_val, climax[0], cold_dur, work, ffmpeg_bin)
                    render_words = shift_words_for_cold_open(words, s_val, e_val, climax[0], cold_dur)
                    if peaks:
                        peaks = [(0.1, max(0.2, cold_dur - 0.1))] + [(round(a + cold_dur, 2), round(b + cold_dur, 2)) for a, b in peaks]
                    render_s, render_e = 0.0, (e_val - s_val) + cold_dur
                    cold_meta = {"climax_rel_window": list(climax), "cold_open_s": round(cold_dur, 2)}

            out_mp4 = out_dir / f"short_{idx:02d}.mp4"
            res = render_clip(
                source_path=render_src,
                start=render_s,
                end=render_e,
                output_mp4=out_mp4,
                words=render_words,
                work_dir=work,
                ffmpeg_bin=ffmpeg_bin,
                ffprobe_bin=ffprobe_bin,
                cam_crop=args.cam,
                pos_y=args.pos_y,
                hook_text=args.hook,
                zoom_peaks=peaks,
                layout=args.layout,
                normalize_lufs=not args.no_loudnorm,
                cold_open_sfx=args.cold_open_sfx,
                quality=args.quality,
                sharpen=not args.no_sharpen,
                hook_theme=args.hook_theme,
                caption_style=args.caption_style,
                caption_color=args.caption_color,
            )
            if cold_meta:
                res["cold_open"] = cold_meta
            try:
                import viral_algorithm as va
                w3_words = [w["word"] for w in render_words if render_s <= w["start"] < render_s + 3.0]
                w3_cnt = len(w3_words)
                w3_disbelief = float(bool(va.DISBELIEF_RE.search(" ".join(w3_words) + " " + (args.hook or ""))))
                sug_desc, sug_tags = va.build_discovery_metadata(args.hook or out_mp4.stem)
                res["v4_audit"] = va.score_short(
                    title=args.hook or out_mp4.stem,
                    duration_s=res["duration"],
                    description=sug_desc,
                    tags=sug_tags,
                    pub_hour_utc=21,
                    video_path=out_mp4,
                    opening_3s_words=float(w3_cnt),
                    has_disbelief_hook_3s=w3_disbelief,
                )
            except Exception:
                pass
            results.append(res)
        print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
