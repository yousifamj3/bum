# -*- coding: utf-8 -*-
"""
حاسبة يوسف الأسطورة
--------------------
تقرأ كشوفات PDF (برايم) وتجمع الطلبات وتخصم التوصيل.

التشغيل:
    pip install streamlit pdfplumber
    streamlit run app.py
"""
import io
import os
import re
import unicodedata
from collections import OrderedDict
from datetime import datetime, timedelta, timezone

import pandas as pd
import pdfplumber
import streamlit as st

# ======================================================================
#                              الإعدادات
#     كل الأرقام بالدينار. إذا تغيّر سعر تعدله من هنا بس.
# ======================================================================
REGIONS = ("محافظات", "بغداد", "موصل")


def F(provinces, baghdad, mosul):
    """سعر التوصيل حسب المنطقة: (محافظات ، بغداد ، موصل)"""
    return {"محافظات": provinces, "بغداد": baghdad, "موصل": mosul}


# ---------- القائمة الأولى: كل كشف يخص متجر واحد ----------
LIST1 = OrderedDict([
    ("اونيلا", F(7000, 6000, 5000)),
    ("روح",    F(7000, 6000, 5000)),
    ("نورا",   F(6000, 6000, 5000)),
    ("سارة",   F(6000, 6000, 5000)),
    ("ادينا",  F(7000, 6000, 5000)),
    ("فينوس",  F(6000, 6000, 5000)),
])

# ---------- القائمة الثانية: كشف فيه عدة متاجر، والنتيجة تنفصل لكل متجر ----------
# القاعدة = (الاسم بالنتيجة ، [كلمات يدور عليها باسم المتجر بالكشف] ، سعر التوصيل)
# السعر None = بدون خصم (المبلغ يبقى كما هو)
LIST2 = OrderedDict([
    ("متفرقة كولدن", {
        "rules": [
            ("شي براند",           ["شي براند"],  F(6000, 6000, 5000)),
            ("أزياء برو",          ["ازياء برو"], F(7000, 7000, 5000)),
            ("أزياء كاريزا",       ["كاريزا"],    F(7000, 7000, 5000)),
            ("زيز فونة",            ["زيز فونة"],   F(6000, 6000, 5000)),
            ("توتة",               ["توته"],      F(7000, 7000, 5000)),
            ("حذيفة براند",        ["حذيفه"],     F(6000, 6000, 5000)),
            ("Velure lingeri",     ["velure", "valure"], F(6000, 6000, 5000)),
            ("سوز",               ["سوز"],       F(6000, 6000, 5000)),
            ("سونامي",            ["سونامي"],    F(6000, 6000, 5000)),
            ("مازن",              ["مازن"],      F(8000, 7000, 5000)),
            ("طلبات متفرقة كولدن", ["متفرقه كولدن", "خارجيه متفرقه"], None),
        ],
        "others": None,        # أي متجر ثاني مو مذكور فوق: بدون خصم
        "warn_others": True,   # ويطلّع عليه تنبيه ⚠️ حتى تنتبه له
    }),
    ("خارجية متفرقة", {
        "rules": [
            ("أزياء رشا",     ["ازياء رشا"], F(6000, 6000, 5000)),
            ("مخور رشا",      ["مخور رشا"],  F(6000, 6000, 5000)),
            ("مكتبة الميثاق", ["الميثاق"],   F(3000, 3000, 3000)),
            ("طوق الحمامة", ["طوق الحمامة"], F(6000, 6000, 5000)),
            ("الحرمين", ["الحرمين"], F(6000, 6000, 5000)),
            ("ابن الأثير", ["ابن الأثير"], F(6000, 6000, 5000)),
            ("الكبيسي", ["الكبيسي"], F(6000, 6000, 5000)),
            ("عبد الرحمن", ["عبد الرحمن"], F(6000, 6000, 5000)),
            ("كنوز", ["كنوز"], F(6000, 6000, 5000)),
            ("المنهجية", ["المنهجية"], F(6000, 6000, 5000)),
            ("العلماء", ["العلماء"], F(6000, 6000, 5000)),
            ("المؤمنين", ["المؤمنين"], F(6000, 6000, 5000)),
            ("تبارك", ["تبارك"], F(6000, 6000, 5000)),
            ("خارجية متفرقة", ["خارجيه متفرقه", "متفرقه كولدن"], None),
        ],
        # باقي المكاتب: تنترك كما هي (بدون خصم).
        # إذا تريد عليهم خصم اكتب مثلاً:  F(6000, 6000, 5000)
        "others": None,
        "warn_others": False,
    }),
])

