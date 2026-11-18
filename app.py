"""
Skrining Risiko Anemia Mahasiswa — versi Streamlit
Data disimpan lewat Google Apps Script (Code.gs) ke Google Sheets.

Secrets (.streamlit/secrets.toml atau menu Secrets di Streamlit Cloud):
    API_URL = "https://script.google.com/macros/s/XXXX/exec"
    API_KEY = "kunci-yang-sama-dengan-API_KEY-di-Code.gs"
Tanpa secrets, aplikasi jalan dalam mode uji lokal (jawaban tidak disimpan).
"""
import html
import random
import string
from datetime import datetime, timedelta
from urllib.parse import quote
from zoneinfo import ZoneInfo

import requests
import streamlit as st
import streamlit.components.v1 as components  # dipakai hanya bila st.iframe belum ada

st.set_page_config(page_title="Skrining Risiko Anemia Mahasiswa", page_icon="🩺", layout="centered")

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


def topbar(judul):
    st.markdown(
        f"<div style='background:#0E7C86;color:#fff;padding:14px 20px;font-weight:600;text-align:center;"
        f"border-radius:10px;margin-bottom:14px'>{html.escape(judul)}</div>", unsafe_allow_html=True)


def tombol(label, key, tipe="secondary", disabled=False):
    return st.button(label, key=key, type=tipe, use_container_width=True, disabled=disabled)


def label_kembali():
    if ss.asal in ("hasil", "hasil-riwayat") or (not ss.asal and ss.hasil):
        return "KEMBALI KE HASIL"
    return "KEMBALI KE BERANDA"


def kembali_asal():
    asal = ss.asal or ("hasil" if ss.hasil else "home")
    ke(asal, asal="")


# =========================================================
# 5. HALAMAN
# =========================================================
def halaman_home():
    topbar("Skrining Risiko Anemia")
    st.title("Skrining Risiko Anemia Mahasiswa")
    st.write("Tujuan: mendeteksi risiko anemia lebih dini, supaya bisa segera diperiksa dan ditangani.")
    st.markdown("- Sekitar 5 menit, terdiri dari 6 bagian singkat.\n"
                "- Hasil dan saran tindak lanjut langsung tampil di akhir.\n"
                "- Ini skrining risiko, **bukan diagnosis**.")
    with st.expander("Lembar persetujuan (informed consent)", expanded=True):
        st.write("Kamu diajak mengisi kuesioner skrining risiko anemia untuk keperluan tugas akhir/penelitian. "
                 "Sebelum mulai, mohon pahami hal berikut:")
        st.markdown(
            "- Keikutsertaan bersifat sukarela. Kamu boleh berhenti kapan saja tanpa konsekuensi apa pun.\n"
            "- Pertanyaan meliputi data diri, gejala, riwayat menstruasi (khusus perempuan), pola makan, konsumsi TTD, dan riwayat kesehatan.\n"
            "- Jawaban disimpan secara rahasia dan hanya dipakai untuk penelitian. Laporan hanya menampilkan data gabungan tanpa identitas.\n"
            "- Hasil skrining bukan diagnosis. Status anemia hanya bisa dipastikan lewat pemeriksaan kadar Hb.")
    ss.consent = st.checkbox("Saya sudah membaca penjelasan di atas dan setuju ikut serta.", value=ss.consent)
    if tombol("MULAI", "mulai", "primary", disabled=not ss.consent):
        ke("form", step=0, errors={})
    if tombol("LIHAT RIWAYAT HASIL", "ke_riwayat"):
        ke("riwayat", asal="", rw={"kode": "", "status": "", "data": None, "pesan": ""})
    if tombol("KONTAK LAYANAN KESEHATAN", "ke_faskes"):
        ke("faskes", asal="home")


def langkah_aktif():
    return [s for s in SECTIONS if tampil(s, ss.a)]


