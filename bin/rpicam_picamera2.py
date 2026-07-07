#!/usr/bin/env python3
"""Picamera2 backend compatible with the raspimjpeg FIFO/status contract."""

from __future__ import annotations

import argparse
import logging
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional


DEFAULT_CONFIG: Dict[str, str] = {
    "annotation": "RPi Cam %Y.%M.%D_%h:%m:%s",
    "brightness": "50",
    "contrast": "0",
    "saturation": "0",
    "exposure_compensation": "0",
    "exposure_mode": "auto",
    "white_balance": "auto",
    "autowbgain_r": "150",
    "autowbgain_b": "150",
    "rotation": "0",
    "hflip": "false",
    "vflip": "false",
    "width": "512",
    "quality": "10",
    "divider": "1",
    "video_width": "1920",
    "video_height": "1080",
    "video_fps": "25",
    "MP4Box": "background",
    "MP4Box_fps": "25",
    "image_width": "2592",
    "image_height": "1944",
    "image_quality": "10",
    "tl_interval": "30",
    "video_bitrate": "17000000",
    "video_split": "0",
    "motion_detection": "false",
    "base_path": "/var/www",
    "preview_path": "/dev/shm/mjpeg/cam.jpg",
    "image_path": "/var/www/media/im_%i_%Y%M%D_%h%m%s.jpg",
    "lapse_path": "/var/www/media/tl_%i_%t_%Y%M%D_%h%m%s.jpg",
    "video_path": "/var/www/media/vi_%v_%Y%M%D_%h%m%s.mp4",
    "status_file": "/dev/shm/mjpeg/status_mjpeg.txt",
    "control_file": "/var/www/FIFO",
    "media_path": "/var/www/media",
    "macros_path": "/var/www/macros",
    "user_config": "/var/www/uconfig",
    "count_format": "%04d",
    "log_file": "/var/www/scheduleLog.txt",
    "log_size": "5000",
}

CONFIG_COMMANDS = {
    "an": "annotation",
    "br": "brightness",
    "co": "contrast",
    "sa": "saturation",
    "ec": "exposure_compensation",
    "em": "exposure_mode",
    "wb": "white_balance",
    "qu": "image_quality",
    "bi": "video_bitrate",
    "vi": "video_split",
    "tv": "tl_interval",
    "ls": "log_size",
}

NO_OP_COMMANDS = {
    "ab",
    "ac",
    "as",
    "at",
    "bu",
    "ce",
    "cn",
    "hp",
    "ie",
    "is",
    "mf",
    "mi",
    "mn",
    "ms",
    "mt",
    "mb",
    "me",
    "mz",
    "mm",
    "qp",
    "ri",
    "rl",
    "sh",
    "st",
    "vp",
    "vs",
    "wd",
}


def parse_bool(value: str) -> bool:
    return str(value).lower() in {"1", "true", "yes", "on"}


