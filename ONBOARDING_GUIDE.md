# 🚀 Resolve Lumvrix™ — VIP Member Quickstart & Agentic Setup Guide

Welcome to **Resolve Lumvrix™ (`STA-6 Pro`)**!  
This guide gets your environment set up and connected to your AI Coding Agents (Claude Code, Antigravity, Cursor) in under **3 minutes**.

---

## ⚡ 1. Prerequisites (What You Need)

| Requirement | Why You Need It | How to Install |
| :--- | :--- | :--- |
| **Python 3.10+** | Runs the MCP server, CLI engine, and neural voice models | `brew install python` (macOS) or [python.org](https://www.python.org) |
| **FFmpeg** | 2K 60fps hardware rendering, audio mastering, and captions | `brew install ffmpeg` (macOS) |
| **Git** | Cloning and syncing updates from the repository | Built into macOS / Linux |
| **AI Agent Client** | Controls Lumvrix via natural language (Claude Code, Cursor, Antigravity, Claude Desktop) | Your preferred AI tool |

---

## 📦 2. Instant 60-Second Setup

Open your terminal and run:

```bash
# 1. Clone your repository
git clone https://github.com/HRL-International-Private-Limited/Resolve-Lumvrix.git
cd Resolve-Lumvrix

# 2. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Verify everything is working (Self-Check)
python3 mcp_bridge.py --check
```

✅ When you see `{"status": "OK", "mcp_tools": 14, ...}` — your engine is 100% operational!

---

## 🤖 3. Connecting to Your AI Agents (MCP Server Setup)

Resolve Lumvrix features a **14-tool zero-dependency AI Bridge MCP Server (`resolve-lumvrix`)** that lets AI assistants directly inspect timelines, generate voiceovers, score viral moments, and assemble videos.

### Option A: Claude Desktop
Add this to your `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "resolve-lumvrix": {
      "command": "python3",
      "args": ["/ABSOLUTE/PATH/TO/Resolve-Lumvrix/mcp_bridge.py"]
    }
  }
}
```

### Option B: Claude Code (CLI)
Run in your terminal:
```bash
claude mcp add resolve-lumvrix python3 /ABSOLUTE/PATH/TO/Resolve-Lumvrix/mcp_bridge.py
```

### Option C: Cursor
1. Go to **Cursor Settings** &rarr; **Features** &rarr; **MCP**.
2. Click **+ Add New MCP Server**.
3. Set **Type**: `command` &bull; **Name**: `resolve-lumvrix` &bull; **Command**: `python3 /ABSOLUTE/PATH/TO/Resolve-Lumvrix/mcp_bridge.py`

### Option D: Google Antigravity
Add to your workspace `.gemini/mcp_servers.json`:
```json
{
  "resolve-lumvrix": {
    "command": "python3",
    "args": ["/ABSOLUTE/PATH/TO/Resolve-Lumvrix/mcp_bridge.py"]
  }
}
```

---

## 🎙️ 4. Free Offline Human Voice AI (Zero API Keys)

Resolve Lumvrix runs **offline Kokoro-82M neural voices** with zero cloud API keys and zero cost:

* **Take #1 Hybrid Blend (Recommended):** 60% Michael conversational cadence + 40% Fenrir vocal depth, normalized to `-16 LUFS` broadcast standard.
* **`hrl` (HRL Narrator):** Authentic conversational reality-check voice.
* **`hrl_navya` (HRL Navya):** 10/10 cheerful smiling female narrator (optimized for English & Hinglish).

### Generate a Voiceover via CLI:
```bash
python3 clip.py voiceover --text "Welcome to the channel. Today we break down the biggest heist blunders in GTA history." --voice hybrid --out output/welcome.wav
```

---

## 🎬 5. Launching the 60fps Web Studio Editor

Prefer a visual editor? Resolve Lumvrix includes a Clideo-easy browser editor:

```bash
python3 harness.py
```
Open **`http://127.0.0.1:52257`** in your browser:
* **0-Lag 60fps Canvas:** Real-time preview with zero export waiting.
* **5 Motion Caption Styles:** Hormozi, Shine (neon sweep), Stopmotion (cream editorial), Flicker (neon pulse), and Inverted.
* **Voice AI Panel:** 1-click voice synthesis and multi-chapter timeline assembly.

---

## 💡 What to Ask Your AI Agent Once Connected

Try asking your agent:
* *"Check bridge status and project health for Resolve Lumvrix."*
* *"Synthesize a 30-second voiceover for GTA 6 using the hybrid blend."*
* *"Customize captions to use the Shine style with neon green accent."*
* *"Build an 8-minute long-form breakdown of viral streamer mistakes."*
