Web based interface for controlling the Raspberry Pi Camera, includes motion detection, time lapse, and image and video recording.
Current version 6.6.26
All information on this project can be found here: http://www.raspberrypi.org/forums/viewtopic.php?f=43&t=63276

The wiki page can be found here:

http://elinux.org/RPi-Cam-Web-Interface

This includes the installation instructions at the top and full technical details.
For latest change details see:

https://github.com/silvanmelchior/RPi_Cam_Web_Interface/commits/master
  
This version has updates for php7.3 / Buster. May need further changes for nginx

Raspberry Pi OS Trixie compatibility
------------------------------------

This fork includes initial Raspberry Pi OS Trixie support. On Debian 13 /
Trixie the installer defaults to:

* PHP 8.4 packages.
* `camera_backend="picamera2"` in `config.txt`.
* `python3-picamera2`, `python3-pil`, and `ffmpeg` instead of the legacy
  `gpac` / `MP4Box` package.
* A systemd autostart unit for the camera service.

Older Raspberry Pi OS releases continue to default to the legacy
`raspimjpeg` backend unless `camera_backend` is changed manually.

The Picamera2 backend is installed behind the existing `raspimjpeg` command
name so the web interface, FIFO commands, preview image, status file,
scheduler, and media gallery remain compatible. Core controls are supported,
including preview, still images, video recording, timelapse, common image
settings, and MP4 remuxing with `ffmpeg`. MMAL-specific controls that do not
map cleanly to Picamera2 are accepted as no-ops and logged.

Hardware testing is currently taking place on a Raspberry Pi Zero W v1.1.
