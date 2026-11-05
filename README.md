# 한끼로그

사진으로 비슷한 한식 메뉴를 추정하고 식단을 기록해 일별·주별 섭취량을 목표와 비교하는 로컬 웹앱입니다. FastAPI와 SQLite를 백엔드로, HTML/CSS/JavaScript를 화면으로 사용합니다. 사진 분석은 CPU에서 실행되는 Apache-2.0 라이선스 사전학습 음식 분류 모델을 사용하고, 분류된 음식 유형을 한식 메뉴 후보로 연결합니다. 후보는 시각적 유사 추정이며 실제 한식 인식 결과가 아니므로 확인하고 필요하면 수정해 주세요.

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

`requirements.txt`에는 CPU 전용 PyTorch, torchvision 및 고정 버전 Transformers가 포함되어 있습니다. 설치 문제가 있으면 [PyTorch 공식 설치 안내](https://pytorch.org/get-started/locally/)에서 Windows, Pip, Python, CPU 설정을 확인하세요.

## 모델 준비

고정 모델 `rajistics/finetuned-indian-food` (`27e01953a394`)를 사용합니다. Hugging Face 모델 카드에는 Apache-2.0 라이선스가 표시되어 있습니다. Windows에서 첫 실행할 때는 모델 가중치를 내려받을 인터넷 연결이 필요하며 캐시는 `data/torch`가 아닌 Hugging Face 기본 캐시 아래에 저장됩니다. Docker 이미지는 빌드 중 모델 가중치를 받아 CPU 추론을 확인하므로 컨테이너 실행 시 별도 다운로드가 없습니다. 모델 파일은 Git에 넣지 않습니다.

## 실행

```powershell
cd path\to\upload
python -m uvicorn app:app --host 127.0.0.1 --port 8765 --log-level info
```

브라우저에서 <http://127.0.0.1:8765>를 여세요. 종료하려면 서버를 실행한 PowerShell에서 `Ctrl+C`를 누릅니다. 기본 설정은 localhost에서만 접속할 수 있습니다.

## 로컬 데이터와 업로드

실행 중 생성되는 SQLite DB, 업로드 이미지, 로그, 모델 캐시는 `data/` 아래에 생성됩니다. 이 폴더는 Git에 올리지 않도록 `.gitignore`에 등록되어 있습니다. 이미지 업로드는 JPEG/PNG/WEBP, 최대 8MB 및 2천만 픽셀로 제한합니다.

## Docker로 실행

Docker Desktop을 설치하고 실행한 뒤 저장소 루트에서 이미지를 빌드합니다. Dockerfile은 고정 모델과 입력 전처리를 준비하고, 무작위 이미지에 대한 CPU 추론 출력 형태와 유한값을 확인합니다.

```powershell
docker build -t meal-app:local .
docker run --rm -p 8765:8765 -v meal-data:/app/data meal-app:local
```

브라우저에서 <http://localhost:8765>를 여세요. `meal-data` 볼륨에는 SQLite 기록과 업로드 파일이 저장됩니다. 모델 가중치는 이미지에 포함되므로 컨테이너 첫 시작 시 별도 다운로드가 없습니다.

## GitHub Actions와 Docker Hub

`.github/workflows/ci.yml`은 push 및 pull request에서 Docker 이미지를 빌드합니다. Push 이벤트에서는 Docker Hub의 `DOCKERHUB_USERNAME/meal-app`에 `latest`(기본 브랜치), 브랜치명, 커밋 SHA 태그로 업로드합니다. GitHub 저장소의 **Settings → Secrets and variables → Actions**에 `DOCKERHUB_USERNAME`과 `DOCKERHUB_TOKEN`을 등록하고, Docker Hub에 `meal-app` 저장소를 준비하세요. 토큰은 읽기/쓰기 권한만 부여한 Docker Hub access token을 사용합니다. PR 빌드는 Secrets 없이 이미지만 빌드하고 업로드하지 않습니다.

`.github/workflows/deploy.yml`은 이미지 게시가 성공하면 해당 커밋의 불변 SHA 태그를 Windows self-hosted runner에 배포합니다. 독립 모니터가 고정 CC0 음식 이미지로 기존 서비스 응답을 확인한 후 canary를 시험하고, 배포 전·중·후 `/api/analyze` 응답을 기록합니다. 서비스는 `http://127.0.0.1:8765`에서 유지되고 `meal-data` Docker volume에 식단 데이터가 보존됩니다. Summary에는 응답 성공/실패, 시간 간격, 최대 기록 공백과 버전이 표시되며 전체 UTF-8 요청 로그는 Artifact로 남습니다. 샘플링 기록의 공백은 가용성이 확인되지 않은 구간입니다.
