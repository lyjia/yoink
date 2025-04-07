import os
import subprocess

from cx_Freeze import setup, Executable

PROJ_ROOT = os.path.dirname(os.path.abspath(__file__))
GIT_VERSION = subprocess.check_output(['git', 'describe', '--tags'], cwd=PROJ_ROOT).decode('ascii').strip()

# Dependencies are automatically detected, but it might need
# fine tuning.
build_options = {'packages': [], 'excludes': []}

base = 'gui'

executables = [
    Executable('main.py', base=base, target_name = 'yoink.exe')
]

setup(name='Yoink!',
      version = GIT_VERSION,
      description = 'A GUI frontend for yt-dlp',
      options = {'build_exe': build_options},
      executables = executables)
