"""CI diagnostic: which ffmpeg resolves, and does it actually encode?

Added after CI logs showed ``merge failed (rc=-11)`` (SIGSEGV) for every
ffmpeg invocation on GitHub's Ubuntu runners while the same code worked on
Windows locally and in Vercel production (imageio-ffmpeg there = AL2023).

Prints one verdict line per candidate binary (imageio-ffmpeg wheel vs PATH)
using a synthetic, network-free encode so the CI log pinpoints *which*
binary crashes instead of everyone guessing. Evidence only — never fails
the run.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile


def probe(label: str, exe: str | None) -> None:
    if not exe or not os.path.isfile(exe):
        print(f"[diag] {label}: NOT FOUND ({exe})")
        return
    try:
        p = subprocess.run([exe, "-hide_banner", "-version"],
                           capture_output=True, text=True, timeout=30)
        lines = ((p.stdout or "") + (p.stderr or "")).splitlines()
        ver = lines[0] if lines else "?"
    except Exception as exc:  # noqa: BLE001
        print(f"[diag] {label}: -version crashed: {exc!r}")
        return

    out = os.path.join(tempfile.gettempdir(), f"ci-diag-{label}.mp4")
    try:
        q = subprocess.run(
            [exe, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
             "-f", "lavfi", "-i", "testsrc=duration=1:size=128x128:rate=10",
             "-movflags", "+faststart", out],
            capture_output=True, text=True, timeout=60,
        )
        rc: object = q.returncode
        err = (q.stderr or "").strip()[:200]
    except subprocess.TimeoutExpired:
        rc, err = "TIMEOUT", ""
    except Exception as exc:  # noqa: BLE001
        rc, err = f"EXC {type(exc).__name__}", str(exc)[:120]
    size = os.path.getsize(out) if os.path.exists(out) else 0
    verdict = "OK" if rc == 0 and size > 0 else "BROKEN"
    print(f"[diag] {label}: exe={exe} | {ver} | synthetic rc={rc} size={size} "
          f"-> {verdict} {err}")
    try:
        if os.path.exists(out):
            os.remove(out)
    except OSError:
        pass


def main() -> None:
    imageio_exe: str | None = None
    try:
        import imageio_ffmpeg  # type: ignore

        imageio_exe = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:  # noqa: BLE001
        print(f"[diag] imageio-ffmpeg unavailable: {exc!r}")
    probe("imageio", imageio_exe)
    probe("path", shutil.which("ffmpeg"))
    print(f"[diag] FFMPEG_PATH={os.getenv('FFMPEG_PATH') or '(unset)'}")


if __name__ == "__main__":
    main()
    sys.exit(0)