def render_pertanyaan(sec, q):
    a = ss.a
    key = f"{sec['id']}_{q['id']}"
    no = f"**{q['no']}.** " if q.get("no") else ""
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
    langkah = langkah_aktif()
    ss.step = min(ss.step, len(langkah) - 1)
    sec = langkah[ss.step]
    topbar(sec["title"])
    st.progress((ss.step + 1) / len(langkah))
    st.caption(f"Bagian {ss.step + 1} dari {len(langkah)}")
    st.subheader(sec["title"])
    if sec.get("hint"):
        st.caption(sec["hint"])

    for q in sec["q"]:
        if tampil(q, ss.a):
            render_pertanyaan(sec, q)

    terakhir = ss.step == len(langkah) - 1
    k1, k2 = st.columns(2)
    with k1:
        kembali = tombol("KEMBALI", "form_kembali")
    with k2:
        lanjut = tombol("LIHAT HASIL" if terakhir else "LANJUT", "form_lanjut", "primary")

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


def tampil_hasil(h, a, kode, baru, waktu=None):
    t = TEKS[h["level"]]
    topbar("Hasil Skrining")

    sub = f"<div style='font-size:.85rem;opacity:.95'>Skrining pada {html.escape(waktu)}</div>" if waktu else ""
    st.markdown(
        f"<div style='background:{WARNA[h['level']]};color:#fff;border-radius:14px;padding:20px 16px;text-align:center'>"
        f"<div style='font-size:1.45rem;font-weight:800;letter-spacing:.5px'>{t['label']}</div>"
        f"<div style='margin-top:4px'>Skor {h['total']} dari {h['maks']} ({fmt(h['persen'])}%)</div>{sub}</div>",
        unsafe_allow_html=True)

    if h["override"] and h["level"] != "tinggi" and h["persen"] < 20:
        st.caption(f"Kategori ditetapkan \"berisiko\" karena: {'; '.join(h['override'])}.")

    if h["segera"]:
        st.error(f"**⚠️ Segera periksa.** {PESAN_OVERRIDE['segera']}")
    if a.get("q26") == "Ya" or a.get("q25") == "Anemia":
        st.warning(PESAN_OVERRIDE["riwayat"])
    if a.get("hamil") == "Ya":
        st.warning(PESAN_OVERRIDE["hamil"])

    st.subheader(t["judul"])
    for p in t["isi"]:
        st.write(p)

    st.markdown("### Faktor yang berkontribusi")
    if not h["faktor"]:
        st.write("Tidak ada faktor risiko yang menonjol dari jawabanmu.")
    else:
        ubah = [f["label"] for f in h["faktor"] if f["bisa_diubah"]]
        lain = [f["label"] for f in h["faktor"] if not f["bisa_diubah"]]
        if ubah:
            st.caption("Yang bisa kamu ubah:")
            st.markdown("\n".join(f"- {x}" for x in ubah))
        if lain:
            st.caption("Gejala dan faktor lain:")
            st.markdown("\n".join(f"- {x}" for x in lain))

    with st.container(border=True):
        st.markdown("### Langkah berikutnya")
        st.markdown("\n".join(f"- {x}" for x in t["langkah"]))

    st.markdown("### Pasang pengingat")
    pengingat = list(PENGINGAT[h["level"]])
    if h["segera"]:
        pengingat.insert(0, {"label": "Ingatkan periksa ke faskes (besok)", "judul": "Segera periksa ke fasilitas kesehatan", "hari": 1})
    detail = ("Pengingat dari aplikasi Skrining Risiko Anemia.\nHasil: " + t["label"]
              + (f"\nKode responden: {kode}" if kode else "")
              + "\nTunjukkan hasil skrining ini kepada petugas kesehatan.")
    for p in pengingat:
        st.link_button(f"🔔 {p['label']}", link_kalender(p["judul"], p["hari"], detail), use_container_width=True)

    st.write("")
    for k in t["tombol"]:
        if k == "faskes":
            if tombol("CARI FASILITAS KESEHATAN TERDEKAT", "hasil_faskes", "primary"):
                ke("faskes", asal="hasil" if baru else "hasil-riwayat")
        elif k == "tips":
            if tombol("LIHAT TIPS GIZI SEIMBANG" if h["level"] == "rendah" else "TIPS POLA MAKAN", "hasil_tips"):
                ke("tips", asal="hasil" if baru else "hasil-riwayat")
        elif k == "selesai":
            if baru:
                if tombol("SELESAI", "hasil_selesai", "primary"):
                    kode_lama = ss.get("kode_terakhir", "")
                    reset_state()
                    ss.kode_terakhir = kode_lama
                    ke("home")
            elif tombol("KEMBALI KE RIWAYAT", "hasil_kembali_rw", "primary"):
                ke("riwayat")

    if not baru:
        kotak = f"Kode responden: **{kode}**"
    elif kode:
        kotak = (f"Kode responden kamu: **{kode}**\n\nKode ini terhubung otomatis dengan NIM-mu. Pakai kode ini untuk melihat "
                 "riwayat hasil. Skrining ulang dengan NIM yang sama akan masuk ke riwayat yang sama.")
    elif ss.simpan == "gagal":
        kotak = "Kode responden belum terbentuk karena jawaban gagal disimpan."
    else:
        kotak = "Membuat kode responden…"
    with st.container(border=True):
        st.markdown(kotak)

    st.caption("*Hasil ini adalah skrining risiko berdasarkan jawabanmu, bukan diagnosis. Status anemia hanya bisa dipastikan lewat "
               "pemeriksaan kadar Hb oleh tenaga kesehatan.*")
    st.markdown("<div style='text-align:center;font-size:.88rem;color:#C2410C'>Jika kamu merasa hampir pingsan, sesak napas berat, "
                "atau nyeri dada, segera ke IGD atau fasilitas kesehatan terdekat, atau hubungi <a href='tel:112'>112</a> (gratis).</div>",
                unsafe_allow_html=True)

    if baru:
        status = {"ok": "Jawaban tersimpan ✓", "lokal": "Mode uji lokal: jawaban tidak dikirim ke Google Sheets."}.get(ss.simpan, "")
        if ss.simpan == "gagal":
            st.error(f"Jawaban gagal disimpan. {ss.galat}")
            if tombol("COBA SIMPAN LAGI", "ulang_simpan"):
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
    topbar("Kontak Layanan Kesehatan")
    st.subheader("Fasilitas kesehatan di Makassar")
    st.caption("Pemeriksaan kadar Hb bisa dilakukan di Puskesmas, klinik kampus, laboratorium, atau rumah sakit.")
    st.error("**Darurat?** Hubungi [**112**](tel:112) (Call Center Kota Makassar, gratis) atau langsung ke IGD terdekat.")
    for i, f in enumerate(FASKES):
        with st.container(border=True):
            st.markdown(f"**{f['nama']}**")
            st.caption(f["jenis"])
            st.write(f["alamat"])
            if f["telp"]:
                tel = "".join(c for c in f["telp"] if c.isdigit())
                st.markdown(f"[📞 {f['telp']}](tel:{tel})")
            st.link_button("📍 Lihat peta", "https://www.google.com/maps/search/?api=1&query=" + quote(f["nama"] + " Makassar"))
    st.link_button("CARI PUSKESMAS TERDEKAT DI GOOGLE MAPS", URL_FASKES, type="primary", use_container_width=True)
    if tombol(label_kembali(), "faskes_kembali"):
        kembali_asal()
    st.caption("Data kontak per November 2026. Jam layanan bisa berubah, sebaiknya hubungi dulu sebelum datang.")


