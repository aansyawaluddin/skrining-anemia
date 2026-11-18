"""
Skrining Risiko Anemia Mahasiswa — versi Streamlit
Data disimpan lewat Google Apps Script (Code.gs) ke Google Sheets.

Secrets (.streamlit/secrets.toml atau menu Secrets di Streamlit Cloud):
    API_URL = "https://script.google.com/macros/s/XXXX/exec"
    API_KEY = "kunci-yang-sama-dengan-API_KEY-di-Code.gs"
Tanpa secrets, aplikasi jalan dalam mode uji lokal (jawaban tidak disimpan).
"""
import base64
import html
import re
import random
import string
from datetime import datetime, timedelta
from urllib.parse import quote
from zoneinfo import ZoneInfo

import requests
import streamlit as st
import streamlit.components.v1 as components  # dipakai hanya bila st.iframe belum ada

st.set_page_config(page_title="Skrining Risiko Anemia Mahasiswa", page_icon="🩺", layout="wide")

TZ = ZoneInfo("Asia/Makassar")

# =========================================================
# 1. INSTRUMEN (sesuai Kuesioner Skrining Risiko Anemia)
# =========================================================
YT = ["Ya", "Tidak"]
FREQ = ["Setiap hari", "3–5 kali per minggu", "1–2 kali per minggu", "Jarang atau tidak pernah"]


def _perempuan(a):
    return a.get("jk") == "Perempuan"


SECTIONS = [
    {
        "id": "data", "title": "Data Responden",
        "hint": "Data ini dijaga kerahasiaannya dan hanya dipakai untuk keperluan penelitian.",
        "q": [
            {"id": "nama", "text": "Nama", "type": "text"},
            {"id": "nim", "text": "NIM", "type": "text"},
            {"id": "prodi", "text": "Program studi", "type": "text"},
            {"id": "semester", "text": "Semester", "type": "number", "min": 1, "max": 14},
            {"id": "usia", "text": "Usia (tahun)", "type": "number", "min": 15, "max": 60},
            {"id": "jk", "text": "Jenis kelamin", "type": "choice", "options": ["Laki-laki", "Perempuan"]},
            {"id": "tb", "text": "Tinggi badan (cm)", "type": "number", "min": 100.0, "max": 220.0, "step": 0.5},
            {"id": "bb", "text": "Berat badan (kg)", "type": "number", "min": 25.0, "max": 200.0, "step": 0.5},
            {"id": "hamil", "no": 4, "text": "Apakah kamu sedang hamil?", "type": "choice", "options": YT, "show": _perempuan},
        ],
    },
    {
        "id": "gejala", "title": "Gejala dalam 1 Bulan Terakhir",
        "hint": "Dalam 1 bulan terakhir, apakah kamu mengalami hal berikut?",
        "q": [
            {"id": "q5", "no": 5, "text": "Mudah lelah, lemas, atau lesu", "score": {"Ya": 1}, "factor": "Mudah lelah, lemas, atau lesu"},
            {"id": "q6", "no": 6, "text": "Sering pusing atau sakit kepala", "score": {"Ya": 1}, "factor": "Sering pusing atau sakit kepala"},
            {"id": "q7", "no": 7, "text": "Mata berkunang-kunang saat berdiri dari posisi duduk atau jongkok", "score": {"Ya": 1}, "factor": "Mata berkunang-kunang saat berdiri"},
            {"id": "q8", "no": 8, "text": "Sulit berkonsentrasi", "score": {"Ya": 1}, "factor": "Sulit berkonsentrasi"},
            {"id": "q9", "no": 9, "text": "Wajah, bibir, kelopak mata bagian dalam, atau telapak tangan tampak pucat", "score": {"Ya": 2}, "factor": "Tampak pucat"},
            {"id": "q10", "no": 10, "text": "Jantung berdebar atau mudah sesak saat aktivitas ringan", "score": {"Ya": 2}, "factor": "Jantung berdebar atau mudah sesak"},
            {"id": "q11", "no": 11, "text": "Kuku rapuh, atau berbentuk cekung seperti sendok", "score": {"Ya": 1}, "factor": "Kuku rapuh atau cekung"},
            {"id": "q12", "no": 12, "text": "Sering mengantuk di kelas atau saat belajar", "score": {"Ya": 1}, "factor": "Sering mengantuk saat belajar"},
            {"id": "q13", "no": 13, "text": "Tangan dan kaki sering dingin", "score": {"Ya": 1}, "factor": "Tangan dan kaki sering dingin"},
        ],
    },
    {
        "id": "haid", "title": "Riwayat Menstruasi", "show": lambda a: a.get("jk") != "Laki-laki",
        "hint": "Bagian ini khusus untuk responden perempuan.",
        "q": [
            {"id": "q14", "no": 14, "text": "Apakah siklus haid kamu teratur?", "score": {"Tidak": 1}, "factor": "Siklus haid tidak teratur"},
            {"id": "q15", "no": 15, "text": "Berapa lama haid biasanya berlangsung?", "options": ["≤ 7 hari", "> 7 hari"], "score": {"> 7 hari": 1}, "factor": "Haid berlangsung lebih dari 7 hari"},
            {"id": "q16", "no": 16, "text": "Apakah darah haid banyak, misalnya ganti pembalut lebih dari 3 kali per hari atau ada gumpalan besar?", "score": {"Ya": 2}, "factor": "Darah haid banyak"},
        ],
    },
    {
        "id": "makan", "title": "Pola Makan dan Gaya Hidup",
        "q": [
            {"id": "q17", "no": 17, "text": "Seberapa sering kamu makan makanan sumber zat besi hewani (daging, hati, ikan, telur)?", "options": FREQ,
             "score": {"1–2 kali per minggu": 1, "Jarang atau tidak pernah": 2}, "factor": "Jarang makan sumber zat besi hewani", "changeable": True},
            {"id": "q18", "no": 18, "text": "Seberapa sering kamu makan sayuran hijau (bayam, kangkung, daun kelor)?", "options": FREQ,
             "score": {"1–2 kali per minggu": 1, "Jarang atau tidak pernah": 1}, "factor": "Jarang makan sayuran hijau", "changeable": True},
            {"id": "q19", "no": 19, "text": "Seberapa sering kamu makan buah sumber vitamin C (jeruk, jambu, pepaya, dll.)?", "options": FREQ,
             "score": {"1–2 kali per minggu": 1, "Jarang atau tidak pernah": 1}, "factor": "Jarang makan buah sumber vitamin C", "changeable": True},
            {"id": "q20", "no": 20, "text": "Apakah kamu sering minum teh atau kopi bersamaan atau tepat setelah makan?", "score": {"Ya": 1}, "factor": "Minum teh/kopi bersamaan dengan makan", "changeable": True},
            {"id": "q21", "no": 21, "text": "Apakah kamu menjalani diet ketat, vegetarian/vegan, atau sering melewatkan makan?", "score": {"Ya": 1}, "factor": "Diet ketat, vegetarian/vegan, atau sering melewatkan makan", "changeable": True},
            {"id": "q22", "no": 22, "text": "Berapa kali kamu makan utama per hari?", "options": ["3 kali atau lebih", "2 kali", "1 kali"],
             "score": {"1 kali": 1}, "factor": "Makan utama hanya 1 kali sehari", "changeable": True},
        ],
    },
    {
        "id": "ttd", "title": "Tablet Tambah Darah (TTD) dan Pemeriksaan Hb",
        "q": [
            # Skor gabungan no. 23–24: 1 poin bila tidak pernah minum TTD atau minum tetapi tidak rutin
            {"id": "q23", "no": 23, "text": "Apakah kamu pernah mendapat atau mengonsumsi Tablet Tambah Darah (TTD)?",
             "score": lambda a: 1 if (a.get("q23") == "Tidak" or a.get("q24") != "Ya, rutin") else 0,
             "factor": lambda a: "Belum pernah minum TTD" if a.get("q23") == "Tidak" else "Minum TTD tidak rutin", "changeable": True},
            {"id": "q24", "no": 24, "text": "Apakah TTD dikonsumsi rutin 1 tablet per minggu?", "options": ["Ya, rutin", "Kadang-kadang", "Tidak"],
             "show": lambda a: a.get("q23") == "Ya"},
            {"id": "q25", "no": 25, "text": "Apakah kamu pernah diperiksa kadar Hb sebelumnya? Bagaimana hasilnya?",
             "options": ["Belum pernah", "Normal", "Anemia", "Tidak tahu hasilnya"], "score": {"Anemia": 2}, "factor": "Hasil Hb sebelumnya anemia"},
            {"id": "q25_kapan", "text": "Kapan terakhir diperiksa? (misalnya: Maret 2026)", "type": "text", "optional": True,
             "show": lambda a: bool(a.get("q25")) and a.get("q25") != "Belum pernah"},
        ],
    },
    {
        "id": "riwayat", "title": "Riwayat Kesehatan dan Faktor Risiko",
        "q": [
            {"id": "q26", "no": 26, "text": "Apakah kamu pernah didiagnosis anemia, talasemia, atau penyakit darah lain?", "score": {"Ya": 3}, "factor": "Riwayat anemia, talasemia, atau penyakit darah"},
            {"id": "q27", "no": 27, "text": "Apakah ada anggota keluarga dengan anemia atau talasemia?", "score": {"Ya": 1}, "factor": "Keluarga dengan anemia atau talasemia"},
            {"id": "q28", "no": 28, "text": "Apakah kamu sedang atau pernah menderita penyakit kronis, infeksi cacing, malaria, atau gangguan pencernaan (misalnya maag kronis atau BAB hitam)?", "score": {"Ya": 1}, "factor": "Penyakit kronis, cacingan, malaria, atau gangguan pencernaan"},
            {"id": "q29", "no": 29, "text": "Apakah kamu sering mengalami perdarahan, seperti mimisan atau gusi berdarah?", "score": {"Ya": 1}, "factor": "Sering mengalami perdarahan"},
            {"id": "q30", "no": 30, "text": "Apakah kamu rutin berolahraga berat atau seorang atlet?"},  # tidak diberi skor
        ],
    },
]

