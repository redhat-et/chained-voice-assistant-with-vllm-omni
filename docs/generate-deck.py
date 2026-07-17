#!/usr/bin/env python3
"""Generate the chained voice assistant architecture deck (.pptx)."""

from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE

# Red Hat colors
RH_RED = RGBColor(0xEE, 0x00, 0x00)
RH_DARK = RGBColor(0x15, 0x15, 0x15)
RH_WHITE = RGBColor(0xFF, 0xFF, 0xFF)
RH_GRAY_80 = RGBColor(0x29, 0x29, 0x29)
RH_GRAY_60 = RGBColor(0x4D, 0x4D, 0x4D)
RH_GRAY_30 = RGBColor(0xC7, 0xC7, 0xC7)
RH_LIGHT_BG = RGBColor(0xF2, 0xF2, 0xF2)
BLUE_ACCENT = RGBColor(0x00, 0x66, 0xCC)
GREEN_ACCENT = RGBColor(0x3E, 0x8A, 0x35)
ORANGE_ACCENT = RGBColor(0xEC, 0x7A, 0x08)

prs = Presentation()
prs.slide_width = Inches(13.333)
prs.slide_height = Inches(7.5)


def add_text(slide, left, top, width, height, text, font_size=18,
             bold=False, color=RH_DARK, align=PP_ALIGN.LEFT, font_name="Arial"):
    txBox = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
    tf = txBox.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = text
    p.font.size = Pt(font_size)
    p.font.bold = bold
    p.font.color.rgb = color
    p.font.name = font_name
    p.alignment = align
    return txBox


def add_box(slide, left, top, width, height, fill_color, text="",
            font_size=14, text_color=RH_WHITE, bold=False, border_color=None):
    shape = slide.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE, Inches(left), Inches(top),
        Inches(width), Inches(height))
    shape.fill.solid()
    shape.fill.fore_color.rgb = fill_color
    if border_color:
        shape.line.color.rgb = border_color
        shape.line.width = Pt(2)
    else:
        shape.line.fill.background()
    if text:
        tf = shape.text_frame
        tf.word_wrap = True
        tf.paragraphs[0].alignment = PP_ALIGN.CENTER
        p = tf.paragraphs[0]
        p.text = text
        p.font.size = Pt(font_size)
        p.font.color.rgb = text_color
        p.font.bold = bold
        p.font.name = "Arial"
        shape.text_frame.paragraphs[0].space_before = Pt(0)
        shape.text_frame.paragraphs[0].space_after = Pt(0)
    return shape


def add_arrow(slide, start_left, start_top, end_left, end_top, color=RH_GRAY_60, width=2.5):
    connector = slide.shapes.add_connector(
        1, Inches(start_left), Inches(start_top), Inches(end_left), Inches(end_top))
    connector.line.color.rgb = color
    connector.line.width = Pt(width)
    return connector


def add_bg(slide, color=RH_WHITE):
    bg = slide.background
    fill = bg.fill
    fill.solid()
    fill.fore_color.rgb = color


# ──────────────────────────────────────────────
# Slide 1: Title
# ──────────────────────────────────────────────
slide1 = prs.slides.add_slide(prs.slide_layouts[6])
add_bg(slide1, RH_WHITE)

# Red accent bar at top
add_box(slide1, 0, 0, 13.333, 0.08, RH_RED)

add_text(slide1, 0.8, 1.5, 11.5, 1.2,
         "Chained Voice Assistant", font_size=44, bold=True, color=RH_DARK)
add_text(slide1, 0.8, 2.5, 11.5, 0.8,
         "Disaggregated STT → LLM → TTS Pipeline with vLLM-Omni",
         font_size=24, color=RH_GRAY_60)
add_text(slide1, 0.8, 3.6, 11.5, 0.6,
         "Runtime model selection  ·  OpenShift & cloud deployment  ·  Latency benchmarking",
         font_size=18, color=RH_GRAY_60)

# Three key boxes
for i, (label, detail, color) in enumerate([
    ("Modular", "Swap any STT, LLM, or\nTTS model at runtime", RH_RED),
    ("Sovereign", "Mix models by provenance\nUS / EU / China flags", BLUE_ACCENT),
    ("Observable", "Per-turn latency overlay\nSTT, LLM TTFT, TTS TTFB", GREEN_ACCENT),
]):
    x = 1.5 + i * 3.8
    add_box(slide1, x, 4.8, 3.2, 1.5, color, f"{label}\n\n{detail}",
            font_size=16, text_color=RH_WHITE, bold=False)