# ======================================================================
#                          أدوات النص العربي
# ======================================================================
_AR_LETTER = re.compile(r"[\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF]")
_PRESENTATION = re.compile(r"[\uFB50-\uFDFF\uFE70-\uFEFF]")
_MARKS = re.compile(r"[\u064B-\u065F\u0670\u0640]")  # تشكيل + تطويل
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def fix_cell(text):
    """pdfplumber يطلّع العربي مقلوب (ترتيب بصري) — هنا نرجّعه للترتيب الصحيح."""
    if not text:
        return ""
    visual = bool(_PRESENTATION.search(text))
    lines = []
    for line in str(text).split("\n"):
        words = line.split()
        if visual:
            words = [w[::-1] if _AR_LETTER.search(w) else w for w in words]
            words.reverse()
        lines.append(" ".join(words))
    out = unicodedata.normalize("NFKC", " ".join(l for l in lines if l))
    return re.sub(r"\s+", " ", _MARKS.sub("", out)).strip()


def norm(text):
    """تطبيع للمقارنة: توحيد الهمزات والياء والتاء المربوطة وحذف التشكيل."""
    s = unicodedata.normalize("NFKC", str(text or ""))
    s = _MARKS.sub("", s)
    for a, b in (("أ", "ا"), ("إ", "ا"), ("آ", "ا"), ("ٱ", "ا"), ("ى", "ي"), ("ئ", "ي"), ("ؤ", "و"), ("ة", "ه")):
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", s).strip().lower()


def to_int(text):
    t = str(text or "").translate(_DIGITS).replace(",", "").replace("٬", "")
    m = re.search(r"\d+(?:\.\d+)?", t)
    return int(round(float(m.group()))) if m else 0


def digits_only(text):
    return re.sub(r"\D", "", str(text or "").translate(_DIGITS))


def region_of(address):
    """أول كلمة بالعنوان هي المحافظة: بغداد / موصل / غيرها = محافظات."""
    words = norm(address).split()
    first = words[0] if words else ""
    if first.startswith("ال"):
        first = first[2:]
    if first == "بغداد":
        return "بغداد"
    if first == "موصل":
        return "موصل"
    return "محافظات"


# ======================================================================
#                            قراءة الـ PDF
# ======================================================================
DEFAULT_COLS = dict(amount=0, notes=1, goods=2, pieces=3, phone=4, address=5, ship=6, store=7)


def header_map(cells):
    """إذا الصف هو سطر العناوين يرجّع مواقع الأعمدة، وإلا None."""
    m = {}
    for i, c in enumerate(cells):
        h = norm(c)
        if "مبلغ" in h:
            m["amount"] = i
        elif "ملاحظ" in h:
            m["notes"] = i
        elif "بضاع" in h:
            m["goods"] = i
        elif "قطع" in h:
            m["pieces"] = i
        elif "هاتف" in h:
            m["phone"] = i
        elif "عنوان" in h:
            m["address"] = i
        elif "رقم" in h and "شحن" in h:
            m["ship"] = i
        elif "متجر" in h:
            m["store"] = i
    return m if {"amount", "address", "store"} <= set(m) else None


def declared_count(page):
    """عدد الشحنات المكتوب بأعلى الكشف (للتأكد إن ما فاتنا طلب)."""
    head = "\n".join((page.extract_text() or "").split("\n")[:8])
    m = re.search(r"عدد الشحنات\s*:?\s*(\d+)", fix_cell(head))
    return int(m.group(1)) if m else None


def to_order(cells, cols):
    def get(key):
        i = cols.get(key)
        return cells[i] if i is not None and i < len(cells) else ""

    ship, phone = digits_only(get("ship")), digits_only(get("phone"))
    if not (ship or phone):
        return None  # مو طلب (سطر فاضي أو مجموع)
    address = get("address")
    return {
        "ship": ship,
        "store": get("store"),
        "address": address,
        "phone": phone,
        "amount": to_int(get("amount")),
        "region": region_of(address),
        "fee": 0,
    }


