# Yoink!

A small GUI front-end for yt-dlp. 

## Download

Builds for Windows, macOS, and Linux are on the
[Releases page](https://github.com/lyjia/yoink/releases). Unzip and run.
If yt-dlp is not found, Yoink offers to fetch it on first run.

macOS blocks the app because it is not notarized. To open it anyway, do
one of the following:

- Right-click Yoink.app, select **Open**, then select **Open** again.

- Launch it once, then go to **System Settings > Privacy & Security** and
  select **Open Anyway**.

## Running from source

Requires Python 3.11+ and a `yt-dlp` executable on PATH.

```
pip install -e .
python -m yoink
```

### Building

Requires uv. From bash (Git Bash on Windows):

```
scripts/build.sh
```

The result lands in `dist/yoink.dist/` (`dist/yoink.app` on macOS).

`scripts/build.sh --release` also zips the build to
`dist/yoink-<version>-<os>-<arch>.zip`. It requires a clean tree on a `v*`
tag.

## License

AGPL-3.0-only. See [LICENSE](LICENSE).
