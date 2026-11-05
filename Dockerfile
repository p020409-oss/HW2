FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TORCH_HOME=/opt/torch

WORKDIR /app

RUN groupadd --system app && useradd --system --gid app --home-dir /app app

COPY requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -r requirements.txt

COPY app.py ./app.py
COPY static ./static

# Download the pinned pretrained weights during build and verify a real CPU inference.
RUN python -c "from PIL import Image; import torch; from torchvision.models import ResNet50_Weights, resnet50; torch.set_num_threads(2); weights=ResNet50_Weights.DEFAULT; model=resnet50(weights=weights).eval(); image=weights.transforms()(Image.new('RGB',(224,224))).unsqueeze(0); output=model(image); assert tuple(output.shape)==(1,1000) and torch.isfinite(output).all().item(); print('CPU ResNet50 inference verified:', tuple(output.shape))"

RUN mkdir -p /app/data \
    && chown app:app /app/data \
    && chmod -R a+rX /opt/torch

USER app

EXPOSE 8765
VOLUME ["/app/data"]

CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8765", "--log-level", "info"]