def _cached(fn):
    """كاش لقراءة الملف (إذا نسخة ستريملت تدعمه) حتى ما ينقرأ كل مرة."""
    deco = getattr(st, "cache_data", None)
    return deco(show_spinner=False)(fn) if deco else fn


@_cached
def parse_pdf(data):
    """يرجّع (قائمة الطلبات ، عدد الشحنات المكتوب بالكشف)."""
    orders, declared, cols = [], None, None
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            if declared is None:
                declared = declared_count(page)
            for table in page.extract_tables():
                for row in table:
                    cells = [fix_cell(c) for c in row]
                    hm = header_map(cells)
                    if hm:
                        cols = hm
                        continue
                    order = to_order(cells, cols or DEFAULT_COLS)
                    if order:
                        orders.append(order)
    return orders, declared


# ======================================================================
#                              الحسابات
# ======================================================================
def money(n):
    return "\u200e" + f"{int(n):,}"


def describe_fees(fees):
    if not fees:
        return "بدون خصم"
    p, b, m = (fees[r] for r in REGIONS)
    if p == b == m:
        return f"{p:,} ثابت"
    if p == b:
        return f"{p:,} (موصل {m:,})"
    return f"محافظات {p:,} · بغداد {b:,} · موصل {m:,}"


def _words(text):
    """الاسم بعد التطبيع وحذف الرموز، محاط بمسافات حتى نقارن بالكلمة الكاملة.
    (ال التعريف ما تفرّق: «العلماء» = «علماء»)"""
    words = re.sub(r"[\W_]+", " ", norm(text)).split()
    words = [w[2:] if w.startswith("ال") and len(w) > 3 else w for w in words]
    return " " + " ".join(words) + " "


def resolve_store(store, cfg):
    """يرجّع (الاسم ، سعر التوصيل ، هل مذكور بالقواعد ، الترتيب)."""
    s = _words(store)
    for rank, (display, keys, fees) in enumerate(cfg["rules"]):
        if any(_words(k) in s for k in keys):
            return display, fees, True, rank
    return store, cfg.get("others"), False, len(cfg["rules"])


def calc_list1(orders, fees):
    for o in orders:
        o["fee"] = fees[o["region"]]
    total = sum(o["amount"] for o in orders)
    fee_total = sum(o["fee"] for o in orders)
    rows = []
    for r in REGIONS:
        n = sum(1 for o in orders if o["region"] == r)
        if n:
            rows.append({"المنطقة": r, "عدد الطلبات": n,
                         "سعر التوصيل": money(fees[r]), "مجموع الخصم": money(n * fees[r])})
    return total, fee_total, total - fee_total, rows


def calc_list2(orders, cfg):
    groups = OrderedDict()
    for o in orders:
        display, fees, known, rank = resolve_store(o["store"], cfg)
        o["fee"] = fees[o["region"]] if fees else 0
        key = display if known else norm(display)
        g = groups.setdefault(key, {"name": display, "rank": rank, "known": known,
                                    "fees": fees, "n": 0, "gross": 0, "fee": 0})
        g["n"] += 1
        g["gross"] += o["amount"]
        g["fee"] += o["fee"]
    return sorted(groups.values(), key=lambda g: g["rank"])  # sorted ثابت: يحافظ على ترتيب الظهور


# ======================================================================
#            كشف المبالغ للمتاجر (PDF) — بنفس شكل الجدول بالصورة
# ======================================================================
IRAQ_TZ = timezone(timedelta(hours=3))

# الكشوفات اللي تدخلها (بنفس هذا الترتيب)
REPORT_INPUTS = ["خارجية متفرقة", "متفرقة كولدن", "اونيلا", "روح", "نورا", "سارة", "ادينا", "فينوس"]

