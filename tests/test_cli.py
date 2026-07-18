import subprocess as sp
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import pytest

from vthumb.cli import (
    VideoResult,
    _ShutdownRequest,
    build_parser,
    create_thumbnail,
    find_videos,
    jpeg_quality,
    main,
    non_negative_float,
    output_path,
    positive_int,
    process_video,
    snapshot_timestamps,
    video_duration,
)

# ---------------------------------------------------------------------------
# Argument parsers
# ---------------------------------------------------------------------------


def test_positive_int():
    assert positive_int("320") == 320


def test_positive_int_rejects_zero():
    with pytest.raises(Exception):
        positive_int("0")


def test_positive_int_rejects_negative():
    with pytest.raises(Exception):
        positive_int("-5")


def test_positive_int_rejects_non_numeric():
    with pytest.raises(Exception):
        positive_int("abc")


def test_non_negative_float_integers():
    assert non_negative_float("0") == 0.0
    assert non_negative_float("10") == 10.0


def test_non_negative_float_decimals():
    assert non_negative_float("2.5") == 2.5
    assert non_negative_float("0.001") == 0.001


def test_non_negative_float_rejects_negative():
    with pytest.raises(Exception):
        non_negative_float("-1.5")


def test_non_negative_float_rejects_non_numeric():
    with pytest.raises(Exception):
        non_negative_float("abc")


def test_non_negative_float_rejects_inf():
    with pytest.raises(Exception):
        non_negative_float("inf")


def test_non_negative_float_rejects_nan():
    with pytest.raises(Exception):
        non_negative_float("nan")


def test_jpeg_quality_valid():
    assert jpeg_quality("1") == 1
    assert jpeg_quality("15") == 15
    assert jpeg_quality("31") == 31


def test_jpeg_quality_rejects_zero():
    with pytest.raises(Exception):
        jpeg_quality("0")


def test_jpeg_quality_rejects_over_31():
    with pytest.raises(Exception):
        jpeg_quality("32")


def test_jpeg_quality_rejects_non_numeric():
    with pytest.raises(Exception):
        jpeg_quality("abc")


# ---------------------------------------------------------------------------
# build_parser
# ---------------------------------------------------------------------------


def test_build_parser_defaults():
    parser = build_parser()
    args = parser.parse_args(["video.mp4"])
    assert args.row == 5
    assert args.col == 5
    assert args.size == 720
    assert args.quality == 2
    assert args.padding == 4
    assert args.margin == 4
    assert args.timestamp is False
    assert args.interval is None
    assert args.recursive is False
    assert args.overwrite is False
    assert args.workers == 2
    assert args.accurate_seek is False
    assert args.skip_start == 10
    assert args.skip_end == 10
    assert args.no_color is False
    assert args.verror is False


def test_build_parser_custom_skip():
    parser = build_parser()
    args = parser.parse_args(["video.mp4", "--skip-start", "2.5", "--skip-end", "3.7"])
    assert args.skip_start == 2.5
    assert args.skip_end == 3.7


def test_build_parser_quality():
    parser = build_parser()
    args = parser.parse_args(["video.mp4", "--quality", "5"])
    assert args.quality == 5


def test_build_parser_padding_margin():
    parser = build_parser()
    args = parser.parse_args(["video.mp4", "--padding", "8", "--margin", "12"])
    assert args.padding == 8
    assert args.margin == 12


def test_build_parser_timestamp():
    parser = build_parser()
    args = parser.parse_args(["video.mp4", "--timestamp"])
    assert args.timestamp is True


def test_build_parser_interval():
    parser = build_parser()
    args = parser.parse_args(["video.mp4", "--interval", "5.0"])
    assert args.interval == 5.0


def test_build_parser_no_color():
    parser = build_parser()
    args = parser.parse_args(["video.mp4", "--no-color"])
    assert args.no_color is True


def test_build_parser_verror():
    parser = build_parser()
    args = parser.parse_args(["video.mp4", "--verror"])
    assert args.verror is True


