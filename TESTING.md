# TESTING — TrackFlow

Plan de pruebas del ticket **AUTH-088** (API de autenticación) y de los tickets extra **API-042** (backoffice) y
**FE-019** (utilidades del frontend).

## Criterio

Las pruebas unitarias llaman a la lógica directamente —funciones de `security.py`, `user_service.py` y los handlers de
ruta como funciones de Python— y comprueban lo que la aplicación **decide**: quién queda autenticado, qué se guarda,
qué se rechaza y con qué motivo. No se comprueba la serialización HTTP ni el enrutado de FastAPI. Por eso los handlers
se invocan sin `TestClient`, y las decisiones de rechazo se verifican por el `status_code` de la `HTTPException` que
lanza la lógica.

Cada endpoint tiene como mínimo un **camino feliz**, un **caso límite** y un **modo de fallo**.

## Cómo ejecutar

Backend (desde la raíz del repo; `pytest` y `pytest-cov` están en el grupo `dev` de `pyproject.toml`):

```bash
uv sync                          # instala dependencias, incluido el grupo dev
uv run pytest                    # toda la batería de Python
uv run pytest --cov              # con informe de cobertura (líneas no cubiertas incluidas)
uv run pytest tests/auth         # solo AUTH-088
uv run pytest tests/backoffice   # solo API-042
uv run pytest tests/inventory    # solo inventario
uv run pytest tests/cache        # solo la caché TTL y su invalidación
```

Frontend, de forma independiente (`uis/backoffice`, configurado en `jest.config.js`):

```bash
cd uis/backoffice
npm install
npm test                         # jest
npm run test:coverage            # jest --coverage
```

Ninguna suite necesita `.env`, red ni la API arrancada: `tests/conftest.py` apunta cada test a bases TinyDB
temporales (`AUTH_DB_PATH`, `SUPPLIERS_DB_PATH`, `INCIDENTS_DB_PATH`), fija un `JWT_SECRET_KEY` de prueba y borra
las variables de Resend y Codespaces, y vacía las cachés del módulo (`products_cache`, `summary_cache`); los tests de Jest sustituyen `fetch` y `window.localStorage` por dobles.

## Estructura

| Carpeta | Qué contiene |
| --- | --- |
| `tests/auth/` | AUTH-088, un módulo por endpoint o pieza: `test_register.py`, `test_login.py`, `test_token.py`, `test_session.py`, `test_users.py`, `test_password_reset.py`, `test_passwords.py`, `test_reset_email.py`. |
| `tests/backoffice/` | API-042: `test_suppliers.py` y `test_incidents.py`. |
| `tests/inventory/` | Inventario (`/inventory`) con SQLite en memoria: stock por almacén, rechazo de salidas sin stock, `tracking_number`, `user_uuid` y restricciones de la base de datos. |
| `tests/cache/` | Caché TTL (`services/api/cache.py`): expiración, invalidación, LRU y carrera de generación; invalidación tras cada escritura de inventario e incidencias, cambios externos visibles tras el TTL y 401 sin token en las rutas cacheadas (`audit/caching/CACHING_REPORT.md`). |
| `tests/http/` | Pruebas de integración anteriores a este ticket (con `TestClient`), movidas desde `services/api/`. Cubren el contrato HTTP y el manejo global de errores, que las unitarias no tocan a propósito. `test_serialization.py` fija la forma de cada respuesta y exige un `response_model` Pydantic en toda ruta JSON (`docs/serialization-audit.md`). |
| `tests/conftest.py`, `tests/helpers.py` | Aislamiento del entorno, fixture `make_user`, `FakeRequest` para el login y `run()` para los handlers async. |
| `uis/backoffice/__tests__/` | Jest: `api-client.test.ts`, `registration.test.ts`, `incidents.test.ts`, `labels.test.ts`. |

## Plan — API de autenticación (AUTH-088)

### Registro — `POST /users` (`register_user`, `create_user`, `UserCreate`)
- Feliz: crea el usuario con rol `user`, activo, email en minúsculas, contraseña hasheada (nunca en claro) y su perfil 1:1.
- Límite: contraseña de exactamente 8 caracteres (aceptada) y de 7 (rechazada); email duplicado que solo difiere en
  mayúsculas (409); perfil sin datos opcionales.