# سطور الجدول بنفس ترتيب الصورة:
#   (الاسم بالجدول ، من أي كشف ، اسم المتجر بالقواعد فوق)
#   اسم المتجر None = الكشف كله لهذا المتجر (القائمة الأولى)
REPORT_ROWS = [
    ("ازياء رشا",      "خارجية متفرقة", "أزياء رشا"),
    ("مخور رشا",       "خارجية متفرقة", "مخور رشا"),
    ("ميثاق",          "خارجية متفرقة", "مكتبة الميثاق"),
    ("ادينا",          "ادينا",         None),
    ("اونيلا",         "اونيلا",        None),
    ("روح",            "روح",           None),
    ("نورا",           "نورا",          None),
    ("سارة",           "سارة",          None),
    ("فينوس",          "فينوس",         None),
    ("Valure lingeri", "متفرقة كولدن",  "Velure lingeri"),
    ("حذيفة براند",    "متفرقة كولدن",  "حذيفة براند"),
    ("برو",            "متفرقة كولدن",  "أزياء برو"),
    ("توتة",           "متفرقة كولدن",  "توتة"),
    ("شي براند",       "متفرقة كولدن",  "شي براند"),
    ("سونامي",         "متفرقة كولدن",  "سونامي"),
    ("سوز",            "متفرقة كولدن",  "سوز"),
    ("زيزفونة",        "متفرقة كولدن",  "زيزفونة"),
    ("تبارك",          "خارجية متفرقة", "تبارك"),
    ("المؤمنين",       "خارجية متفرقة", "المؤمنين"),
    ("العلماء",        "خارجية متفرقة", "العلماء"),
    ("المنهجية",       "خارجية متفرقة", "المنهجية"),
    ("كنوز",           "خارجية متفرقة", "كنوز"),
    ("عبد",            "خارجية متفرقة", "عبد الرحمن"),
    ("كبيسي",          "خارجية متفرقة", "الكبيسي"),
    ("ابن الأثير",     "خارجية متفرقة", "ابن الأثير"),
    ("الحرمين",        "خارجية متفرقة", "الحرمين"),
    ("كاريزا",         "متفرقة كولدن",  "أزياء كاريزا"),
    ("مازن",           "متفرقة كولدن",  "مازن"),
    ("طوق",            "خارجية متفرقة", "طوق الحمامة"),
]

# ---------- تشكيل الحروف العربية (بدون مكتبات إضافية) ----------
_FORMS = {}
_AR_ANY = re.compile(r"[\u0600-\u06FF\uFB50-\uFDFF\uFE70-\uFEFF]")


def _arabic_forms():
    """جدول أشكال الحروف (معزول/أول/وسط/آخر) نبنيه من يونيكود نفسه."""
    if not _FORMS:
        for cp in range(0xFE80, 0xFEFD):
            dec = unicodedata.decomposition(chr(cp))
            if dec.startswith("<"):
                tag, _, rest = dec[1:].partition("> ")
                base = "".join(chr(int(x, 16)) for x in rest.split())
                _FORMS.setdefault(base, {})[tag] = chr(cp)
    return _FORMS


def shape(text):
    """يحوّل الحروف العربية لأشكالها المتصلة (أول/وسط/آخر) حتى تنكتب صح بالـPDF."""
    forms = _arabic_forms()
    items, i = [], 0
    while i < len(text):
        if text[i] == "ل" and i + 1 < len(text) and text[i + 1] in "آأإا":
            items.append(text[i:i + 2])  # لام + ألف = حرف واحد (لا)
            i += 2
        else:
            items.append(text[i])
            i += 1

    def to_next(it):  # يقدر يتصل بالحرف اللي بعده
        return it == "\u0640" or "initial" in forms.get(it, {})

    def to_prev(it):  # يقدر يتصل بالحرف اللي قبله
        return it == "\u0640" or "final" in forms.get(it, {})

    out = []
    for k, it in enumerate(items):
        fm = forms.get(it)
        if not fm:
            out.append(it)
            continue
        prev_ok = k > 0 and to_next(items[k - 1]) and to_prev(it)
        next_ok = k + 1 < len(items) and to_next(it) and to_prev(items[k + 1])
        tag = "medial" if prev_ok and next_ok else "final" if prev_ok else "initial" if next_ok else "isolated"
        out.append(fm.get(tag) or fm.get("isolated") or it)
    return "".join(out)


