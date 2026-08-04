.PHONY: test build run

test:
	cd backend && pytest tests/ -v

build:
	docker build -t pr-review-assistant .

run:
	docker run -p 8000:8000 --env-file .env -v prra-data:/app/data pr-review-assistant
