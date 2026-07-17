"""Media Review Service — ethical pre-screening before video montage.

Provides a structured review workflow for media files (photos & videos)
before they are assembled into a montage video.

Workflow:
  1. Scan: enumerate all media files in the input directory
  2. Analyze: extract metadata + key frames for Vision LLM analysis
  3. Classify: produce a per-file ethical assessment
  4. Report: compile a structured review report
  5. Approve: human must approve before montage proceeds

The actual Vision LLM analysis is done by the agent (Ouroboros) using
vlm_query/view_image tools — this service owns the data model and
persistence.
"""
import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── Default paths ──
DEFAULT_MEDIA_DIR = Path(
    r"C:\Users\User\Ouroboros\Deliverables\video_media\input"
)
DEFAULT_REVIEW_DIR = Path(
    r"C:\Users\User\Ouroboros\Deliverables\video_media\reviews"
)

# ── Classification levels ──
CLASS_GREEN = "green"       # OK — safe to use
CLASS_YELLOW = "yellow"     # Questionable — needs human review
CLASS_RED = "red"           # Blocked — explicit 18+/violence/hate
CLASS_UNKNOWN = "unknown"   # Not yet analyzed


@dataclass
class MediaFile:
    """Represents a single media file found in the input directory."""
    path: str                   # Absolute path
    filename: str               # Just the filename
    ext: str                    # Extension (lowercase)
    file_size_bytes: int        # File size
    file_size_mb: float         # File size in MB
    media_type: str             # "photo" or "video"
    duration_sec: Optional[float] = None  # Video duration (if available)
    width: Optional[int] = None           # Resolution
    height: Optional[int] = None          # Resolution
    classification: str = CLASS_UNKNOWN   # green/yellow/red/unknown
    classification_reason: str = ""       # Why it got this classification
    analyzed_by_vision: bool = False      # Whether Vision LLM has analyzed it
    vision_analysis: str = ""             # Raw Vision LLM analysis text
    frame_count: int = 0                  # Number of frames extracted (videos)
    frame_paths: list = field(default_factory=list)  # Paths to extracted frames


@dataclass
class ReviewReport:
    """Complete review report for one batch of media."""
    review_id: str              # Unique review id
    created_at: str             # ISO timestamp
    media_files: list = field(default_factory=list)  # List of MediaFile
    status: str = "draft"       # draft | in_progress | ready | approved | rejected
    summary: str = ""           # Human-readable summary
    approved_by: str = ""       # Who approved (e.g., "owner", "lpr")
    approved_at: str = ""       # When approved
    event_title: str = ""       # Associated event title (optional)
    event_id: str = ""          # Associated event id (optional)