def visual(text):
    """النص العربي مشكّل وبترتيب العرض (يسار←يمين) حتى ينرسم صح بالـPDF."""
    s = shape(text)
    if not _AR_ANY.search(s):
        return s
    runs = []
    for tok in s.split(" "):
        is_ar = bool(_AR_ANY.search(tok))
        if runs and runs[-1][0] == is_ar:
            runs[-1][1].append(tok)
        else:
            runs.append((is_ar, [tok]))
    parts = [" ".join(t[::-1] for t in reversed(toks)) if is_ar else " ".join(toks)
             for is_ar, toks in reversed(runs)]
    return " ".join(parts)


def _find_font(names):
    """يدور على الخط بجنب app.py، وبعدين بمجلدات الخطوط المعروفة."""
    here = os.path.dirname(os.path.abspath(globals().get("__file__", ".")))
    folders = [here, os.path.join(here, "fonts"),
               "/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/dejavu", "/usr/share/fonts/TTF",
               "/Library/Fonts", "/System/Library/Fonts/Supplemental", "C:/Windows/Fonts"]
    for folder in folders:
        for name in names:
            path = os.path.join(folder, name)
            if os.path.isfile(path):
                return path
    return None


def build_report_pdf(rows, total, date_text):
    """يرسم الجدول ويرجّع الـPDF (bytes).  rows = [{"no", "label", "amount"}]"""
    try:
        from reportlab.lib.colors import HexColor
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.pdfgen import canvas
    except ImportError:
        raise RuntimeError("ينقص مكتبة reportlab — ضيفها بملف requirements.txt") from None

    path = _find_font(["DejaVuSans-Bold.ttf", "arialbd.ttf", "Arial Bold.ttf", "tahomabd.ttf"])
    if not path:
        raise RuntimeError("ما لكيت خط عربي — حط ملف DejaVuSans-Bold.ttf بنفس مكان app.py")
    if "KashfBold" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("KashfBold", path))

    W, H = A4
    M, gap = 24, 7
    title_h, head_h, foot_h = 32, 24, 26
    x0, x1 = M, W - M
    tw = x1 - x0
    n = len(rows)
    row_h = min(26.0, (H - 2 * M - title_h - head_h - foot_h - 2 * gap) / n)

    white, blue, grid = HexColor("#FFFFFF"), HexColor("#213B8E"), HexColor("#CBD5E6")
    alt, ser, ink = HexColor("#F3F6FB"), HexColor("#E8EDF6"), HexColor("#1B2540")
    foot, border, head_line = HexColor("#DEE4EF"), HexColor("#B9C5DD"), HexColor("#5B72B5")

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle("Kashf almabaligh")

    def put(s, x, y_mid, size, color, align):
        c.setFillColor(color)
        c.setFont("KashfBold", size)
        draw = {"r": c.drawRightString, "c": c.drawCentredString, "l": c.drawString}[align]
        draw(x, y_mid - size * 0.36, visual(s))

    # شريط العنوان
    top = H - M
    c.setFillColor(blue)
    c.roundRect(x0, top - title_h, tw, title_h, 5, stroke=0, fill=1)
    put("جدول كشف المبالغ للمتاجر", (x0 + x1) / 2, top - title_h / 2, 15, white, "c")

    # الأعمدة من اليمين لليسار: تسلسل | اسم المتجر | صاعد | رواجع
    edges = [x1]
    for w in (0.10, 0.46, 0.22):
        edges.append(edges[-1] - w * tw)
    edges.append(x0)
    t_top = top - title_h - gap
    body_top = t_top - head_h
    t_bot = body_top - n * row_h

    # رأس الجدول
    c.setFillColor(blue)
    c.rect(x0, body_top, tw, head_h, stroke=0, fill=1)
    for i, h in enumerate(("التسلسل", "اسم المتجر", "صاعد", "رواجع")):
        put(h, (edges[i] + edges[i + 1]) / 2, t_top - head_h / 2, 10.5, white, "c")
    c.setStrokeColor(head_line)
    c.setLineWidth(0.6)
    for e in edges[1:-1]:
        c.line(e, t_top, e, body_top)

    # السطور
    for i, r in enumerate(rows):
        y = body_top - (i + 1) * row_h
        c.setFillColor(alt if i % 2 else white)
        c.rect(x0, y, tw, row_h, stroke=0, fill=1)
        c.setFillColor(ser)
        c.rect(edges[1], y, edges[0] - edges[1], row_h, stroke=0, fill=1)
        mid = y + row_h / 2
        put(str(r["no"]), (edges[0] + edges[1]) / 2, mid, 11, ink, "c")
        put(r["label"], edges[1] - 9, mid, 10.5, ink, "r")
        if r["amount"] is not None:
            put(f"{r['amount']:,}", (edges[2] + edges[3]) / 2, mid, 11, ink, "c")

    # الخطوط
    c.setStrokeColor(grid)
    c.setLineWidth(0.6)
    for i in range(1, n):
        y = body_top - i * row_h
        c.line(x0, y, x1, y)
    for e in edges[1:-1]:
        c.line(e, body_top, e, t_bot)
    c.setStrokeColor(border)
    c.setLineWidth(0.9)
    c.rect(x0, t_bot, tw, t_top - t_bot, stroke=1, fill=0)

    # الشريط السفلي: المجموع الكلي + التاريخ
    c.setFillColor(foot)
    c.roundRect(x0, M, tw, foot_h, 5, stroke=0, fill=1)
    put(f"المجموع الكلي: {total:,}", x1 - 12, M + foot_h / 2, 11, ink, "r")
    put(f"التاريخ: {date_text}", x0 + 0.36 * tw, M + foot_h / 2, 11, ink, "r")

    c.showPage()
    c.save()
    return buf.getvalue()