SKOR_MAKS = {"Perempuan": 31, "Laki-laki": 27}


def tampil(item, a):
    return item.get("show") is None or bool(item["show"](a))


# =========================================================
# 2. SKORING
# =========================================================
def hitung_hasil(a):
    total = 0
    faktor = []
    for sec in SECTIONS:
        if not tampil(sec, a):
            continue
        for q in sec["q"]:
            if "score" not in q or not tampil(q, a):
                continue
            sc = q["score"]
            poin = sc(a) if callable(sc) else sc.get(a.get(q["id"]), 0)
            if poin > 0:
                total += poin
                fc = q["factor"]
                faktor.append({"label": fc(a) if callable(fc) else fc, "poin": poin, "bisa_diubah": bool(q.get("changeable"))})

    maks = SKOR_MAKS[a["jk"]]
    persen = round(total / maks * 1000) / 10
    level = "tinggi" if persen >= 40 else "sedang" if persen >= 20 else "rendah"

    # Aturan khusus (override): langsung "Berisiko", berapa pun skornya
    override = []
    if a.get("q26") == "Ya":
        override.append("Riwayat anemia/talasemia/penyakit darah")
    if a.get("q25") == "Anemia":
        override.append("Hasil Hb sebelumnya anemia")
    if a.get("hamil") == "Ya":
        override.append("Sedang hamil")
    segera = a.get("q9") == "Ya" and a.get("q10") == "Ya"
    if segera:
        override.append("Pucat disertai berdebar/sesak")
    if override and level == "rendah":
        level = "sedang"

    return {"total": total, "maks": maks, "persen": persen, "level": level, "kategori": TEKS[level]["label"],
            "override": override, "segera": segera, "faktor": faktor}


# =========================================================
# 3. TEKS HASIL, FASKES, PENGINGAT
# =========================================================
TEKS = {
    "rendah": {
        "label": "TIDAK BERISIKO",
        "judul": "Hasil skrining kamu baik 🌱",
        "isi": ["Dari jawabanmu, risiko anemia kamu saat ini tergolong rendah. Pertahankan kebiasaan baik ya: makan teratur, cukup lauk sumber zat besi seperti daging, ikan, telur, dan sayuran hijau, ditambah buah yang kaya vitamin C. Sebaiknya hindari minum teh atau kopi bersamaan dengan makan."],
        "langkah": ["Pertahankan pola makan gizi seimbang.", "Skrining ulang dalam 6–12 bulan, atau lebih cepat kalau kamu mulai sering lelah atau pusing."],
        "tombol": ["tips", "selesai"],
    },
    "sedang": {
        "label": "BERISIKO SEDANG",
        "judul": "Ada beberapa hal yang perlu diperhatikan",
        "isi": ["Dari jawabanmu, ada beberapa tanda dan kebiasaan yang bisa meningkatkan risiko anemia. Ini bukan berarti kamu pasti anemia. Cara paling pasti untuk mengetahuinya adalah pemeriksaan kadar hemoglobin (Hb) yang mudah dan cepat."],
        "langkah": ["Periksa Hb di Puskesmas, klinik kampus, atau laboratorium dalam waktu dekat.", "Perbaiki pola makan dengan lebih banyak sumber zat besi dan vitamin C.", "Minum Tablet Tambah Darah (TTD) sesuai anjuran petugas kesehatan."],
        "tombol": ["faskes", "tips", "selesai"],
    },
    "tinggi": {
        "label": "BERISIKO TINGGI",
        "judul": "Yuk, periksakan kondisimu",
        "isi": ["Dari jawabanmu, cukup banyak tanda yang perlu dicek lebih lanjut. Ini bukan diagnosis, tetapi sebaiknya kamu memeriksakan kadar Hb dan berkonsultasi dengan tenaga kesehatan dalam waktu dekat. Kalau ternyata memang anemia, penyebabnya bisa berbeda-beda dan umumnya bisa ditangani dengan baik bila diketahui sejak awal.",
                "Mohon jangan mengonsumsi suplemen zat besi dosis tinggi sendiri sebelum diperiksa, karena dosis dan jenisnya perlu disesuaikan dengan hasil pemeriksaan."],
        "langkah": ["Periksa kadar Hb dalam waktu dekat di Puskesmas, klinik kampus, atau laboratorium.", "Konsultasikan hasilnya dengan dokter atau tenaga kesehatan."],
        "tombol": ["faskes", "selesai"],
    },
}
WARNA = {"rendah": "#1E9E6A", "sedang": "#D99A00", "tinggi": "#C2410C"}
IKON = {"BERISIKO TINGGI": "🔴", "BERISIKO SEDANG": "🟠", "TIDAK BERISIKO": "🟢"}

PESAN_OVERRIDE = {
    "riwayat": "Karena kamu punya riwayat anemia, talasemia, atau hasil Hb sebelumnya anemia, kami sarankan rutin berkonsultasi dengan tenaga kesehatan untuk pemantauan. Penanganannya bisa berbeda tiap orang, jadi ikuti arahan dokter ya.",
    "hamil": "Selama kehamilan, kebutuhan zat besi dan batas Hb berbeda. Kami sarankan memeriksakan diri ke bidan, dokter, atau layanan pemeriksaan kehamilan (ANC) agar mendapat penanganan yang tepat.",
    "segera": "Kamu menyebutkan wajah tampak pucat disertai jantung berdebar atau sesak. Sebaiknya segera periksa ke fasilitas kesehatan, tanpa menunggu jadwal skrining berikutnya.",
}

# Kontak layanan kesehatan Kota Makassar (data Nov 2026; cek ulang sebelum dipakai)
URL_FASKES = "https://www.google.com/maps/search/?api=1&query=puskesmas+terdekat"
FASKES = [
    {"nama": "RS Universitas Hasanuddin", "jenis": "Rumah sakit · IGD 24 jam", "alamat": "Jl. Perintis Kemerdekaan Km. 10, Tamalanrea, Makassar 90245", "telp": "(0411) 591331"},
    {"nama": "RSUP Dr. Wahidin Sudirohusodo", "jenis": "Rumah sakit rujukan · IGD 24 jam", "alamat": "Jl. Perintis Kemerdekaan Km. 11, Tamalanrea, Makassar", "telp": "(0411) 584677"},
    {"nama": "RSUP Dr. Tadjuddin Chalid", "jenis": "Rumah sakit", "alamat": "Jl. Paccerakkang No. 67, Daya, Makassar 90241", "telp": "(0411) 512902"},
    {"nama": "RSUD Daya Makassar", "jenis": "Rumah sakit daerah", "alamat": "Jl. Perintis Kemerdekaan Km. 14, Biringkanaya, Makassar", "telp": ""},
    {"nama": "Puskesmas Tamalanrea", "jenis": "Puskesmas", "alamat": "Perumahan BTP Blok B No. 311, Jl. Kesejahteraan Timur I, Tamalanrea, Makassar", "telp": ""},
    {"nama": "Puskesmas Kapasa", "jenis": "Puskesmas", "alamat": "Kompleks BTN TNI AL, Kapasa, Tamalanrea, Makassar", "telp": ""},
]

PENGINGAT = {
    "rendah": [{"label": "Ingatkan skrining ulang (6 bulan lagi)", "judul": "Skrining ulang risiko anemia", "hari": 182}],
    "sedang": [{"label": "Ingatkan periksa Hb (2 minggu lagi)", "judul": "Periksa kadar Hb di Puskesmas/klinik", "hari": 14},
               {"label": "Ingatkan skrining ulang (6 bulan lagi)", "judul": "Skrining ulang risiko anemia", "hari": 182}],
    "tinggi": [{"label": "Ingatkan periksa Hb (3 hari lagi)", "judul": "Periksa kadar Hb dan konsultasi ke tenaga kesehatan", "hari": 3},
               {"label": "Ingatkan skrining ulang (6 bulan lagi)", "judul": "Skrining ulang risiko anemia", "hari": 182}],
}


def link_kalender(judul, hari, detail):
    mulai = datetime.now(TZ) + timedelta(days=hari)
    akhir = mulai + timedelta(days=1)
    f = lambda d: d.strftime("%Y%m%d")
    return ("https://calendar.google.com/calendar/render?action=TEMPLATE&text=" + quote(judul)
            + "&dates=" + f(mulai) + "/" + f(akhir) + "&details=" + quote(detail))