add_text(slide1, 0.8, 6.8, 6, 0.4,
         "Red Hat OCTO  ·  Emerging Technologies", font_size=14, color=RH_GRAY_60)
add_text(slide1, 7, 6.8, 5.5, 0.4,
         "redhat-et/chained-voice-assistant-with-vllm-omni",
         font_size=12, color=RH_GRAY_30, align=PP_ALIGN.RIGHT)


# ──────────────────────────────────────────────
# Slide 2: Architecture Diagram
# ──────────────────────────────────────────────
slide2 = prs.slides.add_slide(prs.slide_layouts[6])
add_bg(slide2, RH_WHITE)
add_box(slide2, 0, 0, 13.333, 0.08, RH_RED)

add_text(slide2, 0.8, 0.3, 11.5, 0.7,
         "Architecture: Disaggregated Pipeline", font_size=32, bold=True, color=RH_DARK)
add_text(slide2, 0.8, 0.9, 11.5, 0.5,
         "Each stage is an independent service — swap models without touching the pipeline",
         font_size=16, color=RH_GRAY_60)

# Browser box
add_box(slide2, 0.5, 2.0, 2.2, 1.2, RH_GRAY_80, "Browser\n\nModel Selector UI",
        font_size=14, text_color=RH_WHITE)

# Arrow: Browser -> Frontend
add_arrow(slide2, 2.7, 2.6, 3.5, 2.6, RH_RED, 3)

# Frontend box
add_box(slide2, 3.5, 2.0, 2.2, 1.2, RH_DARK, "Frontend\n\nNext.js\nPort 3000",
        font_size=13, text_color=RH_WHITE)

# Arrow: Frontend -> LiveKit
add_arrow(slide2, 5.7, 2.6, 6.5, 2.6, RH_RED, 3)

# LiveKit box
add_box(slide2, 6.5, 1.7, 2.5, 1.8, RH_RED, "LiveKit SFU\n\nWebRTC\nPort 7880",
        font_size=14, text_color=RH_WHITE, bold=True)

# Arrow: LiveKit -> Agent
add_arrow(slide2, 9.0, 2.6, 9.8, 2.6, RH_RED, 3)

# Agent box
add_box(slide2, 9.8, 2.0, 2.5, 1.2, RH_DARK,
        "Agent\n\nlivekit-agents 1.5+",
        font_size=13, text_color=RH_WHITE)

# The three model services below the agent
stt_x, llm_x, tts_x = 7.0, 9.3, 11.5
svc_y = 4.8
svc_h = 1.8

# STT
add_box(slide2, stt_x - 1.0, svc_y, 2.5, svc_h, BLUE_ACCENT,
        "STT\n\nfaster-whisper\nLarge v3\n\nCPU  ·  Port 8001",
        font_size=12, text_color=RH_WHITE)

# LLM
add_box(slide2, llm_x - 1.0, svc_y, 2.5, svc_h, GREEN_ACCENT,
        "LLM\n\nvLLM\nGemma-3 4B\n\nGPU  ·  Port 8002",
        font_size=12, text_color=RH_WHITE)

# TTS
add_box(slide2, tts_x - 1.2, svc_y, 2.5, svc_h, ORANGE_ACCENT,
        "TTS\n\nvLLM-Omni\nQwen3-TTS\n\nGPU  ·  Port 8003",
        font_size=12, text_color=RH_WHITE)

# Arrows: Agent down to each service
agent_bottom = 3.2
for sx in [stt_x - 1.0 + 1.25, llm_x - 1.0 + 1.25, tts_x - 1.2 + 1.25]:
    add_arrow(slide2, 11.05, agent_bottom, sx, svc_y, RH_GRAY_60, 2)

# Labels for the APIs
add_text(slide2, 5.5, 4.3, 3, 0.4,
         "OpenAI-compatible /v1 APIs", font_size=13, color=RH_GRAY_60, align=PP_ALIGN.CENTER)

# Flow label
add_text(slide2, 0.5, 6.9, 12, 0.4,
         "Flow:  Browser → WebRTC → LiveKit → Agent → STT (audio→text) → LLM (text→text) → TTS (text→audio) → LiveKit → Browser",
         font_size=14, bold=True, color=RH_DARK)


# ──────────────────────────────────────────────
# Slide 3: API & Chaining Detail
# ──────────────────────────────────────────────
slide3 = prs.slides.add_slide(prs.slide_layouts[6])
add_bg(slide3, RH_WHITE)
add_box(slide3, 0, 0, 13.333, 0.08, RH_RED)

add_text(slide3, 0.8, 0.3, 11.5, 0.7,
         "How the Chaining Works", font_size=32, bold=True, color=RH_DARK)

