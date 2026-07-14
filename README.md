https://github.com/ZoloVN/ByPass-MusicVideo/blob/main/screenshot_1784013093.png?raw=true
# HƯỚNG DẪN CÀI ĐẶT & SỬ DỤNG

## Script Tách Nhạc Nền - Windows

---

## BƯỚC 1: CÀI PYTHON (nếu chưa có)

1. Vào https://python.org/downloads
2. Tải Python 3.10 hoặc 3.11 (khuyến nghị)
3. Khi cài: ✅ TICK vào "Add Python to PATH"
4. Kiểm tra: mở CMD gõ `python --version`

---

## BƯỚC 2: CÀI FFMPEG (để xử lý video .mp4)

1. Vào https://github.com/BtbN/FFmpeg-Builds/releases
2. Tải file: `ffmpeg-master-latest-win64-gpl.zip`
3. Giải nén → vào thư mục `bin` → copy 3 file:
   - ffmpeg.exe
   - ffprobe.exe
   - ffplay.exe
4. Dán vào: `C:\Windows\System32\`
5. Kiểm tra: mở CMD gõ `ffmpeg -version`

> ⚡ Cách nhanh hơn (nếu có winget):
> Mở PowerShell gõ: `winget install ffmpeg`

---

## BƯỚC 3: CÀI THƯ VIỆN PYTHON

Mở CMD hoặc PowerShell, gõ:

```
pip install demucs ffmpeg-python
```

Lần đầu chạy script sẽ tự tải model AI (~83MB), chỉ tải 1 lần.

---

## BƯỚC 4: CHẠY SCRIPT

### Cách 1: Kéo thả file vào script
- Kéo file video/audio → thả vào `tach_nhac_nen.py`

### Cách 2: Hộp thoại chọn file
- Double-click vào `tach_nhac_nen.py`
- Hộp thoại sẽ mở → chọn file

### Cách 3: Dòng lệnh (CMD/PowerShell)
```
# Một file
python tach_nhac_nen.py "C:\Videos\video.mp4"

# Cả thư mục
python tach_nhac_nen.py "C:\Videos\"
```

---

## KẾT QUẢ OUTPUT

Script tạo thư mục `tach_nhac_nen_output` cạnh file gốc:

```
📁 tach_nhac_nen_output/
  ├── video_no_music.mp4     ← VIDEO GỐC nhưng chỉ có giọng nói
  └── video_music_only.wav   ← Nhạc nền đã tách ra (để kiểm tra)
```

---

## CÁC LOẠI FILE HỖ TRỢ

| Định dạng | Hỗ trợ |
|-----------|--------|
| .mp4, .mkv, .webm | ✅ Video |
| .mp3, .wav, .flac | ✅ Audio |
| .m4a, .aac, .ogg | ✅ Audio |

---

## XỬ LÝ LỖI THƯỜNG GẶP

### ❌ "python không được nhận dạng"
→ Cài lại Python, nhớ tick "Add to PATH"

### ❌ "ffmpeg không được nhận dạng"
→ Cài ffmpeg theo Bước 2, hoặc thêm vào PATH thủ công

### ❌ "No module named demucs"
→ Chạy: `pip install demucs`

### ❌ Chạy lâu / máy nóng
→ Bình thường! AI đang xử lý. Thời gian ~2-5 phút/video 10 phút
→ Máy có GPU Nvidia sẽ nhanh hơn nhiều (tự động dùng CUDA)

### ❌ RAM không đủ
→ Đóng các ứng dụng khác, cần ít nhất 4GB RAM trống

---

## TIPS SỬ DỤNG

1. **Chất lượng tốt nhất**: Script dùng model `htdemucs` - model mới nhất của Meta
2. **Batch xử lý**: Bỏ tất cả video vào 1 thư mục → chạy 1 lần
3. **File output**: Luôn giữ file gốc, script không xóa/sửa file gốc
4. **Sau khi tách**: Import `video_no_music.mp4` vào CapCut để thêm phụ đề

---

## LƯU Ý VỀ CHẤT LƯỢNG

- Nhạc nền **hòa trộn** với giọng nói: AI tách ~85-95% hiệu quả
- Giọng nói rõ, nhạc nhẹ: kết quả rất tốt
- Nhạc to hơn giọng nói: có thể còn sót một ít nhạc

---

*Script sử dụng Demucs - mã nguồn mở của Meta AI Research*
*https://github.com/facebookresearch/demucs*
