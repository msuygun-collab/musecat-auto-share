"""AI Auto-Caption engine for MuseCat Pro (Local faster-whisper + Groq Whisper API + FFmpeg ASS burner)."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from src.config import DATA_DIR

logger = logging.getLogger(__name__)

GROQ_TRANSCRIBE_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
CAPTION_OUTPUT_DIR = DATA_DIR / "captioned_clips"


@dataclass
class CaptionSegment:
    """A single timed subtitle line or short 2-4 word streamer phrase."""

    start: float
    end: float
    text: str


def find_ffmpeg() -> str:
    """Locate ffmpeg executable on PATH or via imageio-ffmpeg fallback."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg  # type: ignore[import-not-found]

        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and Path(exe).is_file():
            return str(exe)
    except Exception:
        pass
    return ""


def _format_ass_time(seconds: float) -> str:
    s = max(0.0, float(seconds))
    hours = int(s // 3600)
    minutes = int((s % 3600) // 60)
    secs = int(s % 60)
    centis = int(round((s - int(s)) * 100))
    if centis >= 100:
        centis = 99
    return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"


def _escape_ass_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}").replace("\n", "\\N")


def _group_words_into_phrases(
    words: list[dict[str, Any]],
    max_words: int = 4,
    max_chars: int = 24,
) -> list[CaptionSegment]:
    """Group word-level timestamps into punchy 2-4 word vertical Shorts/Reels lines."""
    segments: list[CaptionSegment] = []
    buf: list[dict[str, Any]] = []
    char_count = 0

    for w in words:
        word_text = str(w.get("word", "")).strip()
        if not word_text:
            continue
        start = float(w.get("start", 0.0))
        end = float(w.get("end", start + 0.3))

        if buf and (len(buf) >= max_words or char_count + len(word_text) + 1 > max_chars):
            phrase = " ".join(str(x["word"]).strip() for x in buf)
            segments.append(
                CaptionSegment(start=float(buf[0]["start"]), end=float(buf[-1]["end"]), text=phrase)
            )
            buf = []
            char_count = 0

        buf.append({"word": word_text, "start": start, "end": end})
        char_count += len(word_text) + 1

    if buf:
        phrase = " ".join(str(x["word"]).strip() for x in buf)
        segments.append(
            CaptionSegment(start=float(buf[0]["start"]), end=float(buf[-1]["end"]), text=phrase)
        )
    return segments


def build_ass_file(
    segments: list[CaptionSegment],
    ass_path: Path,
    style: str = "streamer",
) -> Path:
    """Write a stylized 1080x1920 vertical ASS subtitle file."""
    style_norm = (style or "streamer").strip().lower()
    if style_norm == "classic":
        # Crisp white with soft dark box
        style_line = (
            "Style: Default,Arial,58,&H00FFFFFF,&H0000FFFF,&H00000000,&H88000000,"
            "-1,0,0,0,100,100,0,0,1,4,2,2,60,60,185,1"
        )
    elif style_norm == "neon":
        # Cyan glow gaming style
        style_line = (
            "Style: Default,Arial Black,62,&H00FFEE22,&H00FF66FF,&H003A124A,&H80000000,"
            "-1,0,0,0,100,100,0,0,1,6,3,2,60,60,195,1"
        )
    else:
        # Streamer (Hormozi-inspired bold yellow/white punchy outline, lower-third subtitle zone)
        style_line = (
            "Style: Default,Arial Black,64,&H0000E5FF,&H00FFFFFF,&H00000000,&H90000000,"
            "-1,0,0,0,100,100,0,0,1,7,3,2,60,60,195,1"
        )

    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "PlayResX: 1080\n"
        "PlayResY: 1920\n"
        "WrapStyle: 2\n"
        "ScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"{style_line}\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    lines = [header]
    for seg in segments:
        txt = _escape_ass_text(seg.text.strip())
        if not txt:
            continue
        if style_norm == "streamer":
            txt = txt.replace("i", "İ").replace("ı", "I").upper()
        lines.append(
            f"Dialogue: 0,{_format_ass_time(seg.start)},{_format_ass_time(seg.end)},Default,,0,0,0,,{txt}\n"
        )

    ass_path.parent.mkdir(parents=True, exist_ok=True)
    ass_path.write_text("".join(lines), encoding="utf-8")
    return ass_path


class CaptionEngine:
    """Dual-engine AI Auto-Captioner supporting Local faster-whisper and Groq Whisper API."""

    def __init__(self, config: Any) -> None:
        self.config = config

    def _engine_mode(self) -> str:
        mode = str(getattr(self.config, "caption_engine", "local") or "local").strip().lower()
        return mode if mode in ("local", "groq") else "local"

    def _language(self) -> str | None:
        lang = str(getattr(self.config, "caption_language", "auto") or "auto").strip().lower()
        return None if lang in ("", "auto") else lang

    def _style(self) -> str:
        return str(getattr(self.config, "caption_style", "streamer") or "streamer").strip().lower()

    def _extract_audio_mp3(self, video_path: Path, ffmpeg_exe: str, out_mp3: Path) -> Path:
        cmd = [
            ffmpeg_exe,
            "-y",
            "-i",
            str(video_path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-b:a",
            "64k",
            str(out_mp3),
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return out_mp3

    def transcribe_groq(self, video_path: Path, ffmpeg_exe: str) -> list[CaptionSegment]:
        api_key = str(getattr(self.config, "groq_api_key", "") or "").strip()
        if not api_key:
            raise RuntimeError(
                "Groq API Key eksik. MuseCat Pro sekmesinden ücretsiz Groq API anahtarınızı girin "
                "veya Yerel Whisper motoruna geçin."
            )

        with tempfile.TemporaryDirectory() as tmp:
            audio_path = Path(tmp) / "audio.mp3"
            upload_file = video_path
            if ffmpeg_exe:
                try:
                    upload_file = self._extract_audio_mp3(video_path, ffmpeg_exe, audio_path)
                except Exception:
                    upload_file = video_path

            data: dict[str, Any] = {
                "model": "whisper-large-v3-turbo",
                "response_format": "verbose_json",
                "timestamp_granularities[]": "word",
            }
            lang = self._language()
            if lang:
                data["language"] = lang

            with upload_file.open("rb") as fh:
                resp = requests.post(
                    GROQ_TRANSCRIBE_URL,
                    headers={"Authorization": f"Bearer {api_key}"},
                    files={"file": (upload_file.name, fh)},
                    data=data,
                    timeout=90,
                )

            if not resp.ok:
                raise RuntimeError(f"Groq Whisper API hatası (HTTP {resp.status_code}): {resp.text[:250]}")

            payload = resp.json()
            words = payload.get("words") or []
            if words:
                return _group_words_into_phrases(words)

            raw_segs = payload.get("segments") or []
            return [
                CaptionSegment(
                    start=float(s.get("start", 0.0)),
                    end=float(s.get("end", 0.0)),
                    text=str(s.get("text", "")).strip(),
                )
                for s in raw_segs
                if str(s.get("text", "")).strip()
            ]

    def transcribe_local(self, video_path: Path) -> list[CaptionSegment]:
        try:
            from faster_whisper import WhisperModel  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError(
                "Yerel altyazı motoru (faster-whisper) yüklü değil.\n"
                "Kurmak için: pip install faster-whisper\n"
                "Veya MuseCat Pro sekmesinden ücretsiz Groq Whisper API motorunu seçin."
            ) from exc

        model_size = str(getattr(self.config, "whisper_model_size", "small") or "small").strip()
        model = WhisperModel(model_size, device="auto", compute_type="auto")
        segs_iter, _ = model.transcribe(
            str(video_path),
            language=self._language(),
            word_timestamps=True,
            vad_filter=True,
        )

        all_words: list[dict[str, Any]] = []
        fallback_segs: list[CaptionSegment] = []
        for seg in segs_iter:
            if getattr(seg, "words", None):
                for w in seg.words:
                    all_words.append({"word": w.word, "start": w.start, "end": w.end})
            elif seg.text and seg.text.strip():
                fallback_segs.append(
                    CaptionSegment(start=float(seg.start), end=float(seg.end), text=seg.text.strip())
                )

        if all_words:
            return _group_words_into_phrases(all_words)
        return fallback_segs

    def generate_captioned_video(self, video_path: str) -> tuple[bool, str, str]:
        """Transcribe and burn styled subtitles onto a copy of the video.

        Returns (success, output_video_path_or_empty, turkish_status_message).
        """
        src = Path(video_path)
        if not src.is_file():
            return False, "", f"Video dosyası bulunamadı: {video_path}"

        ffmpeg_exe = find_ffmpeg()
        if not ffmpeg_exe:
            return (
                False,
                "",
                "FFmpeg bulunamadı. Videoya altyazı gömmek için FFmpeg gereklidir "
                "(winget install Gyan.FFmpeg veya pip install imageio-ffmpeg).",
            )

        try:
            mode = self._engine_mode()
            if mode == "groq":
                segments = self.transcribe_groq(src, ffmpeg_exe)
            else:
                segments = self.transcribe_local(src)

            if not segments:
                return False, "", "Videoda konuşma/altyazı tespit edilemedi."

            CAPTION_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            out_video = CAPTION_OUTPUT_DIR / f"{src.stem}_subtitled.mp4"

            with tempfile.TemporaryDirectory() as tmp:
                ass_file = build_ass_file(segments, Path(tmp) / "captions.ass", style=self._style())
                # Escape Windows drive colon and backslashes for FFmpeg ass filter
                ass_escaped = str(ass_file).replace("\\", "/").replace(":", "\\:")
                cmd = [
                    ffmpeg_exe,
                    "-y",
                    "-i",
                    str(src),
                    "-vf",
                    f"ass='{ass_escaped}'",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    "-crf",
                    "20",
                    "-c:a",
                    "copy",
                    str(out_video),
                ]
                proc = subprocess.run(cmd, capture_output=True, text=True)
                if proc.returncode != 0 or not out_video.is_file():
                    err_tail = (proc.stderr or "")[-300:]
                    return False, "", f"FFmpeg altyazı işleme hatası: {err_tail}"

            return True, str(out_video), f"✓ Altyazılı video hazır ({len(segments)} satır): {out_video.name}"
        except Exception as exc:  # noqa: BLE001
            logger.exception("Otomatik altyazı hatası: %s", exc)
            return False, "", f"Altyazı oluşturulamadı: {exc}"