# Three columns
col_w = 3.5
col_gap = 0.4
start_x = 0.8
col_y = 1.3

for i, (title, subtitle, items) in enumerate([
    ("1. STT Stage", "faster-whisper-server",
     ["OpenAI /v1/audio/transcriptions",
      "Input: raw audio (Opus/PCM)",
      "Output: text transcript",
      "Model: Systran/faster-whisper-large-v3",
      "Runs on CPU (no GPU needed)",
      "~200ms for short utterances"]),
    ("2. LLM Stage", "vLLM (OpenAI-compatible)",
     ["OpenAI /v1/chat/completions",
      "Input: text (streaming)",
      "Output: text (streaming)",
      "Model: google/gemma-3-4b-it",
      "Runs on GPU via vLLM",
      "Streaming reduces TTFT"]),
    ("3. TTS Stage", "vLLM-Omni (--omni flag)",
     ["OpenAI /v1/audio/speech",
      "Input: text",
      "Output: audio stream (PCM)",
      "Model: Qwen3-TTS-1.7B-CustomVoice",
      "Runs on GPU via vLLM-Omni",
      "Custom voice: \"vivian\""]),
]):
    x = start_x + i * (col_w + col_gap)
    add_box(slide3, x, col_y, col_w, 0.7, RH_RED if i == 0 else BLUE_ACCENT if i == 1 else GREEN_ACCENT,
            title, font_size=18, text_color=RH_WHITE, bold=True)
    add_text(slide3, x + 0.1, col_y + 0.75, col_w - 0.2, 0.4,
             subtitle, font_size=14, bold=True, color=RH_GRAY_60)
    for j, item in enumerate(items):
        add_text(slide3, x + 0.15, col_y + 1.2 + j * 0.42, col_w - 0.3, 0.4,
                 f"•  {item}", font_size=13, color=RH_DARK)

# Runtime model selection section
add_text(slide3, 0.8, 5.2, 11.5, 0.6,
         "Runtime Model Selection", font_size=22, bold=True, color=RH_DARK)
add_text(slide3, 0.8, 5.7, 11.5, 1.2,
         "Frontend sends model choices via POST /api/token → encoded as LiveKit RoomAgentDispatch metadata (JSON) →\n"
         "Agent reads ctx.job.metadata at session start → overrides env-var defaults with user selection.\n"
         "Models are swapped per-conversation, not per-deployment. No restart required.",
         font_size=14, color=RH_DARK)


# ──────────────────────────────────────────────
# Slide 4: Model Sovereignty
# ──────────────────────────────────────────────
slide4 = prs.slides.add_slide(prs.slide_layouts[6])
add_bg(slide4, RH_WHITE)
add_box(slide4, 0, 0, 13.333, 0.08, RH_RED)

add_text(slide4, 0.8, 0.3, 11.5, 0.7,
         "Model Sovereignty: Mix & Match by Provenance", font_size=32, bold=True, color=RH_DARK)
add_text(slide4, 0.8, 0.9, 11.5, 0.5,
         "Every stage can use a different model from a different origin — demonstrated via country flags in the UI",
         font_size=16, color=RH_GRAY_60)

# Table-like layout
headers = ["Stage", "Model", "Origin", "GPU", "Why"]
rows = [
    ["STT",  "Whisper Large v3",     "FR (Systran)",       "CPU",  "Best open STT accuracy"],
    ["STT",  "Whisper Base",         "FR (Systran)",       "CPU",  "Faster, lower accuracy"],
    ["LLM",  "Gemma-3 4B",          "US (Google)",        "1 GPU", "Small, fast, instruction-tuned"],
    ["LLM",  "Gemma-3 4B INT4",     "US (Red Hat)",       "1 GPU", "Quantized by RedHatAI, smaller footprint"],
    ["LLM",  "Qwen3 0.6B",          "CN (Alibaba)",       "1 GPU", "Tiny, lowest latency"],
    ["LLM",  "Llama 3.1 8B",        "US (Meta)",          "1 GPU", "Strong general reasoning"],
    ["LLM",  "Mistral 7B",          "EU (Mistral AI)",    "1 GPU", "European sovereign option"],
    ["TTS",  "Qwen3-TTS-CustomVoice","CN (Alibaba)",      "1 GPU", "High quality, custom voices"],
    ["TTS",  "Voxtral 4B",          "EU (Mistral AI)",    "1 GPU", "European TTS alternative"],
]