def safe_int(value: str, default: int) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def read_config_file(config_file: Path) -> Dict[str, str]:
    config: Dict[str, str] = {}
    if not config_file.exists():
        return config
    for raw_line in config_file.read_text(errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if " " in line:
            key, value = line.split(" ", 1)
            config[key] = value
        else:
            config[line] = ""
    return config


def load_config(paths: Iterable[Path]) -> Dict[str, str]:
    config = dict(DEFAULT_CONFIG)
    for path in paths:
        config.update(read_config_file(path))
    return config


def write_user_config(config: Dict[str, str], path: Path) -> None:
    keys = sorted(k for k in config if k in DEFAULT_CONFIG and config[k] != DEFAULT_CONFIG[k])
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        fh.write("#User config file\n")
        for key in keys:
            fh.write(f"{key} {config[key]}\n")


def apply_date_tokens(pattern: str, now: Optional[datetime] = None) -> str:
    now = now or datetime.now()
    replacements = {
        "%Y": now.strftime("%Y"),
        "%M": now.strftime("%m"),
        "%D": now.strftime("%d"),
        "%h": now.strftime("%H"),
        "%m": now.strftime("%M"),
        "%s": now.strftime("%S"),
    }
    for token, value in replacements.items():
        pattern = pattern.replace(token, value)
    return pattern


def next_index(media_path: Path, kind: str, count_format: str = "%04d") -> str:
    existing: List[int] = []
    for path in media_path.rglob(f"*.{kind}*.th.jpg"):
        match = re.search(rf"\.{re.escape(kind)}(\d+)\.th\.jpg$", path.name)
        if match:
            existing.append(int(match.group(1)))
    value = max(existing, default=0) + 1
    try:
        return count_format % value
    except (TypeError, ValueError):
        return f"{value:04d}"


def expand_path(pattern: str, index: str, lapse_index: int = 1, now: Optional[datetime] = None) -> Path:
    value = apply_date_tokens(pattern, now)
    value = value.replace("%i", index).replace("%v", index).replace("%t", f"{lapse_index:04d}")
    return Path(value)


def thumbnail_name(data_file: Path, kind: str, index: str) -> Path:
    return data_file.with_name(f"{data_file.name}.{kind}{index}.th.jpg")


def ffmpeg_remux_command(fps: int, input_file: Path, output_file: Path) -> List[str]:
    return [
        "ffmpeg",
        "-y",
        "-framerate",
        str(fps),
        "-i",
        str(input_file),
        "-c",
        "copy",
        str(output_file),
    ]


class CameraAdapter:
    def start(self) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError

    def capture_jpeg(self, path: Path, size: Optional[tuple[int, int]] = None, quality: int = 85) -> None:
        raise NotImplementedError

    def start_recording(self, path: Path, width: int, height: int, fps: int, bitrate: int) -> None:
        raise NotImplementedError

    def stop_recording(self) -> None:
        raise NotImplementedError

    def set_controls(self, controls: Dict[str, object]) -> None:
        raise NotImplementedError


class Picamera2Adapter(CameraAdapter):
    def __init__(self) -> None:
        from picamera2 import Picamera2
        from picamera2.encoders import H264Encoder
        from picamera2.outputs import FileOutput

        self._picamera2_cls = Picamera2
        self._h264_encoder_cls = H264Encoder
        self._file_output_cls = FileOutput
        self.picam2 = Picamera2()
        self.recording = False

    def _configure_preview(self) -> None:
        if self.picam2.started:
            self.picam2.stop()
        config = self.picam2.create_preview_configuration()
        self.picam2.configure(config)
        self.picam2.start()

    def start(self) -> None:
        if not self.picam2.started:
            self._configure_preview()

    def stop(self) -> None:
        if self.recording:
            self.stop_recording()
        if self.picam2.started:
            self.picam2.stop()

    def capture_jpeg(self, path: Path, size: Optional[tuple[int, int]] = None, quality: int = 85) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.picam2.capture_file(str(path))
        if size:
            resize_jpeg(path, path, size, quality)

    def start_recording(self, path: Path, width: int, height: int, fps: int, bitrate: int) -> None:
        if self.recording:
            return
        if self.picam2.started:
            self.picam2.stop()
        config = self.picam2.create_video_configuration(
            main={"size": (width, height)},
            controls={"FrameRate": fps},
        )
        self.picam2.configure(config)
        encoder = self._h264_encoder_cls(bitrate=bitrate)
        output = self._file_output_cls(str(path))
        self.picam2.start_recording(encoder, output)
        self.recording = True

    def stop_recording(self) -> None:
        if self.recording:
            self.picam2.stop_recording()
            self.recording = False
            self._configure_preview()

    def set_controls(self, controls: Dict[str, object]) -> None:
        if controls:
            self.picam2.set_controls(controls)


class PillowPlaceholderAdapter(CameraAdapter):
    """Test/development adapter used only when explicitly requested."""

    def __init__(self) -> None:
        self.recording_path: Optional[Path] = None

    def start(self) -> None:
        pass

    def stop(self) -> None:
        self.recording_path = None

    def capture_jpeg(self, path: Path, size: Optional[tuple[int, int]] = None, quality: int = 85) -> None:
        from PIL import Image, ImageDraw

        width, height = size or (640, 480)
        path.parent.mkdir(parents=True, exist_ok=True)
        image = Image.new("RGB", (width, height), (32, 48, 64))
        draw = ImageDraw.Draw(image)
        draw.text((12, 12), datetime.now().strftime("%Y-%m-%d %H:%M:%S"), fill=(240, 240, 240))
        image.save(path, "JPEG", quality=quality)

    def start_recording(self, path: Path, width: int, height: int, fps: int, bitrate: int) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.recording_path = path
        path.write_bytes(b"")

    def stop_recording(self) -> None:
        if self.recording_path:
            self.recording_path.write_bytes(b"\x00\x00\x00\x01")
        self.recording_path = None

    def set_controls(self, controls: Dict[str, object]) -> None:
        pass


def resize_jpeg(source: Path, destination: Path, size: tuple[int, int], quality: int = 85) -> None:
    from PIL import Image

    with Image.open(source) as image:
        image.thumbnail(size)
        image.convert("RGB").save(destination, "JPEG", quality=quality)


def atomic_capture(
    capture: Callable[[Path], None],
    destination: Path,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_name(f".{destination.stem}.tmp{destination.suffix}")
    capture(tmp)
    tmp.replace(destination)


@dataclass
class BackendState:
    config: Dict[str, str]
    camera: CameraAdapter
    running: bool = False
    video: bool = False
    timelapse: bool = False
    motion: bool = False
    image: bool = False
    stop_event: threading.Event = field(default_factory=threading.Event)
    lock: threading.RLock = field(default_factory=threading.RLock)
    timelapse_thread: Optional[threading.Thread] = None
    current_video_raw: Optional[Path] = None
    current_video_output: Optional[Path] = None
    current_video_index: Optional[str] = None

    @property
    def media_path(self) -> Path:
        return Path(self.config["media_path"])

    @property
    def status_file(self) -> Path:
        return Path(self.config["status_file"])

    @property
    def preview_file(self) -> Path:
        return Path(self.config["preview_path"])

    @property
    def control_file(self) -> Path:
        return Path(self.config["control_file"])

    @property
    def user_config_file(self) -> Path:
        return Path(self.config["user_config"])

    def status(self) -> str:
        if self.image:
            return "image"
        if not self.running:
            return "halted"
        prefix = ""
        if self.timelapse:
            prefix += "tl_"
        if self.motion:
            prefix += "md_"
        if self.video:
            return f"{prefix}video" if prefix else "video"
        return f"{prefix}ready" if prefix else "ready"

    def write_status(self) -> None:
        self.status_file.parent.mkdir(parents=True, exist_ok=True)
        self.status_file.write_text(self.status())

    def start_camera(self) -> None:
        with self.lock:
            if self.running:
                return
            self.camera.start()
            self.running = True
            self.write_status()

    def stop_camera(self) -> None:
        with self.lock:
            if self.video:
                self.stop_video()
            if self.timelapse:
                self.stop_timelapse()
            self.camera.stop()
            self.running = False
            self.write_status()

    def update_controls(self) -> None:
        controls: Dict[str, object] = {}
        brightness = safe_int(self.config.get("brightness", "50"), 50)
        contrast = safe_int(self.config.get("contrast", "0"), 0)
        saturation = safe_int(self.config.get("saturation", "0"), 0)
        exposure_compensation = safe_int(self.config.get("exposure_compensation", "0"), 0)
        controls["Brightness"] = (brightness - 50) / 50.0
        controls["Contrast"] = max(0.0, 1.0 + contrast / 100.0)
        controls["Saturation"] = max(0.0, 1.0 + saturation / 100.0)
        controls["ExposureValue"] = exposure_compensation
        self.camera.set_controls(controls)

    def capture_preview(self) -> None:
        if not self.running or self.video:
            return
        width = safe_int(self.config.get("width", "512"), 512)
        quality = safe_int(self.config.get("quality", "10"), 10)
        atomic_capture(
            lambda tmp: self.camera.capture_jpeg(tmp, size=(width, width), quality=max(30, min(95, quality))),
            self.preview_file,
        )

    def capture_image(self) -> Path:
        self.start_camera()
        with self.lock:
            self.image = True
            self.write_status()
        try:
            index = next_index(self.media_path, "i", self.config.get("count_format", "%04d"))
            destination = expand_path(self.config["image_path"], index)
            quality = safe_int(self.config.get("image_quality", "85"), 85)
            self.camera.capture_jpeg(destination, quality=max(30, min(95, quality)))
            make_thumbnail(destination, "i", index)
            self.capture_preview()
            return destination
        finally:
            with self.lock:
                self.image = False
                self.write_status()

    def start_video(self) -> None:
        self.start_camera()
        with self.lock:
            if self.video:
                return
            index = next_index(self.media_path, "v", self.config.get("count_format", "%04d"))
            output = expand_path(self.config["video_path"], index)
            raw = output.with_suffix(".h264")
            raw.parent.mkdir(parents=True, exist_ok=True)
            self.current_video_index = index
            self.current_video_output = output
            self.current_video_raw = raw
            self.camera.start_recording(
                raw,
                safe_int(self.config.get("video_width", "1920"), 1920),
                safe_int(self.config.get("video_height", "1080"), 1080),
                safe_int(self.config.get("video_fps", "25"), 25),
                safe_int(self.config.get("video_bitrate", "17000000"), 17000000),
            )
            self.video = True
            self.write_status()

    def stop_video(self) -> None:
        with self.lock:
            if not self.video:
                return
            raw = self.current_video_raw
            output = self.current_video_output
            index = self.current_video_index
            self.camera.stop_recording()
            self.video = False
            self.current_video_raw = None
            self.current_video_output = None
            self.current_video_index = None
            self.write_status()
        if raw and output and index:
            self.remux_video(raw, output)
            make_thumbnail(self.preview_file, "v", index, output)

    def remux_video(self, raw: Path, output: Path) -> None:
        fps = safe_int(self.config.get("MP4Box_fps", self.config.get("video_fps", "25")), 25)
        if self.config.get("MP4Box", "background").lower() == "off":
            return
        cmd = ffmpeg_remux_command(fps, raw, output)
        log_file = raw.with_suffix(".h264.log")
        with log_file.open("w") as log:
            result = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT)
        if result.returncode == 0 and output.exists():
            try:
                shutil.copystat(raw, output)
            except OSError:
                pass
            raw.unlink(missing_ok=True)
            log_file.unlink(missing_ok=True)
        else:
            raw.rename(raw.with_suffix(".h264.bad"))

    def start_timelapse(self) -> None:
        self.start_camera()
        with self.lock:
            if self.timelapse:
                return
            self.timelapse = True
            self.write_status()
            self.timelapse_thread = threading.Thread(target=self.timelapse_loop, daemon=True)
            self.timelapse_thread.start()

    def stop_timelapse(self) -> None:
        with self.lock:
            self.timelapse = False
            self.write_status()
        if self.timelapse_thread:
            self.timelapse_thread.join(timeout=2)
            self.timelapse_thread = None

    def timelapse_loop(self) -> None:
        batch = next_index(self.media_path, "t", self.config.get("count_format", "%04d"))
        shot = 1
        while self.timelapse and not self.stop_event.is_set():
            destination = expand_path(self.config["lapse_path"], batch, shot)
            self.camera.capture_jpeg(destination, quality=safe_int(self.config.get("image_quality", "85"), 85))
            if shot == 1:
                make_thumbnail(destination, "t", batch)
            shot += 1
            interval = max(1, safe_int(self.config.get("tl_interval", "30"), 30)) / 10.0
            self.stop_event.wait(interval)

    def run_macro(self, name: str) -> None:
        if not name:
            return
        macro = Path(self.config["macros_path"]) / name
        if not macro.exists():
            logging.warning("Macro not found: %s", macro)
            return
        subprocess.Popen([str(macro)], cwd=str(macro.parent))

    def handle_command(self, command: str) -> None:
        command = command.strip()
        if not command:
            return
        parts = shlex.split(command)
        if not parts:
            return
        code, args = parts[0], parts[1:]
        logging.info("Command: %s", command)
        if code == "ru":
            if args and args[0] == "0":
                self.stop_camera()
            else:
                self.start_camera()
        elif code == "im":
            self.capture_image()
        elif code == "ca":
            if args and args[0] == "0":
                self.stop_video()
            else:
                self.start_video()
        elif code == "tl":
            if args and args[0] == "0":
                self.stop_timelapse()
            else:
                self.start_timelapse()
        elif code == "md":
            self.motion = bool(args and args[0] == "1")
            self.write_status()
        elif code == "px" and len(args) >= 7:
            self.config.update(
                {
                    "video_width": args[0],
                    "video_height": args[1],
                    "video_fps": args[2],
                    "MP4Box_fps": args[3],
                    "image_width": args[4],
                    "image_height": args[5],
                    "fps_divider": args[6],
                }
            )
            self.save_config()
        elif code == "pv" and len(args) >= 3:
            self.config.update({"quality": args[0], "width": args[1], "divider": args[2]})
            self.save_config()
        elif code == "ro" and args:
            self.config["rotation"] = args[0]
            self.save_config()
        elif code == "fl" and args:
            flip = safe_int(args[0], 0)
            self.config["hflip"] = "true" if flip in {1, 3} else "false"
            self.config["vflip"] = "true" if flip in {2, 3} else "false"
            self.save_config()
        elif code == "bo" and args:
            mode = safe_int(args[0], 2)
            self.config["MP4Box"] = {0: "off", 1: "inline", 2: "background"}.get(mode, "background")
            self.save_config()
        elif code == "ag" and len(args) >= 2:
            self.config["autowbgain_r"] = args[0]
            self.config["autowbgain_b"] = args[1]
            self.save_config()
        elif code == "rs":
            self.user_config_file.unlink(missing_ok=True)
        elif code == "sc":
            logging.info("Rescan command accepted")
        elif code == "sy":
            self.run_macro(args[0] if args else "")
        elif code in CONFIG_COMMANDS and args:
            self.config[CONFIG_COMMANDS[code]] = " ".join(args)
            self.update_controls()
            self.save_config()
        elif code in NO_OP_COMMANDS:
            logging.info("Unsupported Picamera2 command accepted as no-op: %s", command)
        else:
            logging.warning("Unknown command: %s", command)

    def save_config(self) -> None:
        write_user_config(self.config, self.user_config_file)


def make_thumbnail(source: Path, kind: str, index: str, data_file: Optional[Path] = None) -> None:
    data_file = data_file or source
    thumb = thumbnail_name(data_file, kind, index)
    try:
        resize_jpeg(source, thumb, (160, 120), 80)
    except Exception:
        logging.exception("Failed to create thumbnail for %s", source)


def ensure_fifo(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return
    os.mkfifo(path)
    os.chmod(path, 0o666)


def preview_loop(state: BackendState) -> None:
    while not state.stop_event.is_set():
        try:
            state.capture_preview()
        except Exception:
            logging.exception("Preview capture failed")
        fps = max(1, safe_int(state.config.get("video_fps", "25"), 25))
        divider = max(1, safe_int(state.config.get("divider", "1"), 1))
        state.stop_event.wait(max(0.2, divider / fps))


def fifo_loop(state: BackendState) -> None:
    ensure_fifo(state.control_file)
    while not state.stop_event.is_set():
        with state.control_file.open("r") as fifo:
            for line in fifo:
                if state.stop_event.is_set():
                    break
                try:
                    state.handle_command(line)
                except Exception:
                    logging.exception("Command failed: %s", line.strip())
                    state.status_file.write_text("Error: command failed")


def build_camera_adapter(use_placeholder: bool = False) -> CameraAdapter:
    if use_placeholder:
        return PillowPlaceholderAdapter()
    return Picamera2Adapter()


def configure_logging(log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=str(log_path),
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s %(message)s",
    )


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Picamera2 raspimjpeg compatibility backend")
    parser.add_argument("--config", default="/etc/raspimjpeg")
    parser.add_argument("--user-config", default=None)
    parser.add_argument("--placeholder-camera", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    config_paths = [Path(args.config)]
    if args.user_config:
        config_paths.append(Path(args.user_config))
    else:
        default_user = Path(DEFAULT_CONFIG["user_config"])
        if default_user.exists():
            config_paths.append(default_user)
    config = load_config(config_paths)
    configure_logging(Path(config.get("log_file", DEFAULT_CONFIG["log_file"])))
    state = BackendState(config=config, camera=build_camera_adapter(args.placeholder_camera))

    def stop(_signum: int, _frame: object) -> None:
        state.stop_event.set()
        state.stop_camera()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    try:
        state.start_camera()
        threading.Thread(target=preview_loop, args=(state,), daemon=True).start()
        fifo_loop(state)
    except Exception:
        logging.exception("Picamera2 backend failed")
        state.status_file.parent.mkdir(parents=True, exist_ok=True)
        state.status_file.write_text("Error: Picamera2 backend failed")
        return 1
    finally:
        state.stop_camera()
    return 0


if __name__ == "__main__":
    sys.exit(main())