def test_build_parser_all_flags():
    parser = build_parser()
    args = parser.parse_args(
        [
            "video.mp4",
            "--row",
            "3",
            "--col",
            "4",
            "--size",
            "640",
            "--quality",
            "1",
            "--padding",
            "0",
            "--margin",
            "0",
            "--timestamp",
            "--interval",
            "2.5",
            "--recursive",
            "--overwrite",
            "--workers",
            "4",
            "--accurate-seek",
            "--skip-start",
            "5",
            "--skip-end",
            "5",
            "--no-color",
            "--verror",
        ]
    )
    assert args.row == 3
    assert args.col == 4
    assert args.size == 640
    assert args.quality == 1
    assert args.padding == 0
    assert args.margin == 0
    assert args.timestamp is True
    assert args.interval == 2.5
    assert args.recursive is True
    assert args.overwrite is True
    assert args.workers == 4
    assert args.accurate_seek is True
    assert args.skip_start == 5
    assert args.skip_end == 5
    assert args.no_color is True
    assert args.verror is True


# ---------------------------------------------------------------------------
# find_videos
# ---------------------------------------------------------------------------


def test_find_videos_only_returns_supported_files(tmp_path: Path):
    (tmp_path / "movie.mp4").touch()
    (tmp_path / "notes.txt").touch()
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "clip.mkv").touch()
    (tmp_path / "recording.ts").touch()

    assert sorted(find_videos(tmp_path, recursive=False)) == sorted([
        tmp_path / "movie.mp4",
        tmp_path / "recording.ts",
    ])
    assert sorted(find_videos(tmp_path, recursive=True)) == sorted([
        tmp_path / "movie.mp4",
        nested / "clip.mkv",
        tmp_path / "recording.ts",
    ])


def test_find_videos_single_file(tmp_path: Path):
    video = tmp_path / "video.mp4"
    video.touch()
    assert find_videos(video, recursive=False) == [video]


def test_find_videos_unsupported_file(tmp_path: Path):
    (tmp_path / "image.jpg").touch()
    assert find_videos(tmp_path, recursive=False) == []


def test_find_videos_empty_directory(tmp_path: Path):
    assert find_videos(tmp_path, recursive=False) == []


# ---------------------------------------------------------------------------
# output_path
# ---------------------------------------------------------------------------


def test_output_path_defaults_to_video_location(tmp_path: Path):
    video = tmp_path / "video.ts"
    assert output_path(video) == tmp_path / "video.ts.jpg"


def test_output_path_with_output_dir(tmp_path: Path):
    video = tmp_path / "video.mp4"
    out_dir = tmp_path / "output"
    out_dir.mkdir()
    assert output_path(video, out_dir) == out_dir / "video.mp4.jpg"


def test_output_path_preserves_full_name(tmp_path: Path):
    video = tmp_path / "my.movie.file.mkv"
    assert output_path(video) == tmp_path / "my.movie.file.mkv.jpg"


# ---------------------------------------------------------------------------
# video_duration (mocked)
# ---------------------------------------------------------------------------


def test_video_duration_success(tmp_path: Path):
    fake_video = tmp_path / "video.mp4"
    with patch("vthumb.cli.subprocess.run") as mock_run:
        mock_run.return_value.stdout = "120.5\n"
        duration = video_duration(fake_video, "ffprobe")
        assert duration == 120.5


def test_video_duration_rejects_zero(tmp_path: Path):
    fake_video = tmp_path / "video.mp4"
    with patch("vthumb.cli.subprocess.run") as mock_run:
        mock_run.return_value.stdout = "0\n"
        with pytest.raises(ValueError, match="invalid video duration"):
            video_duration(fake_video, "ffprobe")


def test_video_duration_rejects_negative(tmp_path: Path):
    fake_video = tmp_path / "video.mp4"
    with patch("vthumb.cli.subprocess.run") as mock_run:
        mock_run.return_value.stdout = "-5\n"
        with pytest.raises(ValueError, match="invalid video duration"):
            video_duration(fake_video, "ffprobe")


def test_video_duration_empty_output(tmp_path: Path):
    fake_video = tmp_path / "video.mp4"
    with patch("vthumb.cli.subprocess.run") as mock_run:
        mock_run.return_value.stdout = "\n"
        with pytest.raises(ValueError, match="empty output"):
            video_duration(fake_video, "ffprobe")


