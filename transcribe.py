#!/usr/bin/env python3
"""
Stage 1: Transcribe a video/audio file into word-level timestamped JSON.

Two backends, chosen automatically:
  * mlx-whisper  — Apple Silicon GPU. Much faster on an M-series Mac.
  * faster-whisper — CPU int8. Portable fallback (Linux/Windows/Intel).

The output JSON shape is identical either way, so downstream stages
(select_clips.py, render.py) never need to know which one ran.

Usage:
    python3 transcribe.py input/video.mp4 transcripts/video.json [model_size] [language]

`language` is an ISO-639-1 code (e.g. "sr", "en"). Leave it off to let
Whisper auto-detect — but pin it whenever you know it. Auto-detection
drifts badly across closely-related languages (Serbian/Croatian/Bosnian,
Danish/Norwegian), and a wrong guess poisons every downstream stage.
"""
import json
import sys
from pathlib import Path

# faster-whisper sizes -> mlx-community repos
MLX_REPOS = {
    "tiny": "mlx-community/whisper-tiny-mlx",
    "base": "mlx-community/whisper-base-mlx",
    "small": "mlx-community/whisper-small-mlx",
    "medium": "mlx-community/whisper-medium-mlx",
    "large": "mlx-community/whisper-large-v3-mlx",
    "large-v3": "mlx-community/whisper-large-v3-mlx",
    "turbo": "mlx-community/whisper-large-v3-turbo",
    "large-v3-turbo": "mlx-community/whisper-large-v3-turbo",
}


def _mlx_available():
    try:
        import mlx_whisper  # noqa: F401
        import platform
        return platform.system() == "Darwin" and platform.machine() == "arm64"
    except ImportError:
        return False


def _transcribe_mlx(input_path, model_size, language=None):
    import mlx_whisper

    repo = MLX_REPOS.get(model_size, model_size if "/" in model_size else MLX_REPOS["small"])
    print(f"[transcribe] backend=mlx-whisper model={repo} language={language or 'auto'} (Apple Silicon GPU)")
    result = mlx_whisper.transcribe(
        input_path, path_or_hf_repo=repo, word_timestamps=True, verbose=False,
        language=language,
    )
    return result.get("segments", []), result.get("language")


def _transcribe_faster(input_path, model_size, language=None):
    from faster_whisper import WhisperModel

    print(f"[transcribe] backend=faster-whisper model={model_size} language={language or 'auto'} (CPU int8)")
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segments, info = model.transcribe(input_path, word_timestamps=True, vad_filter=True,
                                      language=language)
    return list(segments), info.language


def transcribe(input_path: str, output_path: str, model_size: str = "small",
               language: str | None = None):
    if _mlx_available():
        raw_segments, detected = _transcribe_mlx(input_path, model_size, language)
        print(f"[transcribe] transcribing {input_path} ...")
    else:
        raw_segments, detected = _transcribe_faster(input_path, model_size, language)

    result = {"language": detected, "duration": 0.0, "segments": []}
    full_text_parts = []

    for idx, seg in enumerate(raw_segments):
        # mlx returns dicts, faster-whisper returns objects
        def get(name, default=None):
            if isinstance(seg, dict):
                return seg.get(name, default)
            return getattr(seg, name, default)

        words = []
        for w in (get("words") or []):
            def wget(name, default=None):
                if isinstance(w, dict):
                    return w.get(name, default)
                return getattr(w, name, default)

            word = (wget("word") or "").strip()
            if not word:
                continue
            words.append({
                "word": word,
                "start": round(float(wget("start", 0.0) or 0.0), 2),
                "end": round(float(wget("end", 0.0) or 0.0), 2),
            })

        start = round(float(get("start", 0.0) or 0.0), 2)
        end = round(float(get("end", 0.0) or 0.0), 2)
        text = (get("text") or "").strip()

        result["segments"].append({
            "id": get("id", idx),
            "start": start,
            "end": end,
            "text": text,
            "words": words,
        })
        full_text_parts.append(text)
        result["duration"] = max(result["duration"], end)
        print(f"  [{start:7.2f}s -> {end:7.2f}s] {text}")

    result["text"] = " ".join(full_text_parts)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"[transcribe] wrote {output_path} ({len(result['segments'])} segments)")
    return result


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: python3 transcribe.py <input_media> <output_json> [model_size] [language]")
        sys.exit(1)
    size = sys.argv[3] if len(sys.argv) > 3 else "small"
    lang = sys.argv[4] if len(sys.argv) > 4 else None
    transcribe(sys.argv[1], sys.argv[2], size, lang)
