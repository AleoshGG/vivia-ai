.PHONY: help build up down dev test test-unit test-integration

help:
	@echo "Vivia AI - Makefile"
	@echo "==================="
	@echo "build            - Construye las imágenes Docker"
	@echo "up               - Levanta los servicios de producción"
	@echo "down             - Detiene todos los servicios"
	@echo "dev              - Levanta los servicios en modo desarrollo"
	@echo "test             - Ejecuta todos los tests con cobertura"
	@echo "test-unit        - Ejecuta tests unitarios"
	@echo "test-integration - Ejecuta tests de integración"
	@echo "lint             - Ejecuta ruff y black"

build:
	docker-compose build

up:
	docker-compose up -d

down:
	docker-compose down
	docker-compose -f docker-compose.yml -f docker-compose.dev.yml down

dev:
	docker-compose -f docker-compose.yml -f docker-compose.dev.yml up -d

test:
	pytest tests/ -v --cov=src --cov=shared --cov=data_lake

test-unit:
	pytest tests/unit/ -v

test-integration:
	pytest tests/integration/ -v

lint:
	ruff check .
	black --check .
