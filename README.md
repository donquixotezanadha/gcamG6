# gcamG6

Build otomatis NGCam Lite 2 (GCam 7.4 + mod BSG) untuk **LG G6, Android 9, kamera Snapdragon 821**.
Setiap build memakai APK asli `original-v1` (SHA-256 diverifikasi) lalu menambal Smali-nya lewat GitHub Actions.

## Tujuan
- Pengaturan resmi jadi **default saat instal**: Model **Pixel 3 XL**, Noise Modeler **Google IMX363** (ON),
  Black Level **65**, untuk kamera depan dan belakang. Ini yang terbukti mengatasi **green tint / blur kamera depan**.
- Menu **Advanced dihapus** dari Settings (tanpa force close).
- Bilah sistem Android tetap terlihat (immersive mode dimatikan).
- Bitrate video 4K dibatasi 40 Mbps (stabilitas MediaRecorder).
- Night Sight, Portrait, Video 4K tetap ada. Settings lain tidak diubah.

## Build
| Build | Branch | Catatan |
|---|---|---|
| 4 | `build-4-no-immersive` | Acuan yang berhasil: batas 4K + immersive off |
| 5, 6, 7 | `build-5/6/7-*` | Gagal di HP: default tidak terpasang, Settings force close |
| **8** | `build-8-official-defaults` | Dari Build 4, perbaikan penyebab di bawah |

## Kenapa Build 5-7 gagal (hasil bongkar APK)
1. Default ditulis dengan tipe yang salah: sakelar aplikasi disimpan sebagai String `"1"/"0"`, bukan Boolean,
   dan hanya dijalankan sekali. Build 8 menulis String yang sama persis di setiap peluncuran (Application.onCreate).
2. Menu Advanced dihapus terlalu cepat; `onCreate` halaman Settings masih mencarinya tanpa cek null.
   Build 8 menghapusnya di awal `onResume`, setelah pencarian itu selesai.
3. Tiap build memakai kunci tanda tangan baru. Build 8 memakai kunci tetap `patches/ngcam-g6.jks`.

## Cara pakai
Actions, pilih *NGCam Lite 2 Build 8*, lalu *Run workflow*. Unduh APK dari bagian Artifacts di halaman run.
Instal pertama harus uninstall versi lama dulu (kunci berbeda). Build selanjutnya bisa menimpa.

Kunci tanda tangan ada di repo publik, jadi hanya cocok untuk pemakaian pribadi.
