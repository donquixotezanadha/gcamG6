#!/usr/bin/env python3
"""NGCam Lite 2 - Build 14 (keep previous thumbnail until HDR is done) patch.

Usage: python3 patches/build13_patch.py DECODED_DIR

Build 14 changes (on top of Build 13) - behave like the stock LG camera:
  K. While an HDR+/processing session is running the viewfinder thumbnail keeps
     showing the PREVIOUS photo. Every thumbnail update (RoundedThumbnailView
     .setThumbnail / .startRevealThumbnailAnimation) is held back between
     "session started" and "session done/failed/canceled" (dxm listener). When
     the session ends the app's own final update goes through; if none arrives
     within 1 s the last held bitmap is applied as a fallback. A 90 s watchdog
     can never leave the thumbnail frozen.
  L. Tapping the thumbnail while a photo is still processing no longer waits or
     shows the in-app preview: the gallery opens at once on the newest FINISHED
     photo of /DCIM (the one the thumbnail shows). If there is none (very first
     photo) Build 13's wait-and-open logic is the fallback.

Build 13 changes (on top of Build 12):
  I. Build 12 decided "still processing" from the app's processing-set, but the
     app removes a photo from that set as soon as its thumbnail exists (HDR is
     still running then), so the wait never started. Now "processing" is also
     true when the item's own metadata flag (Letn;->e(), the same flag the
     original code uses to build the processing URI) is set. The wait gives up
     after 20 s and then opens the gallery normally (never stuck).
  J. Status bar on the camera screen is solid black (was grey): applied in
     CameraActivity.onCreate and onResume.

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


BARS_METHOD = """
.method public static bars(Landroid/app/Activity;)V
    .locals 3

    if-eqz p0, :bars_end

    :try_start_bars
    invoke-virtual {p0}, Landroid/app/Activity;->getWindow()Landroid/view/Window;
    move-result-object v0

    const/high16 v1, -0x80000000
    invoke-virtual {v0, v1}, Landroid/view/Window;->addFlags(I)V

    const/16 v1, 0x400
    invoke-virtual {v0, v1}, Landroid/view/Window;->clearFlags(I)V

    const/high16 v1, -0x1000000
    invoke-virtual {v0, v1}, Landroid/view/Window;->setStatusBarColor(I)V
    :try_end_bars
    .catch Ljava/lang/Throwable; {:try_start_bars .. :try_end_bars} :catch_bars

    :bars_end
    return-void

    :catch_bars
    move-exception v0
    goto :bars_end
