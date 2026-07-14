"""
TÁCH NHẠC NỀN - Demucs htdemucs v5
Chạy: py -3.11 tach_nhac_nen_ui.py
Cài:  py -3.11 -m pip install torch==2.3.1+cpu --index-url https://download.pytorch.org/whl/cpu
      py -3.11 -m pip install demucs soundfile "numpy<2.0"
"""
import sys, os, subprocess, shutil, threading
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, ttk

# ─── Cấu hình ─────────────────────────────────────────────────────────────────
# Mục tiêu: Giữ Drums + Bass, bỏ Vocals + Other (melody)
# → Bypass Content ID vì drums/bass không bị nhận diện
MODES = {
    "Drums + Bass (bypass nhạc nền)":     {"stems":["drums","bass"], "two":False},
    "Drums + Bass + Vocals (bỏ melody)":  {"stems":["drums","bass","vocals"], "two":False},
    "Tách 4 stems riêng":                 {"stems":["vocals","drums","bass","other"], "two":False},
}
MODE_DESC = {
    "Drums + Bass (bypass nhạc nền)":
        "✅ Tốt nhất để bypass Content ID.\n"
        "Giữ: drums + bass. Bỏ: vocals + other (melody, strings, piano...).",
    "Drums + Bass + Vocals (bỏ melody)":
        "Giữ: drums + bass + vocals. Bỏ: other (melody thuần nhạc cụ).\n"
        "Dùng khi cần giữ lại giọng nói trong video.",
    "Tách 4 stems riêng":
        "Xuất 4 file riêng: vocals · drums · bass · other.\n"
        "Dùng khi muốn kiểm tra hoặc xử lý thủ công từng phần.",
}

# Xử lý stem OTHER (melody) — chỉ dùng cho chế độ Tách 4 stems
OTHER_OPTIONS = {
    "Bỏ hoàn toàn (an toàn nhất)":                    "drop",
    "⭐ Spectral Mask (vẽ lại sóng âm)":               "spectral_mask",
    "⭐ Spectral Mask + Pitch -5 (mạnh nhất)":          "spectral_pitch",
    "⭐ Spectral Mask + EQ + Noise (tối đa)":           "spectral_full",
    "EQ lọc melody 300Hz-4kHz (giữ SFX)":             "eq_cut",
    "EQ + Pitch -5 + Noise":                          "eq_pitch_noise",
    "Pitch -5 semitones (librosa)":                    "pitch_dn5",
    "Pitch -7 semitones (librosa)":                    "pitch_dn7",
    "Noise + Pitch -5":                               "noise_pitch_dn5",
    "Giảm âm lượng 70%":                              "reduce_70",
    "Thêm noise trắng nhẹ":                           "noise_only",
    "⚙️  Custom (tự chỉnh)":                           "custom_other",
    "Giữ nguyên other":                               "keep",
}
OTHER_DESC = {
    "drop":             "✅ An toàn nhất — bỏ hoàn toàn, mất SFX.",
    "spectral_mask":    "⭐ Phân tích STFT → detect harmonic pattern nhạc → vẽ lại spectrogram → inverse. SFX giữ nguyên vì không có harmonic pattern đều. Bypass fingerprint ở cấp độ vật lý sóng âm.",
    "spectral_pitch":   "⭐ Spectral Mask + Pitch -5 — can thiệp spectrogram rồi dịch tông. 2 lớp bảo vệ, rất khó nhận diện.",
    "spectral_full":    "⭐ Spectral Mask + EQ lọc melody + Noise — 3 lớp toàn diện. Mạnh nhất hiện có trong tool.",
    "eq_cut":           "🎛 EQ lọc dải 300Hz-4kHz — SFX còn nguyên.",
    "eq_pitch_noise":   "🔥 EQ + Pitch -5 + Noise — 3 lớp.",
    "pitch_dn5":        "🎵 Pitch -5 (librosa) — trầm hơn, khó nhận diện.",
    "pitch_dn7":        "🎵 Pitch -7 (librosa) — trầm nhất.",
    "noise_pitch_dn5":  "🔥 Noise + Pitch -5.",
    "reduce_70":        "Giảm 70% âm lượng.",
    "noise_only":       "Noise trắng nhẹ (-45dB).",
    "keep":             "Giữ nguyên other.",
    "custom_other":     "⚙️ Tự chỉnh: chọn Spectral/Pitch/EQ/Noise và kéo slider theo ý muốn.",
}

VIDEO_EXTS = {".mp4",".mkv",".webm",".avi",".mov"}
ALL_EXTS   = VIDEO_EXTS | {".mp3",".wav",".flac",".ogg",".m4a",".aac"}

BG="#0f0f13"; SURFACE="#1a1a22"; SURFACE2="#22222e"
ACCENT="#6c63ff"; ACCENT2="#a78bfa"; SUCCESS="#4ade80"
ERROR="#f87171"; TEXT="#e8e6f0"; MUTED="#6b6880"
BORDER="#2e2e3e"; GOLD="#fbbf24"; ORANGE="#fb923c"

# ─── Audio helpers ────────────────────────────────────────────────────────────
def ensure_deps(log_cb):
    pkgs = {"demucs":"demucs","soundfile":"soundfile","numpy":"numpy"}
    missing = [p for m,p in pkgs.items() if not __import_ok(m)]
    if missing:
        log_cb(f"  Cài: {', '.join(missing)}...\n")
        subprocess.run([sys.executable,"-m","pip","install"]+missing+["-q"], check=True)

def __import_ok(mod):
    try: __import__(mod); return True
    except ImportError: return False

def ffmpeg(*args):
    try:
        subprocess.run(["ffmpeg","-y"]+list(args), capture_output=True, check=True)
    except FileNotFoundError:
        raise RuntimeError("ffmpeg chưa cài! Tải: https://ffmpeg.org/download.html")
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"ffmpeg: {e.stderr.decode(errors='replace')[-150:]}")

def _spectral_mask(data, sr, strength=0.85):
    """
    Can thiệp quang phổ âm thanh — vẽ lại đường cong sóng âm.
    
    Nguyên lý:
    1. STFT → ra spectrogram (magnitude + phase)
    2. Detect các bin tần số có harmonic pattern đều (đặc trưng nhạc)
    3. Làm mờ/reshape các bin đó trên magnitude spectrogram  
    4. Inverse STFT → audio mới có cấu trúc vật lý sóng âm thay đổi
    
    SFX/ambient không bị ảnh hưởng vì:
    - Tiếng động ngẫu nhiên → không có harmonic pattern đều
    - Chỉ các tần số có năng lượng ổn định theo thời gian mới bị mask
    """
    import numpy as np
    try:
        import librosa
    except ImportError:
        import subprocess, sys
        subprocess.run([sys.executable,"-m","pip","install","librosa","-q"], check=True)
        import librosa

    def process_channel(y):
        y = y.astype(np.float32)
        # STFT
        n_fft   = 2048
        hop_len = 512
        D = librosa.stft(y, n_fft=n_fft, hop_length=hop_len)
        magnitude = np.abs(D)
        phase     = np.angle(D)

        # --- Detect harmonic bins ---
        # Tính độ ổn định năng lượng theo thời gian (temporal consistency)
        # Nhạc: năng lượng ổn định theo chu kỳ → std thấp so với mean
        # SFX:  năng lượng bất thường → std cao
        mag_mean = magnitude.mean(axis=1, keepdims=True) + 1e-9
        mag_std  = magnitude.std(axis=1, keepdims=True)
        consistency = mag_std / mag_mean  # thấp = ổn định = nhạc

        # Tính harmonic score: bin nào có năng lượng cao + ổn định = nhạc
        energy_score      = magnitude.mean(axis=1)
        consistency_score = consistency.squeeze()
        
        # Normalize
        e_norm = energy_score / (energy_score.max() + 1e-9)
        c_norm = 1.0 - np.clip(consistency_score / (consistency_score.max() + 1e-9), 0, 1)
        
        # Harmonic mask: bin nào vừa có năng lượng cao vừa ổn định
        harmonic_score = e_norm * c_norm
        threshold      = np.percentile(harmonic_score, 60)  # top 40% bins bị mask
        harmonic_bins  = harmonic_score > threshold

        # --- Vẽ lại spectrogram ---
        # Các bin harmonic: giảm magnitude + thêm phase noise nhẹ
        mask = np.ones_like(magnitude)
        mask[harmonic_bins, :] = 1.0 - strength  # giảm strength%

        # Thêm phase perturbation nhẹ vào harmonic bins → phá waveform pattern
        phase_noise = np.random.uniform(-0.15, 0.15, phase.shape).astype(np.float32)
        phase_mod   = phase.copy()
        phase_mod[harmonic_bins, :] += phase_noise[harmonic_bins, :]

        # Rebuild spectrogram
        magnitude_new = magnitude * mask
        D_new         = magnitude_new * np.exp(1j * phase_mod)

        # Inverse STFT
        y_out = librosa.istft(D_new, hop_length=hop_len, length=len(y))
        # Normalize để giữ nguyên mức âm lượng gốc
        orig_rms = float(np.sqrt(np.mean(y**2))) + 1e-9
        out_rms  = float(np.sqrt(np.mean(y_out**2))) + 1e-9
        y_out    = y_out * (orig_rms / out_rms)
        return y_out.astype(np.float32)

    if data.ndim == 1:
        return process_channel(data)
    else:
        chs = [process_channel(data[:, c]) for c in range(data.shape[1])]
        mn  = min(len(c) for c in chs)
        return np.stack([c[:mn] for c in chs], axis=1)