# =========================================================
# 4. STATE, API, UTILITAS
# =========================================================
ss = st.session_state


def reset_state():
    ss.page = "home"
    ss.step = 0
    ss.a = {}
    ss.consent = False
    ss.hasil = None
    ss.payload = None
    ss.simpan = ""
    ss.galat = ""
    ss.errors = {}
    ss.asal = ""
    ss.lihat = None
    ss.rw = {"kode": "", "status": "", "data": None, "pesan": ""}


if "page" not in ss:
    reset_state()
    ss.kode_terakhir = ""
    ss.scroll = False


def ke(page, **kw):
    """Pindah halaman lalu render ulang."""
    ss.page = page
    for k, v in kw.items():
        setattr(ss, k, v)
    ss.scroll = True
    st.rerun()


def rahasia(nama):
    try:
        return st.secrets[nama]
    except Exception:
        return ""


def api(aksi, **kw):
    """Panggil Apps Script. Mengembalikan None bila secrets belum diisi (mode uji lokal)."""
    url, kunci = rahasia("API_URL"), rahasia("API_KEY")
    if not url:
        return None
    r = requests.post(url, json={"key": kunci, "action": aksi, **kw}, timeout=30)
    r.raise_for_status()
    try:
        res = r.json()
    except ValueError:
        raise RuntimeError("Server tidak mengembalikan JSON. Pastikan Code.gs sudah dipasang sebagai versi baru.")
    if not res.get("ok"):
        raise RuntimeError(res.get("error", "Permintaan gagal."))
    return res


def buat_kode():
    d = datetime.now(TZ)
    acak = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"ANM-{d:%y%m%d}-{acak}"


def fmt(n):
    s = f"{n:.1f}".rstrip("0").rstrip(".")
    return s.replace(".", ",")


