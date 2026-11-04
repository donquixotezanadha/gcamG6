#!/usr/bin/env python3
"""NGCam (original 7.4.104 v2.0) - Build 25 patch.

Usage: python3 patches/build25_patch.py DECODED_DIR

Base: the ORIGINAL full APK (release apk-asli), nothing removed.
Only two changes, both proven solid on the LG G6 in the Lite builds:
  1. Per-frame "APi2 info" logging disabled (was 1000-2300 log lines/s).
     Both logging helpers are void with no other effect, so they return
     immediately (same change as Build 11).
  2. Immersive mode off: status bar and navigation bar stay visible
     (4 View.setSystemUiVisibility sites + FLAG_FULLSCREEN cleared,
     same change as Build 4/8).
Nothing else is touched: HDR+, AWB, camera model, noise modeler, settings,
video, libraries all stay exactly as in the original.
"""
import re
import sys
from pathlib import Path

root = Path(sys.argv[1] if len(sys.argv) > 1 else "decoded")
report = []


def fail(msg):
    raise SystemExit("PATCH FAILED: " + msg)


def patch_disable_api2_logging():
    targets = [
        ("smali_classes2/com/ZLog.smali",
         ".method public static GetAPI2Info(Ljava/lang/Object;Ljava/lang/Object;)V"),
        ("smali/oux.smali",
         ".method public static a(Ljava/lang/Object;Ljava/lang/Object;)V"),
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
    if patched_calls != 4:
        fail(f"expected 4 View.setSystemUiVisibility sites, patched {patched_calls}")

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
    report.append(
        f"Immersive mode off ({patched_calls} setSystemUiVisibility sites + FLAG_FULLSCREEN cleared): "
        "status bar and navigation bar stay visible"
    )


def main():
    patch_disable_api2_logging()
    patch_immersive()
    Path("patch-report.txt").write_text(
        "NGCam original 7.4.104 v2.0 - Build 25 (original base)\n"
        + "\n".join("- " + r for r in report) + "\n",
        encoding="utf-8",
    )
    print("\n".join(report))


main()