.end method
"""


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
    cls.write_text(cls.read_text(encoding="utf-8") + BARS_METHOD, encoding="utf-8")
    bars_call = ["    invoke-static/range {p0 .. p0}, Lcom/NgcamDefaults;->bars(Landroid/app/Activity;)V"]
    cam = root / "smali/com/google/android/apps/camera/legacy/app/activity/main/CameraActivity.smali"
    insert_after_locals(cam, ".method protected onCreate(Landroid/os/Bundle;)V", bars_call)
    insert_after_locals(cam, ".method protected final onResume()V", bars_call)
    report.append("Status bar black on camera screen")
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

    sget-boolean v0, Lngcamwait;->bypass:Z
    if-nez v0, :ngcam_no

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
    if-nez v1, :ngcam_busy

    invoke-interface {p2}, Lbip;->g()Letn;
    move-result-object v1
    invoke-virtual {v1}, Letn;->e()Z
    move-result v1
    if-nez v1, :ngcam_busy

    invoke-static {}, Lngcamthumb;->holding()Z
    move-result v1
    if-eqz v1, :ngcam_no

    :ngcam_busy
    # Photo still processing: open the newest FINISHED photo right away (what
    # the thumbnail shows). Only if there is none, tell the user and wait.
    iget-object v1, p0, Lczy;->q:Landroid/app/Activity;
    invoke-static {v1}, Lngcamthumb;->openLatest(Landroid/content/Context;)Z
    move-result v1
    if-nez v1, :ngcam_waiting

    iget-object v1, p0, Lczy;->j:Landroid/content/Context;
    const-string v2, "HDR masih diproses, galeri terbuka otomatis setelah selesai"
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
    # User pressed Back (blurred preview closed): stop waiting, allow next tap.
    iget-object v0, p0, Lczy;->c:Lcom/google/android/apps/camera/filmstrip/transition/FilmstripTransitionLayout;
    invoke-virtual {v0}, Landroid/view/View;->getVisibility()I
    move-result v0
    if-eqz v0, :tick_visible
    const/4 v0, 0x0
    iput-boolean v0, p0, Lczy;->f:Z
    goto :tick_stop
    :tick_visible

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
    if-nez v2, :tick_busy

    invoke-interface {v0}, Lbip;->g()Letn;
    move-result-object v2
    invoke-virtual {v2}, Letn;->e()Z
    move-result v2
    if-eqz v2, :tick_ready

    :tick_busy
    const/16 v2, 0x28
    if-ge p2, v2, :tick_ready

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
    const/4 v2, 0x1
    sput-boolean v2, Lngcamwait;->bypass:Z
    invoke-virtual {p0, p1, v0}, Lczy;->a(Lbiv;Lbip;)V
    const/4 v2, 0x0
    sput-boolean v2, Lngcamwait;->bypass:Z
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
.field public static bypass:Z
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
        "Fallback when no finished photo exists yet (first photo): toast, then the (LG) gallery opens by itself when the photo is done"
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



# ---------------------------------------------------------------------------
# K/L. Build 14: keep the previous thumbnail while HDR runs, tap opens gallery
# ---------------------------------------------------------------------------
THUMB_CLASS = """
.class public final Lngcamthumb;
.super Ljava/lang/Object;

.field public static bypass:Z
.field public static pend:Landroid/graphics/Bitmap;
.field public static pendRot:I
.field public static sessions:I
.field public static setAfter:Z
.field public static startedAt:J
.field public static view:Ljava/lang/ref/WeakReference;

# A processing session started (dxm.onSessionQueued).
.method public static started()V
    .locals 2

    sget v0, Lngcamthumb;->sessions:I
    add-int/lit8 v0, v0, 0x1
    sput v0, Lngcamthumb;->sessions:I

    invoke-static {}, Landroid/os/SystemClock;->elapsedRealtime()J
    move-result-wide v0
    sput-wide v0, Lngcamthumb;->startedAt:J
    return-void
.end method

# True while at least one session runs (90 s watchdog: never frozen forever).
.method public static holding()Z
    .locals 4

    sget v0, Lngcamthumb;->sessions:I
    if-lez v0, :hold_no

    invoke-static {}, Landroid/os/SystemClock;->elapsedRealtime()J
    move-result-wide v0
    sget-wide v2, Lngcamthumb;->startedAt:J
    sub-long/2addr v0, v2
    const-wide/32 v2, 0x15f90
    cmp-long v0, v0, v2
    if-lez v0, :hold_yes

    const/4 v0, 0x0
    sput v0, Lngcamthumb;->sessions:I

    :hold_no
    const/4 v0, 0x0
    return v0

    :hold_yes
    const/4 v0, 0x1
    return v0
.end method

