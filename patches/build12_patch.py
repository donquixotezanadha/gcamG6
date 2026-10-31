#!/usr/bin/env python3
"""NGCam Lite 2 - Build 12 (Wait for HDR, then open gallery) patch.

Usage: python3 patches/build12_patch.py DECODED_DIR

Build 12 change (on top of Build 11):
  H. Tapping the thumbnail while HDR+ is still processing used to open the LG
     gallery on the in-progress photo. That photo already has a (still empty)
     MediaStore row, so the gallery showed a broken-image placeholder and the
     user had to back out and reopen after the render finished. Now the tap
     shows a short toast and the gallery opens BY ITSELF as soon as the photo
     is finished (checked every 0.5 s, gives up after 60 s). Tapping again while
     waiting only repeats the toast. After the render is done the tap works as
     before.

Build 11 change (on top of Build 10):
  G. The app wrote 1000-2300 log lines PER SECOND while the camera ran (every
     CaptureResult key of every frame, tag "APi2 info"), built with
     StringBuilder + metadataValueToString on the camera callback threads. Both
     logging helpers (com.ZLog.GetAPI2Info and oux.a(Object,Object)) are void
     and have no other effect, so they now return immediately.

Build 10 changes (on top of Build 9):
  E. Thumbnail position: the unused "share to social media" mode moved the
     thumbnail into its own layout with hard-coded coordinates, so it sat too
     low/right on the G6's tall screen. Its activation method (ics.g) is
     disabled, so the thumbnail stays in the normal bottom bar.
  F. Opening the gallery while HDR+ is still processing: the picker of the
     "item to open" skipped every still-processing photo, found none, and the
     preview screen waited and showed an error. In third-party gallery mode it
     now accepts the processing item, and Build 9's helper opens the gallery.

Build 9 changes (kept):
  A. "Use a third-party gallery" (pref_gallery_key) is forced ON. This option
     lives inside the Advanced screen, which Build 8 removed, so it could no
     longer be switched on. The viewfinder thumbnail now opens whatever gallery
     the system default is (e.g. stock LG Gallery) instead of Google Photos.
  B. "Save portraits to /DCIM/Camera" (pref_portrait_single_key) is forced ON
     (same reason): no separate album/folder per portrait photo.
  C. LG Gallery compatibility: while a photo is still processing, the
     thumbnail used to hand the gallery a private "processing" content URI
     that only Google Photos understands. With third-party gallery mode ON the
     thumbnail now opens the gallery (image timeline) straight away instead of
     waiting for processing to finish.

Base: Build 4 (known good on LG G6): 4K bitrate cap + immersive mode off.
Included from Build 8:
  1. Official defaults (Pixel 3 XL + Google IMX363 noise modeler + Black Level 65,
     front AND back camera), written with the SAME value types the app itself
     uses (everything is a String; switches are "1"/"0"), at the earliest point
     of every launch (Application.onCreate) and again in CameraActivity.onCreate.
  2. The whole "Advanced" settings entry is removed from the Settings screen,
     at the start of onResume (AFTER onCreate has finished its unguarded
     lookups of Advanced items, which is what crashed earlier builds).
"""
import re
import sys
from pathlib import Path

root = Path(sys.argv[1] if len(sys.argv) > 1 else "decoded")
report = []


def fail(msg):
    raise SystemExit("PATCH FAILED: " + msg)


