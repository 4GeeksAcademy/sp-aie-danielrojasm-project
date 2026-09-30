# Auditoría de serialización del backend — `services/api`

**Rama:** `feat/serialization-audit` · **Alcance:** las 32 rutas de la API FastAPI de TrackFlow
(31 publicadas en `/openapi.json` más el health check `GET /`, que queda fuera del esquema).

## Resumen

| Estado original | Rutas | Estado final |
|---|---|---|
| ✅ Ya serializado | 14 | ✅ 14 |
| ⚠️ Parcialmente serializado | 11 | ✅ 11 |
| ❌ Sin serializar | 7 | ✅ 7 |
| **Total** | **32** | **✅ 32** |

Hallazgos principales del estado original:

- **Auth reenviaba el email en un flujo sin sesión.** `POST /users` (registro) devolvía `UserResponse` con `email`.
- **Claves internas expuestas.** `GET /auth/me`, `GET /profiles/me` y `PUT /profiles/me` devolvían el documento de perfil
  entero, con `id` y `user_id`. El backoffice usaba `profile.user_id` como id del propio usuario: la UI dependía de una
  clave foránea interna.
- **Seis rutas sin contrato tipado.** Devolvían un `dict` sin esquema: `forgot-password`, `reset-password` y `change-password`
  (`dict[str, str]`), `DELETE /suppliers/{id}` (`dict[str, str]`), `POST /api/incidents/analyze` (`dict[str, object]`,
  que en OpenAPI sale como `object` con `additionalProperties: true`) y el health check. A estas se suma la descarga CSV,
  que no declaraba su tipo de contenido: son las 7 rutas ❌.
- **Seguridad implícita.** Las rutas de usuarios devolvían el modelo interno `User`, que lleva `hashed_password`, y dependían
  de que `response_model` lo filtrara. Si alguien quitaba el decorador o cambiaba la anotación, el hash salía en la respuesta.
- **Listados que reutilizaban el esquema de detalle.** Proveedores, incidencias y SKUs devolvían en cada fila campos que la
  tabla no pinta, y el historial de inventario anidaba un objeto SKU completo del que la UI solo lee tres campos.
- **Escritura permisiva.** Los esquemas de entrada de auth, perfil y proveedores ignoraban en silencio los campos extra
  (`role`, `user_id`, `updated_at`…). Ahora responden 422.

### Metodología

1. Inventario de rutas a partir de `app.openapi()` sobre `main` (commit `6fb98d1`), leyendo el esquema de la respuesta 2xx
   de cada operación.
2. Lectura de cada handler: qué devuelve realmente (modelo interno, `dict` o esquema de respuesta).
3. Trazado de consumidores: los campos que lee el backoffice (`uis/backoffice/lib/*.ts`, `components/**`) en cada respuesta.
4. Clasificación ✅ / ⚠️ / ❌ y decisión por endpoint (más abajo).

### Criterios de clasificación

- **✅ Ya serializado:** `response_model` explícito con un esquema Pydantic cuyos campos coinciden con lo que necesita el
  consumidor, sin datos sensibles.
- **⚠️ Parcialmente serializado:** tiene `response_model`, pero expone campos innecesarios o internos, reutiliza el esquema de
  detalle en un listado o devuelve un modelo interno que solo el decorador filtra.
- **❌ Sin serializar:** devuelve un `dict` sin tipar o no declara el contrato de la respuesta.

---

## 1. Autenticación (`/auth`, `/users`, `/profiles`)

Son las rutas de mayor riesgo y por eso se auditan primero. Reglas aplicadas:

- Ninguna respuesta lleva contraseñas, ni en texto plano ni hasheadas.
- Los flujos sin sesión (registro, login, forgot y reset) no reenvían el email.
- `GET /auth/me` sí devuelve el email del propio llamante, porque la vista de perfil lo muestra.

