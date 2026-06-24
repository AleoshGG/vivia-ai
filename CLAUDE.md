# Vivia — Servicios de Inteligencia Artificial

## Proyecto

- **Nombre:** vivia-ai
- **Descripción:** Servicio que brinda distintos microservicios de IA
- **Lenguaje:** Python 3.12
- **Framework:** Python
- **Arquitectura:** MVC + SOLID
- **Idioma de conversación:** Español México
- **Idioma de documentación:** Español México

## Herramientas
- Usa siempre **codegraph** para navegar sobre el proyecto
- Lee los .md que se encuentran en docs/contexto/ para trabajar de forma eficiente.

## Documentación

- Los scopes del proyecto están en `docs/SCOPES/`
- Los planes de implementación están en `docs/PLANS/`
- Toda documentación se escribe en **Español México**

## Modo Planning

Cuando se entre en modo planning (al planear una nueva feature, refactor, o cambio significativo), **antes de escribir cualquier código** se debe crear un archivo de plan en `docs/PLANS/` con el siguiente formato:

**Nombre del archivo:** `<YYYY-MM-DD>-PLAN_<FEATURE_NAME>_.md`

**Estructura mínima del plan:**
```markdown
# Plan: <Nombre de la feature>

## Objetivo
Descripción breve de qué se va a implementar y por qué.

## Alcance
- Qué está incluido
- Qué está excluido (límites claros)

## Cambios por capa

## Dependencias
Otros features o servicios que este plan toca o requiere.

## Pasos de implementación
1. ...
2. ...
```

El plan se escribe antes de implementar y se actualiza si el alcance cambia durante el desarrollo.