class MediaReviewService:
    """Manages the media review lifecycle.

    Scan → Analyze → Report → Approve → Montage
    """

    def __init__(self, media_dir: Optional[Path] = None,
                 review_dir: Optional[Path] = None):
        self.media_dir = media_dir or DEFAULT_MEDIA_DIR
        self.review_dir = review_dir or DEFAULT_REVIEW_DIR
        self.review_dir.mkdir(parents=True, exist_ok=True)
        self._current_report: Optional[ReviewReport] = None

    # ── Scan ──

    def scan_media(self) -> list[dict]:
        """Scan the input directory and return metadata for all media files.

        Returns a list of dicts (MediaFile-compatible) sorted by filename.
        """
        if not self.media_dir.exists():
            logger.warning("Media directory does not exist: %s", self.media_dir)
            return []

        media_files = []
        for fname in sorted(os.listdir(self.media_dir)):
            fpath = self.media_dir / fname
            if not fpath.is_file():
                continue

            ext = Path(fname).suffix.lower()
            # Determine media type
            if ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"):
                media_type = "photo"
            elif ext in (".mp4", ".mov", ".avi", ".mkv", ".webm", ".wmv", ".m4v"):
                media_type = "video"
            else:
                continue  # Skip non-media files

            fsize = fpath.stat().st_size
            mf = MediaFile(
                path=str(fpath),
                filename=fname,
                ext=ext,
                file_size_bytes=fsize,
                file_size_mb=round(fsize / (1024 * 1024), 2),
                media_type=media_type,
            )
            media_files.append(asdict(mf))

        logger.info("Scanned %d media files in %s", len(media_files), self.media_dir)
        return media_files

    # ── Report management ──

    def create_report(self, media_files: list[dict],
                      event_title: str = "",
                      event_id: str = "") -> ReviewReport:
        """Create a new review report from scanned media."""
        review_id = f"review_{int(time.time())}"
        report = ReviewReport(
            review_id=review_id,
            created_at=datetime.utcnow().isoformat(),
            media_files=media_files,
            status="draft",
            event_title=event_title,
            event_id=event_id,
        )
        self._current_report = report
        self._save_report(report)
        return report

    def get_report(self, review_id: str) -> Optional[ReviewReport]:
        """Load a saved report by review_id."""
        rpath = self.review_dir / f"{review_id}.json"
        if not rpath.exists():
            return None
        try:
            with open(rpath, "r", encoding="utf-8") as f:
                data = json.load(f)
            return ReviewReport(**data)
        except Exception as e:
            logger.error("Failed to load report %s: %s", review_id, e)
            return None

    def update_report(self, report: ReviewReport) -> None:
        """Save an updated report."""
        self._save_report(report)
        self._current_report = report

    def _save_report(self, report: ReviewReport) -> None:
        """Persist a report to disk."""
        rpath = self.review_dir / f"{report.review_id}.json"
        with open(rpath, "w", encoding="utf-8") as f:
            json.dump(asdict(report), f, ensure_ascii=False, indent=2)
        logger.info("Saved review report %s", report.review_id)

    def list_reports(self) -> list[dict]:
        """List all saved review reports (id, status, created_at)."""
        reports = []
        for fname in sorted(os.listdir(self.review_dir), reverse=True):
            if not fname.endswith(".json"):
                continue
            rpath = self.review_dir / fname
            try:
                with open(rpath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                reports.append({
                    "review_id": data.get("review_id", fname),
                    "status": data.get("status", "unknown"),
                    "created_at": data.get("created_at", ""),
                    "file_count": len(data.get("media_files", [])),
                    "event_title": data.get("event_title", ""),
                })
            except Exception:
                continue
        return reports

    # ── Classification helpers ──

    def get_classification_counts(self, report: ReviewReport) -> dict:
        """Return count of files per classification level."""
        counts = {"green": 0, "yellow": 0, "red": 0, "unknown": 0}
        for mf in report.media_files:
            cls = mf.get("classification", CLASS_UNKNOWN)
            counts[cls] = counts.get(cls, 0) + 1
        return counts

    def has_red_flags(self, report: ReviewReport) -> bool:
        """Check if any file is classified as red (blocked)."""
        return any(
            mf.get("classification") == CLASS_RED
            for mf in report.media_files
        )

    def has_yellow_flags(self, report: ReviewReport) -> bool:
        """Check if any file is classified as yellow (questionable)."""
        return any(
            mf.get("classification") == CLASS_YELLOW
            for mf in report.media_files
        )

    def all_analyzed(self, report: ReviewReport) -> bool:
        """Check if all files have been analyzed."""
        return all(
            mf.get("analyzed_by_vision") or mf.get("classification") != CLASS_UNKNOWN
            for mf in report.media_files
        )

    # ── Report text generation ──

    def generate_report_text(self, report: ReviewReport) -> str:
        """Generate a human-readable report text for Telegram/chat."""
        counts = self.get_classification_counts(report)
        total = len(report.media_files)
        lines = [
            f"📋 <b>Отчёт по проверке медиа</b>",
            f"",
            f"📁 Всего файлов: {total}",
            f"",
            f"<b>Статус проверки:</b>",
            f"🟢 Чисто: {counts['green']}",
            f"🟡 Сомнительно: {counts['yellow']}",
            f"🔴 Заблокировано: {counts['red']}",
            f"⚪ Не проверено: {counts['unknown']}",
            f"",
        ]

        if report.event_title:
            lines.append(f"🎯 Мероприятие: {report.event_title}")

        lines.append(f"🆔 Review ID: <code>{report.review_id}</code>")
        lines.append(f"")

        # Per-file details
        if total > 0:
            lines.append(f"<b>Детали по файлам:</b>")
            for i, mf in enumerate(report.media_files, 1):
                cls = mf.get("classification", CLASS_UNKNOWN)
                icon = {"green": "🟢", "yellow": "🟡", "red": "🔴", "unknown": "⚪"}.get(cls, "⚪")
                fname = mf.get("filename", "?")
                fsize = mf.get("file_size_mb", 0)
                mtype = mf.get("media_type", "?")
                reason = mf.get("classification_reason", "")
                info = f"{icon} <b>{fname}</b> ({mtype}, {fsize} MB)"
                if reason:
                    info += f"\n   └ {reason}"
                lines.append(info)

        # Summary
        lines.append(f"")
        if self.has_red_flags(report):
            lines.append(f"🚫 <b>Обнаружены заблокированные файлы!</b>")
            lines.append(f"Монтаж НЕ может быть выполнен до решения по ним.")
        elif self.has_yellow_flags(report):
            lines.append(f"⚠️ <b>Есть сомнительные файлы.</b>")
            lines.append(f"Требуется ручное одобрение перед монтажом.")
        else:
            lines.append(f"✅ <b>Все файлы чисты.</b>")
            lines.append(f"Можно приступать к монтажу (после вашего подтверждения).")

        lines.append(f"")
        lines.append(f"<b>Следующий шаг:</b>")
        lines.append(f"• /media_approve <code>{report.review_id}</code> — ✅ утвердить и монтировать")
        lines.append(f"• /media_reject <code>{report.review_id}</code> — ❌ отклонить (удалить проблемные файлы)")
        lines.append(f"• /media_review_start — начать новую проверку")

        return "\n".join(lines)

    def generate_approval_request_text(self, report: ReviewReport) -> str:
        """Generate a short approval request message."""
        counts = self.get_classification_counts(report)
        total = len(report.media_files)
        status = "⛔ НУЖНО РЕШЕНИЕ" if self.has_red_flags(report) else "⚠️ ТРЕБУЕТ ПОДТВЕРЖДЕНИЯ"

        text = (
            f"🎬 <b>Предпросмотр медиа для монтажа</b>\n\n"
            f"📁 {total} файлов\n"
            f"🟢 {counts['green']} чисты | 🟡 {counts['yellow']} cомнительно | 🔴 {counts['red']} заблокировано\n\n"
            f"<b>Статус: {status}</b>\n\n"
            f"Пожалуйста, проверь отчёт и реши:\n"
            f"✅ /media_approve <code>{report.review_id}</code> — утвердить всё\n"
            f"❌ /media_reject <code>{report.review_id}</code> — отклонить\n"
            f"📋 /media_report <code>{report.review_id}</code> — полный отчёт"
        )
        return text


# ══════════════════════════════════════════════
#  Standalone helper — extract video frames
# ══════════════════════════════════════════════

def extract_preview_frames(video_path: str, output_dir: Path,
                           max_frames: int = 5) -> list[str]:
    """Extract preview frames from a video using ffmpeg (via imageio-ffmpeg).

    Returns list of extracted frame file paths.
    Falls back to empty list if ffmpeg is unavailable.
    """
    import subprocess

    video = Path(video_path)
    if not video.exists():
        logger.warning("Video not found: %s", video_path)
        return []

    # Try to find ffmpeg
    try:
        from imageio_ffmpeg import get_ffmpeg_exe
        ffmpeg_path = get_ffmpeg_exe()
    except (ImportError, RuntimeError):
        logger.warning("imageio-ffmpeg not available, cannot extract frames")
        return []

    output_dir.mkdir(parents=True, exist_ok=True)
    base = video.stem
    frames = []

    # Get video duration
    try:
        result = subprocess.run(
            [ffmpeg_path, "-i", str(video), "-f", "null", "-"],
            capture_output=True, text=True, timeout=30,
        )
        duration = None
        for line in result.stderr.split("\n"):
            if "Duration" in line:
                import re
                m = re.search(r"(\d+):(\d+):(\d+)\.(\d+)", line)
                if m:
                    duration = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
                    break
    except Exception:
        duration = None

    if duration and duration > 0:
        # Extract evenly spaced frames
        step = max(1, duration // (max_frames + 1))
        timestamps = [step * i for i in range(1, max_frames + 1) if step * i < duration]
    else:
        # Default: first few seconds
        timestamps = [1, 3, 5, 7, 10]

    for ts in timestamps:
        out_path = output_dir / f"{base}_frame_{ts}s.jpg"
        try:
            subprocess.run(
                [ffmpeg_path, "-ss", str(ts), "-i", str(video),
                 "-vframes", "1", "-q:v", "2", str(out_path)],
                capture_output=True, timeout=30,
            )
            if out_path.exists():
                frames.append(str(out_path))
        except Exception:
            continue

    return frames


# ══════════════════════════════════════════════
#  Quick test
# ══════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    svc = MediaReviewService()
    if len(sys.argv) > 1 and sys.argv[1] == "scan":
        media = svc.scan_media()
        print(f"Found {len(media)} media files:")
        for m in media:
            print(f"  {m['media_type']:5s} | {m['filename']:40s} | {m['file_size_mb']:6.2f} MB")
    elif len(sys.argv) > 1 and sys.argv[1] == "list":
        reports = svc.list_reports()
        if reports:
            print(f"Saved reviews ({len(reports)}):")
            for r in reports:
                print(f"  {r['review_id']:25s} | {r['status']:10s} | {r['created_at'][:19]}")
        else:
            print("No saved reviews.")
    else:
        print("Usage: python media_review_service.py scan|list")