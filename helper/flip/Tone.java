package flip;

/**
 * Selfie color finish for GCam 5.1 (front camera only, pure math, no Android classes).
 *
 * Brightness is never changed (the front camera brightness is its own character). Only the
 * color is nudged, and only a little:
 *   1. tint: the front camera leans red/magenta compared to the back camera, so red and blue are
 *      pulled back very slightly (brightness is kept equal after the nudge);
 *   2. saturation: a thin lift, pale colors a bit more than vivid ones;
 *   3. yellow-green extra: yellows and greens (stairs paint, leaves) come out pale on the front
 *      camera, so they get a small extra lift. Skin tones (orange) are not part of this.
 * Grey pixels stay grey in brightness; everything is clamped to the valid range.
 *
 * To tune the look, only the numbers below need to change.
 */
final class Tone {
    /** Tint gains (1.00 = none). Lower red/blue = less red/magenta cast. */
    static final float GAIN_R = 0.9775f;
    static final float GAIN_G = 1.0f;
    static final float GAIN_B = 0.9675f;
    /** Thin saturation lift for every colored pixel (1.00 = none). */
    static final float SAT_BASE = 1.03f;
    /** Extra lift for pale colors, fades out for vivid colors (0 = none). */
    static final float VIBRANCE = 0.08f;
    /** Extra lift for pale yellow-green colors only (0 = none). */
    static final float YELLOW_GREEN = 0.12f;

    private Tone() {
    }

    private static int clamp(int v) {
        return v < 0 ? 0 : (v > 255 ? 255 : v);
    }

    /** 0..1 weight for the yellow-green hue range (about 35 to 155 degrees), smooth edges. */
    private static float yellowGreenWeight(float hue) {
        if (hue <= 35f || hue >= 155f) {
            return 0f;
        }
        float a;
        if (hue < 55f) {
            a = (hue - 35f) / 20f;
        } else if (hue > 125f) {
            a = (155f - hue) / 30f;
        } else {
            a = 1f;
        }
        return a * a * (3f - 2f * a);
    }

    /** Enhances px[off .. off+len) in place (ARGB ints, alpha is kept). */
    static void enhance(int[] px, int off, int len) {
        for (int i = off, end = off + len; i < end; i++) {
            int c = px[i];
            float r = (c >> 16) & 0xFF;
            float g = (c >> 8) & 0xFF;
            float b = c & 0xFF;
            float y = 0.299f * r + 0.587f * g + 0.114f * b;
            if (y <= 0f) {
                continue;
            }

            // 1. tint, then rescale so the brightness stays exactly as it was
            float r2 = r * GAIN_R;
            float g2 = g * GAIN_G;
            float b2 = b * GAIN_B;
            float y2 = 0.299f * r2 + 0.587f * g2 + 0.114f * b2;
            float keep = y / y2;
            r = r2 * keep;
            g = g2 * keep;
            b = b2 * keep;

            // 2 + 3. saturation around the brightness (grey stays grey)
            float mx = r > g ? (r > b ? r : b) : (g > b ? g : b);
            float mn = r < g ? (r < b ? r : b) : (g < b ? g : b);
            float d = mx - mn;
            if (d > 0.5f) {
                float sat = d / mx;
                float hue;
                if (mx == r) {
                    hue = 60f * ((g - b) / d);
                    if (hue < 0f) {
                        hue += 360f;
                    }
                } else if (mx == g) {
                    hue = 60f * (2f + (b - r) / d);
                } else {
                    hue = 60f * (4f + (r - g) / d);
                }
                float k = SAT_BASE + (VIBRANCE + YELLOW_GREEN * yellowGreenWeight(hue)) * (1f - sat);
                r = y + (r - y) * k;
                g = y + (g - y) * k;
                b = y + (b - y) * k;
            }

            px[i] = (c & 0xFF000000)
                    | (clamp((int) (r + 0.5f)) << 16)
                    | (clamp((int) (g + 0.5f)) << 8)
                    | clamp((int) (b + 0.5f));
        }
    }
}
