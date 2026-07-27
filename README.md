# Feature Store Query Agent

Sprint 1 là agent hỏi dữ liệu GSM/VinFast bằng tiếng Việt. Agent chỉ đọc feature
tables, luôn hiển thị SQL, có row limit, timeout và guard AST cho raw/PII/DML.

## Local setup

Prerequisites: Docker Desktop, Python 3.11+, Node.js 20+.

```powershell
docker compose up -d db
Copy-Item backend\.env.example backend\.env
cd backend
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Bootstrap bằng database admin (mặc định trong `.env.example` là `postgres`):

```powershell
.venv\Scripts\alembic.exe upgrade head
.venv\Scripts\python.exe -m scripts.generate_semantic_layer
.venv\Scripts\python.exe -m scripts.generate_mock_data
.venv\Scripts\python.exe -m scripts.seed_golden_set
```

`generate_mock_data` xóa và nạp lại dữ liệu mock trong `raw` và `feature`.

## Runtime role

Tạo/đăng nhập bằng database admin, sau đó thay `<app_user>` bằng username trong
`DATABASE_URL` (ví dụ `agent`):

```sql
GRANT feature_agent_reader TO <app_user>;
GRANT feature_agent_logger TO <app_user>;
GRANT USAGE ON SCHEMA eval TO <app_user>;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA eval TO <app_user>;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA eval TO <app_user>;
```

Runtime query sẽ dùng `SET LOCAL ROLE feature_agent_reader`; vì vậy thiếu role
membership sẽ làm query fail an toàn thay vì chạy với quyền rộng.

## Verify and run

```powershell
cd backend
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m scripts.run_eval --tag sprint1-dev --split dev
uvicorn app.main:app --reload

cd ..\frontend
npm.cmd run test
npm.cmd run build
npm.cmd run dev
```

Chỉ chạy `--split holdout` một lần sau khi dev đạt target. Xem
[`docs/sprint1_runbook.md`](docs/sprint1_runbook.md) để đóng release.