# ---------------------------------------------------------------------------
# A. Build 4 base patches (unchanged logic)
# ---------------------------------------------------------------------------
def patch_4k_bitrate_cap():
    p = root / "smali/lng.smali"
    s = p.read_text()
    method = ".method public static a(Landroid/media/CamcorderProfile;)Llnf;"
    start = s.find(method)
    if start < 0:
        fail("CamcorderProfile conversion method not found")
    end = s.find(".end method", start)
    if end < 0:
        fail("CamcorderProfile method boundary not found")
    block = s[start:end]
    if "ngcam_v2_bitrate_skip" in block:
        fail("4K cap already applied")
    if ".locals 2" not in block:
        fail("unexpected local-register layout in CamcorderProfile method")
    needle = "    iget v1, p0, Landroid/media/CamcorderProfile;->videoBitRate:I"
    if block.count(needle) != 1:
        fail(f"expected one videoBitRate read, found {block.count(needle)}")
    block = block.replace(".locals 2", ".locals 4", 1)
    inject = (
        needle + "\n"
        "\n"
        "    # Cap only UHD/4K profile bitrate at 40 Mbps.\n"
        "    iget v2, p0, Landroid/media/CamcorderProfile;->videoFrameWidth:I\n"
        "    const/16 v3, 0xf00\n"
        "    if-lt v2, v3, :ngcam_v2_bitrate_skip\n"
        "    const v3, 0x2625a00\n"
        "    if-le v1, v3, :ngcam_v2_bitrate_skip\n"
        "    move v1, v3\n"
        "    :ngcam_v2_bitrate_skip"
    )
    block = block.replace(needle, inject, 1)
    p.write_text(s[:start] + block + s[end:])
    report.append("4K video bitrate capped at 40 Mbps (width >= 3840)")


def patch_immersive():
    patched_calls = 0
    for p in root.rglob("*.smali"):
        s = p.read_text(encoding="utf-8")
        out = []
        changed = False
        for line in s.splitlines():
            m = re.search(
                r'^(\s*)invoke-virtual(?:/range)? \{([^}]*)\}, '
                r'Landroid/view/View;->setSystemUiVisibility\(I\)V',
                line,
            )
            if m and not line.strip().startswith("#"):
                regs = [x.strip() for x in m.group(2).split(",")]
                if len(regs) == 2:
                    indent = m.group(1)
                    view_reg, flag_reg = regs
                    out.append(f"{indent}const/4 {flag_reg}, 0x0")
                    out.append(
                        f"{indent}invoke-virtual {{{view_reg}, {flag_reg}}}, "
                        "Landroid/view/View;->setSystemUiVisibility(I)V"
                    )
                    patched_calls += 1
                    changed = True
                    continue
            out.append(line)
        if changed:
            p.write_text("\n".join(out) + "\n", encoding="utf-8")
    if patched_calls == 0:
        fail("no View.setSystemUiVisibility calls found")

    p = root / "smali/jve.smali"
    s = p.read_text(encoding="utf-8")
    method = ".method public static a(Landroid/view/Window;)V"
    start = s.find(method)
    end = s.find(".end method", start)
    if start < 0 or end < 0:
        fail("central Window helper not found")
    block = s[start:end]
    if "Window;->clearFlags(I)V" not in block:
        anchor = "    invoke-virtual {p0, v1}, Landroid/view/Window;->setFlags(II)V"
        if anchor in block:
            block = block.replace(
                anchor,
                anchor
                + "\n    const/16 v1, 0x400\n"
                "    invoke-virtual {p0, v1}, Landroid/view/Window;->clearFlags(I)V",
                1,
            )
        else:
            ret = "    return-void"
            if ret not in block:
                fail("no safe return anchor in Window helper")
            block = block.replace(
                ret,
                "    const/16 v1, 0x400\n"
                "    invoke-virtual {p0, v1}, Landroid/view/Window;->clearFlags(I)V\n"
                + ret,
                1,
            )
    p.write_text(s[:start] + block + s[end:], encoding="utf-8")
    report.append(f"Immersive mode off ({patched_calls} setSystemUiVisibility sites + FLAG_FULLSCREEN cleared)")


# ---------------------------------------------------------------------------
# B. Official defaults
# ---------------------------------------------------------------------------
# key -> String value. The app reads ALL of these as Strings:
#  - lists / numbers: getString (+ parseInt for numbers)
#  - switches: settings manager stores "1"/"0" strings (NOT putBoolean!)
DEFAULTS = [
    # Front camera (fixes green tint / blur)
    ("pref_model_front_key", "7"),                    # Pixel 3 XL
    ("pref_noise_modeler_toggle_front_key", "1"),     # Noise Modeler ON
    ("pref_noise_modeler_front_key", "IMX363_GOOGLE"),
    ("pref_blacklevel_front_key", "65"),
    # Back camera
    ("pref_model_back_key", "7"),                     # Pixel 3 XL
    ("pref_noise_modeler_toggle_back_key", "1"),      # Noise Modeler ON
    ("pref_noise_modeler_main_key", "IMX363_GOOGLE"),
    ("pref_blacklevel_back_key", "65"),
    # Build 9: both options live in the hidden Advanced screen, so force them
    ("pref_gallery_key", "1"),                        # third-party (system default) gallery
    ("pref_portrait_single_key", "1"),                # portraits -> DCIM/Camera, no extra album
]


