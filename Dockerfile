# Used when hosting on Hugging Face Spaces, Render, Railway, or Fly.io.
# Not needed to run the app on your own computer.

FROM python:3.12-slim

WORKDIR /app

# Install dependencies first, in their own layer. Docker caches this, so
# changing your code doesn't trigger a fresh 2GB PyTorch download.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Bake the embedding model into the image. Without this, the first visitor
# after every restart waits 30+ seconds for a 90MB download.
RUN python -c "from sentence_transformers import SentenceTransformer; \
    SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"

# Hugging Face Spaces expects port 7860. Other hosts usually set $PORT.
ENV PORT=7860
EXPOSE 7860

CMD uvicorn app:app --host 0.0.0.0 --port ${PORT}
