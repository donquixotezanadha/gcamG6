#!/usr/bin/env python3
"""NGCam Lite 2 - Build 8 (Official Defaults) patch.

Usage: python3 patches/build8_patch.py DECODED_DIR

Base: Build 4 (known good on LG G6): 4K bitrate cap + immersive mode off.
Added in Build 8:
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


def main():
    patch_4k_bitrate_cap()
    patch_immersive()
    patch_defaults()
    patch_hide_advanced()
    Path("patch-report.txt").write_text(
        "NGCam Lite 2 - Build 8 (Official Defaults)\n" + "\n".join("- " + r for r in report) + "\n",
        encoding="utf-8",
    )
    print("\n".join(report))


main()
