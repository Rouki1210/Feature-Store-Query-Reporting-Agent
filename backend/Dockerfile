# psycopg[binary] và numpy/pandas đều có wheel cho 3.12 → không cần toolchain build.
FROM python:3.12-slim

WORKDIR /app

# Layer riêng: đổi code không cài lại dependency.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000
# 0.0.0.0, không phải 127.0.0.1 — bind loopback thì container khác không gọi được.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
