import os, re, json, random, sqlite3, datetime
from flask import Flask, request, jsonify, Response

# بيانات تجريبية — استبدلها بمستندات رسمية من بلدية مسقط قبل أي استخدام فعلي.
CATEGORIES = {
    "roads": ("الطرق والأرصفة", ["حفرة", "طريق", "رصيف", "اسفلت", "أسفلت", "إشارة", "حفر"]),
    "lighting": ("الإنارة", ["إنارة", "انارة", "عمود", "كهرباء", "مصباح", "كيبل", "كابل"]),
    "waste": ("النظافة والنفايات", ["نفايات", "زبالة", "قمامة", "حاوية", "نظافة"]),
    "water": ("المياه والصرف", ["تسرب", "مياه", "صرف", "مجاري", "تجمع"]),
    "pests": ("الصحة العامة والآفات", ["حشرات", "فئران", "قوارض", "بعوض", "آفات"]),
    "building": ("مخالفات البناء", ["بناء", "مخالفة", "تعدي", "سور", "ترخيص"]),
}
CAT_EN = {"roads": "Roads & sidewalks", "lighting": "Lighting", "waste": "Waste & cleanliness",
          "water": "Water & drainage", "pests": "Public health & pests", "building": "Building violations", "other": "Other"}
EN_KW = {"roads": ["pothole", "road", "sidewalk", "asphalt", "traffic light"],
         "lighting": ["street light", "streetlight", "light pole", "lamp", "cable", "wire", "electric"],
         "waste": ["trash", "garbage", "waste", "bin", "dumpster"],
         "water": ["leak", "water", "sewage", "drain", "flood"],
         "pests": ["pest", "rats", "mosquito", "insects", "rodent"],
         "building": ["construction", "violation", "encroach", "wall", "building"]}
EN_DANGER = ["exposed wire", "exposed cable", "exposed electric", "live wire", "collapse", "fire", "gas leak", "electrocut", "drowning"]
EN_URGENT = ["big pothole", "deep", "major leak", "flooding", "overflow", "danger"]
DANGER_WORDS = ["كهرباء مكشوفة", "كيبل مكشوف", "كابل مكشوف", "سلك مكشوف", "انهيار", "حريق", "غاز", "صعق", "غرق"]
URGENT_WORDS = ["حفرة كبيرة", "عميقة", "تسرب كبير", "فيضان", "مجاري طافحة", "خطر"]

KNOWLEDGE = [
    {"title": "رخصة البناء", "kw": ["رخصة بناء", "بناء", "ترخيص بناء"],
     "text": "تُقدَّم الطلبات عبر نظام البلدية الإلكتروني مع مخططات معتمدة من مكتب هندسي، وصك الملكية، وخريطة الموقع. المدة التقديرية 10–20 يوم عمل."},
    {"title": "رخصة محل تجاري", "kw": ["محل", "رخصة تجارية", "نشاط"],
     "text": "يلزم سجل تجاري ساري، وعقد إيجار أو ملكية، وموافقة الدفاع المدني والصحة حسب النشاط. المدة التقديرية 5–7 أيام عمل."},
    {"title": "الإبلاغ عن مشكلة ميدانية", "kw": ["بلاغ", "شكوى", "ابلاغ"],
     "text": "يمكن فتح بلاغ عبر هذا الوكيل بذكر المشكلة والموقع. يُعطى رقم مرجعي (MCT-xxxxxx) للمتابعة."},
    {"title": "حالات الطوارئ", "kw": ["طوارئ", "خطر", "حريق"],
     "text": "في الحالات الخطرة على السلامة اتصل بالرقم 9999 فورًا قبل أي بلاغ."},
]

_EN = [("Building permit", ["building", "permit", "construction"], "Applications are submitted through the municipality e-system with engineer-approved drawings, the title deed and a site map. Estimated time: 10-20 working days."),
       ("Shop license", ["shop", "store", "commercial", "business"], "Requires a valid commercial registration, a lease or ownership document, and Civil Defence and Health approvals depending on the activity. Estimated time: 5-7 working days."),
       ("Reporting a field problem", ["report", "complaint"], "Open a report by describing the problem and its location. You get a reference number (MCT-xxxxxx) to track it."),
       ("Emergencies", ["emergency", "danger", "fire"], "For safety hazards call 9999 immediately, before filing any report.")]
for _k, (_t, _kw, _x) in zip(KNOWLEDGE, _EN):
    _k.update(title_en=_t, kw_en=_kw, text_en=_x)

FEES = {
    "building_permit": {"name": "رخصة بناء", "per_m2": 0.750, "min": 25.0},
    "shop_license": {"name": "رخصة محل تجاري", "flat": 50.0},
    "signboard": {"name": "لوحة إعلانية", "per_m2": 4.0, "min": 10.0},
    "demolition": {"name": "تصريح هدم", "per_m2": 0.250, "min": 15.0},
}


