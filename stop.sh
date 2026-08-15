#!/bin/bash

# Copyright (c) 2015, Bob Tidey
# All rights reserved.

# Redistribution and use, with or without modification, are permitted provided
# that the following conditions are met:
#    * Redistributions of source code must retain the above copyright
#      notice, this list of conditions and the following disclaimer.
#    * Neither the name of the copyright holder nor the
#      names of its contributors may be used to endorse or promote products
#      derived from this software without specific prior written permission.

# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
# ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY
# DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
# (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
# ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

# Description
# This script stops a running RPi_Cam interface
# Based on RPI_Cam_Web_Interface installer by Silvan Melchior
# Edited by jfarcher to work with github
# Edited by slabua to support custom installation folder
# Additions by btidey, miraaz, gigpi
# Split up and refactored by Bob Tidey 
# Stop function expanded by auslaner

#Debug enable next 3 lines
exec 5> stop.txt
BASH_XTRACEFD="5"
set -x

cd $(dirname $(readlink -f $0))

source ./config.txt
if [ -z "$camera_backend" ]; then
   camera_backend="legacy"
fi

fn_stop()
{
    local camera_pattern='^python3[[:space:]]+/usr/bin/raspimjpeg([[:space:]]|$)'

    # Stop processes that might relaunch the camera backend.
    sudo killall motion 2>/dev/null || true
    sudo killall php 2>/dev/null || true

    # Stop current and legacy camera backends gracefully.
    sudo pkill -TERM -f "$camera_pattern" 2>/dev/null || true
    sudo pkill -TERM -f '[r]picam_picamera2.py' 2>/dev/null || true
    sudo pkill -TERM -f '[/]opt/vc/bin/raspimjpeg' 2>/dev/null || true

    # Allow Picamera2 to close and release its device handles.
    for _ in $(seq 1 20); do
        if ! sudo pgrep -f "$camera_pattern" >/dev/null; then
            echo "Camera backend stopped."
            return 0
        fi
        sleep 0.25
    done

    # Force termination only if graceful shutdown did not finish.
    echo "Camera backend did not stop gracefully; forcing termination."
    sudo pkill -KILL -f "$camera_pattern" 2>/dev/null || true
    sleep 0.5

    if sudo pgrep -af "$camera_pattern"; then
        echo "ERROR: Camera backend was restarted by another process."
        return 1
    fi

    echo "Camera backend stopped."
}

#stop operation
fn_stop