def test_video_duration_non_numeric(tmp_path: Path):
    fake_video = tmp_path / "video.mp4"
    with patch("vthumb.cli.subprocess.run") as mock_run:
        mock_run.return_value.stdout = "N/A\n"
        with pytest.raises(ValueError, match="invalid duration"):
            video_duration(fake_video, "ffprobe")


def test_video_duration_called_process_error(tmp_path: Path):
    fake_video = tmp_path / "video.mp4"
    with patch("vthumb.cli.subprocess.run", side_effect=sp.CalledProcessError(1, "ffprobe")):
        with pytest.raises(sp.CalledProcessError):
            video_duration(fake_video, "ffprobe")


def test_video_duration_verbosity_error(tmp_path: Path):
    fake_video = tmp_path / "video.mp4"
    with patch("vthumb.cli.subprocess.run") as mock_run:
        mock_run.return_value.stdout = "60.0\n"
        duration = video_duration(fake_video, "ffprobe", verbosity="error")
        assert duration == 60.0


# ---------------------------------------------------------------------------
# snapshot_timestamps
# ---------------------------------------------------------------------------


def test_snapshot_timestamps_no_skip():
    assert snapshot_timestamps(60, 25, skip_start=0, skip_end=0) == [
        2.4 * index for index in range(1, 25)
    ] + [59.999]


def test_snapshot_timestamps_with_skip():
    timestamps = snapshot_timestamps(60, 25, skip_start=10, skip_end=10)
    assert len(timestamps) == 25
    assert timestamps[0] >= 10.0
    assert timestamps[-1] <= 50.001
    for ts in timestamps:
        assert 10.0 <= ts <= 50.001


def test_snapshot_timestamps_short_video():
    # Video shorter than skip range falls back to full duration
    timestamps = snapshot_timestamps(15, 25, skip_start=10, skip_end=10)
    assert len(timestamps) == 25
    assert timestamps[0] >= 0.0
    assert timestamps[-1] <= 15.001


def test_snapshot_timestamps_float_skip():
    timestamps = snapshot_timestamps(60, 4, skip_start=2.5, skip_end=2.5)
    assert len(timestamps) == 4
    # usable range: 2.5 to 57.5 => interval = 55/4 = 13.75
    # last_seekable clamps the final timestamp to 57.499
    assert timestamps[0] == pytest.approx(16.25)
    assert timestamps[-1] == pytest.approx(57.499)


def test_snapshot_timestamps_count_zero():
    assert snapshot_timestamps(60, 0, skip_start=0, skip_end=0) == []


def test_snapshot_timestamps_single_frame():
    timestamps = snapshot_timestamps(100, 1, skip_start=0, skip_end=0)
    assert len(timestamps) == 1
    assert timestamps[0] == pytest.approx(99.999, abs=0.01)


def test_snapshot_timestamps_skip_exceeds_duration():
    # Skip exceeds duration, falls back to full 5s range
    timestamps = snapshot_timestamps(5, 10, skip_start=3, skip_end=3)
    assert len(timestamps) == 10
    assert timestamps[0] >= 0.0
    assert timestamps[-1] <= 5.001


def test_snapshot_timestamps_with_precomputed_values():
    timestamps = snapshot_timestamps(
        60, 4, skip_start=10, skip_end=10,
        usable_start=10.0, usable_duration=40.0,
    )
    assert len(timestamps) == 4
    assert timestamps[0] == pytest.approx(20.0)
    assert timestamps[-1] == pytest.approx(49.999, abs=0.01)


# ---------------------------------------------------------------------------
# process_video (mocked)
# ---------------------------------------------------------------------------


def _make_args(**overrides):
    """Build a Namespace with all required fields for process_video."""
    defaults = dict(
        row=5,
        col=5,
        size=720,
        quality=2,
        padding=4,
        margin=4,
        timestamp=False,
        interval=None,
        skip_start=10,
        skip_end=10,
        accurate_seek=False,
        verror=False,
        ffmpeg="ffmpeg",
        ffprobe="ffprobe",
    )
    defaults.update(overrides)
    return Namespace(**defaults)


def test_process_video_success(tmp_path: Path):
    video = tmp_path / "video.mp4"
    dest = tmp_path / "video.mp4.jpg"
    args = _make_args()

    with patch("vthumb.cli.create_thumbnail") as mock_create:
        result = process_video(video, dest, args)
        assert result.video == video
        assert result.output == dest
        assert result.error is None
        mock_create.assert_called_once()


