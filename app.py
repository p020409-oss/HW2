import io, json, logging, sqlite3, uuid, os
from datetime import date, timedelta
from pathlib import Path

os.environ.setdefault("TORCH_HOME", str(Path(__file__).resolve().parent / "data" / "torch"))
import torch
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, UnidentifiedImageError
from transformers import AutoImageProcessor, AutoModelForImageClassification

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
UPLOADS = DATA / "uploads"
DB = DATA / "meals.sqlite3"
MAX_BYTES = 8 * 1024 * 1024
DATA.mkdir(exist_ok=True)
DISCLAIMER = "\ucd94\uc815\uce58\uc774\uba70 \uc758\ud559\uc801 \uc870\uc5b8\uc774 \uc544\ub2d9\ub2c8\ub2e4."
logging.basicConfig(filename=DATA / "app.log", level=logging.INFO, encoding="utf-8", format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("mealapp")
DATA.mkdir(exist_ok=True); UPLOADS.mkdir(exist_ok=True)

# USDA FoodData Central reference values, converted to typical portions; editable estimates.
FOODS = {
    "비빔밥": {"kcal": 560, "carbs": 86, "protein": 17, "fat": 15, "portion": "1그릇 450g", "source": "USDA FoodData Central 재료값 조합 추정: 밥, 채소, 달걀, 참기름"},
    "김치찌개": {"kcal": 290, "carbs": 15, "protein": 23, "fat": 15, "portion": "1인분 400g", "source": "USDA FoodData Central 재료값 조합 추정: 돼지고기, 김치, 채소"},
    "불고기": {"kcal": 390, "carbs": 24, "protein": 30, "fat": 19, "portion": "1인분 200g", "source": "USDA FoodData Central 재료값 조합 추정: 소고기, 간장, 설탕"},
    "김밥": {"kcal": 480, "carbs": 72, "protein": 14, "fat": 15, "portion": "1줄 250g", "source": "USDA FoodData Central 재료값 조합 추정: 밥, 달걀, 채소, 김"},
    "된장찌개": {"kcal": 220, "carbs": 18, "protein": 16, "fat": 10, "portion": "1인분 400g", "source": "USDA FoodData Central 재료값 조합 추정: 두부, 된장, 채소"},
    "삼겹살": {"kcal": 590, "carbs": 2, "protein": 28, "fat": 52, "portion": "구운 고기 150g", "source": "USDA FoodData Central 참고값: 조리한 돼지고기"},
    "잡채": {"kcal": 300, "carbs": 43, "protein": 7, "fat": 11, "portion": "1접시 200g", "source": "USDA FoodData Central 재료값 조합 추정: 당면, 채소, 기름"},
    "떡볶이": {"kcal": 430, "carbs": 90, "protein": 8, "fat": 5, "portion": "1인분 300g", "source": "USDA FoodData Central 재료값 조합 추정: 떡, 양념 재료"},
    "갈비탕": {"kcal": 490, "carbs": 40, "protein": 32, "fat": 21, "portion": "1그릇 650g", "source": "USDA FoodData Central 재료값 조합 추정: 소고기, 밥, 국물 재료"},
    "김치볶음밥": {"kcal": 520, "carbs": 78, "protein": 15, "fat": 16, "portion": "1접시 400g", "source": "USDA FoodData Central 재료값 조합 추정: 밥, 김치, 달걀, 기름"},
}
MODEL_ID = "rajistics/finetuned-indian-food"
MODEL_REVISION = "27e01953a3945806138ab2452d0ca5ada4412628"
MODEL_VERSION = f"{MODEL_ID}@{MODEL_REVISION[:12]}"
torch.set_num_threads(2)
model = None
processor = None
model_error = None
try:
    processor = AutoImageProcessor.from_pretrained(MODEL_ID, revision=MODEL_REVISION, use_fast=False)
    model = AutoModelForImageClassification.from_pretrained(MODEL_ID, revision=MODEL_REVISION).eval()
    log.info("Loaded CPU image classifier %s", MODEL_VERSION)
except Exception as e:
    model_error = str(e)
    log.exception("Could not load pretrained food model")

app = FastAPI(title="한끼로그", docs_url="/docs", redoc_url=None)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")

@app.middleware("http")
async def attach_version_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-App-Version"] = os.environ.get("APP_VERSION", "local")
    response.headers["X-Model-Version"] = MODEL_VERSION
    return response

@app.get("/api/version")
def version():
    return {"app_version": os.environ.get("APP_VERSION", "local"), "model_version": MODEL_VERSION, "model_loaded": model is not None}

def connect():
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row; return c
with connect() as c:
    c.execute("CREATE TABLE IF NOT EXISTS meals(id TEXT PRIMARY KEY, eaten_at TEXT NOT NULL, menu TEXT NOT NULL, kcal REAL NOT NULL, carbs REAL NOT NULL, protein REAL NOT NULL, fat REAL NOT NULL, image TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
    c.execute("CREATE TABLE IF NOT EXISTS goals(day TEXT PRIMARY KEY, kcal REAL NOT NULL, carbs REAL NOT NULL, protein REAL NOT NULL, fat REAL NOT NULL)")

# Visual analogy map from Indian-food classes to the closest item in the Korean menu list.
# These are approximate appearance-based suggestions, not Korean-food recognition.
VISUAL_MENU_MAP = {
    "burger": "\uae40\ubc25", "butter_naan": "\ubd88\uace0\uae30", "kaathi_rolls": "\uae40\ubc25",
    "kadai_paneer": "\ubd88\uace0\uae30", "kulfi": "\ubd88\uace0\uae30", "masala_dosa": "\uae40\ubc25",
    "momos": "\uae40\ubc25", "paani_puri": "\ub5a1\ubcf6\uc774", "pakode": "\uc0bc\uacb9\uc0b4",
    "pav_bhaji": "\ube44\ube54\ubc25", "pizza": "\uae40\ubc25", "samosa": "\uae40\ubc25",
    "chai": "\uae40\uce58\ucc0c\uac1c", "chapati": "\ubd88\uace0\uae30", "chole_bhature": "\uae40\uce58\ucc0c\uac1c",
    "dal_makhani": "\ub41c\uc7a5\ucc0c\uac1c",
    "dhokla": "\ub5a1\ubcf6\uc774", "fried_rice": "\uae40\uce58\ubcf6\uc74c\ubc25", "idli": "\ub5a1\ubcf6\uc774",
    "jalebi": "\ub5a1\ubcf6\uc774",
}

def classify(image):
    if model is None or processor is None:
        raise RuntimeError("사전학습 음식 모델을 불러오지 못했습니다.")
    inputs = processor(images=image, return_tensors="pt")
    with torch.inference_mode():
        probs = model(**inputs).logits[0].softmax(0)
    scores = {}
    for index, probability in enumerate(probs.tolist()):
        label = str(model.config.id2label.get(str(index), model.config.id2label.get(index, ""))).lower()
        menu = VISUAL_MENU_MAP.get(label)
        if menu in FOODS:
            scores[menu] = scores.get(menu, 0.0) + probability
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)[:3]
    if not ranked:
        ranked = [("비빔밥", 0.0)]
    choices = [{"menu": menu, "similarity_score": round(score * 100, 1)} for menu, score in ranked]
    note = f"{MODEL_VERSION}의 음식 분류 점수를 한식 메뉴에 대응한 시각적 유사 후보입니다. 점수는 실제 한식 인식 확률이 아니므로 메뉴를 확인하거나 수정해 주세요."
    return choices, note

@app.get("/")
def home(): return FileResponse(ROOT / "static" / "index.html")

@app.get("/api/foods")
def foods(): return {"foods": [{"name": k, **v} for k,v in FOODS.items()], "disclaimer": DISCLAIMER}

@app.post("/api/analyze")
async def analyze(request: Request, file: UploadFile = File(...)):
    if file.content_type not in ("image/jpeg", "image/png", "image/webp"):
        raise HTTPException(415, "JPG, PNG, WEBP 이미지 파일만 올려 주세요.")
    raw = await file.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES: raise HTTPException(413, "이미지는 8MB 이하여야 합니다.")
    try:
        im = Image.open(io.BytesIO(raw)); im.verify(); im = Image.open(io.BytesIO(raw)).convert("RGB")
        if im.width * im.height > 20_000_000: raise HTTPException(413, "이미지 해상도가 너무 큽니다.")
    except (UnidentifiedImageError, OSError): raise HTTPException(400, "읽을 수 있는 이미지가 아닙니다.")
    im.thumbnail((1400,1400))
    choices, note = classify(im)
    image_path = None
    if request.headers.get("x-deployment-monitor") != "1":
        uid = uuid.uuid4().hex + ".jpg"
        im.save(UPLOADS / uid, "JPEG", quality=88)
        image_path = "/api/images/" + uid
    return {"image": image_path, "choices": choices, "note": note, "disclaimer": DISCLAIMER}

@app.get("/api/images/{name}")
def image_file(name: str):
    if not name.endswith(".jpg") or Path(name).name != name: raise HTTPException(404, "이미지를 찾을 수 없습니다.")
    p = UPLOADS / name
    if not p.is_file(): raise HTTPException(404, "이미지를 찾을 수 없습니다.")
    return FileResponse(p, media_type="image/jpeg")

@app.post("/api/meals")
def save_meal(payload: dict):
    menu = payload.get("menu"); d = payload.get("date"); image = payload.get("image")
    if menu not in FOODS: raise HTTPException(400, "목록에서 메뉴를 선택해 주세요.")
    try: date.fromisoformat(d)
    except (ValueError, TypeError): raise HTTPException(400, "날짜 형식이 올바르지 않습니다.")
    if image and (not isinstance(image,str) or not image.startswith("/api/images/") or Path(image).name != image.rsplit("/",1)[-1]): raise HTTPException(400,"이미지 경로가 올바르지 않습니다.")
    base = FOODS[menu]
    vals = {k: float(payload.get(k, base[k])) for k in ("kcal","carbs","protein","fat")}
    if any(v < 0 or v > 5000 for v in vals.values()): raise HTTPException(400,"영양 수치는 0~5000 범위로 입력해 주세요.")
    uid = uuid.uuid4().hex
    with connect() as c: c.execute("INSERT INTO meals(id,eaten_at,menu,kcal,carbs,protein,fat,image) VALUES(?,?,?,?,?,?,?,?)",(uid,d,menu,vals["kcal"],vals["carbs"],vals["protein"],vals["fat"],image))
    return {"id":uid,"menu":menu,**vals,"disclaimer":DISCLAIMER}

@app.get("/api/dashboard")
def dashboard(start: str = "", days: int = 7):
    try: end = date.fromisoformat(start) if start else date.today(); days=max(1,min(int(days),31)); begin=end-timedelta(days=days-1)
    except ValueError: raise HTTPException(400,"날짜 형식이 올바르지 않습니다.")
    out=[]
    with connect() as c:
        for i in range(days):
            day=(begin+timedelta(days=i)).isoformat()
            meals=c.execute("SELECT id,menu,kcal,carbs,protein,fat,image FROM meals WHERE eaten_at=? ORDER BY created_at",(day,)).fetchall()
            goal=c.execute("SELECT kcal,carbs,protein,fat FROM goals WHERE day=?",(day,)).fetchone()
            sums={k:round(sum(m[k] for m in meals),1) for k in ("kcal","carbs","protein","fat")}
            out.append({"date":day,"meals":[dict(m) for m in meals],"totals":sums,"goal":dict(goal) if goal else None})
    return {"days":out,"disclaimer":DISCLAIMER}

@app.put("/api/goals")
def set_goal(payload: dict):
    d=payload.get("date")
    try: date.fromisoformat(d)
    except (ValueError,TypeError): raise HTTPException(400,"날짜 형식이 올바르지 않습니다.")
    try: vals={k:float(payload[k]) for k in ("kcal","carbs","protein","fat")}
    except (KeyError,ValueError,TypeError): raise HTTPException(400,"목표를 숫자로 입력해 주세요.")
    if any(v<=0 or v>10000 for v in vals.values()): raise HTTPException(400,"목표는 0보다 크고 10000 이하여야 합니다.")
    with connect() as c: c.execute("INSERT INTO goals VALUES(?,?,?,?,?) ON CONFLICT(day) DO UPDATE SET kcal=excluded.kcal,carbs=excluded.carbs,protein=excluded.protein,fat=excluded.fat",(d,vals["kcal"],vals["carbs"],vals["protein"],vals["fat"]))
    return {"date":d,**vals}