table_top = 1.7
row_h = 0.44
# Headers
for j, hdr in enumerate(headers):
    widths = [1.0, 2.5, 2.8, 1.2, 4.0]
    x = 0.8 + sum(widths[:j])
    add_box(slide4, x, table_top, widths[j], 0.45, RH_DARK, hdr,
            font_size=13, text_color=RH_WHITE, bold=True)

# Rows
for i, row in enumerate(rows):
    y = table_top + 0.5 + i * row_h
    bg = RH_LIGHT_BG if i % 2 == 0 else RH_WHITE
    for j, cell in enumerate(row):
        widths = [1.0, 2.5, 2.8, 1.2, 4.0]
        x = 0.8 + sum(widths[:j])
        add_box(slide4, x, y, widths[j], row_h - 0.03, bg, cell,
                font_size=12, text_color=RH_DARK, border_color=RH_GRAY_30)

add_text(slide4, 0.8, 6.4, 11.5, 0.8,
         "Key point: Customers can enforce data sovereignty by choosing models from specific jurisdictions.\n"
         "The pipeline doesn't care where the model comes from — all stages use OpenAI-compatible APIs.",
         font_size=14, color=RH_DARK)


# ──────────────────────────────────────────────
# Slide 5: Deployment Options
# ──────────────────────────────────────────────
slide5 = prs.slides.add_slide(prs.slide_layouts[6])
add_bg(slide5, RH_WHITE)
add_box(slide5, 0, 0, 13.333, 0.08, RH_RED)

add_text(slide5, 0.8, 0.3, 11.5, 0.7,
         "Deployment: OpenShift & Cloud", font_size=32, bold=True, color=RH_DARK)

# Two columns
# OpenShift
add_box(slide5, 0.8, 1.3, 5.5, 0.6, RH_RED, "OpenShift (Kubernetes)",
        font_size=18, text_color=RH_WHITE, bold=True)
ocp_items = [
    "9 manifests in openshift/ directory",
    "Namespace: voice-pipeline",
    "LiveKit: hostNetwork + anyuid SCC",
    "LLM & TTS: GPU nodes, runAsUser: 0",
    "STT: CPU-only, no GPU needed",
    "Routes for frontend + LiveKit WebRTC",
    "Secrets templated (bring your own keys)",
    "Deploy: oc apply -f openshift/",
]
for i, item in enumerate(ocp_items):
    add_text(slide5, 1.0, 2.1 + i * 0.45, 5.0, 0.4,
             f"•  {item}", font_size=14, color=RH_DARK)

# AWS / Single box
add_box(slide5, 7.0, 1.3, 5.5, 0.6, BLUE_ACCENT, "AWS / Single GPU Box",
        font_size=18, text_color=RH_WHITE, bold=True)
aws_items = [
    "Terraform: VPC, SG, g6e.2xlarge (L40S 48GB)",
    "Docker Compose: 6 services on one box",
    "LLM + TTS share GPU (40/40% split)",
    "STT, Agent, Frontend, LiveKit on CPU",
    "Auto-deploy via user-data script",
    "~$1.75/hr on-demand (g5.xlarge ~$1/hr alt)",
    "Elastic IP for stable WebRTC endpoint",
    "Best for latency benchmarking",
]
for i, item in enumerate(aws_items):
    add_text(slide5, 7.2, 2.1 + i * 0.45, 5.0, 0.4,
             f"•  {item}", font_size=14, color=RH_DARK)

add_text(slide5, 0.8, 6.2, 11.5, 0.5,
         "Images: quay.io/redhat-et/voice-pipeline-agent  ·  quay.io/redhat-et/voice-pipeline-frontend",
         font_size=13, color=RH_GRAY_60)
add_text(slide5, 0.8, 6.6, 11.5, 0.5,
         "Repo: github.com/redhat-et/chained-voice-assistant-with-vllm-omni",
         font_size=13, color=RH_GRAY_60)


# ──────────────────────────────────────────────
# Slide 6: Why Disaggregated?
# ──────────────────────────────────────────────
slide6 = prs.slides.add_slide(prs.slide_layouts[6])
add_bg(slide6, RH_WHITE)
add_box(slide6, 0, 0, 13.333, 0.08, RH_RED)

add_text(slide6, 0.8, 0.3, 11.5, 0.7,
         "Why Disaggregated Over Monolithic?", font_size=32, bold=True, color=RH_DARK)
add_text(slide6, 0.8, 0.9, 11.5, 0.5,
         '"The pipeline is not the problem. Bad pipeline architecture is the problem."',
         font_size=16, color=RH_GRAY_60)

# Two columns: Concern vs Our Answer
col_y = 1.7
left_x = 0.8
right_x = 7.0
col_w = 5.5

