import importlib.util
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "bin" / "rpicam_picamera2.py"
SPEC = importlib.util.spec_from_file_location("rpicam_picamera2", MODULE_PATH)
rpicam_picamera2 = importlib.util.module_from_spec(SPEC)
sys.modules["rpicam_picamera2"] = rpicam_picamera2
SPEC.loader.exec_module(rpicam_picamera2)


class FakeCamera(rpicam_picamera2.CameraAdapter):
    def start(self):
        self.started = True

    def stop(self):
        self.started = False

    def capture_jpeg(self, path, size=None, quality=85):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"jpg")

    def start_recording(self, path, width, height, fps, bitrate):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"h264")

    def stop_recording(self):
        pass

    def set_controls(self, controls):
        self.controls = controls


class Picamera2BackendTests(unittest.TestCase):
    def test_read_config_ignores_comments_and_blank_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_file = Path(tmp) / "raspimjpeg"
            config_file.write_text("# comment\n\nwidth 640\nmotion_detection false\nflag_only\n")

            parsed = rpicam_picamera2.read_config_file(config_file)

        self.assertEqual(parsed["width"], "640")
        self.assertEqual(parsed["motion_detection"], "false")
        self.assertEqual(parsed["flag_only"], "")

    def test_expand_path_applies_date_and_index_tokens(self):
        value = rpicam_picamera2.expand_path(
            "/var/www/media/vi_%v_%Y%M%D_%h%m%s.mp4",
            "0007",
            now=datetime(2026, 7, 7, 8, 9, 10),
        )

        self.assertEqual(str(value), "/var/www/media/vi_0007_20260707_080910.mp4")

    def test_next_index_uses_existing_thumbnail_indexes(self):
        with tempfile.TemporaryDirectory() as tmp:
            media = Path(tmp)
            (media / "im_0001.jpg.i0001.th.jpg").write_text("")
            (media / "im_0002.jpg.i0002.th.jpg").write_text("")

            index = rpicam_picamera2.next_index(media, "i")

        self.assertEqual(index, "0003")

    def test_status_strings_match_existing_web_ui_contract(self):
        state = rpicam_picamera2.BackendState(
            config=dict(rpicam_picamera2.DEFAULT_CONFIG),
            camera=FakeCamera(),
        )

        self.assertEqual(state.status(), "halted")
        state.running = True
        self.assertEqual(state.status(), "ready")
        state.motion = True
        self.assertEqual(state.status(), "md_ready")
        state.timelapse = True
        self.assertEqual(state.status(), "tl_md_ready")
        state.video = True
        self.assertEqual(state.status(), "tl_md_video")
        state.image = True
        self.assertEqual(state.status(), "image")

    def test_ffmpeg_remux_command_matches_trixie_plan(self):
        cmd = rpicam_picamera2.ffmpeg_remux_command(
            25,
            Path("/var/www/media/test.h264"),
            Path("/var/www/media/test.mp4"),
        )

        self.assertEqual(
            cmd,
            [
                "ffmpeg",
                "-y",
                "-framerate",
                "25",
                "-i",
                "/var/www/media/test.h264",
                "-c",
                "copy",
                "/var/www/media/test.mp4",
            ],
        )


if __name__ == "__main__":
    unittest.main()
