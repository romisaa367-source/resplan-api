# ResPlan API — V17.0 (Input Validation) + V16.7 (Strict Diversity)

نفس أسلوب تسليم الصور بتاع آخر نسخة (روابط PNG حقيقية، بدون base64) — **بالإضافة** لطبقة تحقق جديدة من صحة المدخلات (Input Validation Layer، من النوتبوك `ResPlan_V15_validated.ipynb`) بترفض المدخلات المستحيلة **قبل** ما تحاول تولّد أي حاجة.

## الجديد في النوتبوك دي

1. **`validate_user_program()` (CELL 6.5, V17.0)** — بتتحقق قبل أي توليد:
   - عدد الغرف/الحمامات/المطابخ منطقي (≥1 لكل واحد، مفيش أرقام سالبة)
   - المساحة المطلوبة كافية فعليًا للبرنامج المطلوب (بتحسب حد أدنى تقديري بناءً على مقاسات غرف واقعية) — لو المساحة أقل من الحد الأدنى بحوالي 2%+، بترفض وتقترح مدى مساحة بديل
   - تحذيرات (مش رفض) زي: حمام ماستر بدون حمام ضيوف، غرفة سفرة في شقة صغيرة جدًا، عدد حمامات مبالغ فيه
2. **`generate_one`/`generate_options` بقت V16.7** — بتستكشف لحد **5 نسب عرض/ارتفاع** (مربع → مستطيل طويل) بدل 3، وبتستخدم فحص **"جيومتري مختلف فعليًا"** (`_is_geometrically_distinct`) عشان تضمن إن كل option مختلف حقيقي مش بس شكله متغير شوية.

## الملفات

| الملف | المصدر | ملاحظة |
|---|---|---|
| `planning_engine.py` | CELL 6 (بعد شيل الـ GAN hint) + `ADJACENCY_RULES` من CELL 1 | محرك التقسيم |
| `validation.py` | **جديد** — CELL 6.5 (`validate_user_program`) | يتحقق قبل أي توليد |
| `renderer.py` | CELL 7 (الأعمدة، `ROOM_COLORS`) | الرسم |
| `generator.py` | **معدَّل** — مبني على CELL 12 (V16.7) + بيستدعي `validation.py` الأول | يرجّع PNG bytes + JSON data، أو رد تحقق فاشل منظّم |
| `app.py` | **معدَّل** | بيرجع HTTP **400** لو المدخلات مستحيلة (قبل أي محاولة توليد)، 422 لو التحقق عدّى بس التوليد فشل، 200 للنجاح |
| `requirements.txt`, `Procfile`, `railway.json` | نفس اللي قبل كده | |

## سلوك الـ endpoint الجديد

### `POST /generate` — 3 حالات ممكنة:

**1) HTTP 400 — التحقق فشل (زي مثال الصورة بالظبط):**
```json
POST /generate
{"n_bed": 5, "n_bath": 1, "n_kit": 1, "area": 75, "has_master_bath": false}
```
```json
{
  "request_id": "1641f7bd6daf",
  "options": [{
    "ok": false,
    "validation_failed": true,
    "errors": ["Requested program (5 Bedroom(s), 1 Bathroom(s), 1 Kitchen(s), Living) cannot physically fit inside 75 m² (needs ≥108 m²)."],
    "warnings": [],
    "checks": [["Bedrooms","PASS"],["Bathrooms","PASS"],["Kitchen","PASS"],["Requested Area","FAIL"],["Program Feasibility","FAIL"]],
    "requested_area_m2": 75.0,
    "estimated_min_area_m2": 107.5,
    "suggested_area_range_m2": [107.5, 129.0]
  }]
}
```
مفيش أي محاولة توليد حصلت خالص — رفض فوري زي النوتبوك بالظبط.

**2) HTTP 422 — التحقق عدّى لكن التوليد فشل** (نادر، تركيبة صعبة جدًا رغم إنها "ممكنة نظريًا"):
```json
{"options": [{"ok": false, "validation_failed": false, "error": "..."}]}
```

**3) HTTP 200 — نجاح:**
```json
{
  "request_id": "0f15d3f52a68",
  "options": [
    {"ok": true, "option": 1, "shape": "Square", "image_url": "/image/0f15d3f52a68/1.png", "...": "..."},
    {"ok": true, "option": 2, "shape": "Wide Rectangle", "image_url": "/image/0f15d3f52a68/2.png", "...": "..."},
    {"ok": true, "option": 3, "...": "..."}
  ]
}
```

### `GET /image/<request_id>/<filename>`
برجع الصورة الحقيقية (`image/png`) — لازم تعمل `/generate` الأول.

## Params (زي قبل كده)

`n_bed`, `n_bath`, `n_kit`, `has_bal`, `area`, `has_master_bath`, `has_dining`, `has_dressing`, `n_options` (1-3), `n_attempts`, `seed` (اختياري).

## تجربتها في Swagger

```
https://<your-app>.up.railway.app/apidocs/
```
جرب أول حاجة نفس مثال الصورة (`n_bed=5, area=75`) وشوف الـ 400 response، بعدين جرب مدخلات منطقية وشوف الصور الحقيقية من الـ `image_url`.

## النشر على Railway

ارفع كل الملفات دي على GitHub (استبدل ملفات الريبو الحالي بالكامل، فيه ملف جديد اسمه `validation.py` لازم يترفع معاهم). Railway هيعمل redeploy تلقائي.