def build_defaults_class():
    lines = [
        ".class public Lcom/NgcamDefaults;",
        ".super Ljava/lang/Object;",
        "",
        "# Forces the official NGCam defaults. Called on every launch, so the",
        "# values are right on first run, after reinstall and after any restore.",
        ".method public static apply(Landroid/content/Context;)V",
        "    .locals 3",
        "",
        "    if-eqz p0, :goto_end",
        "",
        "    :try_start_0",
        "    invoke-static {p0}, Landroid/preference/PreferenceManager;->"
        "getDefaultSharedPreferences(Landroid/content/Context;)Landroid/content/SharedPreferences;",
        "    move-result-object v0",
        "",
        "    invoke-interface {v0}, Landroid/content/SharedPreferences;->edit()"
        "Landroid/content/SharedPreferences$Editor;",
        "    move-result-object v0",
        "",
    ]
    for key, value in DEFAULTS:
        lines += [
            f'    const-string v1, "{key}"',
            f'    const-string v2, "{value}"',
            "    invoke-interface {v0, v1, v2}, Landroid/content/SharedPreferences$Editor;->"
            "putString(Ljava/lang/String;Ljava/lang/String;)Landroid/content/SharedPreferences$Editor;",
            "",
        ]
    lines += [
        "    invoke-interface {v0}, Landroid/content/SharedPreferences$Editor;->apply()V",
        "    :try_end_0",
        "    .catch Ljava/lang/Throwable; {:try_start_0 .. :try_end_0} :catch_0",
        "",
        "    :goto_end",
        "    return-void",
        "",
        "    :catch_0",
        "    move-exception v0",
        "    goto :goto_end",
        ".end method",
        "",
    ]
    return "\n".join(lines)


def insert_after_locals(path, header, call_lines):
    s = path.read_text(encoding="utf-8")
    if s.count(header) != 1:
        fail(f"{path.name}: expected exactly one '{header}', found {s.count(header)}")
    i = s.find(header)
    end = s.find(".end method", i)
    m = re.compile(r"^[ \t]*\.locals \d+[ \t]*$", re.M).search(s, i)
    if not m or m.start() > end:
        fail(f"{path.name}: .locals not found for '{header}'")
    s = s[: m.end()] + "\n" + "\n".join(call_lines) + "\n" + s[m.end():]
    path.write_text(s, encoding="utf-8")


def patch_defaults():
    cls = root / "smali_classes2/com/NgcamDefaults.smali"
    if cls.exists():
        fail("NgcamDefaults already exists")
    cls.write_text(build_defaults_class(), encoding="utf-8")

    call = ["    invoke-static/range {p0 .. p0}, Lcom/NgcamDefaults;->apply(Landroid/content/Context;)V"]
    insert_after_locals(
        root / "smali/com/google/android/apps/camera/legacy/app/app/CameraApp.smali",
        ".method public final onCreate()V",
        call,
    )
    insert_after_locals(
        root / "smali/com/google/android/apps/camera/legacy/app/activity/main/CameraActivity.smali",
        ".method protected onCreate(Landroid/os/Bundle;)V",
        call,
    )
    report.append("Official defaults forced each launch (front+back: Pixel 3 XL, IMX363 Google noise modeler ON, Black Level 65)")


# ---------------------------------------------------------------------------
# C. Remove the Advanced settings entry safely
# ---------------------------------------------------------------------------
HIDE_METHOD = """
.method private ngcamHideAdvanced()V
    .locals 3

    const-string v0, "pref_category_advanced"
    invoke-virtual {p0, v0}, Lehf;->findPreference(Ljava/lang/CharSequence;)Landroid/preference/Preference;
    move-result-object v0
    if-eqz v0, :goto_end

    const-string v1, "pref_category_general"
    invoke-virtual {p0, v1}, Lehf;->findPreference(Ljava/lang/CharSequence;)Landroid/preference/Preference;
    move-result-object v1
    instance-of v2, v1, Landroid/preference/PreferenceGroup;
    if-eqz v2, :goto_end

    check-cast v1, Landroid/preference/PreferenceGroup;
    invoke-virtual {v1, v0}, Landroid/preference/PreferenceGroup;->removePreference(Landroid/preference/Preference;)Z

    :goto_end
    return-void
.end method
"""


