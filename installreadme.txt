Run these commands on the pi you are setting up:

- sudo apt-get update
- sudo apt-get install git
- git clone https://github.com/redbuttegarden/RPi_Cam_Web_Interface.git
- RPi_Cam_Web_Interface/./install.sh # run the install script

5 scripts are used instead of combining all together.
This avoids the overhead of a separate selection and makes it easier to run a particular function automatically.
So start and stop can just be run as separate activities.

The scripts are
install.sh main installation
update.sh check for updates and then run main installation
start.sh starts the software
stop.sh stops the software
remove.sh removes the software

The main installation always does the same thing to simplify its logic.
It gathers all user parameters first in one combined dialog and then always
applies the parameters as it goes through the process.
A q (quiet) parameter may be used to skip this and give an automatic install based on config.txt
All parameters are always in the config.txt file, a default version is created if one
doesn't exist and is then changed just once after the initial user dialog.
The installation always tries to upgrade the main software components and then functionally goes through
the configuration steps for each area like apache, motion start up.

Debug is turned on for the moment so it logs its activity to a file called install.txt