DB = os.environ.get("DB_PATH", "reports.db")

def _db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS reports(
        ref TEXT PRIMARY KEY, category TEXT, urgency TEXT, description TEXT,
        location TEXT, contact TEXT, status TEXT, created TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS updates(
        ref TEXT, ts TEXT, note TEXT)""")
    return c

# لوائح واشتراطات تجريبية — ليست نصوصًا رسمية؛ استبدلها بالمستندات الرسمية للبلدية.
REGS = [
 dict(cat_ar="البناء", cat_en="Building", title_ar="رخصة البناء", title_en="Building permit",
      text_ar="لا يجوز البدء بالبناء قبل الحصول على الرخصة. يلزم تقديم مخططات معتمدة من مكتب هندسي، وصك الملكية، وخريطة الموقع عبر نظام البلدية الإلكتروني.",
      text_en="Construction must not start before the permit is issued. Applicants submit engineer-approved drawings, the title deed and the site map through the municipality e-system.",
      kw="رخصة بناء ترخيص مخططات building permit construction drawings"),
 dict(cat_ar="البناء", cat_en="Building", title_ar="الأسوار والارتدادات", title_en="Boundary walls and setbacks",
      text_ar="يجب أن تلتزم الأسوار والارتدادات عن حدود الأرض بالمخطط المعتمد، ولا يجوز التعدي على الشارع أو الأرض المجاورة.",
      text_en="Boundary walls and setbacks from the plot line must follow the approved plan. Encroaching on the street or a neighbouring plot is not allowed.",
      kw="سور اسوار ارتداد تعدي حدود wall fence setback encroachment boundary"),
 dict(cat_ar="البناء", cat_en="Building", title_ar="تصريح الهدم", title_en="Demolition permit",
      text_ar="يلزم الحصول على تصريح قبل هدم أي مبنى، مع تأمين الموقع وإزالة المخلفات إلى المواقع المخصصة.",
      text_en="A permit is required before demolishing any building. The site must be secured and debris taken to designated sites.",
      kw="هدم تصريح demolition permit"),
 dict(cat_ar="البناء", cat_en="Building", title_ar="السلامة في مواقع البناء", title_en="Safety at construction sites",
      text_ar="يجب تسييج موقع العمل ووضع لافتات تحذيرية والحفاظ على سلامة المارة والجيران طوال فترة التنفيذ.",
      text_en="Work sites must be fenced and carry warning signs, and passers-by and neighbours must be kept safe throughout construction.",
      kw="سلامة موقع تسييج لافتات عمال safety site fence signs workers"),
 dict(cat_ar="التراخيص التجارية", cat_en="Business licensing", title_ar="رخصة محل تجاري", title_en="Shop license",
      text_ar="يلزم سجل تجاري ساري، وعقد إيجار أو وثيقة ملكية، وموافقات الجهات المعنية (مثل الدفاع المدني والصحة) حسب نوع النشاط.",
      text_en="Requires a valid commercial registration, a lease or ownership document, and approvals from relevant bodies (such as Civil Defence and Health) depending on the activity.",
      kw="محل تجاري نشاط سجل تجاري shop store commercial business license"),
 dict(cat_ar="التراخيص التجارية", cat_en="Business licensing", title_ar="اللوحات الإعلانية", title_en="Signboards and advertising",
      text_ar="تحتاج اللوحات الإعلانية وواجهات المحلات إلى تصريح، ويجب أن تكون ضمن المقاسات والمواقع المسموحة وألا تعيق الرؤية أو المرور.",
      text_en="Signboards and shopfront advertising need a permit, must stay within allowed sizes and locations, and must not block visibility or traffic.",
      kw="لوحة لوحات اعلان اعلانية signboard sign advertising billboard"),
 dict(cat_ar="الصحة العامة", cat_en="Public health", title_ar="اشتراطات المنشآت الغذائية", title_en="Food establishment requirements",
      text_ar="تلتزم المنشآت الغذائية بالنظافة العامة وتخزين الأغذية بشكل سليم والحصول على الموافقة الصحية قبل التشغيل.",
      text_en="Food establishments must keep premises clean, store food properly and obtain health approval before operating.",
      kw="مطعم غذاء اغذية مقهى صحية food restaurant cafe health hygiene"),
 dict(cat_ar="الصحة العامة", cat_en="Public health", title_ar="مكافحة الحشرات والقوارض", title_en="Pest control",
      text_ar="يتحمل مالك المنشأة أو المبنى مسؤولية منع انتشار الحشرات والقوارض، ويمكن الإبلاغ عن الأماكن التي تنتشر فيها.",
      text_en="Owners are responsible for preventing pests and rodents on their premises. Areas with infestations can be reported to the municipality.",
      kw="حشرات فئران قوارض بعوض آفات pest rats rodents mosquito insects"),
 dict(cat_ar="النظافة والنفايات", cat_en="Waste and cleanliness", title_ar="النفايات والنظافة العامة", title_en="Waste and public cleanliness",
      text_ar="يُمنع رمي النفايات خارج الحاويات المخصصة أو في الأماكن العامة. يمكن الإبلاغ عن الحاويات الممتلئة أو التجمعات العشوائية للنفايات.",
      text_en="Dumping waste outside designated containers or in public places is not allowed. Full containers and illegal dumping can be reported.",
      kw="نفايات زبالة قمامة حاوية نظافة رمي waste garbage trash bin dumping littering"),
 dict(cat_ar="النظافة والنفايات", cat_en="Waste and cleanliness", title_ar="مخلفات البناء", title_en="Construction debris",
      text_ar="على المقاول أو المالك إزالة مخلفات البناء إلى المواقع المخصصة، ولا يجوز تركها في الشوارع أو الأراضي الفضاء.",
      text_en="The contractor or owner must remove construction debris to designated sites and must not leave it in streets or vacant land.",
      kw="مخلفات انقاض بناء ركام debris rubble construction waste"),
 dict(cat_ar="الطرق والمرافق", cat_en="Roads and utilities", title_ar="الحفر في الطرق العامة", title_en="Excavation in public roads",
      text_ar="لا يجوز الحفر في الطرق أو الأرصفة العامة دون تصريح، ويجب إعادة الوضع كما كان وتأمين موقع الحفر.",
      text_en="Digging in public roads or sidewalks needs a permit. The surface must be restored afterwards and the excavation secured.",
      kw="حفر حفرة طريق رصيف اسفلت excavation digging road sidewalk pothole asphalt"),
 dict(cat_ar="الطرق والمرافق", cat_en="Roads and utilities", title_ar="الإنارة والكابلات الكهربائية", title_en="Street lighting and electric cables",
      text_ar="يُبلَّغ عن أعمدة الإنارة المعطلة والكابلات المكشوفة. في حال وجود خطر على السلامة يجب الاتصال بالرقم 9999 أولًا.",
      text_en="Faulty street lights and exposed cables can be reported. If there is a safety risk, call 9999 first.",
      kw="انارة إنارة عمود كهرباء كابل كيبل مكشوف street light lighting pole cable exposed electric"),
 dict(cat_ar="الطرق والمرافق", cat_en="Roads and utilities", title_ar="تسرب المياه والصرف", title_en="Water leaks and drainage",
      text_ar="يمكن الإبلاغ عن تسرب المياه وطفح المجاري وتجمع المياه في الشوارع. يلتزم المالك بصيانة شبكة الصرف داخل ملكه.",
      text_en="Water leaks, sewage overflow and standing water in streets can be reported. Owners must maintain drainage inside their property.",
      kw="تسرب مياه صرف مجاري تجمع طفح leak water sewage drain flood overflow"),
]

def find_regs(query, limit=8):
    q = (query or "").strip().lower()
    if not q:
        return REGS[:limit]
    stop = {"the", "and", "for", "are", "what", "how", "about", "with", "that", "rules", "regulations", "requirements",
            "الخاصة", "اللوائح", "لائحة", "لوائح", "اشتراطات", "اشتراط", "الخاص", "حول", "عن"}
    words = [w for w in re.split(r"[\s,.;:!?؟،]+", q) if len(w) >= 3 and w not in stop]
    cands = set()
    for w in words:
        cands.add(w)
        for p in ("وبال", "بال", "وال", "لل", "ال", "ب", "ل", "و"):
            if w.startswith(p) and len(w) - len(p) >= 3:
                cands.add(w[len(p):])
    if not cands:
        return REGS[:limit]
    scored = []
    for r in REGS:
        blob = " ".join([r["title_ar"], r["title_en"], r["text_ar"], r["text_en"], r["kw"], r["cat_ar"], r["cat_en"]]).lower()
        sc = sum(w in blob for w in cands)
        if sc:
            scored.append((sc, r))
    scored.sort(key=lambda x: -x[0])
    return [r for _, r in scored[:limit]]


def classify_issue(description, lang="ar"):
    d = description
    dl = d.lower()
    cat, best = "other", 0
    for key, (name, words) in CATEGORIES.items():
        n = sum(w in d for w in words) + sum(w in dl for w in EN_KW.get(key, []))
        if n > best:
            cat, best = key, n
    safety = (any(w in d for w in DANGER_WORDS) or any(w in dl for w in EN_DANGER)
              or ("مكشوف" in d and any(w in d for w in ["كهرباء", "كيبل", "كابل", "سلك"]))
              or ("exposed" in dl and any(w in dl for w in ["electric", "wire", "cable"])))
    urgency = "high" if safety or any(w in d for w in URGENT_WORDS) or any(w in dl for w in EN_URGENT) else "normal"
    name = CAT_EN[cat] if lang == "en" else CATEGORIES.get(cat, ("أخرى",))[0]
    return {"category": cat, "category_name": name, "urgency": urgency, "safety_risk": safety,
            "note": "اطلب من المستخدم الاتصال بـ 9999 أولًا" if safety else ""}

def open_report(category, urgency, description, location, contact=""):
    if not location.strip():
        return {"error": "الموقع مطلوب"}
    ref = "MCT-%06d" % random.randint(0, 999999)
    now = datetime.datetime.now().isoformat(timespec="seconds")
    with _db() as c:
        c.execute("INSERT INTO reports VALUES(?,?,?,?,?,?,?,?)",
                  (ref, category, urgency, description, location, contact, "تم الاستلام", now))
        c.execute("INSERT INTO updates VALUES(?,?,?)", (ref, now, "تم استلام البلاغ"))
    return {"ref": ref, "status": "تم الاستلام"}

def track_report(ref):
    ref = ref.strip().upper()
    with _db() as c:
        r = c.execute("SELECT * FROM reports WHERE ref=?", (ref,)).fetchone()
        if not r:
            return {"error": "لا يوجد بلاغ بهذا الرقم"}
        ups = [dict(u) for u in c.execute("SELECT ts, note FROM updates WHERE ref=? ORDER BY ts", (ref,))]
    return {**dict(r), "updates": ups}

def search_knowledge(query):
    ql = query.lower()
    hits = [k for k in KNOWLEDGE if any(w in query for w in k["kw"]) or k["title"] in query or any(w in ql for w in k.get("kw_en", []))]
    regs = [{"title_ar": r["title_ar"], "title_en": r["title_en"], "text_ar": r["text_ar"], "text_en": r["text_en"]} for r in find_regs(query, 4)]
    res = hits + regs
    return {"results": res, "note": "بيانات تجريبية" if res else "لا نتائج؛ قل للمستخدم أنك لا تملك المعلومة ولا تخمّن"}

def calc_fee(service, area_m2=0):
    f = FEES.get(service)
    if not f:
        return {"error": "خدمة غير معروفة", "available": {k: v["name"] for k, v in FEES.items()}}
    fee = f["flat"] if "flat" in f else max(f["min"], f["per_m2"] * float(area_m2))
    return {"service": f["name"], "area_m2": area_m2, "fee_omr": round(fee, 3), "note": "رسوم تجريبية"}

FUNCS = {"classify_issue": classify_issue, "open_report": open_report,
         "track_report": track_report, "search_knowledge": search_knowledge, "calc_fee": calc_fee}

def _t(name, desc, props, req):
    return {"name": name, "description": desc,
            "input_schema": {"type": "object", "properties": props, "required": req}}
S = {"type": "string"}
TOOLS = [
    _t("classify_issue", "صنّف المشكلة وقدّر الاستعجال وهل فيها خطر على السلامة", {"description": S}, ["description"]),
    _t("open_report", "افتح بلاغًا ميدانيًا بعد توفر الوصف والموقع", {"category": S, "urgency": {"type": "string", "enum": ["normal", "high"]}, "description": S, "location": S, "contact": S}, ["category", "urgency", "description", "location"]),
    _t("track_report", "اعرض حالة بلاغ وسجل تحديثاته بالرقم المرجعي", {"ref": S}, ["ref"]),
    _t("search_knowledge", "ابحث في قاعدة معرفة البلدية عن اشتراطات وإجراءات", {"query": S}, ["query"]),
    _t("calc_fee", "احسب رسوم خدمة: building_permit, shop_license, signboard, demolition", {"service": S, "area_m2": {"type": "number"}}, ["service"]),
]

def run_tool(name, args):
    try:
        return json.dumps(FUNCS[name](**args), ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


MODEL = os.environ.get("MODEL", "claude-sonnet-5-5")

SYSTEM = """أنت «وكيل خدمات بلدية مسقط». تساعد المواطنين والمقيمين على اتخاذ القرار وإنجاز المعاملات بسهولة.
القواعد:
- تحدّث بالعربية بإيجاز ولطف، وبالإنجليزية إن كتب المستخدم بها.
- إن ذكر المستخدم مشكلة ميدانية: استدعِ classify_issue أولًا. إن كان فيها خطر على السلامة (كهرباء مكشوفة، حريق، غاز...) فابدأ ردّك بطلب الاتصال بالرقم 9999.
- اسأل عن الخانة الناقصة فقط (غالبًا الموقع)، سؤالًا واحدًا في كل مرة، ثم استدعِ open_report وأعطِ الرقم المرجعي.
- للمتابعة استخدم track_report. للاستفسارات استخدم search_knowledge. للرسوم استخدم calc_fee.
- لا تخترع اشتراطات أو رسومًا أو أرقام بلاغات. إن لم تجد المعلومة فقل ذلك.
- ذكّر أن المعلومات والرسوم تجريبية عند ذكرها."""

def agent_chat(history, lang="ar", max_steps=8):
    """history: قائمة {role, content(text)}. تُرجع (الرد النصي)."""
    import anthropic
    client = anthropic.Anthropic()  # يقرأ ANTHROPIC_API_KEY
    msgs = [dict(m) for m in history]
    for _ in range(max_steps):
        r = client.messages.create(model=MODEL, max_tokens=1000, system=SYSTEM + ("\n\nThe user interface is English: always respond in English." if lang == "en" else ""), tools=TOOLS, messages=msgs)
        if r.stop_reason != "tool_use":
            return "".join(b.text for b in r.content if b.type == "text")
        msgs.append({"role": "assistant", "content": r.content})
        results = [{"type": "tool_result", "tool_use_id": b.id, "content": run_tool(b.name, b.input)}
                   for b in r.content if b.type == "tool_use"]
        msgs.append({"role": "user", "content": results})
    return "تعذّر إكمال الطلب، حاول مرة أخرى."

HTML = r'''<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>وكيل خدمات بلدية مسقط</title>
<style>
:root{--bg:#f6f7f4;--c:#fff;--t:#1d2b24;--m:#5d6b63;--a:#1f6b4a;--b:#dde3dc;--r:#b3261e}
@media(prefers-color-scheme:dark){:root{--bg:#141a17;--c:#1e2622;--t:#e8eee9;--m:#9aa8a0;--a:#4fb487;--b:#2e3933;--r:#f2796f}}
*{box-sizing:border-box}body{margin:0;font-family:system-ui,"Segoe UI",Tahoma,sans-serif;background:var(--bg);color:var(--t)}
main{max-width:720px;margin:0 auto;padding:16px}h1{font-size:20px;margin:8px 0}
.tag{font-size:12px;color:var(--m)}nav{display:flex;gap:6px;margin:12px 0;flex-wrap:wrap}
nav button{flex:1;padding:10px;border:1px solid var(--b);background:var(--c);color:var(--t);border-radius:8px;cursor:pointer;font:inherit}
nav button.on{background:var(--a);color:#fff;border-color:var(--a)}
section{display:none;background:var(--c);border:1px solid var(--b);border-radius:12px;padding:14px}section.on{display:block}
input,select,textarea{width:100%;padding:10px;margin:6px 0 12px;border:1px solid var(--b);border-radius:8px;background:var(--bg);color:var(--t);font:inherit}
.go{background:var(--a);color:#fff;border:0;padding:10px 18px;border-radius:8px;cursor:pointer;font:inherit}
#log{height:380px;overflow-y:auto;display:flex;flex-direction:column;gap:8px;margin-bottom:10px}
.m{padding:8px 12px;border-radius:12px;max-width:85%;white-space:pre-wrap}
.u{background:var(--a);color:#fff;align-self:flex-start}.a{background:var(--bg);border:1px solid var(--b);align-self:flex-end}
.out{margin-top:12px;padding:10px;border-radius:8px;background:var(--bg);white-space:pre-wrap}.warn{color:var(--r);font-weight:700}
#row{display:flex;gap:8px}#row input{margin:0}
.reg{border:1px solid var(--b);border-radius:8px;padding:10px;margin:8px 0}.reg b{display:block;margin-bottom:2px}
</style></head><body><main>
<h1>وكيل خدمات بلدية مسقط</h1><div class="tag">نسخة تجريبية — الاشتراطات والرسوم بيانات تجريبية وليست رسمية. للطوارئ: 9999 · <a href="/en" style="color:inherit">English</a></div>
<nav id="nav"></nav>

<section id="chat"><div id="log"></div><div id="row"><input id="q" placeholder="اكتب مشكلتك أو سؤالك…"><button class="go" id="send">إرسال</button></div></section>

<section id="regs"><div class="tag">بيانات تجريبية وليست لوائح رسمية</div><input id="rq" placeholder="ابحث عن لائحة أو اشتراط…"><div id="rl"></div></section>
<section id="field"><label>وصف المشكلة</label><textarea id="fd" rows="3"></textarea>
<label>الموقع</label><input id="fl"><label>رقم للتواصل (اختياري)</label><input id="fc">
<button class="go" id="fs">فتح البلاغ</button><div class="out" id="fo" hidden></div></section>

<section id="fee"><label>الخدمة</label><select id="fsv">
<option value="building_permit">رخصة بناء</option><option value="shop_license">رخصة محل تجاري</option>
<option value="signboard">لوحة إعلانية</option><option value="demolition">تصريح هدم</option></select>
<label>المساحة (م²)</label><input id="fa" type="number" min="0" value="100">
<button class="go" id="fb">احسب</button><div class="out" id="fr" hidden></div></section>

<section id="track"><label>الرقم المرجعي</label><input id="tr" placeholder="MCT-123456" dir="ltr">
<button class="go" id="tb">تتبّع</button><div class="out" id="to" hidden></div></section>
</main>
<script>
const LANG="ar";const $=id=>document.getElementById(id),post=(u,b)=>fetch(u,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...b,lang:LANG})}).then(r=>r.json());
const tabs=[['chat','المحادثة'],['regs','اللوائح والاشتراطات'],['field','بلاغ ميداني'],['fee','حاسبة الرسوم'],['track','متابعة بلاغ']];
tabs.forEach(([id,n],i)=>{const b=document.createElement('button');b.textContent=n;b.onclick=()=>show(id);b.dataset.id=id;$('nav').append(b)});
function show(id){tabs.forEach(([t])=>$(t).classList.toggle('on',t===id));[...$('nav').children].forEach(b=>b.classList.toggle('on',b.dataset.id===id))}
show('chat');
const hist=[];function add(t,c){const d=document.createElement('div');d.className='m '+c;d.textContent=t;$('log').append(d);$('log').scrollTop=1e9}
add('مرحبًا! أخبرني بمشكلتك الميدانية أو اسأل عن الرسوم والاشتراطات أو تتبّع بلاغًا.','a');
async function send(){const t=$('q').value.trim();if(!t)return;$('q').value='';add(t,'u');hist.push({role:'user',content:t});
 try{const r=await post('/api/chat',{history:hist});hist.push({role:'assistant',content:r.reply});add(r.reply,'a')}catch(e){add('تعذّر الاتصال بالخادم','a')}}
$('send').onclick=send;$('q').onkeydown=e=>{if(e.key==='Enter')send()};
$('fs').onclick=async()=>{const r=await post('/api/report',{description:$('fd').value,location:$('fl').value,contact:$('fc').value});
 const o=$('fo');o.hidden=false;o.innerHTML='';const p=document.createElement('div');
 p.textContent=r.error?r.error:(r.safety_risk?'⚠ ':'')+'تم فتح البلاغ. الرقم المرجعي: '+r.ref+' — التصنيف: '+r.category_name;
 if(r.safety_risk){const w=document.createElement('div');w.className='warn';w.textContent='يوجد خطر على السلامة: اتصل بالرقم 9999 أولًا.';o.append(w)}o.append(p)};
$('fb').onclick=async()=>{const r=await post('/api/fee',{service:$('fsv').value,area_m2:+$('fa').value});$('fr').hidden=false;$('fr').textContent=r.error||r.service+': '+r.fee_omr+' ر.ع (رسوم تجريبية)'};
$('tb').onclick=async()=>{const r=await post('/api/track',{ref:$('tr').value});$('to').hidden=false;
 $('to').textContent=r.error||'الحالة: '+r.status+'\nالموقع: '+r.location+'\n\n'+r.updates.map(u=>u.ts+' — '+u.note).join('\n')};

let rt;async function loadRegs(){const r=await post('/api/regs',{query:$('rq').value}),box=$('rl');box.textContent='';
 if(!r.results.length){box.textContent=LANG==='en'?'No matching regulations.':'لا توجد نتائج مطابقة.';return}
 r.results.forEach(x=>{const d=document.createElement('div');d.className='reg';const t=document.createElement('b');t.textContent=x.title;const c=document.createElement('div');c.className='tag';c.textContent=x.category;const p=document.createElement('div');p.textContent=x.text;d.append(t,c,p);box.append(d)})}
$('rq').oninput=()=>{clearTimeout(rt);rt=setTimeout(loadRegs,250)};loadRegs();
</script></body></html>
'''

HTML_EN = r'''<!doctype html><html lang="en" dir="ltr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Muscat Municipality Services Agent</title>
<style>
:root{--bg:#f6f7f4;--c:#fff;--t:#1d2b24;--m:#5d6b63;--a:#1f6b4a;--b:#dde3dc;--r:#b3261e}
@media(prefers-color-scheme:dark){:root{--bg:#141a17;--c:#1e2622;--t:#e8eee9;--m:#9aa8a0;--a:#4fb487;--b:#2e3933;--r:#f2796f}}
*{box-sizing:border-box}body{margin:0;font-family:system-ui,"Segoe UI",Tahoma,sans-serif;background:var(--bg);color:var(--t)}
main{max-width:720px;margin:0 auto;padding:16px}h1{font-size:20px;margin:8px 0}
.tag{font-size:12px;color:var(--m)}nav{display:flex;gap:6px;margin:12px 0;flex-wrap:wrap}
nav button{flex:1;padding:10px;border:1px solid var(--b);background:var(--c);color:var(--t);border-radius:8px;cursor:pointer;font:inherit}
nav button.on{background:var(--a);color:#fff;border-color:var(--a)}
section{display:none;background:var(--c);border:1px solid var(--b);border-radius:12px;padding:14px}section.on{display:block}
input,select,textarea{width:100%;padding:10px;margin:6px 0 12px;border:1px solid var(--b);border-radius:8px;background:var(--bg);color:var(--t);font:inherit}
.go{background:var(--a);color:#fff;border:0;padding:10px 18px;border-radius:8px;cursor:pointer;font:inherit}
#log{height:380px;overflow-y:auto;display:flex;flex-direction:column;gap:8px;margin-bottom:10px}
.m{padding:8px 12px;border-radius:12px;max-width:85%;white-space:pre-wrap}
.u{background:var(--a);color:#fff;align-self:flex-end}.a{background:var(--bg);border:1px solid var(--b);align-self:flex-start}
.out{margin-top:12px;padding:10px;border-radius:8px;background:var(--bg);white-space:pre-wrap}.warn{color:var(--r);font-weight:700}
#row{display:flex;gap:8px}#row input{margin:0}
.reg{border:1px solid var(--b);border-radius:8px;padding:10px;margin:8px 0}.reg b{display:block;margin-bottom:2px}
</style></head><body><main>
<h1>Muscat Municipality Services Agent</h1><div class="tag">Demo version — requirements and fees are sample data, not official. Emergencies: 9999 · <a href="/" style="color:inherit">العربية</a></div>
<nav id="nav"></nav>

<section id="chat"><div id="log"></div><div id="row"><input id="q" placeholder="Describe your problem or ask a question…"><button class="go" id="send">Send</button></div></section>

<section id="regs"><div class="tag">Sample data, not official regulations</div><input id="rq" placeholder="Search for a regulation or requirement…"><div id="rl"></div></section>
<section id="field"><label>Problem description</label><textarea id="fd" rows="3"></textarea>
<label>Location</label><input id="fl"><label>Contact number (optional)</label><input id="fc">
<button class="go" id="fs">Open report</button><div class="out" id="fo" hidden></div></section>

<section id="fee"><label>Service</label><select id="fsv">
<option value="building_permit">Building permit</option><option value="shop_license">Shop license</option>
<option value="signboard">Signboard</option><option value="demolition">Demolition permit</option></select>
<label>Area (m²)</label><input id="fa" type="number" min="0" value="100">
<button class="go" id="fb">Calculate</button><div class="out" id="fr" hidden></div></section>

<section id="track"><label>Reference number</label><input id="tr" placeholder="MCT-123456" dir="ltr">
<button class="go" id="tb">Track</button><div class="out" id="to" hidden></div></section>
</main>
<script>
const LANG="en";const $=id=>document.getElementById(id),post=(u,b)=>fetch(u,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...b,lang:LANG})}).then(r=>r.json());
const tabs=[['chat','Chat'],['regs','Regulations'],['field','Field report'],['fee','Fee calculator'],['track','Track report']];
tabs.forEach(([id,n],i)=>{const b=document.createElement('button');b.textContent=n;b.onclick=()=>show(id);b.dataset.id=id;$('nav').append(b)});
function show(id){tabs.forEach(([t])=>$(t).classList.toggle('on',t===id));[...$('nav').children].forEach(b=>b.classList.toggle('on',b.dataset.id===id))}
show('chat');
const hist=[];function add(t,c){const d=document.createElement('div');d.className='m '+c;d.textContent=t;$('log').append(d);$('log').scrollTop=1e9}
add('Hello! Tell me about a problem in your area, ask about fees and requirements, or track a report.','a');
async function send(){const t=$('q').value.trim();if(!t)return;$('q').value='';add(t,'u');hist.push({role:'user',content:t});
 try{const r=await post('/api/chat',{history:hist});hist.push({role:'assistant',content:r.reply});add(r.reply,'a')}catch(e){add('Could not reach the server','a')}}
$('send').onclick=send;$('q').onkeydown=e=>{if(e.key==='Enter')send()};
$('fs').onclick=async()=>{const r=await post('/api/report',{description:$('fd').value,location:$('fl').value,contact:$('fc').value});
 const o=$('fo');o.hidden=false;o.innerHTML='';const p=document.createElement('div');
 p.textContent=r.error?r.error:(r.safety_risk?'⚠ ':'')+'Report opened. Reference number: '+r.ref+' — Category: '+r.category_name;
 if(r.safety_risk){const w=document.createElement('div');w.className='warn';w.textContent='Safety risk: call 9999 first.';o.append(w)}o.append(p)};
$('fb').onclick=async()=>{const r=await post('/api/fee',{service:$('fsv').value,area_m2:+$('fa').value});$('fr').hidden=false;$('fr').textContent=r.error||r.service+': '+r.fee_omr+' OMR (sample fee)'};
$('tb').onclick=async()=>{const r=await post('/api/track',{ref:$('tr').value});$('to').hidden=false;
 $('to').textContent=r.error||'Status: '+r.status+'\nLocation: '+r.location+'\n\n'+r.updates.map(u=>u.ts+' — '+u.note).join('\n')};

let rt;async function loadRegs(){const r=await post('/api/regs',{query:$('rq').value}),box=$('rl');box.textContent='';
 if(!r.results.length){box.textContent=LANG==='en'?'No matching regulations.':'لا توجد نتائج مطابقة.';return}
 r.results.forEach(x=>{const d=document.createElement('div');d.className='reg';const t=document.createElement('b');t.textContent=x.title;const c=document.createElement('div');c.className='tag';c.textContent=x.category;const p=document.createElement('div');p.textContent=x.text;d.append(t,c,p);box.append(d)})}
$('rq').oninput=()=>{clearTimeout(rt);rt=setTimeout(loadRegs,250)};loadRegs();
</script></body></html>
'''

app = Flask(__name__)

@app.get("/")
def index():
    return Response(HTML, mimetype="text/html")

@app.get("/en")
def index_en():
    return Response(HTML_EN, mimetype="text/html")

import time
HITS = {}
LIMIT, WINDOW = int(os.environ.get("CHAT_LIMIT", "30")), 3600  # رسائل لكل IP في الساعة

def allowed(ip):
    now = time.time()
    h = [t for t in HITS.get(ip, []) if now - t < WINDOW]
    ok = len(h) < LIMIT
    if ok:
        h.append(now)
    HITS[ip] = h
    return ok

def L(j):
    return "en" if (j or {}).get("lang") == "en" else "ar"

def T(lang, ar, en):
    return en if lang == "en" else ar

FEES_EN = {"building_permit": "Building permit", "shop_license": "Shop license", "signboard": "Signboard", "demolition": "Demolition permit"}
STATUS_EN = {"تم الاستلام": "Received", "تم استلام البلاغ": "Report received"}

@app.post("/api/chat")
def chat():
    j = request.json or {}
    lang = L(j)
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return jsonify(reply=T(lang, "مفتاح ANTHROPIC_API_KEY غير مضبوط. الحاسبة والنموذج والمتابعة تعمل بدونه.",
                               "ANTHROPIC_API_KEY is not set. The calculator, report form and tracking work without it."))
    ip = (request.headers.get("X-Forwarded-For", request.remote_addr) or "").split(",")[0].strip()
    if not allowed(ip):
        return jsonify(reply=T(lang, "تجاوزت الحد المسموح من الرسائل هذه الساعة. حاول لاحقًا.",
                               "You have reached the hourly message limit. Please try again later.")), 429
    hist = [{"role": m["role"], "content": str(m["content"])[:1000]}
            for m in j.get("history", [])[-20:] if m.get("role") in ("user", "assistant")]
    try:
        return jsonify(reply=agent_chat(hist, lang))
    except Exception as e:
        return jsonify(reply=T(lang, "حدث خطأ: %s", "An error occurred: %s") % e), 500

@app.post("/api/report")
def report():
    j = request.json or {}
    lang = L(j)
    c = classify_issue(j.get("description", ""), lang)
    res = open_report(c["category"], c["urgency"], j.get("description", ""), j.get("location", ""), j.get("contact", ""))
    if "error" in res:
        res["error"] = T(lang, res["error"], "Location is required")
    return jsonify(**res, safety_risk=c["safety_risk"], category_name=c["category_name"])

@app.post("/api/fee")
def fee():
    j = request.json or {}
    lang = L(j)
    r = calc_fee(j.get("service"), j.get("area_m2", 0))
    if lang == "en":
        if "error" in r:
            r["error"] = "Unknown service"
        else:
            r["service"] = FEES_EN.get(j.get("service"), r["service"])
    return jsonify(r)

@app.post("/api/track")
def track():
    j = request.json or {}
    lang = L(j)
    r = track_report(j.get("ref", ""))
    if lang == "en":
        if "error" in r:
            r["error"] = "No report found with this number (the free server may reset saved reports)."
        else:
            r["status"] = STATUS_EN.get(r["status"], r["status"])
            r["updates"] = [{"ts": u["ts"], "note": STATUS_EN.get(u["note"], u["note"])} for u in r["updates"]]
    return jsonify(r)

@app.post("/api/regs")
def regs():
    j = request.json or {}
    lang = L(j)
    q = j.get("query", "")
    items = find_regs(q, 12 if q.strip() else 50)
    return jsonify(results=[{"title": r["title_" + lang], "category": r["cat_" + lang], "text": r["text_" + lang]} for r in items])

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
