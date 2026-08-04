.PHONY: test test-backend test-frontend build run

# One-command test: backend pytest + frontend vitest (see also GitHub Actions
# .github/workflows/ci.yml and .gitlab-ci.yml). On Windows without GNU make,
# run the two commands directly: `cd backend && pytest tests/` and
# `cd frontend && npm test -- --run`.
test: test-backend test-frontend

test-backend:
	cd backend && pytest tests/ -q

test-frontend:
	cd frontend && npm test -- --run

build:
	docker build -t pr-review-assistant -f backend/Dockerfile .

run:
	docker run -p 8000:8000 --env-file .env -v prra-data:/app/data pr-review-assistant
