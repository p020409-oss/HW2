# 한끼로그

사진으로 한식 메뉴를 추정하고 식단을 기록해 일별·주별 섭취량을 목표와 비교하는 로컬 웹앱입니다. FastAPI와 SQLite를 백엔드로, HTML/CSS/JavaScript를 화면으로 사용합니다. 사진 분석은 CPU에서 실행되는 사전학습 torchvision ResNet50(ImageNet)으로 동작합니다. ImageNet은 한식 전용 분류 모델이 아니므로 메뉴 제안을 확인하고 필요하면 수정해 주세요.

메뉴 영양값은 USDA FoodData Central의 식재료 참조값을 일반적인 1회 분량으로 조합한 데모 추정치입니다. 각 결과는 추정치이며 의학적 조언이 아닙니다.

## 요구 환경

- Windows 10/11, PowerShell
- Python 3.10 이상 (Python 3.12 권장)
- 인터넷 연결: Python 패키지 설치 및 최초 모델 가중치 준비 시 필요
- GPU는 필요하지 않습니다.

## 설치

프로젝트 폴더에서 시스템 Python을 사용해 설치합니다. 가상환경은 필수가 아닙니다.

```powershell
cd path\to\upload
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

PyTorch 설치가 플랫폼에 맞지 않거나 CPU 전용 설치를 명시하려면 [PyTorch 공식 설치 안내](https://pytorch.org/get-started/locally/)에서 Windows, Pip, Python, CPU를 선택해 안내된 명령으로 `torch`와 `torchvision`을 설치한 다음 나머지 패키지를 설치하세요.

## 모델 준비

첫 서버 실행 때 torchvision이 사전학습 ResNet50 ImageNet 가중치(약 98MB)를 공식 PyTorch 모델 저장소에서 자동으로 내려받습니다. 앱은 이를 `data/torch` 아래에 보관하고 다음 실행부터 재사용합니다. 최초 실행에는 인터넷 연결과 해당 폴더의 쓰기 권한이 필요합니다. 모델 파일은 저장소에 포함하지 않습니다.

## 실행

```powershell
cd path\to\upload
python -m uvicorn app:app --host 127.0.0.1 --port 8765 --log-level info
```

브라우저에서 <http://127.0.0.1:8765>를 여세요. 종료하려면 서버를 실행한 PowerShell에서 `Ctrl+C`를 누릅니다. 기본 설정은 localhost에서만 접속할 수 있습니다.

## 로컬 데이터와 업로드

실행 중 생성되는 SQLite DB, 업로드 이미지, 로그, 모델 캐시는 `data/` 아래에 생성됩니다. 이 폴더는 Git에 올리지 않도록 `.gitignore`에 등록되어 있습니다. 이미지 업로드는 JPEG/PNG/WEBP, 최대 8MB 및 2천만 픽셀로 제한합니다.
