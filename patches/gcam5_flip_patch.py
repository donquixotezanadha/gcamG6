#!/usr/bin/env python3
"""GCam 5.1 (cstark27) - automatic selfie flip, nothing else changed.

How it works (the real pixels of the photo are mirrored, not just a flag):
  1. A small helper (helper/flip/Helper.java, built into classes2.dex by the workflow)
     remembers whether the camera that was just opened is the FRONT camera.
  2. Both places where the app calls CameraManager.openCamera() tell the helper.
  3. The factory that every saved photo goes through (Ldug.a, used by elp, dwm, dur, dvl
     and cpg) first passes the finished JPEG bytes through Helper.flip(). A second hook
     (Lela;->a(JLekw;[BI)V) covers JPEG byte arrays sent to the listeners. A marker inside
     the JPEG makes sure a picture is never flipped twice.
     For the front camera the picture is mirrored left/right; for the back camera the
     bytes are returned untouched.

Every anchor must match exactly once, otherwise the build fails on purpose.
"""
import sys
from pathlib import Path

root = Path(sys.argv[1])
smali = root / "smali"
report = []


def patch(rel, old, new):
    p = smali / rel
    text = p.read_text()
    found = text.count(old)
    if found != 1:
        sys.exit(f"ANCHOR ERROR in {rel}: expected 1, found {found}\n---\n{old}\n---")
    p.write_text(text.replace(old, new))
    report.append(f"patched {rel}")


MARK = "Lflip/Helper;->mark(Landroid/hardware/camera2/CameraManager;Ljava/lang/String;)V"

# 1. remember which camera is being opened -----------------------------------
patch(
    "idf.smali",
    "    new-instance v3, Lidb;\n",
    f"    invoke-static {{v1, v2}}, {MARK}\n\n    new-instance v3, Lidb;\n",
)
patch(
    "zb.smali",
    "    invoke-virtual {v0, v1, v2, p0}, Landroid/hardware/camera2/CameraManager;->openCamera(Ljava/lang/String;Landroid/hardware/camera2/CameraDevice$StateCallback;Landroid/os/Handler;)V\n",
    f"    invoke-static {{v0, v1}}, {MARK}\n\n"
    "    invoke-virtual {v0, v1, v2, p0}, Landroid/hardware/camera2/CameraManager;->openCamera(Ljava/lang/String;Landroid/hardware/camera2/CameraDevice$StateCallback;Landroid/os/Handler;)V\n",
)

# 2a. THE main save path: every photo that gets written to a file is built through
#     Ldug.a(...) (callers: elp, dwm, dur, dvl, cpg). Its 3rd argument is the finished
#     JPEG and its 5th argument is the clockwise rotation in degrees.
patch(
    "dug.smali",
    ".method public static a(J[BLici;ILcom/google/android/libraries/camera/exif/ExifInterface;Lhab;Z)Ldug;\n"
    "    .locals 10\n"
    "\n"
    "    new-instance v1, Ldug;\n",
    ".method public static a(J[BLici;ILcom/google/android/libraries/camera/exif/ExifInterface;Lhab;Z)Ldug;\n"
    "    .locals 10\n"
    "\n"
    "    invoke-static {p2, p4}, Lflip/Helper;->flip([BI)[B\n"
    "\n"
    "    move-result-object p2\n"
    "\n"
    "    new-instance v1, Ldug;\n",
)

# 2b. second hook: JPEG byte arrays that reach the listeners (thumbnail and similar flows).
#     Pictures already flipped carry a marker and are skipped, so nothing is flipped twice.
patch(
    "ela.smali",
    ".method public final a(JLekw;[BI)V\n"
    "    .locals 3\n"
    "\n"
    "    new-instance v0, Lekx;\n",
    ".method public final a(JLekw;[BI)V\n"
    "    .locals 3\n"
    "\n"
    "    if-eqz p3, :flip_skip\n"
    "\n"
    "    iget-object v0, p3, Lekw;->a:Licf;\n"
    "\n"
    "    if-eqz v0, :flip_skip\n"
    "\n"
    "    iget v0, v0, Licf;->e:I\n"
    "\n"
    "    invoke-static {p4, v0}, Lflip/Helper;->flip([BI)[B\n"
    "\n"
    "    move-result-object p4\n"
    "\n"
    "    :flip_skip\n"
    "    new-instance v0, Lekx;\n",
)

Path("patch-report.txt").write_text("\n".join(report) + "\n")
print("\n".join(report))