def patch_hide_advanced():
    p = root / "smali/ehf.smali"
    s = p.read_text(encoding="utf-8")
    if "ngcamHideAdvanced" in s:
        fail("Advanced hiding already applied")
    p.write_text(s + HIDE_METHOD, encoding="utf-8")
    insert_after_locals(
        p,
        ".method public final onResume()V",
        ["    invoke-direct/range {p0 .. p0}, Lehf;->ngcamHideAdvanced()V"],
    )
    report.append("Advanced settings entry removed (done at start of onResume, after onCreate lookups)")


# ---------------------------------------------------------------------------
# D. Build 9: thumbnail opens a third-party gallery even while still processing
# ---------------------------------------------------------------------------
# czy.a(Lbiv;Lbip;)V is the "open gallery from thumbnail" method. For an item
# that is still processing it puts a private content://<authority>/processing/ID
# URI on the intent, which only Google Photos can resolve. Other galleries
# (stock LG Gallery) cannot open it, so the user had to wait.
# New private helper ngcamTryOpen: if third-party mode is ON (pref_gallery_key
# != 0), not a secure-camera session, and the item's URI is in the processing
# set (Lhql;->a), open the gallery's image timeline right away with
# ACTION_VIEW + vnd.android.cursor.dir/image. Anything that does not apply, or
# no gallery that resolves it, returns false and the ORIGINAL code runs as
# before (so this can never be worse than the old behaviour).
GALLERY_HELPER = """
.method private ngcamTryOpen(Lbiv;Lbip;)Z
    .locals 5

    const-string v0, "pref_gallery_key"
    invoke-static {v0}, Lcom/FixBSG;->MenuValue(Ljava/lang/String;)I
    move-result v0
    if-eqz v0, :ngcam_no

    iget-boolean v0, p0, Lczy;->k:Z
    if-nez v0, :ngcam_no

    :try_start_ngcam
    invoke-interface {p2}, Lbip;->e()Leua;
    move-result-object v0
    iget-object v0, v0, Leua;->h:Landroid/net/Uri;

    iget-object v1, p0, Lczy;->n:Lhql;
    iget-object v1, v1, Lhql;->a:Ljava/util/Set;
    invoke-interface {v1, v0}, Ljava/util/Set;->contains(Ljava/lang/Object;)Z
    move-result v1
    if-eqz v1, :ngcam_no

    # Photo still processing: tell the user and wait for it (do NOT open the
    # gallery now, it would show an empty placeholder).
    iget-object v1, p0, Lczy;->j:Landroid/content/Context;
    const-string v2, "HDR masih diproses. Galeri terbuka otomatis setelah selesai."
    const/4 v3, 0x0
    invoke-static {v1, v2, v3}, Landroid/widget/Toast;->makeText(Landroid/content/Context;Ljava/lang/CharSequence;I)Landroid/widget/Toast;
    move-result-object v1
    invoke-virtual {v1}, Landroid/widget/Toast;->show()V

    sget-boolean v1, Lngcamwait;->active:Z
    if-nez v1, :ngcam_waiting

    const/4 v1, 0x1
    sput-boolean v1, Lngcamwait;->active:Z
    const/4 v1, 0x0
    invoke-virtual {p0, p1, v1}, Lczy;->ngcamTick(Lbiv;I)V

    :ngcam_waiting
    :try_end_ngcam
    .catch Ljava/lang/Throwable; {:try_start_ngcam .. :try_end_ngcam} :catch_ngcam

    const/4 v0, 0x1
    return v0

    :catch_ngcam
    move-exception v0

    :ngcam_no
    const/4 v0, 0x0
    return v0
.end method

# Called every 0.5 s by Lngcamwait; while the photo is processing. When the
# photo is finished it runs the normal open-gallery path (the original code).
.method public final ngcamTick(Lbiv;I)V
    .locals 6

    :try_start_tick
    invoke-virtual {p0, p1}, Lczy;->a(Lbiv;)Lbip;
    move-result-object v0
    if-eqz v0, :tick_stop

    invoke-interface {v0}, Lbip;->e()Leua;
    move-result-object v1
    iget-object v1, v1, Leua;->h:Landroid/net/Uri;

    iget-object v2, p0, Lczy;->n:Lhql;
    iget-object v2, v2, Lhql;->a:Ljava/util/Set;
    invoke-interface {v2, v1}, Ljava/util/Set;->contains(Ljava/lang/Object;)Z
    move-result v2
    if-eqz v2, :tick_ready

    const/16 v2, 0x78
    if-ge p2, v2, :tick_stop

    add-int/lit8 p2, p2, 0x1
    new-instance v2, Lngcamwait;
    invoke-direct {v2, p0, p1, p2}, Lngcamwait;-><init>(Lczy;Lbiv;I)V
    iget-object v3, p0, Lczy;->e:Lcom/google/android/apps/camera/bottombar/RoundedThumbnailView;
    const-wide/16 v4, 0x1f4
    invoke-virtual {v3, v2, v4, v5}, Landroid/view/View;->postDelayed(Ljava/lang/Runnable;J)Z
    return-void

    :tick_ready
    const/4 v2, 0x0
    sput-boolean v2, Lngcamwait;->active:Z
    invoke-virtual {p0, p1, v0}, Lczy;->a(Lbiv;Lbip;)V
    return-void
    :try_end_tick
    .catch Ljava/lang/Throwable; {:try_start_tick .. :try_end_tick} :catch_tick

    :tick_stop
    const/4 v0, 0x0
    sput-boolean v0, Lngcamwait;->active:Z
    return-void

    :catch_tick
    move-exception v0
    goto :tick_stop
.end method
"""

