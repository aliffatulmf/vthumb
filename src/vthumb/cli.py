from __future__ import annotations

import argparse
import math
import signal
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

import ffmpeg
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from vthumb import __version__

VIDEO_EXTENSIONS = {
    ".3gp",
    ".avi",
    ".flv",
    ".m4v",
    ".mkv",
    ".mov",
    ".mp4",
    ".mpeg",
    ".mpg",
    ".ts",
    ".webm",
    ".wmv",
}

console = Console()
error_console = Console(stderr=True)


def positive_int(value: str) -> int:
    """Parse a strictly positive integer for argparse.

    Args:
        value: String value from command-line argument.

    Returns:
        The parsed positive integer.

    Raises:
        argparse.ArgumentTypeError: If value is not an integer or is <= 0.
    """
    try:
        result = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if result < 1:
        raise argparse.ArgumentTypeError("must be greater than 0")
    return result


def non_negative_float(value: str) -> float:
    """Parse a non-negative float for argparse.

    Args:
        value: String value from command-line argument.

    Returns:
        The parsed non-negative float.

    Raises:
        argparse.ArgumentTypeError: If value is not a finite non-negative number.
    """
    try:
        result = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a non-negative number") from exc
    if math.isinf(result) or math.isnan(result):
        raise argparse.ArgumentTypeError("must be a finite non-negative number")
    if result < 0:
        raise argparse.ArgumentTypeError("must be greater than or equal to 0")
    return result


@dataclass(frozen=True)
class VideoResult:
    """Outcome of processing a single video."""

    video: Path
    output: Path
    error: Exception | None = None


@dataclass
class _ShutdownRequest:
    """Thread-safe flag for graceful shutdown."""

    requested: bool = field(default=False, init=False)

    def request(self) -> None:
        self.requested = True

    def is_set(self) -> bool:
        return self.requested


def _compute_usable_range(
    duration: float, skip_start: float, skip_end: float
) -> tuple[float, float, float]:
    """Compute the usable time range after applying skip offsets.

    Returns:
        A tuple of (usable_start, usable_end, usable_duration).
    """
    usable_start = min(skip_start, duration)
    usable_end = max(duration - skip_end, usable_start)
    usable_duration = usable_end - usable_start
    if usable_duration <= 0:
        usable_start = 0.0
        usable_end = duration
        usable_duration = duration
    return usable_start, usable_end, usable_duration


