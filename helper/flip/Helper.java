package flip;

import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Matrix;
import android.hardware.camera2.CameraCharacteristics;
import android.hardware.camera2.CameraManager;

import java.io.ByteArrayOutputStream;

/**
 * Selfie flip for GCam 5.1.
 *
 * mark()  - called just before the app opens a camera; remembers if it is the front camera.
 * flip()  - called with the finished JPEG bytes right before they are handed to the saving
 *           code. For the front camera the picture is mirrored the way the preview shows it.
 *           On any problem the original bytes are returned untouched.
 */
public final class Helper {
    public static volatile boolean front = false;

    private Helper() {
    }

    public static void mark(CameraManager manager, String id) {
        front = false;
        try {
            Integer facing = manager.getCameraCharacteristics(id).get(CameraCharacteristics.LENS_FACING);
            front = facing != null && facing.intValue() == CameraCharacteristics.LENS_FACING_FRONT;
        } catch (Throwable ignored) {
            front = false;
        }
    }

    /**
     * @param jpeg    finished JPEG
     * @param degrees clockwise rotation (0, 90, 180, 270) that the app applies to show the raw
     *                pixels upright. A left/right mirror of the upright picture is a left/right
     *                flip of the raw pixels when degrees is 0, otherwise an up/down flip.
     */
    public static byte[] flip(byte[] jpeg, int degrees) {
        if (!front || jpeg == null || jpeg.length < 4) {
            return jpeg;
        }
        try {
            if ((jpeg[0] & 0xFF) != 0xFF || (jpeg[1] & 0xFF) != 0xD8) {
                return jpeg;
            }
            if (isFlipped(jpeg)) {
                return jpeg;
            }
            Bitmap src = BitmapFactory.decodeByteArray(jpeg, 0, jpeg.length);
            if (src == null) {
                return jpeg;
            }
            Matrix matrix = new Matrix();
            if (degrees == 0) {
                matrix.postScale(-1f, 1f);
            } else {
                matrix.postScale(1f, -1f);
            }
            Bitmap out = Bitmap.createBitmap(src, 0, 0, src.getWidth(), src.getHeight(), matrix, false);
            if (out != src) {
                src.recycle();
            }
            ByteArrayOutputStream bos = new ByteArrayOutputStream(jpeg.length + 65536);
            boolean ok = out.compress(Bitmap.CompressFormat.JPEG, 98, bos);
            out.recycle();
            if (!ok) {
                return jpeg;
            }
            return keepMetadata(jpeg, bos.toByteArray());
        } catch (Throwable ignored) {
            return jpeg;
        }
    }

    // A small JPEG comment placed in every picture we flip, so that a picture which passes
    // through more than one hook point is never flipped twice.
    private static final byte[] TAG = {'G', 'C', 'F', 'L', 'I', 'P'};

    private static int segmentLength(byte[] b, int pos) {
        return ((b[pos + 2] & 0xFF) << 8) | (b[pos + 3] & 0xFF);
    }

    private static boolean isFlipped(byte[] b) {
        int pos = 2;
        while (pos + 4 <= b.length && (b[pos] & 0xFF) == 0xFF) {
            int marker = b[pos + 1] & 0xFF;
            boolean header = (marker >= 0xE0 && marker <= 0xEF) || marker == 0xFE;
            if (!header) {
                return false;
            }
            int len = segmentLength(b, pos);
            if (len < 2 || pos + 2 + len > b.length) {
                return false;
            }
            if (marker == 0xFE && len == 2 + TAG.length) {
                boolean same = true;
                for (int i = 0; i < TAG.length; i++) {
                    if (b[pos + 4 + i] != TAG[i]) {
                        same = false;
                        break;
                    }
                }
                if (same) {
                    return true;
                }
            }
            pos += 2 + len;
        }
        return false;
    }

    /** Puts the EXIF/APPn segments of the original file at the start of the re-encoded file. */
    private static byte[] keepMetadata(byte[] orig, byte[] enc) {
        ByteArrayOutputStream meta = new ByteArrayOutputStream();
        int pos = 2;
        while (pos + 4 <= orig.length && (orig[pos] & 0xFF) == 0xFF) {
            int marker = orig[pos + 1] & 0xFF;
            int len = segmentLength(orig, pos);
            if (len < 2 || pos + 2 + len > orig.length) {
                break;
            }
            if (marker == 0xE0) {
                pos += 2 + len;
                continue;
            }
            if (marker < 0xE1 || marker > 0xEF) {
                break;
            }
            meta.write(orig, pos, 2 + len);
            pos += 2 + len;
        }
        int start = 2;
        if (enc.length > 6 && (enc[2] & 0xFF) == 0xFF && (enc[3] & 0xFF) == 0xE0) {
            start = 2 + 2 + segmentLength(enc, 2);
        }
        if (start > enc.length) {
            return enc;
        }
        ByteArrayOutputStream res = new ByteArrayOutputStream(enc.length + meta.size() + 16);
        res.write(enc, 0, 2);
        byte[] m = meta.toByteArray();
        res.write(m, 0, m.length);
        int len = 2 + TAG.length;
        res.write(0xFF);
        res.write(0xFE);
        res.write((len >> 8) & 0xFF);
        res.write(len & 0xFF);
        res.write(TAG, 0, TAG.length);
        res.write(enc, start, enc.length - start);
        return res.toByteArray();
    }
}