# =========================================================
# 5. TAMPILAN: CSS, ILUSTRASI, KOMPONEN
# =========================================================
GAYA = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap');
:root{--teal:#0E7C86;--teal2:#14A3A8;--ink:#17323A;--muted:#5E7378;--line:#DCEBEC;--soft:#EEF7F7;}
html,body,.stApp,button,input,textarea,select,p,li,label,h1,h2,h3,h4,h5,h6,[data-testid="stMarkdownContainer"],[data-testid="stMarkdownContainer"] *,[data-testid="stMetricValue"],[data-testid="stMetricLabel"]{font-family:'Plus Jakarta Sans',system-ui,-apple-system,'Segoe UI',sans-serif !important;}
.stApp{background:radial-gradient(900px 520px at 0% -10%,#DDF2F1 0,transparent 60%),radial-gradient(760px 460px at 100% 0%,#FDE9E9 0,transparent 60%),#F6FAFA;}
[data-testid="stHeader"]{background:transparent;}
#MainMenu,footer{visibility:hidden;}
[data-testid="stElementContainer"]:has(style){display:none;}
.panel-brand{display:flex;align-items:center;gap:10px;margin-bottom:14px;position:relative;}
.panel-brand img{width:38px;height:38px;border-radius:11px;box-shadow:0 4px 12px rgba(0,0,0,.15);}
.panel-brand b{font-size:1rem;}
.panel-brand span{display:block;font-size:.72rem;opacity:.8;}
.block-container,[data-testid="stMainBlockContainer"]{max-width:1080px;padding-top:4.5rem !important;padding-bottom:1.5rem !important;}
h1,h2,h3{color:var(--ink);letter-spacing:-.02em;}
.brand{display:flex;align-items:center;gap:12px;background:rgba(255,255,255,.85);backdrop-filter:blur(6px);border:1px solid var(--line);border-radius:18px;padding:10px 14px;box-shadow:0 6px 20px rgba(14,124,134,.06);margin-bottom:22px;}
.brand img{width:42px;height:42px;border-radius:12px;}
.brand-nama{font-weight:800;color:var(--ink);line-height:1.15;}
.brand-sub{font-size:.75rem;color:var(--muted);}
.brand-hal{margin-left:auto;background:var(--soft);color:var(--teal);font-weight:700;font-size:.8rem;padding:6px 12px;border-radius:999px;white-space:nowrap;}
.panel{position:relative;overflow:hidden;background:linear-gradient(150deg,#0B6E77 0%,#14A3A8 100%);border-radius:28px;padding:34px 30px 6px;color:#fff;box-shadow:0 20px 45px rgba(14,124,134,.25);}
.panel:before{content:"";position:absolute;width:280px;height:280px;border-radius:50%;background:rgba(255,255,255,.08);top:-110px;right:-90px;}
.panel-label{display:inline-block;background:rgba(255,255,255,.18);padding:5px 12px;border-radius:999px;font-size:.72rem;font-weight:700;letter-spacing:.08em;text-transform:uppercase;}
.panel-judul{font-size:2.05rem;font-weight:800;line-height:1.15;margin:14px 0 10px;letter-spacing:-.02em;}
.panel-isi{opacity:.92;font-size:.98rem;line-height:1.65;}
.chips{display:flex;flex-wrap:wrap;gap:8px;margin-top:16px;}
.chip{background:rgba(255,255,255,.16);border:1px solid rgba(255,255,255,.28);padding:6px 12px;border-radius:999px;font-size:.82rem;font-weight:600;}
.panel-img{display:block;width:100%;max-width:380px;margin:10px auto 0;}
.banner{display:flex;align-items:center;gap:18px;background:linear-gradient(150deg,#0B6E77 0%,#14A3A8 100%);color:#fff;border-radius:24px;padding:22px 26px;margin-bottom:18px;box-shadow:0 16px 36px rgba(14,124,134,.22);}
.banner-ikon{font-size:2.4rem;background:rgba(255,255,255,.16);width:68px;height:68px;border-radius:20px;display:grid;place-items:center;flex-shrink:0;}
.banner-judul{font-size:1.45rem;font-weight:800;line-height:1.2;}
.banner-isi{opacity:.92;font-size:.92rem;margin-top:4px;}
[class*="st-key-kartu"]{background:#fff;border:1px solid var(--line) !important;border-radius:22px !important;box-shadow:0 10px 30px rgba(23,50,58,.06);padding:22px !important;}
.judul-kartu{font-size:1.35rem;font-weight:800;color:var(--ink);line-height:1.25;}
.sub-kartu{color:var(--muted);font-size:.92rem;margin-top:4px;line-height:1.55;}
.judul-bagian{font-size:1.08rem;font-weight:800;color:var(--ink);display:flex;align-items:center;gap:10px;}
.judul-bagian .ik{width:34px;height:34px;border-radius:10px;background:var(--soft);display:grid;place-items:center;font-size:1.05rem;}
.pemisah{display:flex;align-items:center;gap:10px;color:var(--muted);font-size:.8rem;margin:2px 0;}
.pemisah:before,.pemisah:after{content:"";flex:1;height:1px;background:var(--line);}
.stButton button,.stFormSubmitButton button,.stDownloadButton button,.stLinkButton a{border-radius:14px !important;min-height:48px;font-weight:700 !important;transition:transform .15s ease,box-shadow .15s ease;}
.stButton button:hover,.stFormSubmitButton button:hover,.stDownloadButton button:hover,.stLinkButton a:hover{transform:translateY(-1px);box-shadow:0 8px 20px rgba(14,124,134,.18);}
[data-testid="stBaseButton-primary"],[data-testid="stBaseButton-primaryFormSubmit"],[data-testid="stBaseLinkButton-primary"]{background:linear-gradient(135deg,#0E7C86,#14A3A8) !important;border:none !important;color:#fff !important;}
[data-testid="stBaseButton-secondary"],[data-testid="stBaseButton-secondaryFormSubmit"],[data-testid="stBaseLinkButton-secondary"]{background:#fff !important;border:1.5px solid var(--line) !important;color:var(--ink) !important;}
.stButton button:disabled{opacity:.45;transform:none;box-shadow:none;}
[class*="st-key-rwitem"] button{justify-content:flex-start;text-align:left;padding:14px 16px;}
[data-baseweb="input"],[data-baseweb="base-input"],[data-baseweb="select"]>div{border-radius:12px !important;}
[data-testid="stWidgetLabel"] p{font-weight:600;color:var(--ink);font-size:.98rem;line-height:1.5;}
div[role="radiogroup"]{gap:8px;align-items:stretch;width:100%;}
div[role="radiogroup"]>div{flex:1 1 auto;background:#fff;border:1.5px solid var(--line);border-radius:12px;transition:all .15s;}
div[role="radiogroup"]>div:hover{border-color:#9FD3D3;}
div[role="radiogroup"]>div:has(input:checked){border-color:var(--teal);background:#E8F6F6;box-shadow:0 0 0 3px rgba(14,124,134,.12);}
div[role="radiogroup"] [data-testid="stRadioOption"]{width:100%;padding:10px 14px;margin:0;cursor:pointer;}
[data-testid="stExpander"] details{border-radius:14px !important;border:1px solid var(--line) !important;background:#FAFDFD;}
[data-testid="stExpander"] summary p{font-weight:700;color:var(--ink);}
[data-testid="stMetric"]{background:#fff;border:1px solid var(--line);border-radius:18px;padding:16px 18px;box-shadow:0 6px 18px rgba(23,50,58,.05);}
[data-testid="stMetricValue"]{font-weight:800;color:var(--ink);}
.langkah-step{display:flex;gap:6px;margin:12px 0 4px;}
.langkah-step span{flex:1;height:8px;border-radius:99px;background:#DCEBEC;}
.langkah-step span.ok{background:#7CC8C8;}
.langkah-step span.kini{background:linear-gradient(90deg,#0E7C86,#14A3A8);}
.form-kepala{display:flex;align-items:center;gap:14px;}
.form-kepala .ik{width:54px;height:54px;border-radius:16px;background:linear-gradient(140deg,#E8F6F6,#D3EEEE);display:grid;place-items:center;font-size:1.6rem;flex-shrink:0;}
.form-kecil{font-size:.78rem;font-weight:700;color:var(--teal);letter-spacing:.06em;text-transform:uppercase;}
.hero{display:flex;align-items:center;gap:22px;flex-wrap:wrap;border-radius:26px;padding:24px 28px;color:#fff;box-shadow:0 18px 40px rgba(23,50,58,.18);margin-bottom:14px;}
.hero img{width:132px;height:132px;}
.hero-label{font-size:.75rem;font-weight:700;letter-spacing:.08em;text-transform:uppercase;opacity:.9;}
.hero-kat{font-size:1.8rem;font-weight:800;line-height:1.15;margin:4px 0;}
.hero-skor{font-size:1rem;opacity:.95;}
.hero-waktu{font-size:.85rem;opacity:.85;margin-top:2px;}
.fchip{display:inline-block;padding:7px 12px;border-radius:999px;margin:0 6px 8px 0;font-size:.85rem;font-weight:600;}
.fchip.ubah{background:#E8F6F6;color:#0B6E77;border:1px solid #BFE3E3;}
.fchip.lain{background:#FFF1F0;color:#B42318;border:1px solid #FBD0CC;}
.kecil{font-size:.78rem;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;margin:10px 0 6px;}
.langkah{display:flex;gap:12px;align-items:flex-start;margin:10px 0;color:var(--ink);line-height:1.5;}
.langkah b{width:28px;height:28px;border-radius:50%;background:linear-gradient(135deg,#0E7C86,#14A3A8);color:#fff;display:grid;place-items:center;font-size:.85rem;flex-shrink:0;}
.tiket{border:2px dashed #9FD3D3;background:#F2FAFA;border-radius:18px;padding:16px 18px;color:var(--ink);line-height:1.55;}
.kode{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:1.35rem;font-weight:800;color:var(--teal);letter-spacing:.06em;}
.darurat{background:linear-gradient(135deg,#FFF1F0,#FFE4E1);border:1px solid #FBD0CC;color:#912018;border-radius:18px;padding:14px 18px;margin-bottom:16px;line-height:1.55;}
.darurat a{color:#B42318;font-weight:800;}
.faskes-kepala{display:flex;gap:12px;align-items:flex-start;}
.faskes-kepala .ik{width:46px;height:46px;border-radius:14px;background:#FFF1F0;display:grid;place-items:center;font-size:1.4rem;flex-shrink:0;}
.badge{display:inline-block;background:var(--soft);color:var(--teal);font-size:.75rem;font-weight:700;padding:3px 10px;border-radius:999px;margin-top:4px;}
.alamat{color:var(--muted);font-size:.9rem;margin:10px 0 4px;line-height:1.5;}
.alamat a{color:var(--teal);font-weight:700;text-decoration:none;}
.tips-kepala{display:flex;gap:12px;align-items:center;margin-bottom:6px;}
.tips-kepala .ik{width:48px;height:48px;border-radius:14px;display:grid;place-items:center;font-size:1.5rem;flex-shrink:0;}
.tips-isi li{margin:6px 0;color:var(--ink);line-height:1.55;}
.kaki{text-align:center;font-size:.78rem;color:var(--muted);margin-top:2.2rem;padding-top:1rem;border-top:1px solid var(--line);}
@media (max-width:640px){
.panel{padding:26px 20px 4px;border-radius:22px;}
.panel-judul{font-size:1.6rem;}
.brand-hal{display:none;}
[class*="st-key-kartu"]{padding:16px !important;}
.hero{padding:20px;justify-content:center;text-align:center;}
.banner{padding:18px;}
.banner-judul{font-size:1.2rem;}
}
</style>
"""


def htm(s):
    """Tampilkan HTML sebagai satu blok (baris baru dihapus agar tidak diproses sebagai Markdown)."""
    st.markdown(re.sub(r"\s*\n\s*", " ", s.strip()), unsafe_allow_html=True)


def svg_uri(svg):
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode()


def _sel(x, y, s=1.0):
    """Satu sel darah merah."""
    return (f"<g transform='translate({x} {y}) scale({s})'><ellipse rx='26' ry='20' fill='url(#rbc)'/>"
            f"<ellipse rx='11' ry='8' fill='#A3162A' opacity='.45'/></g>")


def _kilau(x, y):
    return (f"<path d='M{x} {y - 8}v16M{x - 8} {y}h16' stroke='#fff' stroke-width='3' "
            f"stroke-linecap='round' opacity='.75'/>")


_SVG = ("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 400 300'><defs>"
        "<linearGradient id='tetes' x1='0' y1='0' x2='0' y2='1'><stop offset='0' stop-color='#FF8A8A'/>"
        "<stop offset='1' stop-color='#D62F3C'/></linearGradient>"
        "<radialGradient id='rbc'><stop offset='0' stop-color='#C81E32'/><stop offset='.6' stop-color='#EF5350'/>"
        "<stop offset='1' stop-color='#FF8A80'/></radialGradient></defs>")
_LATAR = "<circle cx='200' cy='160' r='135' fill='#fff' opacity='.08'/><circle cx='200' cy='160' r='98' fill='#fff' opacity='.1'/>"

ILUS = {
    "home": _SVG + _LATAR
    + "<path d='M200 40C200 40 128 125 128 175a72 72 0 0 0 144 0C272 125 200 40 200 40Z' fill='url(#tetes)'/>"
    + "<path d='M166 155c-9 20-8 42 6 58' stroke='#fff' stroke-width='8' stroke-linecap='round' fill='none' opacity='.55'/>"
    + "<polyline points='146,185 172,185 184,162 198,212 212,172 222,185 254,185' stroke='#fff' stroke-width='6' "
      "stroke-linecap='round' stroke-linejoin='round' fill='none'/>"
    + _sel(72, 85) + _sel(330, 95, .8) + _sel(322, 238, 1.1) + _sel(80, 232, .7)
    + _kilau(115, 35) + _kilau(300, 30) + _kilau(365, 170) + _kilau(36, 160) + "</svg>",
    "riwayat": _SVG + _LATAR
    + "<rect x='110' y='50' width='170' height='220' rx='20' fill='#fff'/>"
    + "<rect x='158' y='36' width='74' height='30' rx='10' fill='#FFCDD2'/>"
    + "".join(f"<circle cx='142' cy='{y}' r='11' fill='{c}'/><rect x='164' y='{y - 7}' width='{w}' height='14' rx='7' fill='#D7EEEE'/>"
              for y, c, w in ((110, "#1E9E6A", 90), (155, "#D99A00", 70), (200, "#C2410C", 84), (245, "#1E9E6A", 60)))
    + "<circle cx='292' cy='212' r='40' fill='#fff' fill-opacity='.22' stroke='#fff' stroke-width='10'/>"
    + "<line x1='321' y1='241' x2='352' y2='272' stroke='#fff' stroke-width='14' stroke-linecap='round'/>"
    + "<path d='M70 60c0 0-22 26-22 40a22 22 0 0 0 44 0c0-14-22-40-22-40Z' fill='url(#tetes)'/>"
    + _sel(70, 230, .8) + _kilau(330, 60) + _kilau(40, 170) + _kilau(370, 150) + "</svg>",
    "admin": _SVG + _LATAR
    + "<rect x='55' y='50' width='280' height='180' rx='20' fill='#fff'/>"
    + "<rect x='175' y='230' width='40' height='26' fill='#fff' opacity='.85'/><rect x='135' y='254' width='120' height='12' rx='6' fill='#fff'/>"
    + "".join(f"<rect x='{x}' y='{205 - h}' width='24' height='{h}' rx='6' fill='{c}'/>"
              for x, h, c in ((85, 60, "#1E9E6A"), (119, 95, "#D99A00"), (153, 45, "#C2410C"), (187, 120, "#0E7C86")))
    + "<line x1='78' y1='206' x2='222' y2='206' stroke='#D7EEEE' stroke-width='3'/>"
    + "<circle cx='275' cy='125' r='34' fill='none' stroke='#D7EEEE' stroke-width='14'/>"
    + "".join(f"<circle cx='275' cy='125' r='34' fill='none' stroke='{c}' stroke-width='14' pathLength='100' "
              f"stroke-dasharray='{p} 100' stroke-dashoffset='{-o}' transform='rotate(-90 275 125)'/>"
              for c, p, o in (("#1E9E6A", 45, 0), ("#D99A00", 30, 45), ("#C2410C", 25, 75)))
    + "<path d='M335 170l38 14v26c0 24-17 40-38 48c-21-8-38-24-38-48v-26Z' fill='#FFCDD2' stroke='#fff' stroke-width='5'/>"
    + "<rect x='322' y='203' width='26' height='22' rx='4' fill='#C62828'/>"
    + "<path d='M327 203v-7a8 8 0 0 1 16 0v7' stroke='#C62828' stroke-width='4' fill='none'/>"
    + _kilau(40, 40) + _kilau(370, 60) + _kilau(30, 250) + "</svg>",
}

LOGO = svg_uri("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 48 48'><defs><linearGradient id='g' x1='0' y1='0' x2='1' y2='1'>"
               "<stop offset='0' stop-color='#14A3A8'/><stop offset='1' stop-color='#0B6E77'/></linearGradient></defs>"
               "<rect width='48' height='48' rx='13' fill='url(#g)'/>"
               "<path d='M24 9s-11 13-11 20a11 11 0 0 0 22 0c0-7-11-20-11-20Z' fill='#FF6B6B'/>"
               "<polyline points='15,30 20,30 22,26 25,34 27,28 29,30 33,30' stroke='#fff' stroke-width='2.2' "
               "stroke-linecap='round' stroke-linejoin='round' fill='none'/></svg>")

WARNA2 = {"rendah": "#3CC48D", "sedang": "#F2B42A", "tinggi": "#EA580C"}
IKON_BAGIAN = {"data": "👤", "gejala": "🤒", "haid": "🩸", "makan": "🥗", "ttd": "💊", "riwayat": "📋"}


def atur_lebar(px):
    htm(f"<style>.block-container,[data-testid='stMainBlockContainer']{{max-width:{px}px !important;}}</style>")


def topbar(judul):
    htm(f"""<div class='brand'><img src='{LOGO}' alt=''><div><div class='brand-nama'>Skrining Risiko Anemia</div>
        <div class='brand-sub'>Mahasiswa · Kesehatan Masyarakat</div></div>
        <div class='brand-hal'>{html.escape(judul)}</div></div>""")


def panel(ilus, label, judul, isi, chips=()):
    chip = "".join(f"<span class='chip'>{c}</span>" for c in chips)
    htm(f"""<div class='panel'><div class='panel-brand'><img src='{LOGO}' alt=''><div><b>Skrining Risiko Anemia</b>
        <span>Mahasiswa · Kesehatan Masyarakat</span></div></div><div><span class='panel-label'>{label}</span></div><div class='panel-judul'>{judul}</div>
        <div class='panel-isi'>{isi}</div><div class='chips'>{chip}</div>
        <img class='panel-img' src='{svg_uri(ILUS[ilus])}' alt=''></div>""")


def banner(ikon, judul, isi):
    htm(f"""<div class='banner'><div class='banner-ikon'>{ikon}</div><div><div class='banner-judul'>{judul}</div>
        <div class='banner-isi'>{isi}</div></div></div>""")


def judul_kartu(judul, sub=""):
    htm(f"<div class='judul-kartu'>{judul}</div>" + (f"<div class='sub-kartu'>{sub}</div>" if sub else ""))


def judul_bagian(ikon, teks):
    htm(f"<div class='judul-bagian'><span class='ik'>{ikon}</span>{teks}</div>")


def kartu(nama):
    return st.container(border=True, key=f"kartu_{nama}")


SATU_LAYAR = """<style>
@media (min-width:900px){
.block-container,[data-testid='stMainBlockContainer']{padding-top:3.6rem !important;padding-bottom:.6rem !important;}
.panel{height:calc(100vh - 4.6rem);min-height:440px;display:flex;flex-direction:column;padding:24px 30px 14px;}
.panel-judul{font-size:clamp(1.45rem,3.6vh,2.05rem);margin:10px 0 8px;}
.panel-isi{font-size:.93rem;line-height:1.55;}
.chips{margin-top:12px;}
.panel-img{flex:1 1 0;min-height:0;width:100%;max-width:none;object-fit:contain;margin:8px auto 0;}
.kaki{display:none;}
}
</style>"""


def split():
    """Dua kolom (ilustrasi | form) yang muat satu layar di desktop."""
    htm(SATU_LAYAR)
    return st.columns([1.05, 1], gap="large", vertical_alignment="center")


def tombol(label, key, tipe="secondary", disabled=False):
    return st.button(label, key=key, type=tipe, width="stretch", disabled=disabled)


def label_kembali():
    if ss.asal in ("hasil", "hasil-riwayat") or (not ss.asal and ss.hasil):
        return "← Kembali ke hasil"
    return "← Kembali ke beranda"


def kembali_asal():
    asal = ss.asal or ("hasil" if ss.hasil else "home")
    ke(asal, asal="")


# =========================================================
# 6. HALAMAN
# =========================================================
def halaman_home():
    kiri, kanan = split()
    with kiri:
        panel("home", "Skrining mandiri", "Kenali risiko anemia lebih dini",
              "Isi kuesioner singkat, lalu dapatkan hasil dan saran tindak lanjut yang sesuai, supaya bisa segera diperiksa "
              "dan ditangani.", ["⏱️ ± 5 menit", "📋 6 bagian singkat", "🔒 Data dijaga rahasia"])
    with kanan, kartu("home"):
        judul_kartu("Mulai skrining 👋", "Ini skrining risiko, <b>bukan diagnosis</b>. Hasil dan saran tindak lanjut "
                    "langsung tampil di akhir.")
        with st.expander("📄 Lembar persetujuan (informed consent)", expanded=False):
            st.write("Kamu diajak mengisi kuesioner skrining risiko anemia untuk keperluan tugas akhir/penelitian. "
                     "Sebelum mulai, mohon pahami hal berikut:")
            st.markdown(
                "- Keikutsertaan bersifat sukarela. Kamu boleh berhenti kapan saja tanpa konsekuensi apa pun.\n"
                "- Pertanyaan meliputi data diri, gejala, riwayat menstruasi (khusus perempuan), pola makan, konsumsi TTD, dan riwayat kesehatan.\n"
                "- Jawaban disimpan secara rahasia dan hanya dipakai untuk penelitian. Laporan hanya menampilkan data gabungan tanpa identitas.\n"
                "- Hasil skrining bukan diagnosis. Status anemia hanya bisa dipastikan lewat pemeriksaan kadar Hb.")
        ss.consent = st.checkbox("Saya sudah membaca penjelasan di atas dan setuju ikut serta.", value=ss.consent)
        if tombol("Mulai skrining  →", "mulai", "primary", disabled=not ss.consent):
            ke("form", step=0, errors={})
        htm("<div class='pemisah'>atau</div>")
        k1, k2, k3 = st.columns(3)
        with k1:
            if tombol("🕘 Riwayat", "ke_riwayat"):
                ke("riwayat", asal="", rw={"kode": "", "status": "", "data": None, "pesan": ""})
        with k2:
            if tombol("🏥 Layanan", "ke_faskes"):
                ke("faskes", asal="home")
        with k3:
            if tombol("🥗 Tips gizi", "ke_tips"):
                ke("tips", asal="home")


def langkah_aktif():
    return [s for s in SECTIONS if tampil(s, ss.a)]


def render_pertanyaan(sec, q):
    a = ss.a
    key = f"{sec['id']}_{q['id']}"
    no = f"{q['no']}. " if q.get("no") else ""
    label = f"{no}{q['text']}" + (" *(opsional)*" if q.get("optional") else "")
    tipe = q.get("type")
    cur = a.get(q["id"])

    if tipe == "text":
        a[q["id"]] = st.text_input(label, value=cur or "", key=key).strip()
    elif tipe == "number":
        desimal = isinstance(q["min"], float)
        v = st.number_input(label, min_value=q["min"], max_value=q["max"],
                            value=cur if cur is not None else None,
                            step=q.get("step", 1), format="%.1f" if desimal else "%d", key=key)
        if v is None:
            a.pop(q["id"], None)
        else:
            a[q["id"]] = float(v) if desimal else int(v)
    else:
        opts = q.get("options", YT)
        v = st.radio(label, opts, index=opts.index(cur) if cur in opts else None,
                     horizontal=len(opts) <= 2, key=key)
        if v is None:
            a.pop(q["id"], None)
        else:
            a[q["id"]] = v

    if ss.errors.get(q["id"]):
        st.markdown(f":red[{ss.errors[q['id']]}]")


def validasi(sec):
    errors = {}
    for q in sec["q"]:
        if not tampil(q, ss.a):
            continue
        v = ss.a.get(q["id"])
        if q.get("optional") and (v is None or v == ""):
            continue
        if v is None or str(v).strip() == "":
            errors[q["id"]] = "Wajib diisi." if q.get("type") in ("text", "number") else "Pilih salah satu jawaban."
    return errors


def jawaban_tampil():
    """Hanya jawaban pada pertanyaan yang memang tampil (jawaban sisa yang tersembunyi dibuang)."""
    a, bersih = ss.a, {}
    for sec in SECTIONS:
        if not tampil(sec, a):
            continue
        for q in sec["q"]:
            if tampil(q, a) and q["id"] in a:
                bersih[q["id"]] = a[q["id"]]
    return bersih


def bersihkan_jawaban(visible):
    """Jawaban pada pertanyaan yang tidak tampil diisi 'Tidak berlaku' (sama seperti versi web)."""
    hasil = {}
    for sec in SECTIONS:
        for q in sec["q"]:
            if q["id"] in visible:
                hasil[q["id"]] = visible[q["id"]]
            else:
                hasil[q["id"]] = "" if q.get("optional") else "Tidak berlaku"
    return hasil


def kirim():
    with st.spinner("Menyimpan jawaban…"):
        try:
            res = api("simpan", data=ss.payload)
            if res is None:
                ss.payload["kode"] = buat_kode()
                ss.simpan = "lokal"
            else:
                ss.payload["kode"] = res.get("kode", "")
                ss.simpan = "ok"
                if ss.payload["kode"]:
                    ss.kode_terakhir = ss.payload["kode"]
        except Exception as e:  # noqa: BLE001
            ss.simpan = "gagal"
            ss.galat = str(e)


def selesai_form():
    visible = jawaban_tampil()
    h = hitung_hasil(visible)
    j = bersihkan_jawaban(visible)
    tbm = float(j["tb"]) / 100
    imt = round(float(j["bb"]) / (tbm * tbm) * 10) / 10
    ss.hasil = h
    ss.payload = {**j, "kode": "", "imt": imt, "skor": h["total"], "skorMaks": h["maks"], "persen": h["persen"],
                  "kategori": h["kategori"], "override": "; ".join(h["override"]),
                  "segera": "Ya" if h["segera"] else "Tidak", "faktor": "; ".join(f["label"] for f in h["faktor"])}
    ss.simpan = ""
    kirim()
    ke("hasil")


def halaman_form():
    atur_lebar(780)
    langkah = langkah_aktif()
    ss.step = min(ss.step, len(langkah) - 1)
    sec = langkah[ss.step]
    topbar(f"Bagian {ss.step + 1} dari {len(langkah)}")

    with kartu("formkepala"):
        bar = "".join(f"<span class='{'ok' if i < ss.step else 'kini' if i == ss.step else ''}'></span>"
                      for i in range(len(langkah)))
        hint = f"<div class='sub-kartu'>{html.escape(sec['hint'])}</div>" if sec.get("hint") else ""
        htm(f"""<div class='form-kepala'><div class='ik'>{IKON_BAGIAN.get(sec['id'], '📝')}</div><div>
            <div class='form-kecil'>Bagian {ss.step + 1} dari {len(langkah)}</div>
            <div class='judul-kartu'>{html.escape(sec['title'])}</div>{hint}</div></div>
            <div class='langkah-step'>{bar}</div>""")

    with kartu("formisi"):
        for q in sec["q"]:
            if tampil(q, ss.a):
                render_pertanyaan(sec, q)

    terakhir = ss.step == len(langkah) - 1
    k1, k2 = st.columns(2)
    with k1:
        kembali = tombol("← Kembali", "form_kembali")
    with k2:
        lanjut = tombol("Lihat hasil  ✓" if terakhir else "Lanjut  →", "form_lanjut", "primary")

    if kembali:
        ss.errors = {}
        if ss.step == 0:
            ke("home")
        ss.step -= 1
        ke("form")
    if lanjut:
        ss.errors = validasi(sec)
        if ss.errors:
            st.rerun()
        if terakhir:
            selesai_form()
        ss.step += 1
        ke("form")


def gauge(persen):
    p = max(0.0, min(float(persen), 100.0))
    return svg_uri(
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 120 120'>"
        "<circle cx='60' cy='60' r='50' fill='none' stroke='rgba(255,255,255,.28)' stroke-width='12'/>"
        f"<circle cx='60' cy='60' r='50' fill='none' stroke='#fff' stroke-width='12' stroke-linecap='round' pathLength='100' "
        f"stroke-dasharray='{max(p, .5)} 100' transform='rotate(-90 60 60)'/>"
        f"<text x='60' y='62' text-anchor='middle' font-family='Segoe UI,Arial,sans-serif' font-size='24' font-weight='800' fill='#fff'>{fmt(p)}%</text>"
        "<text x='60' y='80' text-anchor='middle' font-family='Segoe UI,Arial,sans-serif' font-size='10' fill='#fff' opacity='.85'>skor risiko</text></svg>")


def tampil_hasil(h, a, kode, baru, waktu=None):
    atur_lebar(880)
    t = TEKS[h["level"]]
    topbar("Hasil Skrining")

    sub = f"<div class='hero-waktu'>Skrining pada {html.escape(waktu)}</div>" if waktu else ""
    htm(f"""<div class='hero' style='background:linear-gradient(135deg,{WARNA[h['level']]},{WARNA2[h['level']]})'>
        <img src='{gauge(h['persen'])}' alt='Skor {fmt(h['persen'])}%'><div>
        <div class='hero-label'>Hasil skrining kamu</div><div class='hero-kat'>{t['label']}</div>
        <div class='hero-skor'>Skor {h['total']} dari {h['maks']} ({fmt(h['persen'])}%)</div>{sub}</div></div>""")

    if h["override"] and h["level"] != "tinggi" and h["persen"] < 20:
        st.caption(f"Kategori ditetapkan \"berisiko\" karena: {'; '.join(h['override'])}.")
    if h["segera"]:
        st.error(f"**⚠️ Segera periksa.** {PESAN_OVERRIDE['segera']}")
    if a.get("q26") == "Ya" or a.get("q25") == "Anemia":
        st.warning(PESAN_OVERRIDE["riwayat"])
    if a.get("hamil") == "Ya":
        st.warning(PESAN_OVERRIDE["hamil"])

    with kartu("hasilarti"):
        judul_kartu(t["judul"])
        for p in t["isi"]:
            st.write(p)

    k1, k2 = st.columns(2)
    with k1, kartu("hasilfaktor"):
        judul_bagian("🔍", "Faktor yang berkontribusi")
        if not h["faktor"]:
            st.write("Tidak ada faktor risiko yang menonjol dari jawabanmu.")
        else:
            ubah = [f["label"] for f in h["faktor"] if f["bisa_diubah"]]
            lain = [f["label"] for f in h["faktor"] if not f["bisa_diubah"]]
            isi = ""
            if ubah:
                isi += "<div class='kecil'>Yang bisa kamu ubah</div>" + "".join(f"<span class='fchip ubah'>{html.escape(x)}</span>" for x in ubah)
            if lain:
                isi += "<div class='kecil'>Gejala dan faktor lain</div>" + "".join(f"<span class='fchip lain'>{html.escape(x)}</span>" for x in lain)
            htm(f"<div>{isi}</div>")
    with k2, kartu("hasillangkah"):
        judul_bagian("🧭", "Langkah berikutnya")
        htm("".join(f"<div class='langkah'><b>{i}</b><div>{html.escape(x)}</div></div>" for i, x in enumerate(t["langkah"], 1)))

    with kartu("hasilingat"):
        judul_bagian("🔔", "Pasang pengingat di Google Calendar")
        pengingat = list(PENGINGAT[h["level"]])
        if h["segera"]:
            pengingat.insert(0, {"label": "Ingatkan periksa ke faskes (besok)", "judul": "Segera periksa ke fasilitas kesehatan", "hari": 1})
        detail = ("Pengingat dari aplikasi Skrining Risiko Anemia.\nHasil: " + t["label"]
                  + (f"\nKode responden: {kode}" if kode else "")
                  + "\nTunjukkan hasil skrining ini kepada petugas kesehatan.")
        kol = st.columns(len(pengingat))
        for c, p in zip(kol, pengingat):
            c.link_button(p["label"], link_kalender(p["judul"], p["hari"], detail), width="stretch")

    if not baru:
        kotak = f"Kode responden<br><span class='kode'>{html.escape(kode)}</span>"
    elif kode:
        kotak = (f"Kode responden kamu<br><span class='kode'>{html.escape(kode)}</span><br>"
                 "<span style='font-size:.9rem;color:#5E7378'>Kode ini terhubung otomatis dengan NIM-mu. Simpan kode ini untuk melihat "
                 "riwayat hasil. Skrining ulang dengan NIM yang sama akan masuk ke riwayat yang sama.</span>")
    elif ss.simpan == "gagal":
        kotak = "Kode responden belum terbentuk karena jawaban gagal disimpan."
    else:
        kotak = "Membuat kode responden…"
    htm(f"<div class='tiket'>🎫 {kotak}</div>")
    st.write("")

    aksi = []
    for k in t["tombol"]:
        if k == "faskes":
            aksi.append(("🏥 Cari fasilitas kesehatan", "hasil_faskes", "primary",
                         lambda: ke("faskes", asal="hasil" if baru else "hasil-riwayat")))
        elif k == "tips":
            aksi.append(("🥗 Tips gizi seimbang" if h["level"] == "rendah" else "🥗 Tips pola makan", "hasil_tips", "secondary",
                         lambda: ke("tips", asal="hasil" if baru else "hasil-riwayat")))
        elif k == "selesai":
            if baru:
                def _selesai():
                    kode_lama = ss.get("kode_terakhir", "")
                    reset_state()
                    ss.kode_terakhir = kode_lama
                    ke("home")
                aksi.append(("Selesai  ✓", "hasil_selesai", "primary", _selesai))
            else:
                aksi.append(("← Kembali ke riwayat", "hasil_kembali_rw", "primary", lambda: ke("riwayat")))
    for c, (label, key, tipe, fn) in zip(st.columns(len(aksi)), aksi):
        with c:
            if tombol(label, key, tipe):
                fn()

    st.caption("*Hasil ini adalah skrining risiko berdasarkan jawabanmu, bukan diagnosis. Status anemia hanya bisa dipastikan lewat "
               "pemeriksaan kadar Hb oleh tenaga kesehatan.*")
    htm("<div class='darurat' style='text-align:center'>Jika kamu merasa hampir pingsan, sesak napas berat, atau nyeri dada, "
        "segera ke IGD atau fasilitas kesehatan terdekat, atau hubungi <a href='tel:112'>112</a> (gratis).</div>")

    if baru:
        status = {"ok": "Jawaban tersimpan ✓", "lokal": "Mode uji lokal: jawaban tidak dikirim ke Google Sheets."}.get(ss.simpan, "")
        if ss.simpan == "gagal":
            st.error(f"Jawaban gagal disimpan. {ss.galat}")
            if tombol("Coba simpan lagi", "ulang_simpan"):
                kirim()
                st.rerun()
        elif status:
            st.caption(status)


def halaman_hasil():
    tampil_hasil(ss.hasil, jawaban_tampil(), ss.payload.get("kode", ""), True)


def halaman_hasil_riwayat():
    v = ss.lihat
    tampil_hasil(v["h"], v["a"], ss.rw["kode"], False, v["waktu"])


def halaman_faskes():
    atur_lebar(1000)
    topbar("Layanan Kesehatan")
    banner("🏥", "Fasilitas kesehatan di Makassar",
           "Pemeriksaan kadar Hb bisa dilakukan di Puskesmas, klinik kampus, laboratorium, atau rumah sakit.")
    htm("<div class='darurat'>🚨 <b>Darurat?</b> Hubungi <a href='tel:112'>112</a> (Call Center Kota Makassar, gratis) "
        "atau langsung ke IGD terdekat.</div>")
    kol = st.columns(2)
    for i, f in enumerate(FASKES):
        with kol[i % 2], kartu(f"faskes{i}"):
            ikon = "🏨" if "Rumah sakit" in f["jenis"] else "🏥"
            telp = ""
            if f["telp"]:
                tel = "".join(c for c in f["telp"] if c.isdigit())
                telp = f"<div class='alamat'>📞 <a href='tel:{tel}'>{html.escape(f['telp'])}</a></div>"
            htm(f"""<div class='faskes-kepala'><div class='ik'>{ikon}</div><div><div class='judul-bagian'>{html.escape(f['nama'])}</div>
                <span class='badge'>{html.escape(f['jenis'])}</span></div></div>
                <div class='alamat'>📍 {html.escape(f['alamat'])}</div>{telp}""")
            st.link_button("Lihat di peta", "https://www.google.com/maps/search/?api=1&query=" + quote(f["nama"] + " Makassar"),
                           width="stretch")
    k1, k2 = st.columns(2)
    with k1:
        st.link_button("📍 Cari Puskesmas terdekat", URL_FASKES, type="primary", width="stretch")
    with k2:
        if tombol(label_kembali(), "faskes_kembali"):
            kembali_asal()
    st.caption("Data kontak per November 2026. Jam layanan bisa berubah, sebaiknya hubungi dulu sebelum datang.")


def halaman_tips():
    atur_lebar(1000)
    topbar("Tips Gizi")
    banner("🥗", "Tips mencegah anemia lewat pola makan",
           "Kebiasaan kecil yang dilakukan rutin bisa membantu menjaga kadar hemoglobin tetap normal.")
    kartu_tips = [
        ("🥩", "#FFF1F0", "Sumber zat besi", ["Utamakan zat besi hewani yang lebih mudah diserap: hati, daging merah, ikan, ayam, telur.",
                                             "Sumber nabati: bayam, kangkung, daun kelor, kacang-kacangan, tempe, tahu."]),
        ("🍊", "#FFF6E5", "Pasangkan dengan vitamin C", ["Makan buah seperti jeruk, jambu biji, pepaya, atau tomat bersama makanan utama untuk membantu penyerapan zat besi."]),
        ("☕", "#F3EEE9", "Atur waktu minum teh dan kopi", ["Teh dan kopi menghambat penyerapan zat besi. Beri jeda sekitar 1–2 jam dari waktu makan."]),
        ("🍽️", "#E8F6F6", "Makan teratur", ["Usahakan makan utama 3 kali sehari dan jangan sering melewatkan makan.",
                                            "Bila menjalani diet khusus atau vegetarian, konsultasikan menu dengan tenaga kesehatan."]),
        ("💊", "#EEF0FF", "Tablet Tambah Darah (TTD)", ["Minum TTD sesuai anjuran petugas kesehatan. Untuk remaja putri dan wanita usia subur, program pemerintah menganjurkan 1 tablet per minggu.",
                                                       "Jangan minum TTD bersamaan dengan teh, kopi, atau susu."]),
    ]
    kol = st.columns(2)
    for i, (ikon, latar, judul, butir) in enumerate(kartu_tips):
        with kol[i % 2], kartu(f"tips{i}"):
            li = "".join(f"<li>{html.escape(b)}</li>" for b in butir)
            htm(f"""<div class='tips-kepala'><div class='ik' style='background:{latar}'>{ikon}</div>
                <div class='judul-bagian'>{html.escape(judul)}</div></div><ul class='tips-isi'>{li}</ul>""")
    if tombol(label_kembali(), "tips_kembali"):
        kembali_asal()


def cari_riwayat(kode):
    kode = kode.strip().upper()
    rw = ss.rw
    rw["kode"] = kode
    if not re.fullmatch(r"ANM-\d{6}-[A-Z0-9]{4,6}", kode):
        rw.update(status="gagal", pesan="Format kode tidak sesuai, contoh: ANM-261118-AB12CD.")
        return
    try:
        with st.spinner("Mencari…"):
            res = api("riwayat", kode=kode)
        if res is None:
            rw.update(status="gagal", pesan="Riwayat hanya tersedia setelah API_URL diisi di secrets.")
        else:
            rw.update(status="ok", data=res.get("data", []))
    except Exception as e:  # noqa: BLE001
        rw.update(status="gagal", pesan=f"Gagal memuat riwayat. {e}")


def halaman_riwayat():
    rw = ss.rw
    if not rw["kode"]:
        rw["kode"] = (ss.payload or {}).get("kode") or ss.get("kode_terakhir", "")
    kiri, kanan = split()
    with kiri:
        panel("riwayat", "Riwayat hasil", "Pantau perkembangan hasil skriningmu",
              "Semua skrining dengan NIM yang sama otomatis tergabung dalam satu kode responden.",
              ["🎫 Pakai kode responden", "📈 Bandingkan hasil", "🔒 Tanpa data identitas"])
    with kanan, kartu("riwayat"):
        judul_kartu("Masukkan kode responden", "Kode muncul di layar hasil skrining, contoh <b>ANM-261118-AB12CD</b>.")
        with st.form("rw_form", border=False):
            kode = st.text_input("Kode responden", value=rw["kode"], placeholder="ANM-261118-AB12CD", key="rw_input")
            cari = st.form_submit_button("🔍 Cari riwayat", type="primary", width="stretch")
        if cari:
            cari_riwayat(kode)
            st.rerun()

        if rw["status"] == "gagal":
            st.error(rw["pesan"])
        elif rw["status"] == "ok" and not rw["data"]:
            st.info("Belum ada hasil untuk kode ini.")
        elif rw["status"] == "ok":
            st.caption(f"{len(rw['data'])} hasil, terbaru di atas. Ketuk salah satu untuk melihat hasil lengkapnya.")
            for i, r in enumerate(rw["data"]):
                teks = (f"{IKON.get(r['kategori'], '⚪')} **{r['kategori']}** · {r['waktu']}  \n"
                        f"Skor {r['skor']} dari {r['skorMaks']} ({fmt(float(r['persen']))}%)")
                if tombol(teks, f"rwitem_{i}"):
                    j = r.get("j")
                    if not j or j.get("jk") not in SKOR_MAKS:
                        rw.update(status="gagal", pesan="Detail hasil belum tersedia. Pastikan Code.gs sudah diperbarui dan dipasang sebagai versi baru.")
                        st.rerun()
                    a = dict(j)
                    ss.lihat = {"h": hitung_hasil(a), "a": a, "waktu": r["waktu"]}
                    ke("hasil-riwayat")
        if tombol(label_kembali(), "rw_kembali"):
            kembali_asal()


def _waktu(v):
    try:
        if isinstance(v, (int, float)) and v:
            return datetime.fromtimestamp(v / 1000, TZ)
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).astimezone(TZ)
    except Exception:  # noqa: BLE001
        return None


def muat_rekap(pin):
    with st.spinner("Memuat data…"):
        try:
            res = api("rekap", pin=pin)
            if res is None:
                ss.adm = {"status": "gagal", "pesan": "API_URL belum diisi di secrets.", "data": None, "pin": ""}
            else:
                ss.adm = {"status": "ok", "pesan": "", "data": res.get("data") or {}, "pin": pin}
        except Exception as e:  # noqa: BLE001
            ss.adm = {"status": "gagal", "pesan": str(e), "data": None, "pin": ""}


def halaman_admin():
    import pandas as pd

    adm = ss.setdefault("adm", {"status": "", "pesan": "", "data": None, "pin": ""})

    if adm["status"] != "ok":
        kiri, kanan = split()
        with kiri:
            panel("admin", "Khusus petugas", "Dasbor rekap skrining anemia",
                  "Pantau sebaran risiko anemia mahasiswa secara langsung. Data ditampilkan tanpa nama, NIM, dan kode responden.",
                  ["📊 Grafik interaktif", "⬇️ Unduh CSV", "🔐 Dilindungi PIN"])
        with kanan, kartu("admin"):
            judul_kartu("Masuk sebagai petugas 🔐", "Masukkan PIN petugas untuk membuka dasbor.")
            with st.form("adm_login", border=False):
                pin = st.text_input("PIN petugas", type="password", placeholder="••••••")
                masuk = st.form_submit_button("Masuk  →", type="primary", width="stretch")
            if masuk:
                muat_rekap(pin)
                st.rerun()
            if adm["status"] == "gagal":
                st.error(adm["pesan"])
            if tombol("← Kembali ke beranda", "adm_home"):
                st.query_params.clear()
                ke("home")
        return

    atur_lebar(1180)
    topbar("Dasbor Petugas")
    data = adm["data"]
    df = pd.DataFrame(data.get("rows") or [])
    k0, k1, k2 = st.columns([3, 1, 1], vertical_alignment="center")
    with k0:
        judul_kartu("📊 Rekap skrining risiko anemia", "Data gabungan tanpa identitas responden.")
    if k1.button("↻ Muat ulang", width="stretch"):
        muat_rekap(adm["pin"])
        st.rerun()
    if k2.button("Keluar", width="stretch"):
        ss.adm = {"status": "", "pesan": "", "data": None, "pin": ""}
        st.rerun()

    if df.empty:
        st.info("Belum ada responden.")
        return

    df["waktu"] = df["waktu"].map(_waktu)
    df["persen"] = pd.to_numeric(df["persen"], errors="coerce")
    df["imt"] = pd.to_numeric(df["imt"], errors="coerce")

    with st.expander("🔎 Filter data", expanded=False):
        f1, f2, f3 = st.columns(3)
        prodi = f1.multiselect("Prodi", sorted(df["prodi"].dropna().astype(str).unique()))
        jk = f2.multiselect("Jenis kelamin", sorted(df["jk"].dropna().astype(str).unique()))
        tgl = df["waktu"].dropna()
        rentang = None
        if not tgl.empty:
            rentang = f3.date_input("Rentang tanggal", (tgl.min().date(), tgl.max().date()))
    if prodi:
        df = df[df["prodi"].astype(str).isin(prodi)]
    if jk:
        df = df[df["jk"].astype(str).isin(jk)]
    if rentang and isinstance(rentang, tuple) and len(rentang) == 2:
        d = df["waktu"].map(lambda w: w.date() if w else None)
        df = df[(d >= rentang[0]) & (d <= rentang[1])]
    if df.empty:
        st.info("Tidak ada data yang cocok dengan filter.")
        return

    n = len(df)
    lv = df["level"].value_counts()
    m = st.columns(5)
    m[0].metric("👥 Responden", n)
    for kol, key, ikon in ((m[1], "rendah", "🟢"), (m[2], "sedang", "🟠"), (m[3], "tinggi", "🔴")):
        j = int(lv.get(key, 0))
        kol.metric(f"{ikon} Risiko {key}", j, f"{j / n * 100:.0f}%", delta_color="off")
    segera = int((df["segera"] == "Ya").sum()) if "segera" in df else 0
    m[4].metric("⚠️ Perlu segera periksa", segera)
    st.caption(f"Rata-rata skor risiko: {fmt(df['persen'].mean())}% · Rata-rata IMT: {fmt(df['imt'].mean())}")

    urut = ["rendah", "sedang", "tinggi"]
    warna = [WARNA[k] for k in urut]
    g1, g2 = st.columns(2)
    with g1, kartu("g_kategori"):
        judul_bagian("🎯", "Sebaran kategori risiko")
        label = [k.capitalize() for k in urut]
        sebaran = pd.DataFrame({label[i]: [int(lv.get(k, 0)) if j == i else 0 for j in range(3)] for i, k in enumerate(urut)},
                               index=label)
        st.bar_chart(sebaran, color=warna, height=280)
    with g2, kartu("g_jk"):
        judul_bagian("⚧️", "Kategori risiko per jenis kelamin")
        per_jk = pd.crosstab(df["jk"], df["level"]).reindex(columns=urut, fill_value=0)
        per_jk.columns = [k.capitalize() for k in per_jk.columns]
        st.bar_chart(per_jk, color=warna, height=280)

    with kartu("g_prodi"):
        judul_bagian("🎓", "Kategori risiko per prodi")
        per_prodi = pd.crosstab(df["prodi"], df["level"]).reindex(columns=urut, fill_value=0)
        per_prodi.columns = [k.capitalize() for k in per_prodi.columns]
        st.bar_chart(per_prodi, color=warna, horizontal=True, height=max(220, 44 * len(per_prodi)))

    g3, g4 = st.columns(2)
    harian = df.dropna(subset=["waktu"]).assign(Tanggal=lambda x: x["waktu"].map(lambda w: w.date()))
    with g3, kartu("g_harian"):
        judul_bagian("📅", "Responden per hari")
        if harian.empty:
            st.caption("Belum ada data tanggal.")
        else:
            st.area_chart(harian.groupby("Tanggal").size().rename("Responden"), color="#14A3A8", height=260)
    with g4, kartu("g_faktor"):
        judul_bagian("🔍", "10 faktor risiko terbanyak")
        faktor = df["faktor"].fillna("").astype(str).str.split(";").explode().str.strip()
        faktor = faktor[faktor != ""].value_counts().head(10)
        if faktor.empty:
            st.caption("Belum ada faktor risiko tercatat.")
        else:
            st.dataframe(faktor.rename_axis("Faktor").reset_index(name="Jumlah"), hide_index=True, width="stretch",
                         height=260, column_config={"Jumlah": st.column_config.ProgressColumn(
                             "Jumlah", format="%d", min_value=0, max_value=int(faktor.max()))})

    with kartu("g_tabel"):
        judul_bagian("🗂️", "Data responden (tanpa kode responden)")
        tampil_df = df.assign(waktu=df["waktu"].map(lambda w: w.strftime("%d-%m-%Y %H:%M") if w else "")).rename(columns={
            "waktu": "Waktu", "usia": "Usia", "jk": "Jenis kelamin", "prodi": "Prodi", "semester": "Semester", "imt": "IMT",
            "hamil": "Hamil", "persen": "Skor (%)", "kategori": "Kategori", "level": "Level risiko", "segera": "Segera periksa",
            "faktor": "Faktor risiko"})
        st.dataframe(tampil_df, hide_index=True, width="stretch")
        t1, t2 = st.columns(2)
        with t1:
            st.download_button("⬇️ Unduh CSV", tampil_df.to_csv(index=False).encode("utf-8"),
                               "rekap-skrining-anemia.csv", "text/csv", width="stretch")
        with t2:
            if data.get("sheetUrl"):
                st.link_button("📄 Buka Google Sheets", data["sheetUrl"], width="stretch")


# =========================================================
# 7. JALANKAN
# =========================================================
htm(GAYA)

HALAMAN = {
    "home": halaman_home, "form": halaman_form, "hasil": halaman_hasil, "hasil-riwayat": halaman_hasil_riwayat,
    "tips": halaman_tips, "faskes": halaman_faskes, "riwayat": halaman_riwayat, "admin": halaman_admin,
}
if "admin" in st.query_params:  # dasbor petugas: buka URL aplikasi + ?admin
    ss.page = "admin"
HALAMAN[ss.page]()

htm("<div class='kaki'>Aplikasi Skrining dalam Kesehatan Masyarakat · Tugas Akhir</div>")

if ss.scroll:  # kembali ke atas setiap pindah halaman
    ss.scroll = False
    JS = ("<script>const d=window.parent.document;"
          "(d.querySelector('[data-testid=\"stMain\"]')||d.querySelector('section.main')||d.documentElement).scrollTo(0,0);</script>")
    if hasattr(st, "iframe"):  # Streamlit terbaru
        st.iframe(JS, height=1)
    else:  # Streamlit lama
        components.html(JS, height=0)