- Fallo: contraseña vacía, email mal formado y contraseña de más de 72 **bytes** (rechazadas por el modelo).

### Login — `POST /auth/login` (`login`, `_login_payload`)
- Feliz: credenciales JSON devuelven un token cuyo `sub` es el id del usuario; también acepta el formulario OAuth2
  (`username`).
- Límite: email con mayúsculas; contraseña de más de 72 bytes (debe ser 401, no un error interno).
- Fallo: contraseña incorrecta, email inexistente (mismo mensaje, sin revelar qué cuentas existen), usuario desactivado
  y cuerpo sin contraseña o sin email.

### Tokens — `create_access_token`, `get_current_user`, `create_reset_token`, `reset_token_user_id`
- Feliz: el token válido identifica al usuario; `exp` respeta `ACCESS_TOKEN_EXPIRE_MINUTES`.
- Límite: token a un segundo de caducar (aceptado) frente a uno caducado hace un segundo (rechazado); expiración
  personalizada.
- Fallo: token caducado (la regresión que originó el ticket), mal formado, firmado con otra clave, alterado, token de
  recuperación usado como acceso, sin `sub`, usuario borrado o desactivado, y configuración ausente o inválida
  (`JWT_SECRET_KEY`, `ACCESS_TOKEN_EXPIRE_MINUTES`), que es un error del servidor y no un 401.

### Sesión — `GET /auth/me` y perfiles `GET/PUT /profiles/me`
- Feliz: devuelve email, rol y perfil; el perfil se actualiza.
- Límite: perfil con campos vacíos; `PUT` es un reemplazo completo (un campo omitido queda a `None`).
- Fallo: usuario sin perfil (404).

### Usuarios — `GET/PUT/DELETE /users`, `GET /users/{id}`
- Feliz: el propietario lee, edita y borra su cuenta (borrado en cascada de perfil y tokens de recuperación); un admin
  lista usuarios y cambia roles.
- Límite: cambiar el email al suyo propio con otras mayúsculas; cambiar la contraseña invalida los enlaces de
  recuperación pendientes.
- Fallo: un usuario normal lista usuarios, accede a otra cuenta o se cambia el rol (403); email en uso (409); usuario
  inexistente (404).

### Recuperación — `POST /auth/forgot-password`, `/auth/reset-password`, `/auth/change-password`
- Feliz: se envía un enlace con un token que se guarda solo como hash; el reset cambia la contraseña y consume el
  token; el cambio autenticado funciona.
- Límite: pedir un segundo enlace invalida el primero; en Codespaces la URL local se transforma en la del puerto
  reenviado; la misma respuesta para cuentas inexistentes o desactivadas (y sin enviar email).
- Fallo: token reutilizado, caducado, inválido o de acceso; usuario borrado; contraseña actual incorrecta; el proveedor
  de email falla (la respuesta sigue siendo genérica).

### Contraseñas — `hash_password`, `verify_password`
- Feliz: el hash verifica la contraseña correcta.
- Fallo: contraseña incorrecta; contraseña de más de 72 bytes.

## Plan — backoffice (API-042)

### Proveedores — `/suppliers`
- Feliz: alta con `updated_at`, filtros por país y categoría, cambio de tarifa y de estado, borrado.
- Límite: moneda que no corresponde al país; tarifa 0; sin categorías.
- Fallo: proveedor inexistente (404) en lectura, tarifa, estado y borrado.

### Incidencias — `/api/incidents`
- Feliz: alta con estado `open` y `reported_by`; filtros; resumen.
- Límite: base de datos vacía (lista vacía y métricas a cero); título de 120 caracteres; título con solo espacios.
- Fallo: estado inicial distinto de `open`; transiciones no permitidas y estados finales; incidencia inexistente.

## Plan — TypeScript (Jest, `uis/backoffice`)

- Autenticación (`lib/api-client.ts`): guardado y borrado del token, cabecera `Authorization`, cierre de sesión ante
  `401`, error de red, mensajes de error por estado y respuesta no JSON.
- Registro (`validateRegistration`): datos válidos frente a email vacío o mal formado, contraseña corta o larga y
  confirmación distinta.
