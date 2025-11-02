"""
scripts/pipeline_blip_ollama.py

Pipeline:
 - read data/processed/<video>/metadata.json
 - build overlapping windows (window_size, stride)
 - sample N frames per window (start/mid/end)
 - caption each sampled frame using BLIP (Salesforce/blip-image-captioning-base)
 - summarize each window by calling Ollama (local LLM) via CLI with strict JSON markers
 - merge overlapping/adjacent window summaries
 - optionally refine merged summaries with Ollama
 - save final JSON report to data/reports/<video>_summaries.json

Usage:
    python scripts/pipeline_blip_ollama.py data/processed/EJFBM --window 20 --stride 10 --frames-per-window 3

Requirements:
    .venv active
    pip install transformers pillow torch requests
    ollama installed and models available (e.g., qwen3:8b)
"""
from pathlib import Path
from typing import List, Dict, Any, Optional
import json
from PIL import Image
import argparse
from datetime import datetime, timezone
import subprocess
import math
import sys

# BLIP imports
from transformers import BlipProcessor, BlipForConditionalGeneration

# ---------- Config ----------
OLLAMA_MODEL = "qwen3:8b"                        # change to a model you have locally (ollama list)
BLIP_MODEL_NAME = "Salesforce/blip-image-captioning-base"
DEFAULT_WINDOW = 20.0
DEFAULT_STRIDE = 10.0
DEFAULT_FRAMES_PER_WINDOW = 3
DEFAULT_MERGE_GAP = 2.0
DEFAULT_OUTPUT_DIR = Path("data") / "reports"

# ---------- Utilities ----------
def load_metadata(processed_dir: Path) -> Dict[str, Any]:
    meta_path = processed_dir / "metadata.json"
    if not meta_path.exists():
        raise FileNotFoundError(f"metadata.json not found in {processed_dir}")
    return json.loads(meta_path.read_text(encoding="utf-8"))

def build_windows(frames: List[Dict[str, Any]], window_size: float, stride: float) -> List[Dict]:
    if not frames:
        return []
    last_ts = frames[-1]["ts"]
    windows = []
    start = 0.0
    while start <= last_ts:
        end = start + window_size
        in_frames = [f for f in frames if f["ts"] >= start and f["ts"] < end]
        windows.append({"start": start, "end": end, "frames": in_frames})
        start += stride
    return windows

def sample_frames_for_window(win: Dict, frames_per_window: int) -> List[Path]:
    in_frames = win["frames"]
    if not in_frames:
        return []
    n = min(frames_per_window, len(in_frames))
    if n == 1:
        picks = [in_frames[0]]
    else:
        indices = [ round(i*(len(in_frames)-1)/(n-1)) for i in range(n) ]
        picks = [ in_frames[i] for i in indices ]
    picked_paths = []
    for p in picks:
        pth = Path(p["path"])
        if not pth.exists():
            # try relative to processed dir or cwd
            alt = Path.cwd() / p["path"]
            if alt.exists():
                pth = alt
            else:
                # fallback: try processed dir name
                pth = Path.cwd() / p["path"]
        picked_paths.append(pth)
    return picked_paths

# ---------- BLIP wrapper ----------
class BlipWrapper:
    def __init__(self, model_name: str = BLIP_MODEL_NAME, device: str = "cpu"):
        print(f"[BLIP] loading {model_name} (device={device}) ...")
        self.processor = BlipProcessor.from_pretrained(model_name)
        self.model = BlipForConditionalGeneration.from_pretrained(model_name)
        # model.to(device)  # Leave on CPU by default; uncomment for GPU
        self.device = device

    def caption(self, image_path: Path) -> str:
        img = Image.open(image_path).convert("RGB")
        inputs = self.processor(images=img, return_tensors="pt")
        outputs = self.model.generate(**inputs, max_length=40)
        caption = self.processor.decode(outputs[0], skip_special_tokens=True)
        return caption

# ---------- Ollama CLI helpers (robust JSON extraction) ----------
def run_ollama_cli(model: str, prompt: str, timeout: int = 60) -> str:
    """Call: ollama run <model> <prompt> via subprocess and return stdout text."""
    cmd = ["ollama", "run", model, prompt]
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True, timeout=timeout)
        return out
    except subprocess.CalledProcessError as e:
        return e.output or ""
    except subprocess.TimeoutExpired as e:
        return e.output or ""