WAIT_CLASS = """
.class public final Lngcamwait;
.super Ljava/lang/Object;
.implements Ljava/lang/Runnable;

.field public static active:Z
.field private final a:Lczy;
.field private final b:Lbiv;
.field private final c:I

.method public constructor <init>(Lczy;Lbiv;I)V
    .locals 0
    invoke-direct {p0}, Ljava/lang/Object;-><init>()V
    iput-object p1, p0, Lngcamwait;->a:Lczy;
    iput-object p2, p0, Lngcamwait;->b:Lbiv;
    iput p3, p0, Lngcamwait;->c:I
    return-void
.end method

.method public run()V
    .locals 3

    :try_start_run
    iget-object v0, p0, Lngcamwait;->a:Lczy;
    iget-object v1, p0, Lngcamwait;->b:Lbiv;
    iget v2, p0, Lngcamwait;->c:I
    invoke-virtual {v0, v1, v2}, Lczy;->ngcamTick(Lbiv;I)V
    :try_end_run
    .catch Ljava/lang/Throwable; {:try_start_run .. :try_end_run} :catch_run

    return-void

    :catch_run
    move-exception v0
    const/4 v0, 0x0
    sput-boolean v0, Lngcamwait;->active:Z
    return-void
.end method
"""



def patch_gallery_processing():
    p = root / "smali/czy.smali"
    s = p.read_text(encoding="utf-8")
    if "ngcamTryOpen" in s:
        fail("gallery processing patch already applied")
    header = ".method public final a(Lbiv;Lbip;)V"
    if s.count(header) != 1:
        fail(f"czy.smali: expected one '{header}', found {s.count(header)}")
    i = s.find(header)
    end = s.find(".end method", i)
    m = re.compile(r"^[ \t]*\.locals (\d+)[ \t]*$", re.M).search(s, i)
    if not m or m.start() > end:
        fail("czy.smali: .locals not found in the gallery launch method")
    if int(m.group(1)) < 2:
        fail("czy.smali: gallery launch method has too few registers")
    call = [
        "    invoke-direct/range {p0 .. p2}, Lczy;->ngcamTryOpen(Lbiv;Lbip;)Z",
        "    move-result v0",
        "    if-eqz v0, :ngcam_continue",
        "    return-void",
        "    :ngcam_continue",
    ]
    s = s[: m.end()] + "\n" + "\n".join(call) + "\n" + s[m.end():]
    s += GALLERY_HELPER
    p.write_text(s, encoding="utf-8")
    wait_cls = root / "smali/ngcamwait.smali"
    if wait_cls.exists():
        fail("ngcamwait.smali already exists")
    wait_cls.write_text(WAIT_CLASS, encoding="utf-8")
    report.append(
        "Thumbnail tap while HDR is processing: toast, then the (LG) gallery opens by itself when the photo is done"
    )


