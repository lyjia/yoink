@echo off
rem Windows wrapper: runs scripts/build.sh under Git Bash with the same arguments.
rem Git Bash is named explicitly because a bare "bash" may resolve to WSL.
"%ProgramFiles%\Git\bin\bash.exe" "%~dp0build.sh" %*
