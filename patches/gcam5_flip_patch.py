#!/usr/bin/env python3
"""GCam 5.1 (cstark27) - automatic selfie flip, nothing else changed.

How it works (the real pixels of the photo are mirrored, not just a flag):
  1. A small helper (helper/flip/Helper.java, built into classes2.dex by the workflow)
     remembers whether the camera that was just opened is the FRONT camera.
  2. Both places where the app calls CameraManager.openCamera() tell the helper.
  3. The single place where every finished JPEG byte[] is handed to the saving code
     (Lela;->a(JLekw;[BI)V) first passes the bytes through Helper.flip().
     For the front camera this mirrors the picture left/right; for the back camera the
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

# 2. mirror every finished JPEG of the front camera before it is saved ----------
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
