#!/usr/bin/env python3
"""GCam 5.1 (cstark27) - automatic selfie flip, nothing else changed.

What it does
  1. Adds a tiny helper class (flip/FrontFlag) that remembers whether the camera
     that was just opened is the FRONT camera (CameraCharacteristics.LENS_FACING == 0).
  2. Hooks both places where the app calls CameraManager.openCamera().
  3. Where GCam writes the EXIF Orientation tag of a saved photo, a front-camera
     photo gets the horizontally mirrored version of the orientation
     (1<->2, 3<->4, 5<->6, 7<->8). The pixels are untouched, so quality is the same.
  4. The in-app thumbnail decoder is taught to rotate mirrored values (5, 7),
     otherwise selfie thumbnails inside the app would show up sideways.

Every anchor must match exactly once, otherwise the build fails on purpose.
"""
import sys
from pathlib import Path

root = Path(sys.argv[1])
smali = root / "smali"
report = []


def patch(rel, old, new, count=1):
    p = smali / rel
    text = p.read_text()
    found = text.count(old)
    if found != count:
        sys.exit(f"ANCHOR ERROR in {rel}: expected {count}, found {found}\n---\n{old}\n---")
    p.write_text(text.replace(old, new))
    report.append(f"patched {rel}")


# 1. helper class -------------------------------------------------------------
helper = """.class public final Lflip/FrontFlag;
.super Ljava/lang/Object;
.source "FrontFlag.java"


# static fields
.field public static volatile front:Z


# direct methods
.method public static mark(Landroid/hardware/camera2/CameraManager;Ljava/lang/String;)V
    .locals 3

    const/4 v0, 0x0

    sput-boolean v0, Lflip/FrontFlag;->front:Z

    :try_start_0
    invoke-virtual {p0, p1}, Landroid/hardware/camera2/CameraManager;->getCameraCharacteristics(Ljava/lang/String;)Landroid/hardware/camera2/CameraCharacteristics;

    move-result-object v1

    sget-object v2, Landroid/hardware/camera2/CameraCharacteristics;->LENS_FACING:Landroid/hardware/camera2/CameraCharacteristics$Key;

    invoke-virtual {v1, v2}, Landroid/hardware/camera2/CameraCharacteristics;->get(Landroid/hardware/camera2/CameraCharacteristics$Key;)Ljava/lang/Object;

    move-result-object v1

    check-cast v1, Ljava/lang/Integer;

    if-eqz v1, :cond_done

    invoke-virtual {v1}, Ljava/lang/Integer;->intValue()I

    move-result v1

    if-nez v1, :cond_done

    const/4 v0, 0x1

    sput-boolean v0, Lflip/FrontFlag;->front:Z
    :try_end_0
    .catch Ljava/lang/Throwable; {:try_start_0 .. :try_end_0} :catch_0

    :cond_done
    :goto_0
    return-void

    :catch_0
    move-exception v0

    goto :goto_0
.end method

.method public static fix(S)S
    .locals 1

    sget-boolean v0, Lflip/FrontFlag;->front:Z

    if-eqz v0, :cond_ret

    const/4 v0, 0x1

    if-lt p0, v0, :cond_ret

    const/16 v0, 0x8

    if-gt p0, v0, :cond_ret

    and-int/lit8 v0, p0, 0x1

    if-eqz v0, :cond_even

    add-int/lit8 v0, p0, 0x1

    int-to-short v0, v0

    return v0

    :cond_even
    add-int/lit8 v0, p0, -0x1

    int-to-short v0, v0

    return v0

    :cond_ret
    return p0
.end method
"""
(smali / "flip").mkdir(exist_ok=True)
(smali / "flip" / "FrontFlag.smali").write_text(helper)
report.append("added flip/FrontFlag.smali")

# 2. remember which camera is being opened -------------------------------------
patch(
    "idf.smali",
    "    new-instance v3, Lidb;\n",
    "    invoke-static {v1, v2}, Lflip/FrontFlag;->mark(Landroid/hardware/camera2/CameraManager;Ljava/lang/String;)V\n\n"
    "    new-instance v3, Lidb;\n",
)
patch(
    "zb.smali",
    "    invoke-virtual {v0, v1, v2, p0}, Landroid/hardware/camera2/CameraManager;->openCamera(Ljava/lang/String;Landroid/hardware/camera2/CameraDevice$StateCallback;Landroid/os/Handler;)V\n",
    "    invoke-static {v0, v1}, Lflip/FrontFlag;->mark(Landroid/hardware/camera2/CameraManager;Ljava/lang/String;)V\n\n"
    "    invoke-virtual {v0, v1, v2, p0}, Landroid/hardware/camera2/CameraManager;->openCamera(Ljava/lang/String;Landroid/hardware/camera2/CameraDevice$StateCallback;Landroid/os/Handler;)V\n",
)

# 3. mirror the EXIF orientation of front-camera photos -------------------------
patch(
    "ieu.smali",
    "    iget-short v3, v3, Liel;->b:S\n",
    "    iget-short v3, v3, Liel;->b:S\n\n"
    "    invoke-static {v3}, Lflip/FrontFlag;->fix(S)S\n\n"
    "    move-result v3\n",
)

# 4. in-app thumbnail: rotate for mirrored orientations 5 and 7 ----------------
patch(
    "chs.smali",
    "    .packed-switch 0x3\n"
    "        :pswitch_2\n"
    "        :pswitch_0\n"
    "        :pswitch_0\n"
    "        :pswitch_1\n"
    "        :pswitch_0\n"
    "        :pswitch_3\n"
    "    .end packed-switch\n",
    "    .packed-switch 0x3\n"
    "        :pswitch_2\n"
    "        :pswitch_0\n"
    "        :pswitch_1\n"
    "        :pswitch_1\n"
    "        :pswitch_3\n"
    "        :pswitch_3\n"
    "    .end packed-switch\n",
)

Path("patch-report.txt").write_text("\n".join(report) + "\n")
print("\n".join(report))
