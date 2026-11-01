@echo off
rem Windows wrapper: runs scripts/build.sh under Git Bash with the same arguments.
bash "%~dp0build.sh" %*
