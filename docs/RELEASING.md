# Releasing Yoink

How to version and publish Yoink. Background: `docs/DESIGN.md` section 7.

## How versions work

- The version comes from git tags shaped `v<major>.<minor>.<patch>`. You
  bump it by tagging; there is no file to edit.

- A build on the tag reports `0.3.0`. A build 5 commits past it reports
  `0.3.0+5.<hash>`. Uncommitted changes append `.dirty`.

- A `+` in the version means "not a release". To check what a checkout
  would report, run `uv run python -c "import yoink; print(yoink.__version__)"`.

## Cutting a release

1. **Pre-flight.** Confirm Woodpecker is green on `development`.
   Optionally dry-run packaging first (see the next section).

2. **Merge to `master`.** Use `--no-ff` so each release is one merge commit:

   ```bash
   git checkout master
   git pull origin master
   git merge --no-ff development
   git push origin master
   ```

3. **Tag the merge commit on `master`, and push the tag.**

   ```bash
   git tag v0.3.0
   git push origin v0.3.0
   ```

4. **CI takes over.** The tag push runs the `Release` workflow
   (`.github/workflows/release.yml`). It creates a **draft** GitHub
   Release, builds on Linux (x64, arm64), Windows (x64), and macOS (arm64,
   x64), smoke-tests each build, and uploads the zips with
   `scripts/release_upload.py`. If one platform fails, fix it and re-run
   that job; re-uploads replace same-named assets. A draft is visible
   only to repo collaborators.

5. **Test the real binaries.** Open the draft and check that every asset
   carries the bare version:

   - `yoink-0.3.0-windows-x86_64.zip`
   - `yoink-0.3.0-linux-x86_64.zip`, `yoink-0.3.0-linux-aarch64.zip`
   - `yoink-0.3.0-macos-arm64.zip`, `yoink-0.3.0-macos-x86_64.zip`
   - `SHA256SUMS.txt`, written last from GitHub's digests

   Run them on your own machines and confirm About shows the version.
   If something is broken, delete the draft and the tag
   (`git push origin :refs/tags/v0.3.0`), fix, and re-tag the same
   version. Nobody outside has downloaded it yet.

6. **Publish.** Edit the draft, summarize the changes, and include the
   macOS "Open Anyway" steps from the README (the app is not notarized).
   Click **Publish release**.

## Testing builds before tagging

To check that packaging works on an untagged commit, run the `Release`
workflow by hand (GitHub > Actions > Release > Run workflow) with a
branch name as `ref`. It builds and smoke-tests every platform but
publishes nothing, and the builds are discarded when the run ends.