def test_process_video_failure(tmp_path: Path):
    video = tmp_path / "video.mp4"
    dest = tmp_path / "video.mp4.jpg"
    args = _make_args()

    with patch(
        "vthumb.cli.create_thumbnail",
        side_effect=sp.CalledProcessError(1, "ffmpeg"),
    ):
        result = process_video(video, dest, args)
        assert result.video == video
        assert result.output == dest
        assert isinstance(result.error, sp.CalledProcessError)


def test_process_video_passes_new_flags(tmp_path: Path):
    video = tmp_path / "video.mp4"
    dest = tmp_path / "video.mp4.jpg"
    args = _make_args(quality=1, padding=0, margin=0, timestamp=True, interval=5.0)

    with patch("vthumb.cli.create_thumbnail") as mock_create:
        process_video(video, dest, args)
        mock_create.assert_called_once_with(
            video,
            dest,
            rows=5,
            cols=5,
            size=720,
            quality=1,
            padding=0,
            margin=0,
            timestamp=True,
            interval=5.0,
            skip_start=10,
            skip_end=10,
            accurate_seek=False,
            verbose=False,
            ffmpeg="ffmpeg",
            ffprobe="ffprobe",
        )


def test_process_video_value_error(tmp_path: Path):
    video = tmp_path / "video.mp4"
    dest = tmp_path / "video.mp4.jpg"
    args = _make_args()

    with patch(
        "vthumb.cli.create_thumbnail",
        side_effect=ValueError("video too short"),
    ):
        result = process_video(video, dest, args)
        assert isinstance(result.error, ValueError)


def test_process_video_file_not_found(tmp_path: Path):
    video = tmp_path / "video.mp4"
    dest = tmp_path / "video.mp4.jpg"
    args = _make_args()

    with patch(
        "vthumb.cli.create_thumbnail",
        side_effect=FileNotFoundError("ffmpeg not found"),
    ):
        result = process_video(video, dest, args)
        assert isinstance(result.error, FileNotFoundError)


def test_process_video_os_error(tmp_path: Path):
    video = tmp_path / "video.mp4"
    dest = tmp_path / "video.mp4.jpg"
    args = _make_args()

    with patch(
        "vthumb.cli.create_thumbnail",
        side_effect=OSError("disk full"),
    ):
        result = process_video(video, dest, args)
        assert isinstance(result.error, OSError)


# ---------------------------------------------------------------------------
# create_thumbnail (mocked)
# ---------------------------------------------------------------------------


def test_create_thumbnail_success(tmp_path: Path):
    video = tmp_path / "video.mp4"
    output = tmp_path / "video.mp4.jpg"

    def fake_run(cmd, **kwargs):
        out = Path(cmd[-1])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"\xff")

    with patch("vthumb.cli.video_duration", return_value=60.0), \
         patch("vthumb.cli.subprocess.run", side_effect=fake_run):
        create_thumbnail(
            video, output, rows=2, cols=2, size=320, quality=2,
            padding=4, margin=4, timestamp=False, interval=None,
            skip_start=0, skip_end=0, accurate_seek=False,
            verbose=False, ffmpeg="ffmpeg", ffprobe="ffprobe",
        )
        assert output.exists()


def test_create_thumbnail_interval_mode(tmp_path: Path):
    video = tmp_path / "video.mp4"
    output = tmp_path / "video.mp4.jpg"

    def fake_run(cmd, **kwargs):
        out = Path(cmd[-1])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"\xff")

    with patch("vthumb.cli.video_duration", return_value=60.0), \
         patch("vthumb.cli.subprocess.run", side_effect=fake_run):
        create_thumbnail(
            video, output, rows=5, cols=5, size=320, quality=2,
            padding=4, margin=4, timestamp=False, interval=10.0,
            skip_start=0, skip_end=0, accurate_seek=False,
            verbose=False, ffmpeg="ffmpeg", ffprobe="ffprobe",
        )
        assert output.exists()


