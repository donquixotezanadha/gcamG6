package flip;

/**
 * Selfie color finish for GCam 5.1 (front camera only, pure math, no Android classes).
 *
 * The front camera comes out paler than the back camera. This gives pale colors a lift
 * (vibrance: dull colors are boosted more than already vivid ones, so skin does not turn
 * orange) plus a very gentle S-curve for contrast. Grey pixels stay grey.
 *
 * To tune the look, only these three numbers need to change.
 */
final class Tone {
    /** Overall saturation lift for every colored pixel (1.00 = none). */
    static final float SAT_BASE = 1.08f;
    /** Extra lift for pale colors, fades out for vivid colors (0 = none). */
    static final float VIBRANCE = 0.22f;
    /** Strength of the S-curve contrast (0 = none). */
    static final float CURVE = 0.18f;

    private static final int[] LUT = buildLut();

    private Tone() {
    }

    private static int[] buildLut() {
        int[] lut = new int[256];
        for (int i = 0; i < 256; i++) {
            float x = i / 255f;
            float s = x * x * (3f - 2f * x);
            float v = x + CURVE * (s - x);
            lut[i] = clamp((int) (v * 255f + 0.5f));
        }
        return lut;
    }

    private static int clamp(int v) {
        return v < 0 ? 0 : (v > 255 ? 255 : v);
    }

    /** Enhances px[off .. off+len) in place (ARGB ints, alpha is kept). */
    static void enhance(int[] px, int off, int len) {
        final int[] lut = LUT;
        for (int i = off, end = off + len; i < end; i++) {
            int c = px[i];
            int r = (c >> 16) & 0xFF;
            int g = (c >> 8) & 0xFF;
            int b = c & 0xFF;
            int mx = r > g ? (r > b ? r : b) : (g > b ? g : b);
            int mn = r < g ? (r < b ? r : b) : (g < b ? g : b);
            if (mx != mn) {
                float sat = (mx - mn) / (float) mx;
                float k = SAT_BASE + VIBRANCE * (1f - sat);
                float y = 0.299f * r + 0.587f * g + 0.114f * b;
                r = clamp((int) (y + (r - y) * k + 0.5f));
                g = clamp((int) (y + (g - y) * k + 0.5f));
                b = clamp((int) (y + (b - y) * k + 0.5f));
            }
            px[i] = (c & 0xFF000000) | (lut[r] << 16) | (lut[g] << 8) | lut[b];
        }
    }
}