def jpeg_quality(value: str) -> int:
    """Parse a JPEG quality value (1-31) for argparse.

    Lower values produce higher quality. 1 is best, 31 is worst.

    Args:
        value: String value from command-line argument.

    Returns:
        The parsed quality value.

    Raises:
        argparse.ArgumentTypeError: If value is not an integer in 1-31.
    """
    try:
        result = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if not 1 <= result <= 31:
        raise argparse.ArgumentTypeError("must be between 1 and 31")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vthumb",
        description="Create thumbnail contact sheets from one video or a folder of videos.",
    )
    parser.add_argument(
        "targets",
        type=Path,
        nargs="+",
        help="one or more video files, or a folder to process",
    )
    parser.add_argument(
        "--row",
        type=positive_int,
        default=5,
        help="number of rows (default: 5)",
    )
    parser.add_argument(
        "--col",
        type=positive_int,
        default=5,
        help="number of columns (default: 5)",
    )
    parser.add_argument(
        "--size",
        type=positive_int,
        default=720,
        help="thumbnail width in pixels (default: 720)",
    )
    parser.add_argument(
        "--quality",
        type=jpeg_quality,
        default=2,
        help="JPEG quality 1-31, lower is better (default: 2)",
    )
    parser.add_argument(
        "--padding",
        type=non_negative_float,
        default=4,
        help="padding between thumbnails in pixels (default: 4)",
    )
    parser.add_argument(
        "--margin",
        type=non_negative_float,
        default=4,
        help="outer margin around the grid in pixels (default: 4)",
    )
    parser.add_argument(
        "--timestamp",
        action="store_true",
        help="overlay timestamp text on each thumbnail frame",
    )
    parser.add_argument(
        "--interval",
        type=non_negative_float,
        default=None,
        help="seconds between frames; overrides --row/--col grid count",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="output folder (default: next to the video)",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="search for videos in subfolders",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="overwrite existing output files",
    )
    parser.add_argument(
        "--workers",
        type=positive_int,
        default=2,
        help="videos processed concurrently (default: 2)",
    )
    parser.add_argument(
        "--accurate-seek",
        action="store_true",
        help=(
            "decode from the nearest keyframe for accurate snapshots; "
            "slower but useful for problematic .ts files"
        ),
    )
    parser.add_argument(
        "--skip-start",
        type=non_negative_float,
        default=10,
        help="seconds to skip from the start of the video (default: 10)",
    )
    parser.add_argument(
        "--skip-end",
        type=non_negative_float,
        default=10,
        help="seconds to skip from the end of the video (default: 10)",
    )
    parser.add_argument(
        "--verror",
        action="store_true",
        help="show ffmpeg/ffprobe errors (default: silent)",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="disable colored output",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def find_videos(target: Path, recursive: bool) -> list[Path]:
    """Return supported video files found in target.

    Args:
        target: A file path or directory to search.
        recursive: If True, search subdirectories as well.

    Returns:
        List of video file paths with supported extensions (unsorted).
    """
    if target.is_file():
        return [target] if target.suffix.lower() in VIDEO_EXTENSIONS else []
    pattern = "**/*" if recursive else "*"
    try:
        return [
            path
            for path in target.glob(pattern)
            if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS
        ]
    except PermissionError:
        error_console.print(f"[yellow]Permission denied:[/] {target}")
        return []


def video_duration(video: Path, verbosity: str = "quiet") -> float:
    """Get the duration of a video in seconds via ffprobe.

    Args:
        video: Path to the video file.
        verbosity: FFmpeg verbosity level (``"quiet"`` or ``"error"``).

    Returns:
        Duration in seconds.

    Raises:
        ValueError: If the reported duration is <= 0 or output is invalid.
        ffmpeg.Error: If ffprobe fails.
    """
    kwargs: dict = {}
    if verbosity == "error":
        kwargs["v"] = "error"
    try:
        probe = ffmpeg.probe(str(video), **kwargs)
    except ffmpeg.Error as exc:
        raise ValueError(f"ffprobe failed for {video.name}") from exc
    raw = probe["format"]["duration"]
    if not raw:
        raise ValueError(f"ffprobe returned empty output for {video.name}")
    try:
        duration = float(raw)
    except ValueError:
        raise ValueError(f"ffprobe returned invalid duration: {raw!r}") from None
    if duration <= 0:
        raise ValueError(f"invalid video duration ({duration}) for {video.name}")
    return duration


def output_path(video: Path, output_dir: Path | None = None) -> Path:
    """Return the JPEG destination path for a thumbnail.

    Args:
        video: Path to the source video file.
        output_dir: Optional output directory. If None, places the
            thumbnail next to the video.

    Returns:
        Full path to the output JPEG file.
    """
    filename = f"{video.name}.jpg"
    return (output_dir / filename) if output_dir else video.with_name(filename)


def snapshot_timestamps(
    duration: float,
    count: int,
    *,
    skip_start: float = 10,
    skip_end: float = 10,
    usable_start: float | None = None,
    usable_duration: float | None = None,
) -> list[float]:
    """Return evenly spaced seek points within the usable video range.

    The usable range starts at ``skip_start`` and ends at
    ``duration - skip_end``. Timestamps are clamped to avoid the
    unseekable final EOF frame.

    Args:
        duration: Total video duration in seconds.
        count: Number of timestamps to generate.
        skip_start: Seconds to skip from the start of the video.
        skip_end: Seconds to skip from the end of the video.
        usable_start: Pre-computed usable start (avoids redundant call).
        usable_duration: Pre-computed usable duration (avoids redundant call).

    Returns:
        List of seek-point timestamps, or an empty list if the usable
        range is too short or count is zero.
    """
    if usable_start is None or usable_duration is None:
        usable_start, _, usable_duration = _compute_usable_range(duration, skip_start, skip_end)

    if usable_duration <= 0 or count <= 0:
        return []

    usable_end = usable_start + usable_duration
    interval = usable_duration / count
    last_seekable = max(usable_end * 0.999, usable_end - 0.001)
    return [min(usable_start + interval * index, last_seekable) for index in range(1, count + 1)]


def create_thumbnail(
        video: Path,
        output: Path,
        *,
        rows: int,
        cols: int,
        size: int,
        quality: int,
        padding: float,
        margin: float,
        timestamp: bool,
        interval: float | None,
        skip_start: float,
        skip_end: float,
        accurate_seek: bool,
        verbose: bool,
) -> None:
    """Create a JPEG contact sheet from a video.

    Extracts individual frames at evenly spaced timestamps, scales them,
    and tiles them into a single JPEG grid image.

    Args:
        video: Path to the source video file.
        output: Path to write the output JPEG.
        rows: Number of rows in the grid.
        cols: Number of columns in the grid.
        size: Thumbnail width in pixels (height is computed automatically).
        quality: JPEG quality (1=best, 31=worst).
        padding: Padding in pixels between thumbnail cells.
        margin: Outer margin in pixels around the grid.
        timestamp: If True, overlay a timestamp on each frame.
        interval: Seconds between frames. When set, overrides rows*cols
            count and arranges frames in a single row.
        skip_start: Seconds to skip from the start of the video.
        skip_end: Seconds to skip from the end of the video.
        accurate_seek: If True, decode after -i for frame-accurate seeks.
            If False, use fast keyframe seeks before -i.
        verbose: If True, use ``-v error`` for ffmpeg/ffprobe. If False,
            use ``-v quiet`` to suppress output.

    Raises:
        ValueError: If the video is too short for the given skip values.
        ffmpeg.Error: If ffmpeg or ffprobe fails.
    """
    verbosity = "error" if verbose else "quiet"

    duration = video_duration(video, verbosity)
    usable_start, usable_end, usable_duration = _compute_usable_range(
        duration, skip_start, skip_end
    )

    if interval is not None and interval > 0:
        frame_count = max(1, math.ceil(usable_duration / interval))
    else:
        frame_count = rows * cols

    if usable_duration <= 0:
        raise ValueError("video too short to generate thumbnails with the given skip values")

    with tempfile.TemporaryDirectory(prefix="vthumb-", ignore_cleanup_errors=True) as tmp_dir:
        tmp_path = Path(tmp_dir)
        frame_temp = str(tmp_path / "frame_%04d.jpg")
        timestamps = snapshot_timestamps(
            duration,
            frame_count,
            skip_start=skip_start,
            skip_end=skip_end,
            usable_start=usable_start,
            usable_duration=usable_duration,
        )
        video_str = str(video)

        for index, seek_time in enumerate(timestamps, start=1):
            frame_path = tmp_path / f"frame_{index:04d}.jpg"

            if accurate_seek:
                inp = ffmpeg.input(video_str)
            else:
                inp = ffmpeg.input(video_str, ss=f"{seek_time:.6f}")

            stream = inp.video.filter("scale", size, -2)
            if timestamp:
                minutes = int(seek_time // 60)
                seconds = seek_time % 60
                time_text = f"{minutes:02d}\\:{seconds:05.2f}"
                stream = stream.drawtext(
                    text=time_text,
                    fontsize=14,
                    fontcolor="white",
                    borderw=1,
                    bordercolor="black",
                    x=5,
                    y=5,
                )

            if accurate_seek:
                out = ffmpeg.output(
                    stream,
                    str(frame_path),
                    **{
                        "an": None,
                        "sn": None,
                        "dn": None,
                        "frames:v": 1,
                        "q:v": quality,
                        "ss": f"{seek_time:.6f}",
                    },
                )
            else:
                out = ffmpeg.output(
                    stream,
                    str(frame_path),
                    **{"an": None, "sn": None, "dn": None, "frames:v": 1, "q:v": quality},
                )
            out.overwrite_output().run(quiet=verbosity == "quiet")

        if interval and interval > 0:
            effective_rows, effective_cols = 1, frame_count
        else:
            effective_rows, effective_cols = rows, cols

        tile_padding = round(padding)
        tile_margin = round(margin)

        inp = ffmpeg.input(frame_temp, framerate=1)
        stream = inp.video.filter(
            "tile",
            f"{effective_cols}x{effective_rows}",
            padding=tile_padding,
            margin=tile_margin,
        )
        out = ffmpeg.output(
            stream,
            str(output),
            **{"an": None, "sn": None, "dn": None, "frames:v": 1, "q:v": quality},
        )
        out.overwrite_output().run(quiet=verbosity == "quiet")

        if not output.exists() or output.stat().st_size == 0:
            raise ValueError(f"ffmpeg produced empty or missing output: {output}")


def process_video(
        video: Path,
        output: Path,
        args: argparse.Namespace
) -> VideoResult:
    """Create one thumbnail and return its outcome for main-thread reporting.

    Args:
        video: Path to the source video file.
        output: Path to write the output JPEG.
        args: Parsed CLI arguments namespace.

    Returns:
        A VideoResult with the outcome.
    """
    try:
        create_thumbnail(
            video,
            output,
            rows=args.row,
            cols=args.col,
            size=args.size,
            quality=args.quality,
            padding=args.padding,
            margin=args.margin,
            timestamp=args.timestamp,
            interval=args.interval,
            skip_start=args.skip_start,
            skip_end=args.skip_end,
            accurate_seek=args.accurate_seek,
            verbose=args.verror,
        )
    except (
        ffmpeg.Error,
        ValueError, FileNotFoundError, OSError,
    ) as exc:
        return VideoResult(video=video, output=output, error=exc)
    return VideoResult(video=video, output=output)


def main(argv: list[str] | None = None) -> int:
    """Entry point for the CLI.

    Validates inputs, discovers video files, and processes them in
    parallel using a thread pool. Handles SIGINT/SIGTERM for graceful
    shutdown — running jobs are allowed to finish, remaining jobs are
    skipped, and a partial summary is printed.

    Args:
        argv: Optional list of arguments. Defaults to sys.argv[1:].

    Returns:
        0 on success, 1 if any video failed or no videos found,
        2 for invalid arguments or missing dependencies.
    """
    args = build_parser().parse_args(argv)

    if args.no_color:
        console.no_color = True
        error_console.no_color = True

    targets = [target.expanduser().resolve() for target in args.targets]
    output_dir = args.output_dir.expanduser().resolve() if args.output_dir else None

    missing = next((t for t in targets if not t.exists()), None)
    if missing:
        error_console.print(f"[bold red]Target not found:[/] {missing}")
        return 2

    if output_dir and not output_dir.exists():
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            error_console.print(f"[bold red]Cannot create output directory:[/] {exc}")
            return 2

    videos = sorted(
        {video for target in targets for video in find_videos(target, args.recursive)},
        key=lambda path: str(path).lower(),
    )
    if not videos:
        error_console.print("[bold red]No supported video files found to process.[/]")
        return 1

    jobs: list[tuple[Path, Path]] = []
    for video in videos:
        output = output_path(video, output_dir)
        if output.exists() and not args.overwrite:
            console.print(f"[dim]Skipped (already exists):[/] {output.name}")
            continue
        jobs.append((video, output))

    if not jobs:
        console.print("[dim]All thumbnails already exist. Use --overwrite to regenerate.[/]")
        return 0

    shutdown = _ShutdownRequest()

    def _handle_signal(signum: int, _frame: object) -> None:
        shutdown.request()
        console.print("\n[yellow]Interrupted — waiting for running jobs to finish...[/]")

    # Register signal handlers (main thread only).
    signal.signal(signal.SIGINT, _handle_signal)
    if sys.platform != "win32":
        signal.signal(signal.SIGTERM, _handle_signal)

    succeeded = 0
    failed = 0
    cancelled = 0
    failed_videos: list[tuple[Path, str]] = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Processing videos...", total=len(jobs))
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {
                executor.submit(process_video, video, output, args): video for video, output in jobs
            }
            pending = set(futures)
            cancelled_rest = False
            for future in as_completed(futures):
                if shutdown.is_set() and not cancelled_rest:
                    # Cancel futures that haven't started yet.
                    for p in pending:
                        p.cancel()
                    cancelled += len(pending)
                    pending.clear()
                    cancelled_rest = True
                try:
                    result = future.result()
                except Exception as exc:
                    vid = futures[future]
                    failed += 1
                    failed_videos.append((vid, str(exc)))
                    progress.update(task, description=f"[red]Failed:[/] {vid.name}")
                    progress.advance(task)
                    pending.discard(future)
                    continue
                pending.discard(future)
                if result.error:
                    failed += 1
                    failed_videos.append((result.video, str(result.error)))
                    progress.update(task, description=f"[red]Failed:[/] {result.video.name}")
                else:
                    succeeded += 1
                    progress.update(task, description=f"[green]Created:[/] {result.output.name}")
                progress.advance(task)

    console.print()
    summary = Table(title="Summary", show_lines=False)
    summary.add_column("Metric", style="bold")
    summary.add_column("Value", justify="right")
    summary.add_row("Succeeded", f"[green]{succeeded}[/]")
    summary.add_row("Failed", f"[red]{failed}[/]" if failed else "0")
    if cancelled:
        summary.add_row("Cancelled", f"[yellow]{cancelled}[/]")
    summary.add_row("Total", str(len(jobs)))
    console.print(summary)

    if failed_videos:
        console.print()
        error_table = Table(title="Failed Videos", show_lines=False)
        error_table.add_column("File", style="red")
        error_table.add_column("Error")
        for video, error in failed_videos:
            error_table.add_row(str(video), error)
        error_console.print(error_table)

    return 1 if (failed or cancelled) else 0


if __name__ == "__main__":
    raise SystemExit(main())