# A session ended (done / failed / canceled). When the last one ends, give the
# app 1 s to push its own final thumbnail, then apply the held one if it did not.
.method public static finished()V
    .locals 4

    sget v0, Lngcamthumb;->sessions:I
    if-lez v0, :fin_done

    add-int/lit8 v0, v0, -0x1
    sput v0, Lngcamthumb;->sessions:I
    if-gtz v0, :fin_done

    const/4 v0, 0x0
    sput-boolean v0, Lngcamthumb;->setAfter:Z

    :try_start_fin
    new-instance v0, Landroid/os/Handler;
    invoke-static {}, Landroid/os/Looper;->getMainLooper()Landroid/os/Looper;
    move-result-object v1
    invoke-direct {v0, v1}, Landroid/os/Handler;-><init>(Landroid/os/Looper;)V
    new-instance v1, Lngcamthumbrel;
    invoke-direct {v1}, Lngcamthumbrel;-><init>()V
    const-wide/16 v2, 0x3e8
    invoke-virtual {v0, v1, v2, v3}, Landroid/os/Handler;->postDelayed(Ljava/lang/Runnable;J)Z
    :try_end_fin
    .catch Ljava/lang/Throwable; {:try_start_fin .. :try_end_fin} :catch_fin

    :fin_done
    return-void

    :catch_fin
    move-exception v0
    return-void
.end method

.method public static fallback()V
    .locals 4

    :try_start_fb
    sget-boolean v0, Lngcamthumb;->setAfter:Z
    if-nez v0, :fb_done

    sget v0, Lngcamthumb;->sessions:I
    if-gtz v0, :fb_done

    sget-object v0, Lngcamthumb;->pend:Landroid/graphics/Bitmap;
    if-eqz v0, :fb_done

    invoke-virtual {v0}, Landroid/graphics/Bitmap;->isRecycled()Z
    move-result v1
    if-nez v1, :fb_done

    sget-object v1, Lngcamthumb;->view:Ljava/lang/ref/WeakReference;
    if-eqz v1, :fb_done

    invoke-virtual {v1}, Ljava/lang/ref/WeakReference;->get()Ljava/lang/Object;
    move-result-object v1
    if-eqz v1, :fb_done

    check-cast v1, Lcom/google/android/apps/camera/bottombar/RoundedThumbnailView;
    sget v2, Lngcamthumb;->pendRot:I

    const/4 v3, 0x1
    sput-boolean v3, Lngcamthumb;->bypass:Z
    invoke-virtual {v1, v0, v2}, Lcom/google/android/apps/camera/bottombar/RoundedThumbnailView;->setThumbnail(Landroid/graphics/Bitmap;I)V
    const/4 v3, 0x0
    sput-boolean v3, Lngcamthumb;->bypass:Z
    const/4 v3, 0x0
    sput-object v3, Lngcamthumb;->pend:Landroid/graphics/Bitmap;

    :fb_done
    return-void
    :try_end_fb
    .catch Ljava/lang/Throwable; {:try_start_fb .. :try_end_fb} :catch_fb

    :catch_fb
    move-exception v0
    const/4 v0, 0x0
    sput-boolean v0, Lngcamthumb;->bypass:Z
    return-void
.end method

# Called first thing in RoundedThumbnailView.setThumbnail(Bitmap,int).
# true = swallow the update (HDR still running), false = let it through.
.method public static gate(Lcom/google/android/apps/camera/bottombar/RoundedThumbnailView;Landroid/graphics/Bitmap;I)Z
    .locals 2

    sget-boolean v0, Lngcamthumb;->bypass:Z
    if-nez v0, :gate_pass

    :try_start_gate
    new-instance v0, Ljava/lang/ref/WeakReference;
    invoke-direct {v0, p0}, Ljava/lang/ref/WeakReference;-><init>(Ljava/lang/Object;)V
    sput-object v0, Lngcamthumb;->view:Ljava/lang/ref/WeakReference;

    invoke-static {}, Lngcamthumb;->holding()Z
    move-result v0
    if-eqz v0, :gate_free

    sput-object p1, Lngcamthumb;->pend:Landroid/graphics/Bitmap;
    sput p2, Lngcamthumb;->pendRot:I
    const/4 v0, 0x1
    return v0
    :try_end_gate
    .catch Ljava/lang/Throwable; {:try_start_gate .. :try_end_gate} :catch_gate

    :gate_free
    const/4 v0, 0x1
    sput-boolean v0, Lngcamthumb;->setAfter:Z
    const/4 v1, 0x0
    sput-object v1, Lngcamthumb;->pend:Landroid/graphics/Bitmap;

    :gate_pass
    const/4 v0, 0x0
    return v0

    :catch_gate
    move-exception v0
    goto :gate_pass