def _eq_cut_melody(data, sr):
    """Lọc bỏ dải tần 300Hz-4kHz — vùng chứa melody chính.
    SFX (tiếng nổ, tiếng bước chân, ambient) nằm ngoài dải này nên còn nguyên."""
    import numpy as np
    try:
        from scipy import signal as scipy_signal
    except ImportError:
        import subprocess, sys
        subprocess.run([sys.executable, "-m", "pip", "install", "scipy", "-q"], check=True)
        from scipy import signal as scipy_signal

    def apply_notch_channel(ch_data):
        # Butterworth bandstop filter 300Hz-4000Hz
        nyq = sr / 2.0
        low  = 300.0  / nyq
        high = 4000.0 / nyq
        low  = max(0.001, min(low,  0.999))
        high = max(0.001, min(high, 0.999))
        b, a = scipy_signal.butter(4, [low, high], btype='bandstop')
        return scipy_signal.filtfilt(b, a, ch_data.astype(np.float64)).astype(np.float32)

    import numpy as np
    if data.ndim == 1:
        out = apply_notch_channel(data)
    else:
        result = np.zeros_like(data)
        for ch in range(data.shape[1]):
            result[:, ch] = apply_notch_channel(data[:, ch])
        out = result
    # Normalize RMS
    orig_rms = float(np.sqrt(np.mean(data**2))) + 1e-9
    out_rms  = float(np.sqrt(np.mean(out**2)))  + 1e-9
    return (out * (orig_rms / out_rms)).astype(data.dtype)

def _librosa_pitch_shift(data, sr, semitones):
    """Pitch shift thật sự dùng librosa — giữ nguyên tempo"""
    import numpy as np
    try:
        import librosa
    except ImportError:
        import subprocess, sys
        subprocess.run([sys.executable, "-m", "pip", "install", "librosa", "-q"], check=True)
        import librosa
    # librosa làm việc với mono float32
    if data.ndim == 2:
        # stereo → xử lý từng channel
        ch_results = []
        for ch in range(data.shape[1]):
            shifted = librosa.effects.pitch_shift(
                data[:, ch].astype(np.float32), sr=sr, n_steps=semitones)
            ch_results.append(shifted)
        return np.stack(ch_results, axis=1).astype(data.dtype)
    else:
        return librosa.effects.pitch_shift(
            data.astype(np.float32), sr=sr, n_steps=semitones).astype(data.dtype)

def _add_noise(data, noise_level=-45.0):
    """Thêm noise trắng nhẹ — phá fingerprint mà tai không nghe được"""
    import numpy as np
    # noise_level dB so với signal
    rms = float(np.sqrt(np.mean(data**2))) + 1e-9
    noise_rms = rms * (10 ** (noise_level / 20.0))
    noise = np.random.normal(0, noise_rms, data.shape).astype(data.dtype)
    return data + noise

def process_other(data, sr, mode):
    """Xử lý stem other theo mode đã chọn"""
    import numpy as np
    if mode == "drop":
        return np.zeros_like(data)
    elif mode == "spectral_mask":
        return _spectral_mask(data, sr, strength=0.85)
    elif mode == "spectral_pitch":
        masked = _spectral_mask(data, sr, strength=0.85)
        return _librosa_pitch_shift(masked, sr, -5)
    elif mode == "spectral_full":
        masked  = _spectral_mask(data, sr, strength=0.90)
        eq      = _eq_cut_melody(masked, sr)
        return _add_noise(eq, noise_level=-42.0)
    elif mode == "reduce_70":
        return data * 0.30
    elif mode == "eq_cut":
        return _eq_cut_melody(data, sr)
    elif mode == "eq_pitch_noise":
        eq      = _eq_cut_melody(data, sr)
        shifted = _librosa_pitch_shift(eq, sr, -5)
        return _add_noise(shifted, noise_level=-42.0)
    elif mode == "pitch_dn5":
        return _librosa_pitch_shift(data, sr, -5)
    elif mode == "pitch_dn7":
        return _librosa_pitch_shift(data, sr, -7)
    elif mode == "noise_pitch_dn5":
        shifted = _librosa_pitch_shift(data, sr, -5)
        return _add_noise(shifted, noise_level=-42.0)
    elif mode == "noise_only":
        return _add_noise(data, noise_level=-45.0)
    elif mode == "custom_other":
        # Xử lý bởi _apply_co_custom trong UI — fallback giữ nguyên nếu gọi standalone
        return data
    else:  # keep
        return data

def _time_stretch_audio(data, sr, ts_mode):
    """Time stretch toàn bộ audio ±1-3% — thay đổi độ dài, qua mặt fingerprint"""
    import numpy as np
    if ts_mode == "off": return data
    rates = {"ts1": 1.01, "ts2": 1.02, "ts3": 1.03}
    rate = rates.get(ts_mode, 1.0)
    # Xen kẽ + và - để không bias
    import time
    rate = rate if int(time.time()) % 2 == 0 else (2.0 - rate)
    try:
        import librosa
        if data.ndim == 1:
            return librosa.effects.time_stretch(data.astype(np.float32), rate=rate)
        else:
            chs = [librosa.effects.time_stretch(data[:,c].astype(np.float32), rate=rate)
                   for c in range(data.shape[1])]
            mn = min(len(c) for c in chs)
            return np.stack([c[:mn] for c in chs], axis=1).astype(data.dtype)
    except Exception:
        # fallback: resampling đơn giản
        orig = len(data)
        new_len = int(orig / rate)
        if data.ndim == 1:
            return np.interp(np.linspace(0,orig-1,new_len),
                             np.arange(orig), data).astype(data.dtype)
        result = np.zeros((new_len, data.shape[1]), dtype=data.dtype)
        for c in range(data.shape[1]):
            result[:,c] = np.interp(np.linspace(0,orig-1,new_len),
                                    np.arange(orig), data[:,c]).astype(data.dtype)
        return result

def mix_and_process(stem_paths, other_path, other_mode, output, ts_mode="off"):
    """Mix các stems lại, xử lý other theo mode, áp dụng time stretch"""
    import numpy as np, soundfile as sf
    mixed, sr = None, None
    for p in [Path(x) for x in stem_paths]:
        if not p.exists(): continue
        data, rate = sf.read(str(p), dtype='float32')
        if mixed is None: mixed, sr = data.copy(), rate
        else:
            n = min(len(mixed),len(data)); mixed[:n]+=data[:n]; mixed=mixed[:n]

    # Xử lý other
    if other_path and Path(other_path).exists() and other_mode != "drop":
        odata, _ = sf.read(str(other_path), dtype='float32')
        odata = process_other(odata, sr, other_mode)  # custom_other → keep (handled separately)
        if mixed is None: mixed, sr = odata, _
        else:
            n = min(len(mixed),len(odata)); mixed[:n]+=odata[:n]; mixed=mixed[:n]

    if mixed is None: raise RuntimeError("Không có stem nào!")

    # Time stretch
    if ts_mode != "off":
        mixed = _time_stretch_audio(mixed, sr, ts_mode)

    peak = float(abs(mixed).max())
    if peak > 0.98: mixed *= 0.98/peak
    sf.write(str(output), mixed, sr, subtype='PCM_16')

def run_demucs(src, out_dir, mode_name, mode_cfg, other_mode, ts_mode, log_cb, prog_cb):
    import soundfile as sf, numpy as np
    src    = Path(src)
    two    = mode_cfg["two"]
    s_keep = mode_cfg["stems"]
    import tempfile
    tmp    = out_dir/"_tmp";  tmp.mkdir(parents=True, exist_ok=True)
    # Dùng thư mục work trong %TEMP% để tránh lỗi Unicode đường dẫn tiếng Việt
    _tmp_base = Path(tempfile.gettempdir()) / f"demucs_work_{abs(hash(str(src)))}"
    work = _tmp_base; work.mkdir(parents=True, exist_ok=True)
    results = []

    # Trích audio nếu video
    wav_src = src
    if src.suffix.lower() in VIDEO_EXTS:
        log_cb("  Trích audio từ video...\n")
        wav_src = tmp/f"{src.stem}.wav"
        ffmpeg("-i",str(src),"-vn","-acodec","pcm_s16le",
               "-ar","44100","-ac","2",str(wav_src))
    prog_cb(12)

    if two:
        # Nhanh: 2-stem mode
        log_cb("  Demucs 2-stem (nhanh)...\n")
        cmd = [sys.executable,"-m","demucs","-n","htdemucs",
               "--two-stems","vocals","-o",str(work),str(wav_src)]
    else:
        log_cb("  Demucs 4-stem...\n")
        cmd = [sys.executable,"-m","demucs","-n","htdemucs",
               "-o",str(work),str(wav_src)]

    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env)
    if r.returncode != 0:
        raise RuntimeError(f"Demucs lỗi:\n{r.stderr[-500:]}")
    prog_cb(80)

    stem_dir = work/"htdemucs"/wav_src.stem

    if two:
        v = stem_dir/"vocals.wav"
        i = stem_dir/"no_vocals.wav"
        if not v.exists(): raise RuntimeError("Không tìm thấy vocals output!")
        out_v = out_dir/f"{src.stem}_vocals.wav"; shutil.copy2(v, out_v)
        results.append(str(out_v))
        if i.exists():
            out_i = out_dir/f"{src.stem}_instrumental.wav"; shutil.copy2(i, out_i)
            results.append(str(out_i))
        if src.suffix.lower() in VIDEO_EXTS:
            out_vid = out_dir/f"{src.stem}_no_music{src.suffix}"
            log_cb("  Ghép vocals vào video...\n")
            ffmpeg("-i",str(src),"-i",str(v),"-map","0:v:0","-map","1:a:0",
                   "-c:v","copy","-c:a","aac","-b:a","192k","-shortest",str(out_vid))
            results.insert(0, str(out_vid))
    else:
        stems = {s: stem_dir/f"{s}.wav" for s in ["vocals","drums","bass","other"]}

        is_split4 = "4 stems" in mode_name

        if is_split4:
            # Tách 4 file riêng — xử lý other theo option
            for sn, sp in stems.items():
                if not sp.exists(): continue
                if sn == "other":
                    data, rate2 = sf.read(str(sp), dtype='float32')
                    processed = process_other(data, rate2, other_mode)
                    if other_mode == "drop": continue  # bỏ hẳn
                    dst = out_dir/f"{src.stem}_other_{other_mode}.wav"
                    peak = float(abs(processed).max())
                    if peak > 0.98: processed *= 0.98/peak
                    sf.write(str(dst), processed, rate2, subtype='PCM_16')
                    results.append(str(dst))
                else:
                    dst = out_dir/f"{src.stem}_{sn}.wav"; shutil.copy2(sp, dst)
                    results.append(str(dst))
        else:
            # Mix chỉ các stems muốn giữ (drums+bass hoặc drums+bass+vocals)
            # other KHÔNG được giữ trong các mode này
            base_stems = [stems[s] for s in s_keep if s in stems and stems[s].exists()]
            mixed      = tmp/f"{src.stem}_mixed.wav"
            log_cb(f"  Mix stems: {'+'.join(s_keep)}...\n")
            mix_and_process(base_stems, None, "drop", mixed, ts_mode)

            if src.suffix.lower() in VIDEO_EXTS:
                out_vid = out_dir/f"{src.stem}_no_melody{src.suffix}"
                log_cb("  Ghép audio vào video...\n")
                ffmpeg("-i",str(src),"-i",str(mixed),"-map","0:v:0","-map","1:a:0",
                       "-c:v","copy","-c:a","aac","-b:a","192k","-shortest",str(out_vid))
                results.append(str(out_vid))
            else:
                dst = out_dir/f"{src.stem}_no_melody.wav"; shutil.copy2(mixed, dst)
                results.append(str(dst))

    shutil.rmtree(tmp, ignore_errors=True)
    shutil.rmtree(work, ignore_errors=True)
    prog_cb(100)
    return results

