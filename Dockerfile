FROM node:20-bookworm-slim

RUN apt-get update && \
    apt-get install -y python3 python3-pip && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt

COPY . .

CMD ["sh", "-c", "python3 -m uvicorn reanime:app --host 0.0.0.0 --port ${PORT}"]