def patch_item_picker():
    p = root / "smali/czy.smali"
    s = p.read_text(encoding="utf-8")
    header = ".method public final a(Lbiv;)Lbip;"
    if s.count(header) != 1:
        fail(f"czy.smali: expected one '{header}', found {s.count(header)}")
    i = s.find(header)
    end = s.find(".end method", i)
    block = s[i:end]
    needle = "invoke-interface {v3, v2}, Ljava/util/Set;->contains(Ljava/lang/Object;)Z"
    if block.count(needle) != 1:
        fail(f"item picker: expected one contains() call, found {block.count(needle)}")
    j = block.find(needle)
    mr = block.find("move-result v2", j)
    if mr < 0 or mr - j > 200:
        fail("item picker: move-result v2 not right after contains()")
    mr_end = mr + len("move-result v2")
    inject = (
        "\n\n    const-string v3, \"pref_gallery_key\"\n"
        "    invoke-static {v3}, Lcom/FixBSG;->MenuValue(Ljava/lang/String;)I\n"
        "    move-result v3\n"
        "    if-eqz v3, :ngcam_keep_processing\n"
        "    const/4 v2, 0x0\n"
        "    :ngcam_keep_processing\n"
    )
    block = block[:mr_end] + inject + block[mr_end:]
    p.write_text(s[:i] + block + s[end:], encoding="utf-8")
    report.append("Photo picker accepts photos that are still processing (third-party gallery mode)")


def patch_social_thumbnail():
    p = root / "smali/ics.smali"
    s = p.read_text(encoding="utf-8")
    header = ".method public final g()V"
    if s.count(header) != 1:
        fail(f"ics.smali: expected one '{header}', found {s.count(header)}")
    i = s.find(header)
    end = s.find(".end method", i)
    m = re.compile(r"^[ \t]*\.locals \d+[ \t]*$", re.M).search(s, i)
    if not m or m.start() > end:
        fail("ics.smali: .locals not found in g()")
    s = s[: m.end()] + "\n\n    return-void\n" + s[m.end():]
    p.write_text(s, encoding="utf-8")
    report.append("Thumbnail stays in the normal bottom bar (social-share relayout disabled)")


def patch_disable_api2_logging():
    targets = [
        ("smali_classes2/com/ZLog.smali", ".method public static GetAPI2Info(Ljava/lang/Object;Ljava/lang/Object;)V"),
        ("smali/oux.smali", ".method public static a(Ljava/lang/Object;Ljava/lang/Object;)V"),
    ]
    for rel, header in targets:
        p = root / rel
        s = p.read_text(encoding="utf-8")
        if s.count(header) != 1:
            fail(f"{rel}: expected one '{header}', found {s.count(header)}")
        i = s.find(header)
        end = s.find(".end method", i)
        block = s[i:end]
        if "APi2 info" not in block:
            fail(f"{rel}: method is not the APi2 logger")
        m = re.compile(r"^[ \t]*\.locals \d+[ \t]*$", re.M).search(s, i)
        if not m or m.start() > end:
            fail(f"{rel}: .locals not found")
        s = s[: m.end()] + "\n\n    return-void\n" + s[m.end():]
        p.write_text(s, encoding="utf-8")
    report.append("Per-frame CaptureResult logging (APi2 info) disabled")


def main():
    patch_4k_bitrate_cap()
    patch_immersive()
    patch_defaults()
    patch_hide_advanced()
    patch_gallery_processing()
    patch_item_picker()
    patch_social_thumbnail()
    patch_disable_api2_logging()
    report.append("Third-party gallery mode forced ON and portraits saved to DCIM/Camera (no separate album)")
    Path("patch-report.txt").write_text(
        "NGCam Lite 2 - Build 12 (Wait for HDR)\n" + "\n".join("- " + r for r in report) + "\n",
        encoding="utf-8",
    )
    print("\n".join(report))


main()
