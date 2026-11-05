FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TORCH_HOME=/opt/torch \
    HF_HOME=/opt/huggingface

WORKDIR /app

RUN groupadd --system app && useradd --system --gid app --home-dir /app app

COPY requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -r requirements.txt

COPY app.py ./app.py
COPY static ./static

# Download the pinned Apache-2.0 model during build and verify a real CPU inference.
RUN python -c "import torch; from PIL import Image; from transformers import AutoImageProcessor, AutoModelForImageClassification; repo='rajistics/finetuned-indian-food'; rev='27e01953a3945806138ab2452d0ca5ada4412628'; torch.set_num_threads(2); processor=AutoImageProcessor.from_pretrained(repo,revision=rev,use_fast=False); model=AutoModelForImageClassification.from_pretrained(repo,revision=rev).eval(); inputs=processor(images=Image.new('RGB',(224,224)),return_tensors='pt'); output=model(**inputs).logits; assert tuple(output.shape)==(1,20) and torch.isfinite(output).all().item(); print('CPU model inference verified:',tuple(output.shape),rev)"

RUN mkdir -p /app/data \
    /opt/torch \
    /opt/huggingface \
    && chown app:app /app/data \
    && chmod -R a+rX /opt/torch /opt/huggingface

USER app

EXPOSE 8765
VOLUME ["/app/data"]

CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8765", "--log-level", "info"]
