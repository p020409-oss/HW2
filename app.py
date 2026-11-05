import io, json, logging, sqlite3, uuid, os
from datetime import date, timedelta
from pathlib import Path

os.environ.setdefault("TORCH_HOME", str(Path(__file__).resolve().parent / "data" / "torch"))
import torch
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, UnidentifiedImageError
from torchvision.models import ResNet50_Weights, resnet50

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
UPLOADS = DATA / "uploads"
DB = DATA / "meals.sqlite3"
MAX_BYTES = 8 * 1024 * 1024
DISCLAIMER = "추정치이며 의학적 조언이 아닙니다."
logging.basicConfig(filename=DATA / "app.log", level=logging.INFO, encoding="utf-8", format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("mealapp")
DATA.mkdir(exist_ok=True); UPLOADS.mkdir(exist_ok=True)

# USDA FoodData Central reference values, converted to typical portions; editable estimates.
FOODS = {
 "비빔밥": {"kcal": 560, "carbs": 86, "protein": 17, "fat": 15, "portion": "1그릇 450g", "source": "USDA FoodData Central: rice, cooked; vegetables, mixed; egg; sesame oil (조합 추정)"},
 "김치찌개": {"kcal": 290, "carbs": 15, "protein": 23, "fat": 15, "portion": "1인분 400g", "source": "USDA FoodData Central: pork, cooked; kimchi/vegetables (조합 추정)"},
 "불고기": {"kcal": 390, "carbs": 24, "protein": 30, "fat": 19, "portion": "1인분 200g", "source": "USDA FoodData Central: beef, cooked; soy sauce/sugar (조합 추정)"},
 "김밥": {"kcal": 480, "carbs": 72, "protein": 14, "fat": 15, "portion": "1줄 250g", "source": "USDA FoodData Central: rice, cooked; egg; vegetables; seaweed (조합 추정)"},
 "된장찌개": {"kcal": 220, "carbs": 18, "protein": 16, "fat": 10, "portion": "1인분 400g", "source": "USDA FoodData Central: tofu; soybean paste/vegetables (조합 추정)"},
 "삼겹살": {"kcal": 590, "carbs": 2, "protein": 28, "fat": 52, "portion": "구운 고기 150g", "source": "USDA FoodData Central: pork belly, cooked (조리/부위 편차 있음)"},
 "잡채": {"kcal": 300, "carbs": 43, "protein": 7, "fat": 11, "portion": "1접시 200g", "source": "USDA FoodData Central: sweet potato noodles; vegetables; oil (조합 추정)"},
 "떡볶이": {"kcal": 430, "carbs": 90, "protein": 8, "fat": 5, "portion": "1인분 300g", "source": "USDA FoodData Central: rice cake; chili sauce ingredients (조합 추정)"},
 "갈비탕": {"kcal": 490, "carbs": 40, "protein": 32, "fat": 21, "portion": "1그릇 650g", "source": "USDA FoodData Central: beef; rice; broth components (조합 추정)"},
 "김치볶음밥": {"kcal": 520, "carbs": 78, "protein": 15, "fat": 16, "portion": "1접시 400g", "source": "USDA FoodData Central: rice, cooked; kimchi; egg; oil (조합 추정)"},
}
torch.set_num_threads(2)
model = None; preprocess = None; categories = None; model_error = None
try:
    weights = ResNet50_Weights.DEFAULT
    model = resnet50(weights=weights).eval()
    preprocess = weights.transforms(); categories = weights.meta["categories"]
    log.info("Loaded torchvision ResNet50 ImageNet pretrained weights on CPU")
except Exception as e:
    model_error = str(e); log.exception("Could not load pretrained weights")

app = FastAPI(title="한끼로그", docs_url="/docs", redoc_url=None)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")

def connect():
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row; return c
with connect() as c:
    c.execute("CREATE TABLE IF NOT EXISTS meals(id TEXT PRIMARY KEY, eaten_at TEXT NOT NULL, menu TEXT NOT NULL, kcal REAL NOT NULL, carbs REAL NOT NULL, protein REAL NOT NULL, fat REAL NOT NULL, image TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
    c.execute("CREATE TABLE IF NOT EXISTS goals(day TEXT PRIMARY KEY, kcal REAL NOT NULL, carbs REAL NOT NULL, protein REAL NOT NULL, fat REAL NOT NULL)")

def classify(image):
    if model is None: return [{"menu": "비빔밥", "confidence": 0.0}], "모델 가중치를 불러오지 못해 기본 제안을 표시합니다."
    with torch.inference_mode():
        p = model(preprocess(image).unsqueeze(0))[0].softmax(0)
    top = p.topk(5)
    labels = [categories[i].lower() for i in top.indices.tolist()]
    # Food- and ingredient-related ImageNet labels produce weak hints; user confirms the Korean dish.
    hints = []
    for label in labels:
        if any(k in label for k in ("rice", "meat", "beef", "pork", "soup", "vegetable", "broccoli", "cauliflower", "meatloaf", "potpie")):
            hints.extend(["비빔밥", "김치찌개", "불고기"])
    picks = list(dict.fromkeys(hints + list(FOODS)))[:3]
    return [{"menu": m, "confidence": round(float(top.values[0]) * 100, 1) if i == 0 else 0} for i, m in enumerate(picks)], "ImageNet 범용 분류 결과를 참고한 제안입니다. 한식 메뉴 인식 전용 모델이 아니므로 메뉴를 확인해 주세요."

@app.get("/")
def home(): return FileResponse(ROOT / "static" / "index.html")

@app.get("/api/foods")
def foods(): return {"foods": [{"name": k, **v} for k,v in FOODS.items()], "disclaimer": DISCLAIMER}

@app.post("/api/analyze")
async def analyze(file: UploadFile = File(...)):
    if file.content_type not in ("image/jpeg", "image/png", "image/webp"):
        raise HTTPException(415, "JPG, PNG, WEBP 이미지 파일만 올려 주세요.")
    raw = await file.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES: raise HTTPException(413, "이미지는 8MB 이하여야 합니다.")
    try:
        im = Image.open(io.BytesIO(raw)); im.verify(); im = Image.open(io.BytesIO(raw)).convert("RGB")
        if im.width * im.height > 20_000_000: raise HTTPException(413, "이미지 해상도가 너무 큽니다.")
    except (UnidentifiedImageError, OSError): raise HTTPException(400, "읽을 수 있는 이미지가 아닙니다.")
    uid = uuid.uuid4().hex + ".jpg"
    im.thumbnail((1400,1400)); im.save(UPLOADS / uid, "JPEG", quality=88)
    choices, note = classify(im)
    return {"image": "/api/images/" + uid, "choices": choices, "note": note, "disclaimer": DISCLAIMER}

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