- FE-019: `validateIncidentForm`, `toFriendlyError`, `formatIncidentDate` y `formatUSD`.

## Resultados

- `uv run pytest`: 146 tests en verde (89 en `tests/auth`, 26 en `tests/backoffice`, 31 en `tests/http`).
- `npm test` en `uis/backoffice`: 40 tests en 4 suites, en verde.

### Cobertura de AUTH-088 (solo `tests/auth`, objetivo ≥ 70 %)

| Módulo | Cobertura |
| --- | --- |
| `routes/auth.py`, `routes/users.py`, `routes/profiles.py` | 100 % |
| `security.py`, `passwords.py`, `reset_email.py`, `auth_models.py` | 100 % |
| `user_service.py` | 97 % (sin cubrir: la reversión del alta si falla la escritura del perfil y un token de recuperación de un usuario borrado a mitad de la operación) |

### Cobertura de API-042 (solo `tests/backoffice`, objetivo ≥ 60 %)

| Módulo | Cobertura |
| --- | --- |
| `routes/suppliers.py`, `models.py` | 100 % |
| `routes/incidents.py` | 91 % (sin cubrir: los manejadores de error HTTP, que prueba `tests/http`) |
| `incident_models.py` | 100 % |

Con toda la batería, la cobertura global de `services/api` y `packages/shared` es del 88 %; `seed.py` (script de
carga manual) queda fuera al 0 %.

### Cobertura de Jest (`uis/backoffice/lib`)

| Módulo | Cobertura de líneas |
| --- | --- |
| `registration.ts`, `labels.ts` | 100 % |
| `api-client.ts` | 89 % (sin cubrir: `requestBlob`, usado solo en la descarga de CSV) |
| `incidents.ts` | 86 % (sin cubrir: los envoltorios `fetch*`, que solo montan la URL) |

## Bugs detectados por la batería

1. **Contraseñas de más de 72 bytes (backend).** `UserCreate` limitaba a 72 *caracteres*, pero bcrypt limita a 72
   *bytes*: una contraseña de 40 «ñ» (80 bytes) pasaba la validación y `bcrypt` lanzaba `ValueError`, que acababa
   en un 500 al registrarse o al hacer login. Arreglo: `passwords.exceeds_bcrypt_limit` y el tipo `NewPassword` en
   `auth_models.py` rechazan la contraseña con un mensaje claro, y `verify_password` devuelve `False` (login → 401).
   Tests: `test_register.py` y `test_login.py`.
2. **El mismo límite en el frontend.** `validateRegistration` contaba caracteres, así que el formulario daba por
   buena una contraseña que la API rechazaba. Se extrajo del componente a `lib/registration.ts` (para poder probarla)
   y ahora mide bytes con `TextEncoder`. Test: `registration.test.ts`.
3. **`formatIncidentDate` con una fecha inválida.** `Intl.DateTimeFormat` lanza `RangeError` y un solo registro
   corrupto tumbaba el listado de incidencias. Ahora devuelve «Fecha no disponible». Test: `incidents.test.ts`.

## Casos sugeridos por la IA

Se pasó al agente la lógica de cada endpoint y se le pidió qué casos límite faltaban. De sus propuestas se
incorporaron, tras revisarlas:

- Contraseñas multibyte (acentos, «ñ») en el límite de bcrypt: de ahí salieron los bugs 1 y 2.
- Tokens en la frontera exacta de caducidad (un segundo antes y un segundo después), que es la regresión que motivó
  AUTH-088.
- Un token de recuperación usado como token de acceso, y al revés.
- Configuración ausente (`JWT_SECRET_KEY`) tratada como error del servidor y no como 401, para no esconder un fallo
  de despliegue tras «credenciales incorrectas».
- En el cliente, no redirigir a `/login` cuando el 401 llega desde el propio login (evita un bucle de recargas).
- Filtros de incidencias: FastAPI entrega los valores ya convertidos a enum, así que los tests pasan enums y no
  cadenas, igual que en producción.

Se descartaron las propuestas que solo comprobaban la forma del JSON o los códigos de FastAPI (por ejemplo, el 422
de un campo ausente), porque prueban el framework y no nuestra lógica.