def test_create_thumbnail_accurate_seek(tmp_path: Path):
    video = tmp_path / "video.mp4"
    output = tmp_path / "video.mp4.jpg"
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        out = Path(cmd[-1])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"\xff")

    with patch("vthumb.cli.video_duration", return_value=60.0), \
         patch("vthumb.cli.subprocess.run", side_effect=fake_run):
        create_thumbnail(
            video, output, rows=1, cols=1, size=320, quality=2,
            padding=4, margin=4, timestamp=False, interval=None,
            skip_start=0, skip_end=0, accurate_seek=True,
            verbose=False, ffmpeg="ffmpeg", ffprobe="ffprobe",
        )
        frame_cmd = calls[0]
        assert "-i" in frame_cmd
        idx_i = frame_cmd.index("-i")
        assert frame_cmd[idx_i + 2] == "-ss"


def test_create_thumbnail_timestamp_mode(tmp_path: Path):
    video = tmp_path / "video.mp4"
    output = tmp_path / "video.mp4.jpg"
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        out = Path(cmd[-1])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"\xff")

    with patch("vthumb.cli.video_duration", return_value=60.0), \
         patch("vthumb.cli.subprocess.run", side_effect=fake_run):
        create_thumbnail(
            video, output, rows=1, cols=1, size=320, quality=2,
            padding=4, margin=4, timestamp=True, interval=None,
            skip_start=0, skip_end=0, accurate_seek=False,
            verbose=False, ffmpeg="ffmpeg", ffprobe="ffprobe",
        )
        frame_cmd = calls[0]
        vf_idx = frame_cmd.index("-vf")
        assert "drawtext" in frame_cmd[vf_idx + 1]


def test_create_thumbnail_video_too_short(tmp_path: Path):
    video = tmp_path / "video.mp4"
    output = tmp_path / "video.mp4.jpg"
    # duration=0 after fallback triggers the ValueError
    with patch("vthumb.cli.video_duration", return_value=0.0):
        with pytest.raises(ValueError, match="too short"):
            create_thumbnail(
                video, output, rows=5, cols=5, size=320, quality=2,
                padding=4, margin=4, timestamp=False, interval=None,
                skip_start=10, skip_end=10, accurate_seek=False,
                verbose=False, ffmpeg="ffmpeg", ffprobe="ffprobe",
            )


def test_create_thumbnail_ffmpeg_fails(tmp_path: Path):
    video = tmp_path / "video.mp4"
    output = tmp_path / "video.mp4.jpg"
    with patch("vthumb.cli.video_duration", return_value=60.0), \
         patch("vthumb.cli.subprocess.run", side_effect=sp.CalledProcessError(1, "ffmpeg")):
        with pytest.raises(sp.CalledProcessError):
            create_thumbnail(
                video, output, rows=1, cols=1, size=320, quality=2,
                padding=4, margin=4, timestamp=False, interval=None,
                skip_start=0, skip_end=0, accurate_seek=False,
                verbose=False, ffmpeg="ffmpeg", ffprobe="ffprobe",
            )


# ---------------------------------------------------------------------------
# main (integration, mocked)
# ---------------------------------------------------------------------------


def test_main_missing_target(tmp_path: Path):
    fake = tmp_path / "nonexistent.mp4"
    assert main([str(fake)]) == 2


def test_main_no_videos_found(tmp_path: Path):
    (tmp_path / "readme.txt").touch()
    assert main([str(tmp_path)]) == 1


def test_main_all_exist_no_overwrite(tmp_path: Path):
    video = tmp_path / "video.mp4"
    video.touch()
    output = tmp_path / "video.mp4.jpg"
    output.touch()
    assert main([str(video)]) == 0


def test_main_creates_thumbnails(tmp_path: Path):
    video = tmp_path / "video.mp4"
    video.touch()
    with patch("vthumb.cli.process_video") as mock_pv, \
         patch("vthumb.cli.video_duration", return_value=60.0):
        mock_pv.return_value = VideoResult(video=video, output=video.with_suffix(".mp4.jpg"))
        result = main([str(video)])
        assert result == 0
        mock_pv.assert_called_once()


# ---------------------------------------------------------------------------
# _ShutdownRequest
# ---------------------------------------------------------------------------


def test_shutdown_request_initially_not_set():
    req = _ShutdownRequest()
    assert req.is_set() is False


def test_shutdown_request_set():
    req = _ShutdownRequest()
    req.request()
    assert req.is_set() is True
