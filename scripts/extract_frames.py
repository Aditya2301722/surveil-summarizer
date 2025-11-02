"""
Extract sampled frames from a video and save them under data/processed/<video_id>/
Usage:
    python scripts/extract_frames.py path/to/video.mp4 --fps 1.0
"""

import argparse
from pathlib import Path
import cv2
import json


def safe_name(p: Path) -> str:
    """Generate a safe folder name from the video filename."""
    return p.stem.replace(" ", "_").replace(".", "_")


def extract_frames(video_path: Path, out_dir: Path, sample_fps: float = 1.0, max_frames: int = None):
    """Extract frames from the given video at a target FPS and save them with timestamps."""
    out_dir.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(video_path))

    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")

    # Get basic video info
    video_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    duration = frame_count / video_fps if video_fps else 0.0
    print(f"Video FPS={video_fps:.2f}, frames={frame_count}, duration={duration:.2f}s")

    # Determine how often to sample frames
    step = max(1, int(round(video_fps / sample_fps)))

    idx = 0
    saved = 0
    metadata = {"video": str(video_path.name), "frames": []}

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        # Save every nth frame
        if idx % step == 0:
            ts = idx / video_fps
            fname = f"frame_{saved:04d}.jpg"
            out_path = out_dir / fname

            # Save frame as JPEG
            cv2.imwrite(str(out_path), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])

            # Robust relative path handling for Windows
            try:
                rel_path = out_path.resolve().relative_to(Path.cwd().resolve())
                rel_path_str = str(rel_path)
            except Exception:
                rel_path_str = str(out_path.resolve())

            metadata["frames"].append({
                "index": saved,
                "ts": ts,
                "path": rel_path_str
            })

            saved += 1
            if max_frames and saved >= max_frames:
                break

        idx += 1

    cap.release()

    # Save metadata
    meta_path = out_dir / "metadata.json"
    with open(meta_path, "w", encoding="utf-8") as fh:
        json.dump(metadata, fh, indent=2)

    print(f"✅ Saved {saved} frames to {out_dir}")
    print(f"📝 Metadata written to {meta_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract frames from video files for captioning.")
    parser.add_argument("video", type=str, help="Path to the input MP4 file.")
    parser.add_argument("--fps", type=float, default=1.0, help="Frames per second to sample (default: 1.0)")
    parser.add_argument("--max-frames", type=int, default=None, help="Stop after this many frames (optional).")

    args = parser.parse_args()
    video_path = Path(args.video)

    if not video_path.exists():
        raise SystemExit(f"Video file not found: {video_path}")

    vidname = safe_name(video_path)
    out_dir = Path("data") / "processed" / vidname

    extract_frames(video_path, out_dir, sample_fps=args.fps, max_frames=args.max_frames)
