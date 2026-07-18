# vthumb

A command-line utility for generating thumbnail contact sheets from video files. It extracts evenly spaced frames from a video and composites them into a single JPEG grid image.

Built on top of [FFmpeg](https://ffmpeg.org/). Both `ffmpeg` and `ffprobe` must be available in your system `PATH`.

## Installation

### From PyPI

```powershell
uv tool install vthumb
```

### From Git

```powershell
uv tool install git+https://github.com/aliffatulmf/python-vthumb.git
```

### From source (development)

```powershell
uv tool install .
```

## Usage

```powershell
# Generate thumbnail for a single video
vthumb video.mp4

# Process multiple videos
vthumb intro.mp4 recording.ts trailer.mkv

# Process all videos in a directory
vthumb "D:\Videos"

# Customize grid layout and thumbnail size
vthumb "D:\Videos" --row 4 --col 6 --size 480

# Include subdirectories and specify output location
vthumb "D:\Videos" --recursive --output-dir .\output-thumbnails
```

Output files are placed adjacent to the source video by default. For example, `video.mp4` produces `video.mp4.jpg`.

## How It Works

1. **Duration extraction** - The tool reads video duration from container metadata via `ffprobe`. No decoding is performed at this stage.
2. **Timestamp calculation** - Given a grid of `R x C` frames and a usable duration `D`, the interval is computed as `D / (R x C)`. The usable duration accounts for configurable skip offsets at the start and end of the video.
3. **Frame extraction** - Each frame is extracted using `ffmpeg` with `-ss` positioned before `-i` (fast seek mode by default). Only the first video stream is mapped; audio, subtitle, and data tracks are excluded.
4. **Tiling** - Extracted frames are scaled to the target width and composited into a grid using the `tile` filter, producing a single JPEG output.

### Seek modes

- **Fast seek** (default): `-ss` is placed before `-i`. FFmpeg seeks to the nearest keyframe, which is fast but may produce frames slightly off from the requested timestamp.
- **Accurate seek** (`--accurate-seek`): `-ss` is placed after `-i`. FFmpeg decodes frames from the nearest keyframe up to the requested timestamp. Slower but more accurate, particularly useful for MPEG-TS files with poor indexing.

### Supported formats

| Format  | Support         | Notes                                                                                 |
| ------- | --------------- | ------------------------------------------------------------------------------------- |
| `.mp4`  | Fully supported | -                                                                                     |
| `.mkv`  | Fully supported | -                                                                                     |
| `.avi`  | Fully supported | -                                                                                     |
| `.mov`  | Fully supported | -                                                                                     |
| `.webm` | Fully supported | -                                                                                     |
| `.m4v`  | Fully supported | -                                                                                     |
| `.wmv`  | Fully supported | -                                                                                     |
| `.flv`  | Fully supported | -                                                                                     |
| `.mpeg` | Fully supported | -                                                                                     |
| `.mpg`  | Fully supported | -                                                                                     |
| `.ts`   | Partial         | May require `--accurate-seek` for streams with poor indexing or keyframe distribution |
| `.3gp`  | Fully supported | -                                                                                     |

Files with unrecognized extensions are ignored.

## Options

| Option              | Description                                                   | Default                  |
| ------------------- | ------------------------------------------------------------- | ------------------------ |
| `--row N`           | Number of grid rows                                           | `5`                      |
| `--col N`           | Number of grid columns                                        | `5`                      |
| `--size N`          | Thumbnail width in pixels (height is computed automatically)  | `720`                    |
| `--quality N`       | JPEG quality (`1` = best, `31` = worst)                       | `2`                      |
| `--padding N`       | Spacing between thumbnails in pixels                          | `4`                      |
| `--margin N`        | Outer margin around the grid in pixels                        | `4`                      |
| `--timestamp`       | Overlay timestamp text on each frame                          | off                      |
| `--interval S`      | Seconds between frames (overrides `--row`/`--col` grid count) | -                        |
| `--output-dir PATH` | Output directory                                              | adjacent to source video |
| `--recursive`       | Search for videos in subdirectories                           | off                      |
| `--overwrite`       | Overwrite existing output files                               | off                      |
| `--skip-start S`    | Seconds to skip from the start of the video                   | `10`                     |
| `--skip-end S`      | Seconds to skip from the end of the video                     | `10`                     |
| `--workers N`       | Number of videos processed concurrently                       | `2`                      |
| `--accurate-seek`   | Use frame-accurate seeking (slower)                           | off                      |
| `--verror`          | Display ffmpeg/ffprobe error output                           | off                      |
| `--no-color`        | Disable colored terminal output                               | off                      |
| `--ffmpeg PATH`     | Path to the ffmpeg executable                                 | `ffmpeg`                 |
| `--ffprobe PATH`    | Path to the ffprobe executable                                | `ffprobe`                |

## Exit Codes

| Code | Meaning                                                        |
| ---- | -------------------------------------------------------------- |
| `0`  | All videos processed successfully                              |
| `1`  | One or more videos failed, or no videos were found             |
| `2`  | Invalid arguments or missing dependencies (`ffmpeg`/`ffprobe`) |