def extract_between_markers(text: str, start_marker: str = "<JSON_START>", end_marker: str = "<JSON_END>") -> Optional[str]:
    s = text.find(start_marker)
    e = text.find(end_marker, s + len(start_marker)) if s != -1 else -1
    if s != -1 and e != -1:
        return text[s + len(start_marker): e].strip()
    return None

def extract_first_json(text: str) -> Optional[str]:
    """Prefer marker extraction, fall back to bracket matching to find the first {...}."""
    between = extract_between_markers(text)
    if between:
        return between
    start = text.find('{')
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(text)):
        ch = text[i]
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return text[start:i+1]
    return None

def call_ollama_summarize(model: str, frames_captioned: List[Dict[str, Any]], timeout: int = 60) -> Dict[str, Any]:
    """
    frames_captioned: [{"ts": float, "caption": str}, ...]
    Returns parsed JSON or fallback {"summary":..., "evidence":..., "confidence":0.0}
    """
    lines = [
        "You are a JSON-only summarizer for short surveillance windows.",
        "DO NOT output any explanations, reasoning, or commentary.",
        "Return EXACTLY one valid JSON object and nothing else, between the markers <JSON_START> and <JSON_END>.",
        "The JSON must have keys: summary (string), evidence (list of {ts, text}), confidence (0.0-1.0).",
        "<JSON_START>",
        '{"summary":"...","evidence":[{"ts":0.0,"text":"..."}],"confidence":0.0}',
        "<JSON_END>",
        "",
        "Now the frame captions follow:"
    ]
    for f in frames_captioned:
        lines.append(f"- [{f['ts']:.1f}s] {f['caption']}")
    prompt = "\n".join(lines)

    raw = run_ollama_cli(model, prompt, timeout=timeout)
    json_text = extract_first_json(raw)
    if json_text:
        try:
            parsed = json.loads(json_text)
            if "summary" in parsed:
                return parsed
            # otherwise wrap whatever we got
            return {"summary": str(parsed), "evidence": frames_captioned, "confidence": float(parsed.get("confidence", 0.0)) if isinstance(parsed, dict) else 0.0}
        except Exception:
            return {"summary": json_text, "evidence": frames_captioned, "confidence": 0.0}
    # fallback - naive join
    summary = " ".join([f["caption"] for f in frames_captioned])[:400]
    return {"summary": summary, "evidence": frames_captioned, "confidence": 0.0}

def refine_merged_with_ollama(merged: List[Dict], model: str, timeout: int = 60) -> List[Dict]:
    """Rewrite combined merged summaries into concise single-sentence outputs via Ollama."""
    refined = []
    for item in merged:
        evidence = item.get("evidence", []) or []
        lines = [
            "You are a JSON-only concise summarizer. Do NOT output explanations.",
            "Given the evidence (timestamps included), produce a single concise 1-2 sentence summary.",
            "Return EXACTLY one JSON object between <JSON_START> and <JSON_END> with keys: summary, evidence, confidence.",
            "<JSON_START>",
            '{"summary":"...","evidence":[{"ts":0.0,"text":"..."}],"confidence":0.0}',
            "<JSON_END>"
        ]
        for e in evidence[:12]:
            text = e.get("caption") if isinstance(e, dict) else str(e)
            ts = e.get("ts", None) if isinstance(e, dict) else None
            if ts is not None:
                lines.append(f"- [{ts:.1f}s] {text}")
            else:
                lines.append(f"- {text}")
        prompt = "\n".join(lines)
        raw = run_ollama_cli(model, prompt, timeout=timeout)
        json_text = extract_first_json(raw)
        if json_text:
            try:
                parsed = json.loads(json_text)
                refined.append({
                    "start": item["start"],
                    "end": item["end"],
                    "summary": parsed.get("summary", item.get("summary","")),
                    "evidence": item.get("evidence", []),
                    "confidence": parsed.get("confidence", 0.0)
                })
                continue
            except Exception:
                pass
        refined.append({
            "start": item["start"],
            "end": item["end"],
            "summary": item.get("summary",""),
            "evidence": item.get("evidence", []),
            "confidence": 0.0
        })
    return refined

