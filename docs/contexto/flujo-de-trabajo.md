# Flujo de Trabajo — Vivia AI

## Pasos para Hacer un Cambio

[PENDIENTE: no hay código ni pipeline CI/CD. El flujo se definirá cuando exista el scaffolding. Se anticipa algo como:]

1. Crear branch desde `main`
2. [PENDIENTE: convención de nombres de branches]
3. Hacer cambios en el código
4. Correr tests localmente: `make test`
5. [PENDIENTE: linter/formatter obligatorio antes de commit]
6. Commit con [PENDIENTE: convención de commits]
7. Push y crear PR
8. [PENDIENTE: revisión de código requerida?]
9. Merge a `main`

## Checklist de "Terminado"

- [ ] El código compila/corre sin errores
- [ ] Tests unitarios pasan (`make test-unit`)
- [ ] [PENDIENTE: tests de integración pasan?]
- [ ] [PENDIENTE: linter pasa sin warnings?]
- [ ] [PENDIENTE: documentación actualizada?]
- [ ] [PENDIENTE: cambios reflejados en el CHANGELOG?]

## Deploy

[PENDIENTE: no hay pipeline de deploy configurado. Se planea:]

- Docker images construidas con `infrastructure/docker/*.Dockerfile`
- Deploy con `docker-compose up -d`
- Script de deploy en `infrastructure/cloud_deploy/build_and_push.sh`
- [PENDIENTE: ¿deploy a qué entorno? ¿VPS directo, Kubernetes, Cloud Run?]

## Desarrollo Local

[PENDIENTE: se planea usar `docker-compose.dev.yml` con mounts para desarrollo. Comando anticipado:]

```bash
# Levantar servicios en modo desarrollo
make dev          # docker-compose -f docker-compose.yml -f docker-compose.dev.yml up

# Correr tests
make test         # pytest tests/ -v

# Solo un servicio
make dev-anomaly  # docker-compose up anomaly-api
```