def halaman_tips():
    topbar("Tips Gizi Seimbang")
    st.subheader("Tips mencegah anemia lewat pola makan")
    kartu = [
        ("🥩 Sumber zat besi", ["Utamakan zat besi hewani yang lebih mudah diserap: hati, daging merah, ikan, ayam, telur.",
                                 "Sumber nabati: bayam, kangkung, daun kelor, kacang-kacangan, tempe, tahu."]),
        ("🍊 Pasangkan dengan vitamin C", ["Makan buah seperti jeruk, jambu biji, pepaya, atau tomat bersama makanan utama untuk membantu penyerapan zat besi."]),
        ("☕ Atur waktu minum teh dan kopi", ["Teh dan kopi menghambat penyerapan zat besi. Beri jeda sekitar 1–2 jam dari waktu makan."]),
        ("🍽️ Makan teratur", ["Usahakan makan utama 3 kali sehari dan jangan sering melewatkan makan.",
                              "Bila menjalani diet khusus atau vegetarian, konsultasikan menu dengan tenaga kesehatan."]),
        ("💊 Tablet Tambah Darah (TTD)", ["Minum TTD sesuai anjuran petugas kesehatan. Untuk remaja putri dan wanita usia subur, program pemerintah menganjurkan 1 tablet per minggu.",
                                           "Jangan minum TTD bersamaan dengan teh, kopi, atau susu."]),
    ]
    for judul, butir in kartu:
        with st.container(border=True):
            st.markdown(f"**{judul}**")
            st.markdown("\n".join(f"- {b}" for b in butir))
    if tombol(label_kembali(), "tips_kembali"):
        kembali_asal()


