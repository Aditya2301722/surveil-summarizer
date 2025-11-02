"""
A tiny mock captioner for development.
Reads data/processed/<video>/metadata.json and returns simple templated captions per frame/window.
"""
import json
from pathlib import Path
from datetime import datetime

def load_metadata(video_processed_dir: Path):
    meta_file = video_processed_dir / "metadata.json"
    with open(meta_file, encoding="utf-8") as fh:
        return json.load(fh)

def simple_aggregate_captions(metadata, window=20.0):
    frames = metadata["frames"]
    if not frames:
        return []
    caps = []
    last_ts = frames[-1]["ts"]
    start = 0.0
    while start <= last_ts:
        end = start + window
        texts = [f for f in frames if start <= f["ts"] < end]
        if texts:
            caps.append({
                "start": start,
                "end": end,
                "summary": f"{len(texts)} sampled frames between {start:.1f}s and {end:.1f}s (demo summary)."
            })
        start = end
    return caps

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("video_processed_dir", type=str, help="Path to data/processed/<video_name>")
    p.add_argument("--window", type=float, default=20.0, help="Window size in seconds for demo summaries")
    args = p.parse_args()
    video_dir = Path(args.video_processed_dir)
    if not video_dir.exists():
        raise SystemExit("Processed directory not found: " + str(video_dir))
    meta = load_metadata(video_dir)
    captions = simple_aggregate_captions(meta, window=args.window)
    out = {
        "video": meta.get("video"),
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "captions": captions
    }
    print(json.dumps(out, indent=2))