add_box(slide6, left_x, col_y, col_w, 0.6, RH_GRAY_80, "The Concern",
        font_size=18, text_color=RH_WHITE, bold=True)
add_box(slide6, right_x, col_y, col_w, 0.6, GREEN_ACCENT, "Our Answer",
        font_size=18, text_color=RH_WHITE, bold=True)

concerns = [
    ('"800–1200ms latency kills\nconversational quality"',
     "Co-located services on one box\neliminate vendor network hops.\n~800ms with proper endpointing\nactually feels conversational."),
    ('"Transcription errors are a\nsingle point of failure"',
     "STT confidence scores let you\ncatch bad transcriptions.\nRetry or fallback per stage."),
    ('"No interruption handling —\nuser waits for full response"',
     "LiveKit agents SDK has native\nbarge-in support. Streaming\nTTS allows mid-sentence cutoff."),
    ('"Voice-to-voice models\nare faster end-to-end"',
     "But you lose observability.\nNo per-stage latency. No audit\nlog. Can't debug production issues.\nOur TimingOverlay proves this."),
]

for i, (concern, answer) in enumerate(concerns):
    row_y = col_y + 0.75 + i * 1.3
    add_box(slide6, left_x, row_y, col_w, 1.15, RH_LIGHT_BG, concern,
            font_size=13, text_color=RH_DARK, border_color=RH_GRAY_30)
    add_box(slide6, right_x, row_y, col_w, 1.15, RH_WHITE, answer,
            font_size=13, text_color=RH_DARK, border_color=GREEN_ACCENT)

add_text(slide6, 0.8, 6.7, 11.5, 0.5,
         "Bottom line: Disaggregated is the production architecture — debuggable, auditable, controllable. "
         "Co-location solves the latency.",
         font_size=15, bold=True, color=RH_DARK)


# ──────────────────────────────────────────────
# Slide 7: Next Steps
# ──────────────────────────────────────────────
slide7 = prs.slides.add_slide(prs.slide_layouts[6])
add_bg(slide7, RH_WHITE)
add_box(slide7, 0, 0, 13.333, 0.08, RH_RED)

add_text(slide7, 0.8, 0.3, 11.5, 0.7,
         "Next Steps & Latency Targets", font_size=32, bold=True, color=RH_DARK)

# Latency budget breakdown
add_text(slide7, 0.8, 1.2, 11.5, 0.5,
         "Latency Budget (target: < 1s voice-to-voice)", font_size=22, bold=True, color=RH_DARK)

stages = [
    ("VAD + Turn Detection", "50–200ms", "Tune silence_duration, biggest easy win"),
    ("STT (Whisper Large v3)", "150–300ms", "CPU-bound, consider smaller model for speed"),
    ("LLM TTFT (Gemma 4B)", "100–400ms", "Streaming reduces perceived latency"),
    ("TTS TTFA (Qwen3-TTS)", "40–200ms", "First audio chunk, not full synthesis"),
    ("Transport (WebRTC)", "20–60ms", "Not the bottleneck — co-location matters more"),
]

for i, (stage, time, note) in enumerate(stages):
    y = 1.9 + i * 0.55
    add_box(slide7, 0.8, y, 3.5, 0.45, RH_LIGHT_BG, stage,
            font_size=13, text_color=RH_DARK, border_color=RH_GRAY_30)
    add_box(slide7, 4.35, y, 1.8, 0.45, RH_RED, time,
            font_size=14, text_color=RH_WHITE, bold=True)
    add_text(slide7, 6.3, y, 6.2, 0.45, note, font_size=13, color=RH_GRAY_60)

# Next steps
add_text(slide7, 0.8, 4.9, 11.5, 0.5,
         "What's Next", font_size=22, bold=True, color=RH_DARK)

next_items = [
    "Deploy to AWS and capture baseline latency metrics per stage",
    "Evaluate Pipecat as LiveKit alternative (P2P WebRTC, eliminates SFU hop)",
    "Test model combinations: smallest viable models for sub-1s response",
    "Explore vLLM speculative decoding for faster LLM TTFT",
    "Record proper demo video with latency overlay",
]
for i, item in enumerate(next_items):
    add_text(slide7, 0.8, 5.4 + i * 0.4, 11.5, 0.4,
             f"•  {item}", font_size=14, color=RH_DARK)


# Save
output_path = "/Users/shwalsh/work/voice-pipeline-disaggregated/docs/chained-voice-assistant-architecture.pptx"
prs.save(output_path)
print(f"Saved to {output_path}")