def cari_riwayat(kode):
    import re
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
    topbar("Riwayat Hasil")
    rw = ss.rw
    if not rw["kode"]:
        rw["kode"] = (ss.payload or {}).get("kode") or ss.get("kode_terakhir", "")
    st.subheader("Lihat riwayat hasil skrining")
    st.caption("Masukkan kode responden yang muncul di layar hasil skrining. Semua skrining dengan NIM yang sama otomatis tergabung di kode ini.")
    kode = st.text_input("Kode responden", value=rw["kode"], placeholder="ANM-261118-AB12CD", key="rw_input")
    if tombol("CARI", "rw_cari", "primary"):
        cari_riwayat(kode)
        st.rerun()

    if rw["status"] == "gagal":
        st.markdown(f":red[{rw['pesan']}]")
    elif rw["status"] == "ok" and not rw["data"]:
        st.write("Belum ada hasil untuk kode ini.")
    elif rw["status"] == "ok":
        st.caption(f"{len(rw['data'])} hasil, terbaru di atas. Ketuk salah satu untuk melihat hasil lengkapnya.")
        for i, r in enumerate(rw["data"]):
            teks = f"{IKON.get(r['kategori'], '⚪')} {r['kategori']} · {r['waktu']} · Skor {r['skor']} dari {r['skorMaks']} ({fmt(float(r['persen']))}%)"
            if tombol(teks, f"rw_{i}"):
                j = r.get("j")
                if not j or j.get("jk") not in SKOR_MAKS:
                    rw.update(status="gagal", pesan="Detail hasil belum tersedia. Pastikan Code.gs sudah diperbarui dan dipasang sebagai versi baru.")
                    st.rerun()
                a = dict(j)
                ss.lihat = {"h": hitung_hasil(a), "a": a, "waktu": r["waktu"]}
                ke("hasil-riwayat")
    if tombol(label_kembali(), "rw_kembali"):
        kembali_asal()


# =========================================================
# 6. JALANKAN
# =========================================================
st.markdown("""
<style>
#MainMenu, footer {visibility: hidden;}
.block-container, [data-testid="stMainBlockContainer"] {
    max-width: 720px;
    padding-top: 4.5rem !important;    /* beri ruang di bawah header Streamlit (Share/GitHub) */
    padding-bottom: 1.5rem !important; /* default Streamlit ~10rem, terlalu jauh */
}
</style>""", unsafe_allow_html=True)

HALAMAN = {
    "home": halaman_home, "form": halaman_form, "hasil": halaman_hasil, "hasil-riwayat": halaman_hasil_riwayat,
    "tips": halaman_tips, "faskes": halaman_faskes, "riwayat": halaman_riwayat,
}
HALAMAN[ss.page]()

st.markdown("<hr style='margin-top:2rem'><div style='text-align:center;font-size:.75rem;color:#5B6B6C'>"
            "Aplikasi Skrining dalam Kesehatan Masyarakat · Tugas Akhir</div>", unsafe_allow_html=True)

if ss.scroll:  # kembali ke atas setiap pindah halaman
    ss.scroll = False
    JS = ("<script>const d=window.parent.document;"
          "(d.querySelector('[data-testid=\"stMain\"]')||d.querySelector('section.main')||d.documentElement).scrollTo(0,0);</script>")
    if hasattr(st, "iframe"):  # Streamlit terbaru
        st.iframe(JS, height=1)
    else:  # Streamlit lama
        components.html(JS, height=0)