# ─── UI ───────────────────────────────────────────────────────────────────────
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Tách Nhạc Nền v5")
        self.configure(bg=BG)
        self.resizable(True, True)
        self.minsize(700, 500)
        # Căn giữa sau khi build xong
        self.after(10, self._center_window)
        self.files       = []
        self.last_output = None
        self.mode_var    = tk.StringVar(value=list(MODES.keys())[0])
        self.other_var   = tk.StringVar(value=list(OTHER_OPTIONS.keys())[0])
        self.out_var     = tk.StringVar(value="(cùng thư mục với file gốc)")
        self.prog_var    = tk.DoubleVar(value=0)
        self.workers_var = tk.IntVar(value=1)
        self.ts_var      = tk.StringVar(value='off')
        self.tab_var     = tk.StringVar(value='stems')
        self._tab_btns   = {}
        # Custom other vars
        self.co_spectral  = tk.BooleanVar(value=True)
        self.co_strength  = tk.IntVar(value=85)
        self.co_pitch     = tk.BooleanVar(value=False)
        self.co_pitch_n   = tk.IntVar(value=-5)
        self.co_eq        = tk.BooleanVar(value=False)
        self.co_eq_lo     = tk.IntVar(value=300)
        self.co_eq_hi     = tk.IntVar(value=4000)
        self.co_noise     = tk.BooleanVar(value=False)
        self.co_noise_db  = tk.IntVar(value=-45)
        self.co_volume    = tk.BooleanVar(value=False)
        self.co_volume_pc = tk.IntVar(value=70)
        self.mode_var.trace_add("write",  lambda *_: self.after(10, self._update_info))
        self.other_var.trace_add("write", lambda *_: self.after(10, self._update_other_info))
        self._setup_styles()
        self._build()
        self.after(80, self._update_info)
        self.after(80, self._update_other_info)

    def _setup_styles(self):
        s = ttk.Style(); s.theme_use("clam")
        s.configure("P.Horizontal.TProgressbar",
                    troughcolor=SURFACE2, background=ACCENT,
                    bordercolor=SURFACE2, lightcolor=ACCENT, darkcolor=ACCENT2)
        s.configure("TCombobox", fieldbackground=SURFACE2, background=SURFACE2,
                    foreground=TEXT, selectbackground=ACCENT, arrowcolor=TEXT)
        s.map("TCombobox",
              fieldbackground=[("readonly",SURFACE2)],
              foreground=[("readonly",TEXT)])

    def _build(self):
        tk.Frame(self, bg=ACCENT, height=3).pack(fill="x")
        tk.Label(self, text="TÁCH NHẠC NỀN", font=("Segoe UI",15,"bold"),
                 bg=BG, fg=TEXT).pack(pady=(8,2))
        tk.Label(self, text="Demucs htdemucs · Bypass Content ID · Spectral Mask",
                 font=("Segoe UI",8), bg=BG, fg=MUTED).pack(pady=(0,4))

        # ── Tab switcher ──
        tab_row = tk.Frame(self, bg=BG)
        tab_row.pack(fill="x", padx=22, pady=(0,6))
        self.tab_var = tk.StringVar(value="stems")
        self._tab_btns = {}
        for lbl, val in [("✂️  Tách Stems", "stems"), ("🌊  Spectral Direct", "spectral")]:
            b = tk.Button(tab_row, text=lbl, relief="flat", font=("Segoe UI",9,"bold"),
                          cursor="hand2", padx=18, pady=5,
                          command=lambda v=val: self._switch_tab(v))
            b.pack(side="left", padx=(0,4))
            self._tab_btns[val] = b
        self._update_tab_style()

        # Frame container cho 2 tab
        self._container = tk.Frame(self, bg=BG)
        self._container.pack(fill="both", expand=True)

        # Tab 1: Stems — frame đơn giản
        stems_outer = tk.Frame(self._container, bg=BG)
        stems_outer.pack(fill="both", expand=True)
        P = tk.Frame(stems_outer, bg=BG)
        P.pack(fill="both", expand=True)
        self._stems_frame = stems_outer
        self._stems_canvas = None

        # Tab 2: Spectral Direct (build sau)
        self._spectral_frame = tk.Frame(self._container, bg=BG)
        self._build_spectral_tab(self._spectral_frame)

        # ── Input zone — 1 hàng duy nhất ──
        inp = tk.Frame(P, bg=SURFACE2, highlightthickness=1,
                        highlightbackground=BORDER)
        inp.pack(fill="x", padx=22, pady=(4,10))
        tk.Label(inp, text="📂", font=("Segoe UI",13),
                  bg=SURFACE2, fg=ACCENT).pack(side="left", padx=(10,6), pady=8)
        self.lbl_file = tk.Label(inp, text="Chưa chọn file",
                                  font=("Segoe UI",9), bg=SURFACE2, fg=MUTED)
        self.lbl_file.pack(side="left", fill="x", expand=True)
        tk.Button(inp, text="Thư Mục", bg=SURFACE, fg=TEXT,
                  relief="flat", font=("Segoe UI",8), cursor="hand2",
                  command=self._pick_folder, padx=10, pady=5).pack(side="right", padx=(4,8), pady=6)
        tk.Button(inp, text="File", bg=ACCENT, fg="white",
                  relief="flat", font=("Segoe UI",8,"bold"), cursor="hand2",
                  command=self._pick, padx=10, pady=5).pack(side="right", pady=6)
        self._inp_frame = inp
        self.lbl_sub = tk.Label(P, text="", font=("Segoe UI",8),
                                 bg=BG, fg=MUTED, wraplength=660, justify="left")
        self.lbl_sub.pack(anchor="w", padx=22, pady=(0,4))

        # ── Chế độ tách ──
        self._section(P, "✂️  CHẾ ĐỘ TÁCH")
        for name, cfg in MODES.items():
            row = tk.Frame(P, bg=SURFACE2, highlightthickness=1,
                           highlightbackground=BORDER, cursor="hand2")
            row.pack(fill="x", padx=22, pady=2)
            rb = tk.Radiobutton(row, variable=self.mode_var, value=name,
                                text=name, bg=SURFACE2, fg=TEXT, selectcolor=SURFACE2,
                                activebackground=SURFACE2, activeforeground=ACCENT2,
                                font=("Segoe UI",10), cursor="hand2")
            rb.pack(side="left", padx=10, pady=8)
            row.bind("<Button-1>", lambda e, n=name: self.mode_var.set(n))
            badge = "⚡ Nhanh" if cfg["two"] else f"📁 {len(cfg['stems'])} stems"
            bc    = SUCCESS if cfg["two"] else ACCENT2
            tk.Label(row, text=badge, font=("Segoe UI",8,"bold"),
                     bg=SURFACE2, fg=bc).pack(side="right", padx=12)

        self.mode_info = tk.Label(P, text="", font=("Segoe UI",9),
                                   bg=SURFACE, fg=ACCENT2, justify="left",
                                   wraplength=650, anchor="w")
        self.mode_info.pack(fill="x", padx=22, pady=(6,14), ipady=7, ipadx=12)

        # ── Xử lý stem OTHER (compact dropdown) ──
        self._section(P, "🎵  XỬ LÝ STEM OTHER")
        other_row = tk.Frame(P, bg=BG); other_row.pack(fill="x", padx=22, pady=(0,4))
        # Badge hiện tại
        self.other_badge = tk.Label(other_row, text="", font=("Segoe UI",8,"bold"),
                                     bg=BG, fg=SUCCESS, width=10)
        self.other_badge.pack(side="right")
        # Combobox
        owrap = tk.Frame(other_row, bg=SURFACE2, highlightthickness=1,
                          highlightbackground=BORDER)
        owrap.pack(side="left", fill="x", expand=True)
        self.other_cb = ttk.Combobox(owrap, textvariable=self.other_var,
                                      values=list(OTHER_OPTIONS.keys()),
                                      state="readonly", font=("Segoe UI",10))
        self.other_cb.pack(fill="x", ipady=6, padx=2, pady=2)
        self.other_info = tk.Label(P, text="", font=("Segoe UI",9),
                                    bg=SURFACE, fg=ACCENT2, justify="left",
                                    wraplength=650, anchor="w")
        self.other_info.pack(fill="x", padx=22, pady=(4,6), ipady=6, ipadx=12)

        # ── Custom Other Panel ──
        self._co_panel = tk.Frame(P, bg=SURFACE, highlightthickness=1,
                                   highlightbackground=ACCENT)

        def _co_slider_row(parent, cb_var, cb_text, cb_color, items):
            row = tk.Frame(parent, bg=SURFACE); row.pack(fill="x", padx=10, pady=3)
            tk.Checkbutton(row, variable=cb_var, text=cb_text, bg=SURFACE,
                           fg=cb_color, selectcolor=SURFACE, activebackground=SURFACE,
                           font=("Segoe UI",9,"bold"), cursor="hand2",
                           width=11, anchor="w").pack(side="left")
            for lbl, var, lo, hi, fmt in items:
                tk.Label(row, text=lbl, font=("Segoe UI",8),
                          bg=SURFACE, fg=MUTED).pack(side="left", padx=(8,2))
                vl = tk.Label(row, text=fmt(var.get()), font=("Segoe UI",8,"bold"),
                               bg=SURFACE, fg=ACCENT2, width=7)
                vl.pack(side="right")
                ttk.Scale(row, from_=lo, to=hi, variable=var, orient="horizontal",
                          command=lambda v,l=vl,f=fmt: l.config(
                              text=f(int(float(v))))).pack(
                                  side="left", fill="x", expand=True, padx=2)

        _co_slider_row(self._co_panel, self.co_spectral, "Spectral", "#00d4ff",
                       [("Strength:", self.co_strength, 50, 99, lambda v: f"{v}%")])
        _co_slider_row(self._co_panel, self.co_pitch, "Pitch Shift", GOLD,
                       [("Semitones:", self.co_pitch_n, -12, 12, lambda v: f"{v:+d}")])
        _co_slider_row(self._co_panel, self.co_eq, "EQ Cut", ACCENT2,
                       [("Lo:", self.co_eq_lo, 100, 2000, lambda v: f"{v}Hz"),
                        ("Hi:", self.co_eq_hi, 1000, 8000, lambda v: f"{v}Hz")])
        _co_slider_row(self._co_panel, self.co_noise, "White Noise", MUTED,
                       [("Level:", self.co_noise_db, -60, -20, lambda v: f"{v}dB")])
        _co_slider_row(self._co_panel, self.co_volume, "Giảm âm lượng", ORANGE,
                       [("Còn lại:", self.co_volume_pc, 10, 100, lambda v: f"{v}%")])
        tk.Frame(self._co_panel, bg=BORDER, height=1).pack(fill="x", padx=10, pady=(4,0))
        tk.Label(self._co_panel, text="  Chọn ít nhất 1 lớp · Mỗi lớp tự normalize RMS",
                 font=("Segoe UI",8), bg=SURFACE, fg=MUTED).pack(anchor="w", pady=(2,8))
        self._co_panel.pack_forget()  # ẩn mặc định

        # Bind combobox để toggle panel
        self.other_cb.bind("<<ComboboxSelected>>", lambda e: self.after(10, self._toggle_co_panel))
        self.other_var.trace_add("write", lambda *_: self.after(10, self._toggle_co_panel))

        # ── Output ──
        self._section(P, "📁  LƯU VÀO")
        orow = tk.Frame(P, bg=BG); orow.pack(fill="x", padx=22, pady=(0,14))
        tk.Entry(orow, textvariable=self.out_var, bg=SURFACE2, fg=TEXT,
                 relief="flat", font=("Segoe UI",9), highlightthickness=1,
                 highlightbackground=BORDER, insertbackground=TEXT).pack(
                     side="left", fill="x", expand=True, ipady=7, padx=(0,8))
        tk.Button(orow, text="Chọn...", bg=SURFACE2, fg=TEXT, relief="flat",
                  font=("Segoe UI",9), cursor="hand2",
                  command=self._pick_out, padx=12, pady=5).pack(side="left")

        # ── Xử lý hàng loạt ──
        self._section(P, "⚡  XỬ LÝ HÀNG LOẠT")
        wrow = tk.Frame(P, bg=BG); wrow.pack(fill="x", padx=22, pady=(0,6))
        tk.Label(wrow, text="Song song:",
                 font=("Segoe UI",9), bg=BG, fg=TEXT).pack(side="left")
        for n in [1,2,3,4]:
            tk.Radiobutton(wrow, variable=self.workers_var, value=n, text=str(n),
                           bg=BG, fg=TEXT, selectcolor=BG,
                           activebackground=BG, activeforeground=ACCENT2,
                           font=("Segoe UI",10,"bold"), cursor="hand2").pack(side="left", padx=6)
        tk.Label(wrow, text="luồng  (1=an toàn · 2-3 nếu RAM >8GB)",
                 font=("Segoe UI",8), bg=BG, fg=MUTED).pack(side="left", padx=6)

        # Time stretch bypass
        tsrow = tk.Frame(P, bg=BG); tsrow.pack(fill="x", padx=22, pady=(0,14))
        tk.Label(tsrow, text="Time stretch:",
                 font=("Segoe UI",9), bg=BG, fg=TEXT).pack(side="left")
        ts_opts = [("Tắt","off"),("±1% nhẹ","ts1"),("±2% mạnh","ts2"),("±3% rất mạnh","ts3")]
        for lbl, val in ts_opts:
            tk.Radiobutton(tsrow, variable=self.ts_var, value=val, text=lbl,
                           bg=BG, fg=TEXT, selectcolor=BG,
                           activebackground=BG, activeforeground=ACCENT2,
                           font=("Segoe UI",9), cursor="hand2").pack(side="left", padx=6)
        tk.Label(tsrow, text="← áp dụng lên toàn bộ audio sau tách",
                 font=("Segoe UI",8), bg=BG, fg=MUTED).pack(side="left", padx=4)

        # ── Progress ──
        tk.Frame(P, bg=BORDER, height=1).pack(fill="x", padx=22, pady=(0,10))
        self.lbl_status = tk.Label(P, text="Sẵn sàng", font=("Segoe UI",9),
                                    bg=BG, fg=MUTED)
        self.lbl_status.pack(pady=(0,4))
        ttk.Progressbar(P, variable=self.prog_var, maximum=100,
                        style="P.Horizontal.TProgressbar").pack(
                            fill="x", padx=22, pady=(0,10))

        # ── Log ──
        lf = tk.Frame(P, bg=SURFACE, highlightthickness=1, highlightbackground=BORDER)
        lf.pack(fill="both", expand=True, padx=22, pady=(0,8))
        self.log = tk.Text(lf, bg=SURFACE, fg=TEXT, font=("Consolas",9),
                           relief="flat", state="disabled", wrap="word", height=8)
        self.log.pack(fill="both", padx=8, pady=8)

        # ── Buttons ──
        br = tk.Frame(P, bg=BG); br.pack(fill="x", padx=22, pady=(2,20))
        tk.Button(br, text="Xóa log", bg=SURFACE2, fg=MUTED, relief="flat",
                  font=("Segoe UI",9), cursor="hand2",
                  command=self._clear_log, padx=14, pady=7).pack(side="left")
        tk.Button(br, text="📂 Mở output", bg=SURFACE2, fg=TEXT, relief="flat",
                  font=("Segoe UI",9), cursor="hand2",
                  command=self._open_output, padx=14, pady=7).pack(side="left", padx=8)
        self.btn_run = tk.Button(br, text="▶  BẮT ĐẦU TÁCH", bg=ACCENT, fg="white",
                                  relief="flat", font=("Segoe UI",11,"bold"),
                                  cursor="hand2", command=self._start, padx=26, pady=7)
        self.btn_run.pack(side="right")
        self._log("✦ Sẵn sàng. Chọn file, chế độ tách và xử lý other.\n")

    def _section(self, parent, title):
        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", padx=22, pady=(0,10))
        tk.Label(parent, text=title, font=("Segoe UI",9,"bold"),
                 bg=BG, fg=MUTED).pack(anchor="w", padx=22, pady=(0,6))

    def _update_info(self):
        if not hasattr(self, 'mode_info'): return
        name = self.mode_var.get()
        self.mode_info.config(text=MODE_DESC.get(name,""))
        # Ẩn/hiện other section nếu mode là "Chỉ giọng nói"
        is_two = MODES.get(name,{}).get("two", False)
        self.other_info.config(
            fg=MUTED if is_two else ACCENT2,
            text="ℹ️  Chế độ 2-stem không tách other riêng — cài other không có tác dụng."
                 if is_two else OTHER_DESC.get(OTHER_OPTIONS.get(self.other_var.get(),"keep"),""))

    def _update_other_info(self):
        if not hasattr(self, 'other_info'): return
        name = self.other_var.get()
        val  = OTHER_OPTIONS.get(name,"keep")
        is_two = MODES.get(self.mode_var.get(),{}).get("two", False)
        if not is_two:
            self.other_info.config(fg=ACCENT2, text=OTHER_DESC.get(val,""))
        # Update badge
        if hasattr(self, 'other_badge'):
            if val == "drop":                        tag, tc = "AN TOAN",   SUCCESS
            elif val == "spectral_full":             tag, tc = "TOI DA",    ERROR
            elif val.startswith("spectral"):         tag, tc = "SPECTRAL",  "#00d4ff"
            elif val.startswith("noise_pitch"):      tag, tc = "MANH NHAT", ERROR
            elif val.startswith("noise"):            tag, tc = "NOISE",     ACCENT2
            elif val.startswith("pitch") and "7" in val: tag, tc = "PITCH MANH", GOLD
            elif val.startswith("pitch"):            tag, tc = "BYPASS ID", GOLD
            elif val == "keep":                      tag, tc = "GIU NGUYEN",ORANGE
            else:                                    tag, tc = "GIAM AM",   ACCENT2
            self.other_badge.config(text=tag, fg=tc)

    def _pick(self):
        files = filedialog.askopenfilenames(
            title="Chọn file",
            filetypes=[("Audio/Video",
                        "*.mp3 *.mp4 *.wav *.flac *.ogg *.m4a *.mkv *.aac *.webm *.avi *.mov"),
                       ("All","*.*")])
        if not files: return
        self.files = list(files)
        names = [Path(f).name for f in self.files]
        self.lbl_file.config(
            text=names[0] if len(names)==1 else f"{len(names)} files đã chọn", fg=SUCCESS)
        self.lbl_sub.config(
            text="  ".join(f"· {n}" for n in names[:3]) +
            (f"  +{len(names)-3} nữa" if len(names)>3 else ""))
        self._inp_frame.config(highlightbackground=ACCENT)
        self._log(f"✓ Chọn {len(self.files)} file:\n" +
                  "".join(f"  · {Path(f).name}\n" for f in self.files))

    def _pick_folder(self):
        folder = filedialog.askdirectory(title="Chọn thư mục chứa file audio/video")
        if not folder: return
        exts = ALL_EXTS
        found = sorted([f for f in Path(folder).iterdir()
                        if f.suffix.lower() in exts])
        if not found:
            self._log("⚠ Không tìm thấy file audio/video trong thư mục!\n", GOLD)
            return
        self.files = [str(f) for f in found]
        self.lbl_file.config(text=f"📁 {Path(folder).name}/ — {len(self.files)} file", fg=SUCCESS)
        self.lbl_sub.config(
            text="  ".join(f"· {f.name}" for f in found[:3]) +
            (f"  +{len(found)-3} nữa" if len(found)>3 else ""))
        self._inp_frame.config(highlightbackground=GOLD)
        self._log(f"✓ Thư mục: {folder}\n  {len(self.files)} file:\n" +
                  "".join(f"  · {Path(f).name}\n" for f in found[:5]) +
                  (f"  ... +{len(found)-5} file nữa\n" if len(found)>5 else ""))

    def _pick_out(self):
        d = filedialog.askdirectory()
        if d: self.out_var.set(d)

    def _log(self, msg, color=None):
        self.log.config(state="normal")
        if color:
            tag = f"t{abs(hash(color))}"
            self.log.tag_config(tag, foreground=color)
            self.log.insert("end", msg, tag)
        else:
            self.log.insert("end", msg)
        self.log.see("end"); self.log.config(state="disabled")

    def _update_tab_style(self):
        for val, btn in self._tab_btns.items():
            if val == self.tab_var.get():
                btn.config(bg=ACCENT, fg="white")
            else:
                btn.config(bg=SURFACE2, fg=MUTED)

    def _switch_tab(self, val):
        self.tab_var.set(val)
        self._update_tab_style()
        if val == "stems":
            self._spectral_frame.pack_forget()
            self._stems_frame.pack(fill="both", expand=True)
        else:
            self._stems_frame.pack_forget()
            self._spectral_frame.pack(fill="both", expand=True)
        self.after(50, self._center_window)

    def _build_spectral_tab(self, P):
        """Tab Spectral Direct — xử lý thẳng không cần tách stems"""

        # ── Input zone (dùng chung files list) ──
        sp_inp = tk.Frame(P, bg=SURFACE2, highlightthickness=1,
                           highlightbackground=BORDER)
        sp_inp.pack(fill="x", padx=22, pady=(8,4))
        tk.Label(sp_inp, text="📂", font=("Segoe UI",13),
                  bg=SURFACE2, fg=ACCENT).pack(side="left", padx=(10,6), pady=8)
        self.sp_lbl_file = tk.Label(sp_inp, text="Chưa chọn file",
                                     font=("Segoe UI",9), bg=SURFACE2, fg=MUTED)
        self.sp_lbl_file.pack(side="left", fill="x", expand=True)
        tk.Button(sp_inp, text="Thư Mục", bg=SURFACE, fg=TEXT,
                  relief="flat", font=("Segoe UI",8), cursor="hand2",
                  command=self._sp_pick_folder, padx=10, pady=5).pack(side="right", padx=(4,8), pady=6)
        tk.Button(sp_inp, text="File", bg=ACCENT, fg="white",
                  relief="flat", font=("Segoe UI",8,"bold"), cursor="hand2",
                  command=self._sp_pick, padx=10, pady=5).pack(side="right", pady=6)
        self.sp_lbl_sub = tk.Label(P, text="", font=("Segoe UI",8),
                                    bg=BG, fg=MUTED, wraplength=660, justify="left")
        self.sp_lbl_sub.pack(anchor="w", padx=22, pady=(0,4))

        # Chế độ Spectral
        tk.Frame(P, bg=BORDER, height=1).pack(fill="x", padx=22, pady=(4,8))
        tk.Label(P, text="🌊  SPECTRAL DIRECT — Xử lý toàn bộ audio",
                 font=("Segoe UI",9,"bold"), bg=BG, fg=MUTED).pack(anchor="w", padx=22)
        tk.Label(P, text="Áp dụng Spectral Mask trực tiếp lên file gốc, không tách stems. Nhanh hơn 3-5x.",
                 font=("Segoe UI",8), bg=BG, fg=MUTED).pack(anchor="w", padx=22, pady=(2,8))

        SPECTRAL_MODES = [
            ("Spectral Mask chuẩn (85%)",        "sm85",    "Detect + vẽ lại harmonic bins 85%. Nhanh, bypass tốt."),
            ("Spectral Mask mạnh (92%)",          "sm92",    "Mask 92% harmonic — mạnh hơn, SFX vẫn còn."),
            ("Spectral + Pitch -5",               "sm_p5",   "Mask 85% + Pitch -5."),
            ("Spectral + EQ lọc melody",          "sm_eq",   "Mask 85% + EQ cắt 300Hz-4kHz."),
            ("Spectral + Pitch -5 + Noise",       "sm_p5n",  "Mask 88% + Pitch -5 + Noise."),
            ("Spectral Full (Mask+EQ+Pitch+Noise)","sm_full", "4 lớp — mỗi lớp đã normalize riêng."),
            ("⚙️  Custom (tự chỉnh)",              "custom",  "Tự chọn từng thông số."),
        ]

        self.sp_mode_var = tk.StringVar(value="sm85")
        for name, val, desc in SPECTRAL_MODES:
            row = tk.Frame(P, bg=SURFACE2, highlightthickness=1,
                           highlightbackground=BORDER)
            row.pack(fill="x", padx=22, pady=2)
            rb = tk.Radiobutton(row, variable=self.sp_mode_var, value=val,
                                text=name, bg=SURFACE2, fg=TEXT, selectcolor=SURFACE2,
                                activebackground=SURFACE2, activeforeground=ACCENT2,
                                font=("Segoe UI",9), cursor="hand2",
                                command=self._toggle_custom_panel)
            rb.pack(side="left", padx=10, pady=6)
            row.bind("<Button-1>", lambda e, v=val: [self.sp_mode_var.set(v), self._toggle_custom_panel()])
            if "Custom" in name:  tc = "#00d4ff"; tag = "CUSTOM"
            elif "Full" in name:  tc = ERROR;     tag = "4 LOP"
            elif "Noise" in name: tc = GOLD;      tag = "3 LOP"
            elif "+" in name:     tc = ACCENT2;   tag = "2 LOP"
            else:                 tc = SUCCESS;   tag = "NHANH"
            tk.Label(row, text=tag, font=("Segoe UI",7,"bold"),
                     bg=SURFACE2, fg=tc).pack(side="right", padx=12)

        # ── Custom panel — nằm ngay sau danh sách modes ──
        self._custom_panel = tk.Frame(P, bg=SURFACE, highlightthickness=1,
                                       highlightbackground=ACCENT)
        # Không pack ngay — chỉ hiện khi chọn Custom
        # Spectral strength
        self.c_spectral_var = tk.BooleanVar(value=True)
        self.c_strength_var = tk.IntVar(value=85)
        cr1 = tk.Frame(self._custom_panel, bg=SURFACE); cr1.pack(fill="x", padx=12, pady=(8,4))
        tk.Checkbutton(cr1, text="Spectral Mask", variable=self.c_spectral_var,
                       bg=SURFACE, fg=TEXT, selectcolor=SURFACE, activebackground=SURFACE,
                       font=("Segoe UI",9,"bold"), cursor="hand2").pack(side="left")
        tk.Label(cr1, text="Strength:", font=("Segoe UI",8), bg=SURFACE, fg=MUTED).pack(side="left", padx=(12,4))
        self._strength_lbl = tk.Label(cr1, text="85%", font=("Segoe UI",9,"bold"),
                                       bg=SURFACE, fg=ACCENT2, width=4)
        self._strength_lbl.pack(side="right")
        sl = ttk.Scale(cr1, from_=50, to=99, variable=self.c_strength_var, orient="horizontal",
                       command=lambda v: self._strength_lbl.config(text=f"{int(float(v))}%"))
        sl.pack(side="left", fill="x", expand=True, padx=4)

        # Pitch
        self.c_pitch_var   = tk.BooleanVar(value=False)
        self.c_pitch_n_var = tk.IntVar(value=-5)
        cr2 = tk.Frame(self._custom_panel, bg=SURFACE); cr2.pack(fill="x", padx=12, pady=4)
        tk.Checkbutton(cr2, text="Pitch Shift", variable=self.c_pitch_var,
                       bg=SURFACE, fg=TEXT, selectcolor=SURFACE, activebackground=SURFACE,
                       font=("Segoe UI",9,"bold"), cursor="hand2").pack(side="left")
        tk.Label(cr2, text="Semitones:", font=("Segoe UI",8), bg=SURFACE, fg=MUTED).pack(side="left", padx=(12,4))
        self._pitch_lbl = tk.Label(cr2, text="-5", font=("Segoe UI",9,"bold"),
                                    bg=SURFACE, fg=GOLD, width=4)
        self._pitch_lbl.pack(side="right")
        ttk.Scale(cr2, from_=-12, to=12, variable=self.c_pitch_n_var, orient="horizontal",
                  command=lambda v: self._pitch_lbl.config(text=f"{int(float(v)):+d}")).pack(
                      side="left", fill="x", expand=True, padx=4)

        # EQ
        self.c_eq_var      = tk.BooleanVar(value=False)
        self.c_eq_lo_var   = tk.IntVar(value=300)
        self.c_eq_hi_var   = tk.IntVar(value=4000)
        cr3 = tk.Frame(self._custom_panel, bg=SURFACE); cr3.pack(fill="x", padx=12, pady=4)
        tk.Checkbutton(cr3, text="EQ Cut", variable=self.c_eq_var,
                       bg=SURFACE, fg=TEXT, selectcolor=SURFACE, activebackground=SURFACE,
                       font=("Segoe UI",9,"bold"), cursor="hand2").pack(side="left")
        tk.Label(cr3, text="Lo:", font=("Segoe UI",8), bg=SURFACE, fg=MUTED).pack(side="left", padx=(12,2))
        self._eq_lo_lbl = tk.Label(cr3, text="300Hz", font=("Segoe UI",8,"bold"),
                                    bg=SURFACE, fg=ACCENT2, width=5)
        self._eq_lo_lbl.pack(side="left")
        ttk.Scale(cr3, from_=100, to=2000, variable=self.c_eq_lo_var, orient="horizontal",
                  command=lambda v: self._eq_lo_lbl.config(text=f"{int(float(v))}Hz")).pack(
                      side="left", fill="x", expand=True, padx=(2,8))
        tk.Label(cr3, text="Hi:", font=("Segoe UI",8), bg=SURFACE, fg=MUTED).pack(side="left", padx=2)
        self._eq_hi_lbl = tk.Label(cr3, text="4000Hz", font=("Segoe UI",8,"bold"),
                                    bg=SURFACE, fg=ACCENT2, width=6)
        self._eq_hi_lbl.pack(side="left")
        ttk.Scale(cr3, from_=1000, to=8000, variable=self.c_eq_hi_var, orient="horizontal",
                  command=lambda v: self._eq_hi_lbl.config(text=f"{int(float(v))}Hz")).pack(
                      side="left", fill="x", expand=True, padx=2)

        # Noise
        self.c_noise_var   = tk.BooleanVar(value=False)
        self.c_noise_db_var= tk.IntVar(value=-45)
        cr4 = tk.Frame(self._custom_panel, bg=SURFACE); cr4.pack(fill="x", padx=12, pady=(4,10))
        tk.Checkbutton(cr4, text="White Noise", variable=self.c_noise_var,
                       bg=SURFACE, fg=TEXT, selectcolor=SURFACE, activebackground=SURFACE,
                       font=("Segoe UI",9,"bold"), cursor="hand2").pack(side="left")
        tk.Label(cr4, text="Level:", font=("Segoe UI",8), bg=SURFACE, fg=MUTED).pack(side="left", padx=(12,4))
        self._noise_lbl = tk.Label(cr4, text="-45dB", font=("Segoe UI",9,"bold"),
                                    bg=SURFACE, fg=MUTED, width=6)
        self._noise_lbl.pack(side="right")
        ttk.Scale(cr4, from_=-60, to=-20, variable=self.c_noise_db_var, orient="horizontal",
                  command=lambda v: self._noise_lbl.config(text=f"{int(float(v))}dB")).pack(
                      side="left", fill="x", expand=True, padx=4)

        # Custom panel placeholder — pack vào đây khi chọn Custom
        self._custom_placeholder = tk.Frame(P, bg=BG, height=0)
        self._custom_placeholder.pack(fill="x", padx=22)
        self._custom_panel_parent = P  # lưu parent để insert đúng chỗ

        # Time stretch
        tk.Frame(P, bg=BORDER, height=1).pack(fill="x", padx=22, pady=(10,6))
        tsrow = tk.Frame(P, bg=BG); tsrow.pack(fill="x", padx=22, pady=(0,8))
        tk.Label(tsrow, text="Time stretch:", font=("Segoe UI",9), bg=BG, fg=TEXT).pack(side="left")
        for lbl, val in [("Tắt","off"),("±1%","ts1"),("±2%","ts2"),("±3%","ts3")]:
            tk.Radiobutton(tsrow, variable=self.ts_var, value=val, text=lbl,
                           bg=BG, fg=TEXT, selectcolor=BG, activebackground=BG,
                           font=("Segoe UI",9), cursor="hand2").pack(side="left", padx=6)

        # Workers
        wrow = tk.Frame(P, bg=BG); wrow.pack(fill="x", padx=22, pady=(0,8))
        tk.Label(wrow, text="Song song:", font=("Segoe UI",9), bg=BG, fg=TEXT).pack(side="left")
        for n in [1,2,3,4]:
            tk.Radiobutton(wrow, variable=self.workers_var, value=n, text=str(n),
                           bg=BG, fg=TEXT, selectcolor=BG, activebackground=BG,
                           font=("Segoe UI",10,"bold"), cursor="hand2").pack(side="left", padx=6)
        tk.Label(wrow, text="luồng", font=("Segoe UI",8), bg=BG, fg=MUTED).pack(side="left", padx=4)

        # Output
        tk.Frame(P, bg=BORDER, height=1).pack(fill="x", padx=22, pady=(0,8))
        tk.Label(P, text="📁  LƯU VÀO", font=("Segoe UI",9,"bold"),
                 bg=BG, fg=MUTED).pack(anchor="w", padx=22, pady=(0,4))
        orow = tk.Frame(P, bg=BG); orow.pack(fill="x", padx=22, pady=(0,8))
        tk.Entry(orow, textvariable=self.out_var, bg=SURFACE2, fg=TEXT, relief="flat",
                 font=("Segoe UI",9), highlightthickness=1, highlightbackground=BORDER,
                 insertbackground=TEXT).pack(side="left", fill="x", expand=True, ipady=7, padx=(0,8))
        tk.Button(orow, text="Chọn...", bg=SURFACE2, fg=TEXT, relief="flat",
                  font=("Segoe UI",9), cursor="hand2", command=self._pick_out,
                  padx=12, pady=5).pack(side="left")

        # Progress + Log
        tk.Frame(P, bg=BORDER, height=1).pack(fill="x", padx=22, pady=(0,6))
        self.sp_status = tk.Label(P, text="Sẵn sàng", font=("Segoe UI",9), bg=BG, fg=MUTED)
        self.sp_status.pack(pady=(0,3))
        ttk.Progressbar(P, variable=self.prog_var, maximum=100,
                        style="P.Horizontal.TProgressbar").pack(fill="x", padx=22, pady=(0,6))
        sp_lf = tk.Frame(P, bg=SURFACE, highlightthickness=1, highlightbackground=BORDER)
        sp_lf.pack(fill="both", expand=True, padx=22, pady=(0,6))
        self.sp_log = tk.Text(sp_lf, bg=SURFACE, fg=TEXT, font=("Consolas",9),
                              relief="flat", state="disabled", wrap="word", height=3)
        self.sp_log.pack(fill="both", padx=8, pady=6)

        # ── Buttons ──
        sp_br = tk.Frame(P, bg=BG)
        sp_br.pack(fill="x", padx=22, pady=(4,10))
        tk.Button(sp_br, text="Xóa log", bg=SURFACE2, fg=MUTED, relief="flat",
                  font=("Segoe UI",9), cursor="hand2",
                  command=lambda: [self.sp_log.config(state="normal"),
                                   self.sp_log.delete("1.0","end"),
                                   self.sp_log.config(state="disabled")],
                  padx=14, pady=7).pack(side="left")
        tk.Button(sp_br, text="📂 Mở output", bg=SURFACE2, fg=TEXT, relief="flat",
                  font=("Segoe UI",9), cursor="hand2",
                  command=self._open_output, padx=14, pady=7).pack(side="left", padx=8)
        self.sp_btn_run = tk.Button(sp_br, text="▶  BẮT ĐẦU TÁCH",
                                     bg=ACCENT, fg="white", relief="flat",
                                     font=("Segoe UI",11,"bold"), cursor="hand2",
                                     command=self._start, padx=26, pady=7)
        self.sp_btn_run.pack(side="right")

    def _toggle_co_panel(self):
        """Hiện/ẩn custom panel trong tab Stems"""
        if not hasattr(self, '_co_panel'): return
        val = OTHER_OPTIONS.get(self.other_var.get(), "")
        if val == "custom_other":
            self._co_panel.pack(fill="x", pady=(0,4))
        else:
            self._co_panel.pack_forget()
        self.after(50, self._center_window)

    def _get_co_cfg(self):
        return {
            "spectral":  self.co_spectral.get(),
            "s_strength":self.co_strength.get(),
            "pitch":     self.co_pitch.get(),
            "pitch_n":   self.co_pitch_n.get(),
            "eq":        self.co_eq.get(),
            "eq_lo":     self.co_eq_lo.get(),
            "eq_hi":     self.co_eq_hi.get(),
            "noise":     self.co_noise.get(),
            "noise_db":  float(self.co_noise_db.get()),
            "volume":    self.co_volume.get(),
            "volume_pc": self.co_volume_pc.get(),
        }

    def _apply_co_custom(self, data, sr):
        """Áp dụng custom other chain"""
        import numpy as np
        cfg = self._get_co_cfg()
        result = data.copy()
        orig_rms = float(np.sqrt(np.mean(data**2))) + 1e-9
        if cfg["spectral"]:
            result = _spectral_mask(result, sr, cfg["s_strength"]/100.0)
        if cfg["eq"]:
            try:
                from scipy import signal as sg
                def notch(y):
                    nyq = sr/2.0
                    l = max(0.001, min(cfg["eq_lo"]/nyq, 0.999))
                    h = max(0.001, min(cfg["eq_hi"]/nyq, 0.999))
                    if l >= h: return y
                    b,a = sg.butter(4,[l,h],btype='bandstop')
                    return sg.filtfilt(b,a,y.astype(np.float64)).astype(np.float32)
                if result.ndim == 1: result = notch(result)
                else:
                    out = np.zeros_like(result)
                    for c in range(result.shape[1]): out[:,c] = notch(result[:,c])
                    result = out
            except Exception: pass
        if cfg["pitch"] and cfg["pitch_n"] != 0:
            result = _librosa_pitch_shift(result, sr, cfg["pitch_n"])
        if cfg["noise"]:
            result = _add_noise(result, cfg["noise_db"])
        # Normalize về mức gốc
        out_rms = float(np.sqrt(np.mean(result**2))) + 1e-9
        result  = (result * (orig_rms / out_rms))
        # Giảm âm lượng cuối cùng (sau normalize) — theo % người dùng chọn
        if cfg["volume"]:
            result = result * (cfg["volume_pc"] / 100.0)
        peak = float(abs(result).max())
        if peak > 0.98: result *= 0.98/peak
        return result.astype(data.dtype)

    def _toggle_custom_panel(self):
        if not hasattr(self, '_custom_panel'): return
        if self.sp_mode_var.get() == "custom":
            # Pack ngay sau placeholder (dưới danh sách modes)
            self._custom_panel.pack(fill="x", padx=22, pady=(4,0),
                                     in_=self._custom_panel_parent,
                                     after=self._custom_placeholder)
        else:
            self._custom_panel.pack_forget()
        self.after(50, self._center_window)

    def _apply_custom(self, data, sr):
        """Áp dụng custom chain theo checkboxes"""
        import numpy as np
        result = data.copy()
        orig_rms = float(np.sqrt(np.mean(data**2))) + 1e-9

        if self.c_spectral_var.get():
            strength = self.c_strength_var.get() / 100.0
            result = _spectral_mask(result, sr, strength=strength)

        if self.c_eq_var.get():
            lo = self.c_eq_lo_var.get()
            hi = self.c_eq_hi_var.get()
            # Dùng EQ cut với lo/hi tùy chỉnh
            try:
                from scipy import signal as scipy_signal
                def notch_ch(ch_data):
                    nyq = sr / 2.0
                    l = max(0.001, min(lo/nyq, 0.999))
                    h = max(0.001, min(hi/nyq, 0.999))
                    if l >= h: return ch_data
                    b, a = scipy_signal.butter(4, [l, h], btype='bandstop')
                    return scipy_signal.filtfilt(b, a, ch_data.astype(np.float64)).astype(np.float32)
                import numpy as np
                if result.ndim == 1:
                    result = notch_ch(result)
                else:
                    out = np.zeros_like(result)
                    for c in range(result.shape[1]): out[:,c] = notch_ch(result[:,c])
                    result = out
            except Exception: pass

        if self.c_pitch_var.get():
            n = self.c_pitch_n_var.get()
            if n != 0:
                result = _librosa_pitch_shift(result, sr, n)

        if self.c_noise_var.get():
            db = self.c_noise_db_var.get()
            result = _add_noise(result, noise_level=float(db))

        # Normalize về mức âm lượng gốc
        out_rms = float(np.sqrt(np.mean(result**2))) + 1e-9
        result  = result * (orig_rms / out_rms)
        peak = float(abs(result).max())
        if peak > 0.98: result *= 0.98 / peak
        return result.astype(data.dtype)

    def _sp_pick(self):
        files = filedialog.askopenfilenames(
            title="Chọn file",
            filetypes=[("Audio/Video",
                        "*.mp3 *.mp4 *.wav *.flac *.ogg *.m4a *.mkv *.aac *.webm *.avi *.mov"),
                       ("All","*.*")])
        if not files: return
        self.files = list(files)
        names = [Path(f).name for f in self.files]
        txt = names[0] if len(names)==1 else f"{len(names)} files đã chọn"
        self.sp_lbl_file.config(text=txt, fg=SUCCESS)
        self.sp_lbl_sub.config(
            text="  ".join(f"· {n}" for n in names[:3]) +
            (f"  +{len(names)-3} nữa" if len(names)>3 else ""))
        # Sync với tab stems
        self.lbl_file.config(text=txt, fg=SUCCESS)
        self._sp_log(f"✓ Chọn {len(self.files)} file\n")

    def _sp_pick_folder(self):
        folder = filedialog.askdirectory(title="Chọn thư mục")
        if not folder: return
        found = sorted([f for f in Path(folder).iterdir()
                        if f.suffix.lower() in ALL_EXTS])
        if not found:
            self._sp_log("⚠ Không tìm thấy file!\n", GOLD); return
        self.files = [str(f) for f in found]
        txt = f"📁 {Path(folder).name}/ — {len(self.files)} file"
        self.sp_lbl_file.config(text=txt, fg=SUCCESS)
        self.sp_lbl_sub.config(
            text="  ".join(f"· {f.name}" for f in found[:3]) +
            (f"  +{len(found)-3} nữa" if len(found)>3 else ""))
        self.lbl_file.config(text=txt, fg=SUCCESS)
        self._sp_log(f"✓ Thư mục: {folder} — {len(self.files)} file\n")

    def _sp_log(self, msg, color=None):
        self.sp_log.config(state="normal")
        if color:
            tag = f"t{abs(hash(color))}"
            self.sp_log.tag_config(tag, foreground=color)
            self.sp_log.insert("end", msg, tag)
        else:
            self.sp_log.insert("end", msg)
        self.sp_log.see("end")
        self.sp_log.config(state="disabled")

    def _run_spectral_direct(self, src, out_dir, sp_mode, ts_mode, log_cb, prog_cb):
        """Xử lý Spectral Mask trực tiếp — không tách stems"""
        import soundfile as sf, numpy as np, shutil
        src = Path(src)
        tmp = out_dir / "_sp_tmp"; tmp.mkdir(parents=True, exist_ok=True)
        try:
            prog_cb(5)
            # Trích audio nếu video
            wav_src = src
            if src.suffix.lower() in VIDEO_EXTS:
                log_cb("  Trích audio từ video...\n")
                wav_src = tmp / f"{src.stem}.wav"
                ffmpeg("-i", str(src), "-vn", "-acodec","pcm_s16le",
                       "-ar","44100", "-ac","2", str(wav_src))
            prog_cb(15)

            # Đọc audio
            log_cb("  Đọc audio...\n")
            data, sr = sf.read(str(wav_src), dtype='float32')
            prog_cb(25)

            # Áp dụng spectral mode
            log_cb(f"  Spectral processing ({sp_mode})...\n")
            if sp_mode == "sm85":
                result = _spectral_mask(data, sr, strength=0.85)
            elif sp_mode == "sm92":
                result = _spectral_mask(data, sr, strength=0.92)
            elif sp_mode == "sm_p5":
                result = _spectral_mask(data, sr, strength=0.85)
                result = _librosa_pitch_shift(result, sr, -5)
            elif sp_mode == "sm_eq":
                result = _spectral_mask(data, sr, strength=0.85)
                result = _eq_cut_melody(result, sr)
            elif sp_mode == "sm_p5n":
                result = _spectral_mask(data, sr, strength=0.88)
                result = _librosa_pitch_shift(result, sr, -5)
                result = _add_noise(result, noise_level=-42.0)
            elif sp_mode == "sm_full":
                result = _spectral_mask(data, sr, strength=0.90)
                result = _eq_cut_melody(result, sr)
                result = _librosa_pitch_shift(result, sr, -5)
                result = _add_noise(result, noise_level=-42.0)
            elif sp_mode == "custom":
                result = self._apply_custom(data, sr)
            else:
                result = data
            prog_cb(80)

            # Time stretch
            if ts_mode != "off":
                log_cb(f"  Time stretch ({ts_mode})...\n")
                result = _time_stretch_audio(result, sr, ts_mode)
            prog_cb(90)

            # Normalize
            peak = float(abs(result).max())
            if peak > 0.98: result *= 0.98 / peak

            # Lưu output
            out_wav = tmp / f"{src.stem}_spectral.wav"
            sf.write(str(out_wav), result, sr, subtype='PCM_16')

            if src.suffix.lower() in VIDEO_EXTS:
                out_final = out_dir / f"{src.stem}_spectral{src.suffix}"
                log_cb("  Ghép audio vào video...\n")
                ffmpeg("-i", str(src), "-i", str(out_wav),
                       "-map","0:v:0", "-map","1:a:0",
                       "-c:v","copy", "-c:a","aac", "-b:a","192k",
                       "-shortest", str(out_final))
            else:
                out_final = out_dir / f"{src.stem}_spectral.wav"
                shutil.copy2(out_wav, out_final)

            prog_cb(100)
            return str(out_final)
        except Exception as e:
            import traceback
            raise RuntimeError(f"{e}\n{traceback.format_exc()[-300:]}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def _center_window(self):
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        w  = self.winfo_reqwidth()
        h  = min(self.winfo_reqheight(), sh - 80)
        w  = max(w, 720)
        x  = (sw - w) // 2
        y  = max(20, (sh - h) // 2)
        self.geometry(f"{w}x{h}+{x}+{y}")

    def _clear_log(self):
        self.log.config(state="normal"); self.log.delete("1.0","end")
        self.log.config(state="disabled")

    def _open_output(self):
        p = self.last_output
        if not p and self.files:
            pv = self.out_var.get()
            p = str(Path(self.files[0]).parent/"tach_nhac_nen_output") \
                if pv=="(cùng thư mục với file gốc)" else pv
        if p and Path(p).exists(): os.startfile(p)

    def _set_prog(self, v):
        self.prog_var.set(v); self.update_idletasks()

    def _start(self):
        if not self.files:
            self._log("⚠ Chưa chọn file!\n", GOLD)
            if hasattr(self, 'sp_log'): self._sp_log("⚠ Chưa chọn file!\n", GOLD)
            return
        self.btn_run.config(state="disabled", text="⏳ Đang xử lý...")
        if self.tab_var.get() == "spectral":
            threading.Thread(target=self._run_spectral_all, daemon=True).start()
        else:
            threading.Thread(target=self._run_all, daemon=True).start()

    def _run_spectral_all(self):
        from concurrent.futures import ThreadPoolExecutor, as_completed
        try:
            if not hasattr(self, 'sp_mode_var'):
                self._sp_log("⚠ Lỗi: sp_mode_var chưa khởi tạo\n", ERROR)
                return
            self._sp_log("\n─────────────────────────────\n")
            sp_mode  = self.sp_mode_var.get()
            ts_mode  = self.ts_var.get()
            workers  = self.workers_var.get()
            total    = len(self.files)
            self._sp_log(f"Mode: {sp_mode}  TS: {ts_mode}  Workers: {workers}\n", ACCENT2)
            ok, errs = 0, []
            done = [0]

            def do_one(f):
                src = Path(f)
                pv  = self.out_var.get()
                out_dir = (src.parent / "spectral_output")                           if pv == "(cùng thư mục với file gốc)" else Path(pv)
                out_dir.mkdir(parents=True, exist_ok=True)
                self.last_output = str(out_dir)
                return self._run_spectral_direct(
                    src, out_dir, sp_mode, ts_mode,
                    lambda m: self._sp_log(m, MUTED),
                    lambda v: self._set_prog(v))

            if workers == 1:
                for i, f in enumerate(self.files):
                    self._sp_log(f"\n[{i+1}/{total}] {Path(f).name}\n", ACCENT2)
                    self.sp_status.config(text=f"[{i+1}/{total}] {Path(f).name}")
                    self._set_prog(0)
                    try:
                        out = do_one(f)
                        self._sp_log(f"  ✓ {Path(out).name}\n", SUCCESS)
                        ok += 1
                    except Exception as e:
                        self._sp_log(f"  ✗ {e}\n", ERROR)
                        errs.append((Path(f).name, str(e)))
            else:
                with ThreadPoolExecutor(max_workers=workers) as ex:
                    futs = {ex.submit(do_one, f): f for f in self.files}
                    for fut in as_completed(futs):
                        fname = Path(futs[fut]).name
                        try:
                            out = fut.result()
                            self._sp_log(f"  ✓ {Path(out).name}\n", SUCCESS)
                            ok += 1
                        except Exception as e:
                            self._sp_log(f"  ✗ {fname}: {e}\n", ERROR)
                            errs.append((fname, str(e)))
                        done[0] += 1
                        self._set_prog(int(done[0]/total*100))
                        self.sp_status.config(text=f"Xong {done[0]}/{total}...")

            self._sp_log(f"\n✓ Thành công: {ok}/{total}\n", SUCCESS)
            if errs:
                for n, e in errs: self._sp_log(f"✗ {n}: {e}\n", ERROR)
            self.sp_status.config(text=f"Hoàn tất! {ok}/{total} file")
            self._set_prog(100 if not errs else 60)
        except Exception as e:
            self._sp_log(f"\n✗ Lỗi: {e}\n", ERROR)
        finally:
            self.btn_run.config(state="normal", text="▶  BẮT ĐẦU TÁCH")

    def _run_all(self):
        from concurrent.futures import ThreadPoolExecutor, as_completed
        try:
            self._log("\n─────────────────────────────\n")
            if not self.files:
                self._log("⚠ Không có file nào!\n", GOLD)
                return
            mode_name  = self.mode_var.get()
            other_name = self.other_var.get()
            mode_cfg   = MODES[mode_name]
            other_mode = OTHER_OPTIONS[other_name]
            workers    = self.workers_var.get()
            self._log(f"Chế độ : {mode_name}\n", ACCENT2)
            self._log(f"Other  : {other_name}\n", ACCENT2)
            self._log(f"Workers: {workers} luồng song song\n", ACCENT2)
            self._log(f"TimeStr: {self.ts_var.get()}\n", ACCENT2)
            ensure_deps(lambda m: self._log(m, MUTED))
            ok, errs = 0, []
            total = len(self.files)
            done_count = [0]  # dùng list để mutate trong closure

            def process_one(args):
                idx, f = args
                src = Path(f)
                pv  = self.out_var.get()
                out_dir = (src.parent/"tach_nhac_nen_output") \
                          if pv=="(cùng thư mục với file gốc)" else Path(pv)
                out_dir.mkdir(parents=True, exist_ok=True)
                self.last_output = str(out_dir)
                self._log(f"\n[{idx}/{total}] {src.name}\n", ACCENT2)
                results = run_demucs(src, out_dir, mode_name, mode_cfg, other_mode,
                                     lambda m: self._log(m, MUTED),
                                     lambda v: None)  # progress per-file disabled khi parallel
                return src.name, results, None

            if workers == 1:
                # Sequential — hiện progress bar đầy đủ
                for i, f in enumerate(self.files):
                    src = Path(f)
                    pv  = self.out_var.get()
                    out_dir = (src.parent/"tach_nhac_nen_output") \
                              if pv=="(cùng thư mục với file gốc)" else Path(pv)
                    out_dir.mkdir(parents=True, exist_ok=True)
                    self.last_output = str(out_dir)
                    self._log(f"\n[{i+1}/{total}] {src.name}\n", ACCENT2)
                    self.lbl_status.config(text=f"[{i+1}/{total}] {src.name}")
                    self._set_prog(0)
                    try:
                        results = run_demucs(src, out_dir, mode_name, mode_cfg, other_mode, self.ts_var.get(),
                                             lambda m: self._log(m, MUTED), self._set_prog)
                        for r in results:
                            self._log(f"  ✓ {Path(r).name}\n", SUCCESS)
                        ok += 1
                    except Exception as e:
                        self._log(f"  ✗ {e}\n", ERROR)
                        errs.append((src.name, str(e)))
                    self._set_prog(int((i+1)/total*100))
            else:
                # Parallel
                self.lbl_status.config(text=f"Xử lý song song {workers} luồng...")
                with ThreadPoolExecutor(max_workers=workers) as ex:
                    futures = {ex.submit(process_one, (i+1, f)): f
                               for i,f in enumerate(self.files)}
                    for fut in as_completed(futures):
                        try:
                            name, results, _ = fut.result()
                            for r in results:
                                self._log(f"  ✓ {Path(r).name}\n", SUCCESS)
                            ok += 1
                        except Exception as e:
                            fname = Path(futures[fut]).name
                            self._log(f"  ✗ {fname}: {e}\n", ERROR)
                            errs.append((fname, str(e)))
                        done_count[0] += 1
                        self._set_prog(int(done_count[0]/total*100))
                        self.lbl_status.config(text=f"Xong {done_count[0]}/{total}...")

            self._log(f"\n─────────────────────────────\n")
            self._log(f"✓ Thành công: {ok}/{total}\n", SUCCESS)
            if errs:
                for n,e in errs: self._log(f"✗ {n}: {e}\n", ERROR)
            self.lbl_status.config(text=f"Hoàn tất! {ok}/{total} file")
            self._set_prog(100 if not errs else 60)
        except Exception as e:
            self._log(f"\n✗ Lỗi: {e}\n", ERROR)
            self.lbl_status.config(text="Lỗi!")
        finally:
            self.btn_run.config(state="normal", text="▶  BẮT ĐẦU TÁCH")
            if hasattr(self, 'sp_btn_run'):
                self.sp_btn_run.config(state="normal", text="▶  BẮT ĐẦU TÁCH")

if __name__ == "__main__":
    try:
        app = App()
        app.mainloop()
    except Exception as e:
        import traceback
        try:
            import tkinter.messagebox as mb
            mb.showerror("Lỗi khởi động", f"{e}\n\n{traceback.format_exc()[-500:]}")
        except Exception:
            print("CRASH:", traceback.format_exc())
        input("Nhấn Enter để thoát...")