# ---------- Merging logic ----------
def merge_summaries(windows: List[Dict], merge_gap: float = DEFAULT_MERGE_GAP) -> List[Dict]:
    if not windows:
        return []
    windows = sorted(windows, key=lambda w: w["start"])
    merged = []
    cur = {"start": windows[0]["start"], "end": windows[0]["end"],
           "summaries": [windows[0].get("summary","")], "evidence": windows[0].get("evidence", [])}
    for w in windows[1:]:
        if w["start"] <= cur["end"] or (w["start"] - cur["end"]) <= merge_gap:
            cur["end"] = max(cur["end"], w["end"])
            cur["summaries"].append(w.get("summary",""))
            cur["evidence"].extend(w.get("evidence", []))
        else:
            combined_text = " ".join(s for s in cur["summaries"] if s)
            merged.append({"start": cur["start"], "end": cur["end"], "summary": combined_text, "evidence": cur["evidence"]})
            cur = {"start": w["start"], "end": w["end"], "summaries": [w.get("summary","")], "evidence": w.get("evidence", [])}
    combined_text = " ".join(s for s in cur["summaries"] if s)
    merged.append({"start": cur["start"], "end": cur["end"], "summary": combined_text, "evidence": cur["evidence"]})
    return merged

# ---------- Main pipeline ----------
def run_pipeline(processed_dir: Path,
                 window_size: float = DEFAULT_WINDOW,
                 stride: float = DEFAULT_STRIDE,
                 frames_per_window: int = DEFAULT_FRAMES_PER_WINDOW,
                 merge_gap: float = DEFAULT_MERGE_GAP,
                 ollama_model: str = OLLAMA_MODEL):
    print("Loading metadata...")
    meta = load_metadata(processed_dir)
    frames = meta.get("frames", [])
    windows = build_windows(frames, window_size=window_size, stride=stride)
    print(f"Built {len(windows)} windows (window={window_size}s stride={stride}s)")

    blip = BlipWrapper()

    per_window_results = []
    for i, win in enumerate(windows):
        sampled_paths = sample_frames_for_window(win, frames_per_window)
        captioned = []
        for p in sampled_paths:
            try:
                caption = blip.caption(p)
            except Exception as e:
                print("[BLIP] failed to caption", p, e)
                caption = ""
            ts = None
            for fr in win["frames"]:
                if Path(fr["path"]).name == p.name or str(Path.cwd() / fr["path"]).endswith(str(p)):
                    ts = fr.get("ts", None)
                    break
            if ts is None:
                ts = (win["start"] + win["end"]) / 2.0
            captioned.append({"ts": ts, "caption": caption})

        summary_obj = call_ollama_summarize(ollama_model, captioned)
        per_window_results.append({
            "start": win["start"],
            "end": win["end"],
            "summary": summary_obj.get("summary", ""),
            "evidence": captioned,
            "confidence": summary_obj.get("confidence", 0.0)
        })
        print(f"[Window {i}] {win['start']:.1f}-{win['end']:.1f}s -> {len(captioned)} captions -> summary length {len(per_window_results[-1]['summary'])}")

    print("Merging overlapping/adjacent windows ...")
    merged = merge_summaries(per_window_results, merge_gap=merge_gap)

    print("Refining merged summaries with Ollama ...")
    refined = refine_merged_with_ollama(merged, ollama_model)

    DEFAULT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = DEFAULT_OUTPUT_DIR / f"{meta.get('video','video')}_summaries.json"
    report = {"video": meta.get("video"), "generated_at": datetime.now(timezone.utc).isoformat(), "summaries": refined}
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("Saved final summaries to", out_path)

# ---------- CLI ----------
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("processed_dir", type=str, help="Path to data/processed/<video_folder>")
    parser.add_argument("--window", type=float, default=DEFAULT_WINDOW)
    parser.add_argument("--stride", type=float, default=DEFAULT_STRIDE)
    parser.add_argument("--frames-per-window", type=int, default=DEFAULT_FRAMES_PER_WINDOW)
    parser.add_argument("--merge-gap", type=float, default=DEFAULT_MERGE_GAP)
    parser.add_argument("--ollama-model", type=str, default=OLLAMA_MODEL)
    args = parser.parse_args()
    run_pipeline(Path(args.processed_dir), window_size=args.window, stride=args.stride,
                 frames_per_window=args.frames_per_window, merge_gap=args.merge_gap, ollama_model=args.ollama_model)