| # | Método y ruta | Propósito | Original | Qué devolvía | Cambio aplicado | Estado |
|---|---|---|---|---|---|---|
| 1 | `POST /auth/login` | Emitir JWT | ✅ | `TokenResponse` | Ninguno | ✅ |
| 2 | `POST /auth/forgot-password` | Pedir enlace de recuperación | ❌ | `dict[str, str]` | `MessageResponse`; entrada con `extra="forbid"` | ✅ |
| 3 | `POST /auth/reset-password` | Restablecer con token | ❌ | `dict[str, str]` | `MessageResponse`; entrada con `extra="forbid"` | ✅ |
| 4 | `POST /auth/change-password` | Cambiar contraseña con sesión | ❌ | `dict[str, str]` | `MessageResponse`; entrada con `extra="forbid"` | ✅ |
| 5 | `GET /auth/me` | Sesión actual | ⚠️ | `profile` con `id` y `user_id` internos; sin `id` de usuario | `CurrentUserResponse` con `id` y `ProfileRead` | ✅ |
| 6 | `POST /users` | Registro público | ⚠️ | `UserResponse` con **`email`**, `is_active`, `created_at` | `UserRegistered`; entrada con `extra="forbid"` | ✅ |
| 7 | `GET /users` | Listado (admin) | ⚠️ | Mismo esquema que el detalle; el handler devolvía `User` (con hash) | `UserListItem` | ✅ |
| 8 | `GET /users/{user_id}` | Detalle (dueño o admin) | ⚠️ | `UserResponse`, pero el handler devolvía `User` (con hash) | `UserRead`, construido explícitamente | ✅ |
| 9 | `PUT /users/{user_id}` | Actualizar credenciales | ⚠️ | Igual que #8 | `UserRead`; entrada con `extra="forbid"` | ✅ |
| 10 | `DELETE /users/{user_id}` | Baja de cuenta | ✅ | 204 sin cuerpo | Se declara `response_model=None` y `response_class=Response` | ✅ |
| 11 | `GET /profiles/me` | Perfil propio | ⚠️ | `Profile` con `id` y `user_id` | `ProfileRead` | ✅ |
| 12 | `PUT /profiles/me` | Editar perfil propio | ⚠️ | Igual que #11 | `ProfileRead`; entrada `ProfileUpdate` con `extra="forbid"` | ✅ |

### Payloads de salida objetivo

```jsonc
// POST /auth/login → TokenResponse (sin cambios)
{ "access_token": "<jwt>", "token_type": "bearer" }

// POST /auth/forgot-password | /auth/reset-password | /auth/change-password → MessageResponse
{ "message": "Si esa dirección está registrada, recibirás un enlace en breve" }

// POST /users → UserRegistered (201)
{ "id": "uuid", "role": "user", "created_at": "…" }

// GET /auth/me → CurrentUserResponse
{ "id": "uuid", "email": "ana@example.com", "role": "user",
  "profile": { "name": "Ana", "phone": null, "address": null } }

// GET /users/{id}, PUT /users/{id} → UserRead
{ "id": "uuid", "email": "ana@example.com", "role": "user", "is_active": true, "created_at": "…" }

// GET /users → UserListItem[]
[{ "id": "uuid", "email": "ana@example.com", "role": "user", "is_active": true }]

// GET /profiles/me, PUT /profiles/me → ProfileRead
{ "name": "Ana", "phone": null, "address": null }
```

### Decisiones y motivos