# ======================================================================
#                              الواجهة
# ======================================================================
CSS = """
<style>
.stApp { direction: rtl; text-align: right; }
.stApp h1, .stApp h2, .stApp h3, .stApp p, .stApp label, .stApp li { text-align: right; }
[data-testid="stMetric"] { text-align: right; }
[data-testid="stTable"] table { direction: rtl; }
pre, code { direction: ltr; unicode-bidi: plaintext; text-align: start; }
</style>
"""


def show_df(df):
    try:
        st.dataframe(df, hide_index=True)
    except TypeError:  # نسخ ستريملت القديمة
        st.dataframe(df)


def load_orders(files):
    orders, first = [], {}
    for idx, f in enumerate(files):
        try:
            found, declared = parse_pdf(f.getvalue())
        except Exception as e:  # noqa: BLE001
            st.error(f"ما كدرت أقرأ الملف «{f.name}»: {e}")
            continue
        dups = []
        for o in found:
            ship = o["ship"]
            if ship and ship in first:  # نفس رقم الشحنة انحسب قبل
                dups.append((ship, first[ship]))
                continue
            if ship:
                first[ship] = (idx, f.name)
            orders.append(o)
        if declared is not None and declared != len(found):
            st.warning(f"⚠️ «{f.name}»: الكشف مكتوب بيه {declared} شحنة بس انقرأ {len(found)} — "
                       "راجع الملف قبل ما تعتمد الحساب.")
        elif declared is not None:
            st.caption(f"✅ «{f.name}»: {len(found)} طلب (مطابق لعدد الشحنات بالكشف)")
        else:
            st.caption(f"📄 «{f.name}»: {len(found)} طلب")
        if dups:
            parts = [f"{ship} (أصله بـ " + ("نفس الملف" if i == idx else f"«{name}»") + ")"
                     for ship, (i, name) in dups[:5]]
            more = f" … و{len(dups) - 5} غيرها" if len(dups) > 5 else ""
            st.warning(f"⚠️ {len(dups)} طلب مكرر (نفس رقم الشحنة) بـ «{f.name}» انتجاهل وانحسب مرة وحدة: "
                       + " ، ".join(parts) + more)
    return orders


def ask_orders(key):
    files = st.file_uploader("ارفع ملف الكشف (PDF)", type=["pdf"],
                             accept_multiple_files=True, key=key)
    if not files:
        st.info("ارفع الكشف حتى ينحسب.")
        return []
    orders = load_orders(files)
    if not orders:
        st.error("ما لكيت طلبات داخل الملف. تأكد انه كشف برايم الأصلي.")
    return orders


