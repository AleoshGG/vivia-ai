# Documentación de Endpoints

---

# GET `/subscriptions/me` — Estado premium del lessor autenticado

Devuelve si el lessor que hace la petición tiene una suscripción premium activa y, en caso afirmativo, hasta cuándo. Es el contrato que los servicios externos (IA, chat) deben consumir para aplicar su propio gating.

- **Autenticación:** JWT con el claim `userId` (Bearer token).
- **Quién lo llama:** la app móvil (para mostrar/ocultar funciones) y los servicios externos de IA y chat.
- **Respuesta exitosa:** `200` con envelope `BaseResponse<PremiumStatusResponseDto>`.

## Respuesta

```json
{
    "success": true,
    "data": {
        "active": true,
        "premiumUntil": "2027-01-01T00:00:00Z"
    },
    "message": "Estado premium consultado.",
    "status": "OK"
}
```

| Campo | Tipo | Descripción |
|---|---|---|
| `active` | boolean | `true` si `premiumUntil` existe y está en el futuro |
| `premiumUntil` | ISO 8601 / `null` | Fecha de vencimiento. `null` si el lessor nunca ha sido premium |

### Lessor sin premium

```json
{
    "success": true,
    "data": {
        "active": false,
        "premiumUntil": null
    },
    "message": "Estado premium consultado.",
    "status": "OK"
}
```

## Errores

| Código | Causa |
|---|---|
| `401 Unauthorized` | Token ausente, inválido o expirado |

---

## Cómo lo debe consumir el servicio de IA

### Idea de implementación

El servicio de IA debe verificar el estado premium **antes de generar** título o descripción con IA. El flujo es:

```
Cliente móvil solicita generación de IA
        │
        ▼
Servicio de IA recibe el JWT del usuario en el header Authorization
        │
        ▼
GET {VIVIA_BACKEND_URL}/subscriptions/me
    Header: Authorization: Bearer <mismo JWT>
        │
        ├── active: true  →  procede a generar con IA
        └── active: false →  responde 403 al cliente
```

### Detalles de la llamada

El servicio de IA reenvía **el mismo JWT que recibió del cliente** al backend Spring. No necesita una API key interna — el backend valida el token con el mismo secreto compartido (`jwt.secret`) y resuelve el `userId` internamente.

```python
# Ejemplo en Python/FastAPI
import httpx

VIVIA_BACKEND_URL = os.environ["VIVIA_BACKEND_URL"]  # ej. https://api.vivia.aleosh.online

async def is_premium(authorization_header: str) -> bool:
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{VIVIA_BACKEND_URL}/subscriptions/me",
            headers={"Authorization": authorization_header},
            timeout=5.0
        )
    if response.status_code != 200:
        return False
    return response.json()["data"]["active"]
```

### Regla de negocio

| Situación | Acción del servicio de IA |
|---|---|
| `active: true` | Procede a generar título/descripción con IA |
| `active: false` | Responde `403` con mensaje "Requiere suscripción Premium" |
| Error de red / timeout al consultar | Responde `503` — no asumir premium por defecto |

> **Importante:** ante cualquier falla al consultar `/subscriptions/me`, el servicio de IA debe **negar el acceso por defecto** (fail closed), no concederlo. Asumir premium ante una falla de red sería un bypass de seguridad.

---