.end method

# Newest finished photo in /DCIM (file exists and is not empty) -> gallery.
.method public static openLatest(Landroid/content/Context;)Z
    .locals 14

    if-eqz p0, :ol_none

    :try_start_ol
    invoke-virtual {p0}, Landroid/content/Context;->getContentResolver()Landroid/content/ContentResolver;
    move-result-object v0

    sget-object v1, Landroid/provider/MediaStore$Images$Media;->EXTERNAL_CONTENT_URI:Landroid/net/Uri;

    const/4 v2, 0x2
    new-array v2, v2, [Ljava/lang/String;
    const/4 v3, 0x0
    const-string v4, "_id"
    aput-object v4, v2, v3
    const/4 v3, 0x1
    const-string v4, "_data"
    aput-object v4, v2, v3

    const-string v3, "_data LIKE ?"
    const/4 v4, 0x1
    new-array v4, v4, [Ljava/lang/String;
    const/4 v5, 0x0
    const-string v6, "%/DCIM/%"
    aput-object v6, v4, v5

    const-string v5, "_id DESC"

    invoke-virtual/range {v0 .. v5}, Landroid/content/ContentResolver;->query(Landroid/net/Uri;[Ljava/lang/String;Ljava/lang/String;[Ljava/lang/String;Ljava/lang/String;)Landroid/database/Cursor;
    move-result-object v6
    if-eqz v6, :ol_none

    const-wide/16 v7, -0x1

    :ol_loop
    invoke-interface {v6}, Landroid/database/Cursor;->moveToNext()Z
    move-result v2
    if-eqz v2, :ol_done

    const/4 v2, 0x1
    invoke-interface {v6, v2}, Landroid/database/Cursor;->getString(I)Ljava/lang/String;
    move-result-object v2
    if-eqz v2, :ol_loop

    new-instance v3, Ljava/io/File;
    invoke-direct {v3, v2}, Ljava/io/File;-><init>(Ljava/lang/String;)V
    invoke-virtual {v3}, Ljava/io/File;->length()J
    move-result-wide v10
    const-wide/16 v12, 0x0
    cmp-long v9, v10, v12
    if-lez v9, :ol_loop

    const/4 v9, 0x0
    invoke-interface {v6, v9}, Landroid/database/Cursor;->getLong(I)J
    move-result-wide v7

    :ol_done
    invoke-interface {v6}, Landroid/database/Cursor;->close()V

    const-wide/16 v10, 0x0
    cmp-long v9, v7, v10
    if-ltz v9, :ol_none

    sget-object v1, Landroid/provider/MediaStore$Images$Media;->EXTERNAL_CONTENT_URI:Landroid/net/Uri;
    invoke-static {v1, v7, v8}, Landroid/content/ContentUris;->withAppendedId(Landroid/net/Uri;J)Landroid/net/Uri;
    move-result-object v1

    new-instance v2, Landroid/content/Intent;
    const-string v3, "android.intent.action.VIEW"
    invoke-direct {v2, v3}, Landroid/content/Intent;-><init>(Ljava/lang/String;)V
    const-string v3, "image/*"
    invoke-virtual {v2, v1, v3}, Landroid/content/Intent;->setDataAndType(Landroid/net/Uri;Ljava/lang/String;)Landroid/content/Intent;
    const/4 v3, 0x1
    instance-of v4, p0, Landroid/app/Activity;
    if-nez v4, :ol_flags
    const v3, 0x10000001
    :ol_flags
    invoke-virtual {v2, v3}, Landroid/content/Intent;->addFlags(I)Landroid/content/Intent;
    invoke-virtual {p0, v2}, Landroid/content/Context;->startActivity(Landroid/content/Intent;)V

    const/4 v0, 0x1
    return v0
    :try_end_ol
    .catch Ljava/lang/Throwable; {:try_start_ol .. :try_end_ol} :catch_ol

    :ol_none
    const/4 v0, 0x0
    return v0

    :catch_ol
    move-exception v0
    const/4 v0, 0x0
    return v0
.end method
"""

THUMB_REL_CLASS = """
.class public final Lngcamthumbrel;
.super Ljava/lang/Object;
.implements Ljava/lang/Runnable;

.method public constructor <init>()V
    .locals 0
    invoke-direct {p0}, Ljava/lang/Object;-><init>()V
    return-void
.end method

.method public run()V
    .locals 0
    invoke-static {}, Lngcamthumb;->fallback()V
    return-void
.end method
"""


def patch_keep_thumbnail():
    cls = root / "smali/ngcamthumb.smali"
    rel = root / "smali/ngcamthumbrel.smali"
    if cls.exists() or rel.exists():
        fail("ngcamthumb classes already exist")
    cls.write_text(THUMB_CLASS, encoding="utf-8")
    rel.write_text(THUMB_REL_CLASS, encoding="utf-8")

    # 1. Gate the thumbnail view itself (covers every caller).
    view = root / "smali/com/google/android/apps/camera/bottombar/RoundedThumbnailView.smali"
    insert_after_locals(
        view,
        ".method public setThumbnail(Landroid/graphics/Bitmap;I)V",
        [
            "    invoke-static {p0, p1, p2}, Lngcamthumb;->gate(Lcom/google/android/apps/camera/bottombar/RoundedThumbnailView;Landroid/graphics/Bitmap;I)Z",
            "    move-result v0",
            "    if-eqz v0, :ngcam_set_go",
            "    return-void",
            "    :ngcam_set_go",
        ],
    )
    insert_after_locals(
        view,
        ".method public startRevealThumbnailAnimation(Ljava/lang/String;)V",
        [
            "    invoke-static {}, Lngcamthumb;->holding()Z",
            "    move-result v0",
            "    if-eqz v0, :ngcam_reveal_go",
            "    return-void",
            "    :ngcam_reveal_go",
        ],
    )

    # 2. Session lifecycle (listener of the camera UI controller).
    dxm = root / "smali/dxm.smali"
    insert_after_locals(
        dxm,
        ".method public final a(Landroid/net/Uri;Lhon;Leso;)V",
        ["    invoke-static {}, Lngcamthumb;->started()V"],
    )
    for header in (
        ".method public final a(Landroid/net/Uri;Ljava/util/List;)V",
        ".method public final a(Landroid/net/Uri;Z)V",
        ".method public final b(Landroid/net/Uri;)V",
    ):
        insert_after_locals(dxm, header, ["    invoke-static {}, Lngcamthumb;->finished()V"])
    report.append(
        "Thumbnail keeps the previous photo while HDR runs; it changes only when processing is done (stock-camera behaviour)"
    )
    report.append(
        "Thumbnail tap while HDR runs opens the gallery at once on the newest finished photo (no in-app preview, no waiting)"
    )


def main():
    patch_4k_bitrate_cap()
    patch_immersive()
    patch_defaults()
    patch_hide_advanced()
    patch_gallery_processing()
    patch_item_picker()
    patch_social_thumbnail()
    patch_disable_api2_logging()
    patch_keep_thumbnail()
    report.append("Third-party gallery mode forced ON and portraits saved to DCIM/Camera (no separate album)")
    Path("patch-report.txt").write_text(
        "NGCam Lite 2 - Build 14 (keep previous thumbnail until HDR done)\n" + "\n".join("- " + r for r in report) + "\n",
        encoding="utf-8",
    )
    print("\n".join(report))


main()