def zero_note(orders):
    z = sum(1 for o in orders if o["amount"] == 0)
    if z:
        st.info(f"ℹ️ فيه {z} طلب مبلغه 0 — انحسب عليه التوصيل مثل باقي الطلبات.")


def warn_foreign(orders, name):
    """تنبيه إذا الكشف فيه متجر غير الاسم المختار."""
    key = norm(name)
    foreign = [o for o in orders if key not in norm(o["store"])]
    if foreign:
        names = " ، ".join(sorted({o["store"] for o in foreign}))
        st.warning(f"⚠️ {len(foreign)} طلب باسم متجر غير «{name}»: {names} — "
                   "تأكد انك مختار الاسم الصحيح.")


def details_table(orders):
    df = pd.DataFrame([{
        "رقم الشحنة": o["ship"], "المتجر": o["store"], "المنطقة": o["region"],
        "العنوان": o["address"], "المبلغ": money(o["amount"]),
        "التوصيل": money(o["fee"]), "الصافي": money(o["amount"] - o["fee"]),
    } for o in orders])
    with st.expander("تفاصيل الطلبات واحد واحد (للتأكد)"):
        show_df(df)


def show_list1(name):
    fees = LIST1[name]
    st.caption("سعر التوصيل لكل طلب: " + describe_fees(fees))
    orders = ask_orders("up1")
    if not orders:
        return

    warn_foreign(orders, name)

    total, fee_total, net, rows = calc_list1(orders, fees)
    c1, c2, c3 = st.columns(3)
    c1.metric("عدد الطلبات", len(orders))
    c2.metric("مجموع الكشف", money(total))
    c3.metric("خصم التوصيل", money(fee_total))
    st.success(f"✅ الصافي لـ {name}:  {money(net)} د.ع")
    st.table(pd.DataFrame(rows).set_index("المنطقة"))
    zero_note(orders)
    details_table(orders)
    st.code(f"{name}\nعدد الطلبات: {len(orders)}\nمجموع الكشف: {money(total)}\n"
            f"خصم التوصيل: {money(fee_total)}\nالصافي: {money(net)}", language=None)


def show_list2(name):
    cfg = LIST2[name]
    orders = ask_orders("up2")
    if not orders:
        return

    groups = calc_list2(orders, cfg)
    rows, lines = [], [name]
    tot_n = tot_gross = tot_fee = 0
    unknown = []
    for g in groups:
        flag = " ⚠️" if (not g["known"] and cfg.get("warn_others")) else ""
        if flag:
            unknown.append(g["name"])
        net = g["gross"] - g["fee"]
        rows.append({"المتجر": g["name"] + flag, "الطلبات": g["n"],
                     "المجموع": money(g["gross"]), "الخصم": money(g["fee"]),
                     "الصافي": money(net), "نوع الخصم": describe_fees(g["fees"])})
        lines.append(f"{g['name']} ({g['n']} طلب): {money(net)}")
        tot_n += g["n"]
        tot_gross += g["gross"]
        tot_fee += g["fee"]
    rows.append({"المتجر": "الإجمالي", "الطلبات": tot_n, "المجموع": money(tot_gross),
                 "الخصم": money(tot_fee), "الصافي": money(tot_gross - tot_fee), "نوع الخصم": ""})
    lines.append(f"الإجمالي: {money(tot_gross - tot_fee)}")

    if unknown:
        st.warning("⚠️ هذي المتاجر مو مذكورة بالقواعد فانحسبت بدون خصم: " + " ، ".join(unknown))
    c1, c2, c3 = st.columns(3)
    c1.metric("عدد الطلبات", tot_n)
    c2.metric("المجموع", money(tot_gross))
    c3.metric("الخصم", money(tot_fee))
    st.success(f"✅ الصافي الكلي:  {money(tot_gross - tot_fee)} د.ع")
    st.table(pd.DataFrame(rows).set_index("المتجر"))
    zero_note(orders)
    details_table(orders)
    st.code("\n".join(lines), language=None)