- **Registro (#6) sin email.** El cliente acaba de enviarlo en la petición y el backoffice ignora la respuesta, porque justo
  después llama a `/auth/login`. Se devuelve el `id` para que otros consumidores puedan referenciar la cuenta, el `role`
  (confirma que el alta nunca crea un admin) y `created_at`. `is_active` se omite: en el alta siempre vale `true`.
- **Login (#1) y forgot y reset (#2 y #3).** Solo token o mensaje genérico. El mensaje de forgot no cambia exista o no la
  cuenta, así que no revela qué emails están registrados.
- **Relación usuario → perfil en `/auth/me` (#5): se mantiene anidada como proyección.** El perfil sigue en un objeto
  `profile` porque agrupa los datos editables y tiene la misma forma que `PUT /profiles/me` (el formulario rellena sus
  valores por defecto con él). Se quitan sus claves internas (`id` del documento y `user_id`). El id del usuario sube al
  nivel superior como `id`: es el propio llamante, y la UI lo necesita para marcar «Tú» en el historial de inventario. Antes
  lo sacaba de `profile.user_id`.
- **Listado de admin (#7) más ligero que el detalle (#8).** Para identificar y gestionar una cuenta basta con `id`, `email`,
  `role` e `is_active`; `created_at` queda en el detalle. Aquí el email sí se incluye, porque la ruta exige sesión de admin y
  es el identificador humano de la cuenta.
- **Construcción explícita.** Todos los handlers devuelven ya el esquema de salida (`UserRead.model_validate(user)`…) y no
  el modelo interno `User`. El hash ya no depende de que el decorador lo filtre.
- **Entrada estricta.** `UserCreate`, `UserUpdate`, `ProfileUpdate`, `ForgotPasswordRequest`, `ResetPasswordRequest` y
  `ChangePasswordRequest` llevan `extra="forbid"`. Así, un `{"role": "admin"}` en el registro o un `user_id` en el perfil
  responden 422 en lugar de ignorarse en silencio. `LoginRequest` no lo lleva: el formulario OAuth2 ya se reduce a mano a
  `email` y `password`. En JSON, un campo extra acabaría en el 422 genérico «Email y contraseña son obligatorios», que
  confundiría al usuario, y el login no persiste nada de lo que recibe.
- **DELETE 204 (#10).** No tiene cuerpo que serializar. Se declara `response_model=None` para que la ausencia de contrato
  sea explícita y no casual.

---

## 2. Proveedores (`/suppliers`)

| # | Método y ruta | Propósito | Original | Qué devolvía | Cambio aplicado | Estado |
|---|---|---|---|---|---|---|
| 13 | `POST /suppliers` | Alta | ✅ | `Supplier` (entrada `SupplierCreate`, esquema distinto) | Entrada con `extra="forbid"` (`id` y `updated_at` los pone el servidor) | ✅ |
| 14 | `GET /suppliers` | Directorio con filtros | ⚠️ | `Supplier[]` completo, con `contact_email`, `notes` y `updated_at` | `SupplierListItem[]` | ✅ |
| 15 | `GET /suppliers/{id}` | Detalle | ✅ | `Supplier` | Ninguno | ✅ |
| 16 | `PATCH /suppliers/{id}/rate` | Cambiar tarifa | ✅ | `Supplier` | `RateUpdate` con `extra="forbid"` | ✅ |
| 17 | `PATCH /suppliers/{id}/status` | Suspender o reactivar | ✅ | `Supplier` | `StatusUpdate` con `extra="forbid"` | ✅ |
| 18 | `DELETE /suppliers/{id}` | Baja | ❌ | `dict[str, str]` | `MessageResponse` | ✅ |

```jsonc
// GET /suppliers → SupplierListItem[]
[{ "id": 1, "name": "MRW España", "country": "Spain", "categories": ["carrier_last_mile"],
   "rate_per_shipment": 4.1, "currency": "EUR", "status": "active", "service_zone": "Península" }]
```

- **Por qué:** la tabla de `SupplierDirectory` solo pinta nombre, zona, país, categorías, tarifa con moneda y estado.
  `notes` es texto libre de longitud arbitraria y `contact_email` es un dato de contacto que no se muestra. Con los 15
  proveedores de referencia el listado pasa de **4.823 a 2.679 bytes (−44,5 %)**.
- El detalle y las respuestas de escritura conservan `Supplier` completo. El backoffice inserta esas respuestas en la tabla,
  y un objeto de detalle es un superconjunto de la fila, así que encaja sin conversión.

---

## 3. Incidencias (`/api/incidents`)

| # | Método y ruta | Propósito | Original | Qué devolvía | Cambio aplicado | Estado |
|---|---|---|---|---|---|---|
| 19 | `POST /api/incidents` | Registrar incidencia | ✅ | `Incident` (entrada `IncidentCreate` con `extra="forbid"`) | Ninguno | ✅ |
| 20 | `GET /api/incidents` | Tablero con filtros | ⚠️ | `Incident[]` con `reported_by` (email del empleado) y `updated_at` | `IncidentListItem[]` | ✅ |
| 21 | `GET /api/incidents/summary` | Totales agregados | ✅ | `IncidentSummary` | Ninguno | ✅ |
| 22 | `GET /api/incidents/{id}` | Detalle | ✅ | `Incident` | Ninguno | ✅ |
| 23 | `PATCH /api/incidents/{id}/status` | Cambio de estado | ✅ | `Incident` (entrada `IncidentStatusUpdate` con `extra="forbid"`) | Ninguno | ✅ |
| 24 | `POST /api/incidents/analyze` | Analizar CSV subido | ❌ | `dict[str, object]` sin tipar | `IncidentAnalysisSummary` (con `BreakdownValue` e `InvalidReasonCount`) | ✅ |
| 25 | `GET /api/incidents/results/export` | Descargar métricas en CSV | ❌ | `StreamingResponse` sin contrato declarado | `response_model=None`, `response_class=StreamingResponse` y `text/csv` documentado | ✅ |

```jsonc
// GET /api/incidents → IncidentListItem[]
[{ "id": 7, "title": "Palé dañado en muelle 3", "description": "…", "category": "warehouse_incident",
   "status": "open", "origin": "branch", "branch": "zaragoza_warehouse", "created_at": "…" }]
```

- **Listado sin `reported_by`.** Es el email del empleado que registró la incidencia: el tablero no lo muestra y un listado
  no debe repartir emails internos a todo el que tenga sesión. Sigue en el detalle y en la respuesta del alta, donde sirve
  para la trazabilidad. `updated_at` tampoco se usa en el tablero. `description` **se mantiene**: el tablero la pinta
  debajo del título. Con las 95 incidencias del seed el listado pasa de **30.958 a 25.733 bytes (−16,9 %)**.
- **Coherencia en la UI.** Tras un cambio de estado, el tablero solo copia `status` de la respuesta en su fila, en lugar del
  objeto completo, para que el estado local siga el contrato del listado.
- **`status` en `IncidentCreate`.** Se acepta a propósito: el formulario lo envía y la ruta responde 400 con el campo
  afectado si no es `open`. Quitarlo rompería el contrato con el backoffice sin ganar seguridad, porque el valor ya se valida.
- **Analizador.** El esquema documenta en `/docs` la forma exacta del resumen (antes era un `object` opaco) y solo contiene
  métricas agregadas, sin datos de los registros originales.
- **Exportación CSV.** Es una descarga `text/csv` y no JSON, así que no hay modelo Pydantic que aplicar. La ausencia de
  modelo se declara de forma explícita y el tipo de contenido queda documentado en OpenAPI.

---

## 4. Inventario (`/inventory`)

| # | Método y ruta | Propósito | Original | Qué devolvía | Cambio aplicado | Estado |
|---|---|---|---|---|---|---|
| 26 | `GET /inventory/products` | Tabla de stock y selectores | ⚠️ | `SKURead[]` con `stock_by_warehouse` | `SKUListItem[]` | ✅ |
| 27 | `POST /inventory/products` | Alta de SKU | ✅ | `SKURead` (entrada `SKUCreate` con `extra="forbid"`) | Ninguno | ✅ |
| 28 | `GET /inventory/products/{id}` | Stock de un SKU | ✅ | `SKURead` | Ninguno (ahora extiende `SKUListItem`) | ✅ |
| 29 | `POST /inventory/orders/inbound` | Registrar recepción | ✅ | `StockEntryRead` (entrada con `extra="forbid"`) | Ninguno | ✅ |
| 30 | `POST /inventory/orders/outbound` | Registrar salida | ✅ | `StockExitRead` (entrada con `extra="forbid"`) | Ninguno | ✅ |
| 31 | `GET /inventory/orders` | Historial de movimientos | ⚠️ | `InventoryOrderRead` con `sku: SKUSummary` anidado (5 campos) | SKU aplanado: `sku_code`, `sku_name`, `client_name` | ✅ |

```jsonc
// GET /inventory/products → SKUListItem[]
[{ "id": 1, "name": "Zapatilla W 42", "sku": "CLT-SNK-W-42", "client_name": "…",
   "category": "fashion", "warehouse": "LA", "current_stock": 165 }]

// GET /inventory/orders → InventoryOrderRead[]
[{ "order_type": "outbound", "id": 5, "sku_code": "TEC-CHG-065", "sku_name": "…", "client_name": "…",
   "quantity": 10, "warehouse": "ZGZ", "created_at": "…", "user_uuid": "uuid",
   "reference": null, "exit_type": "dispatch", "tracking_number": "1Z…" }]
```

- **Relación movimiento → SKU: proyección plana.** El historial solo pinta el nombre, el código y el cliente del SKU. El
  objeto anidado repetía el `id` del SKU (que la UI no usa) y su `warehouse`, que ya es el `warehouse` del movimiento.
  Aplanar quita un nivel de anidación y dos campos por fila.
- **`stock_by_warehouse` solo en el detalle.** La tabla de stock y los selectores usan `current_stock`, que es el stock del
  almacén del SKU. El desglose LA/ZGZ queda en `GET /inventory/products/{id}`, que es donde se consulta un SKU concreto.
  `SKURead` hereda de `SKUListItem`, así que los dos contratos no pueden divergir.
- **Claves foráneas en bruto.** `StockEntryRead` y `StockExitRead` devuelven `sku_id`: no hay objeto anidado disponible y
  es el mismo valor que el cliente acaba de enviar, así que no se cambia. `user_uuid` se mantiene en el historial por
  trazabilidad (quién movió el stock) y porque la UI lo muestra. No es una credencial.
- La serialización del inventario ya era explícita: `schemas.py` separa entrada y salida de los modelos ORM de SQLModel, y
  ningún handler devuelve una fila del ORM.

---

## 5. Servicio

| # | Método y ruta | Propósito | Original | Qué devolvía | Cambio aplicado | Estado |
|---|---|---|---|---|---|---|
| 32 | `GET /` | Health check (Docker) | ❌ | `dict[str, str]` | `HealthResponse` (sigue fuera del OpenAPI) | ✅ |

---

## Cambios en el backoffice

Los contratos nuevos se reflejan en `uis/backoffice`:

- `types/auth.ts`: `AuthUser.id` y `Profile` sin `id`/`user_id`.
- `InventoryOrderHistory`: usa `user.id` y los campos planos del SKU.
- `lib/inventory.ts`: tipos `SKUListItem` (listado) y `SKU` (detalle, que lo extiende); `InventoryOrder` pasa a ser plano.
- `lib/incidents.ts`: `IncidentListItem` (listado) e `Incident` (detalle, que lo extiende).
- `SupplierDirectory`: `SupplierListItem` para las filas y `Supplier` para las respuestas de escritura.

## Verificación

- **Guardarraíl automático.** `tests/http/test_serialization.py::test_every_json_route_declares_a_pydantic_response_model`
  recorre `app.openapi()` y falla si una ruta JSON no declara un esquema Pydantic con nombre. Solo están exceptuadas las dos
  rutas sin cuerpo JSON (#10 y #25). Ejecutado contra `main` habría fallado con #2, #3, #4, #18 y #24; el health check
  tiene su propio test.
- **Tests de contrato** (13 en total) de la forma exacta de las respuestas de auth, perfiles, usuarios, proveedores,
  incidencias e inventario, y del 422 ante campos no escribibles.
- **Tests existentes.** `uv run pytest`: 179 en verde (los 166 anteriores más los 13 nuevos). Se adaptaron 8 tests que
  inspeccionaban `hashed_password` o `profile.user_id` en el valor devuelto por los handlers: ahora leen el hash desde TinyDB
  y comprueban que no sale en la respuesta. Jest del backoffice: 59 en verde.
- **Prueba manual** con Uvicorn, `/docs` y `/openapi.json`: el detalle está en `memory-bank/progress.md` (entrada
  «Auditoría de serialización del backend»).

## Compatibilidad y próximos pasos

- Los cambios de contrato que rompen compatibilidad (#5, #6, #11, #12, #14, #20, #26 y #31) solo tienen como consumidor el
  backoffice, que se actualiza en el mismo cambio. No hay clientes externos de estas rutas.
- Las futuras APIs de tracking y devoluciones deben seguir el mismo patrón: esquemas `*Create`/`*Update` con
  `extra="forbid"`, `*Read` para el detalle, `*ListItem` para los listados y construcción explícita en el handler. El
  guardarraíl de OpenAPI las cubrirá automáticamente.