def collect_report(uploads):
    """يرجّع (صافي كل سطر بالجدول ، الباقي اللي ما إله سطر بالجدول)."""
    wanted = {(inp, norm(key) if key else None) for _, inp, key in REPORT_ROWS}
    nets, extra, seen_in, cross = {}, [], {}, []
    for inp, files in uploads.items():
        if not files:
            continue
        orders = load_orders(files)
        if not orders:
            continue
        for o in orders:  # نفس رقم الشحنة بخانتين مختلفتين؟
            if o["ship"]:
                other = seen_in.setdefault(o["ship"], inp)
                if other != inp:
                    cross.append((o["ship"], other, inp))
        if inp in LIST1:
            warn_foreign(orders, inp)
            net = calc_list1(orders, LIST1[inp])[2]
            nets[(inp, None)] = nets.get((inp, None), 0) + net
            continue
        cfg = LIST2[inp]
        for g in calc_list2(orders, cfg):
            net = g["gross"] - g["fee"]
            k = (inp, norm(g["name"]))
            if g["known"] and k in wanted:
                nets[k] = nets.get(k, 0) + net
            else:
                why = describe_fees(g["fees"])
                if not g["known"] and cfg.get("warn_others"):
                    why += " ⚠️ مو مذكور بالقواعد"
                extra.append((inp, g["name"], g["n"], net, why))
    if cross:
        more = f" … و{len(cross) - 5} غيرها" if len(cross) > 5 else ""
        st.warning("⚠️ نفس رقم الشحنة موجود بكشفين مختلفين وانحسب بالاثنين — راجع: "
                   + " ، ".join(f"{ship} («{x}» و«{y}»)" for ship, x, y in cross[:5]) + more)
    return nets, extra


def show_report():
    st.caption("ارفع الكشوفات كل وحدة بمكانها (مو لازم كلها)، وبالنهاية ينطيك PDF بنفس شكل الجدول "
               "وعمود «صاعد» بيه صافي كل محل بعد خصم التوصيل.")
    uploads = {}
    for name in REPORT_INPUTS:
        uploads[name] = st.file_uploader(f"كشف {name}", type=["pdf"],
                                         accept_multiple_files=True, key="rep_" + name)
    day = st.date_input("التاريخ", value=datetime.now(IRAQ_TZ).date())
    if not any(uploads.values()):
        st.info("ارفع كشف واحد على الأقل حتى ينعمل الجدول.")
        return

    nets, extra = collect_report(uploads)
    rows = [{"no": i, "label": label, "amount": nets.get((inp, norm(key) if key else None))}
            for i, (label, inp, key) in enumerate(REPORT_ROWS, 1)]
    total = sum(r["amount"] for r in rows if r["amount"] is not None)

    st.success(f"✅ المجموع الكلي:  {money(total)} د.ع")
    if extra:
        st.info("خارج الجدول (ما انكتبوا بالـPDF):\n" + "\n".join(
            f"- {name} ({inp}): {n} طلب — {money(net)} — {why}" for inp, name, n, net, why in extra))
    show_df(pd.DataFrame([{"التسلسل": r["no"], "اسم المتجر": r["label"],
                           "صاعد": "" if r["amount"] is None else money(r["amount"])} for r in rows]))

    date_text = f"{day.day:02d} / {day.month:02d} / {day.year} م"
    try:
        pdf = build_report_pdf(rows, total, date_text)
    except Exception as e:  # noqa: BLE001
        st.error(f"ما كدرت أسوي الـPDF: {e}")
        return
    st.download_button("⬇️ تحميل كشف المبالغ (PDF)", data=pdf,
                       file_name=f"كشف_المبالغ_{day.isoformat()}.pdf", mime="application/pdf")


def main():
    st.set_page_config(page_title="حاسبة يوسف الأسطورة", page_icon="🧮")
    st.markdown(CSS, unsafe_allow_html=True)
    st.title("🧮 حاسبة يوسف الأسطورة")

    menu = st.radio("القائمة", ["القائمة الأولى", "القائمة الثانية", "كشف المبالغ PDF"], horizontal=True)
    if menu == "القائمة الأولى":
        show_list1(st.selectbox("اختر المتجر", list(LIST1)))
    elif menu == "القائمة الثانية":
        show_list2(st.selectbox("اختر الكشف", list(LIST2)))
    else:
        show_report()


if __name__ == "__main__":
    main()
