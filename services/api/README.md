# TrackFlow API

API de autenticación, proveedores y análisis agregado de incidencias. Los
usuarios y perfiles se guardan exclusivamente en TinyDB; las contraseñas se
almacenan con bcrypt y la autenticación usa JWT stateless.

## Ejecutar

```bash
uv sync
uv run uvicorn services.api.main:app --reload --port 8000 --env-file .env
```

La configuración local vive en `.env` y no se versiona:

```dotenv
JWT_SECRET_KEY=una-clave-aleatoria-larga
ACCESS_TOKEN_EXPIRE_MINUTES=30
RESEND_API_KEY=tu-clave-de-resend
RESEND_FROM_EMAIL=onboarding@resend.dev
PASSWORD_RESET_URL=http://localhost:3002/reset-password
```

`RESEND_API_KEY` es obligatoria para enviar correos reales. Con el remitente de
onboarding de Resend solo se puede enviar al email de la cuenta Resend; para
otros destinatarios configura `RESEND_FROM_EMAIL` con un dominio verificado.
El envío usa el SDK oficial de Resend, sin claves incrustadas en el código.
`PASSWORD_RESET_URL` debe apuntar a la ruta pública del backoffice (incluido
el origen correcto en despliegue). En Codespaces, si apunta a `localhost`,
se sustituye automáticamente por la URL HTTPS del puerto reenviado. El puerto
3002 puede requerir iniciar sesión en GitHub antes de mostrar la página.
Nunca publiques la clave en el repositorio.
Si el proveedor falla, la respuesta de recuperación sigue siendo genérica y
el fallo se registra en el servidor sin incluir el enlace ni el token.

`AUTH_DB_PATH` permite cambiar la ubicación de `services/api/auth.json`, por
ejemplo para aislar pruebas. La API no arranca sesiones ni usa cookies.

El backoffice se sirve en `http://localhost:3002` y reenvía `/api/incidents/*`
al servicio desde Next, en el mismo origen que la página. En Codespaces, no hace
falta exponer el puerto 8000 al navegador. Si la API se ejecuta en otro host,
configura `INCIDENTS_API_INTERNAL_URL` en el proceso del backoffice.
`BACKOFFICE_ORIGIN` permite autorizar otro origen si se consume la API
directamente.

## Endpoints

- `POST /users`: registra credenciales y crea su perfil uno a uno. Es público.
- `GET/PUT/DELETE /users`: CRUD protegido; el listado global y el acceso o la
  modificación de otro usuario requieren rol `admin`.
- `POST /auth/login`: acepta JSON (`email`, `password`) y el formulario OAuth2
  (`username` contiene el email). Devuelve un bearer token.
- `POST /auth/forgot-password`: acepta `email`; responde siempre 200 y envía
  por Resend un enlace si la cuenta existe. El token dura 30 minutos.
- `POST /auth/reset-password`: acepta `token` y `new_password`; el token firmado
  solo puede usarse una vez. Responde 400 para enlaces inválidos o caducados.
- `POST /auth/change-password`: requiere bearer; acepta `current_password` y
  `new_password`, y responde 400 si la contraseña actual es incorrecta.
- `GET /auth/me` y `GET/PUT /profiles/me`: devuelven o actualizan los datos del
  usuario autenticado.
- Todas las rutas de `/suppliers` requieren un bearer token.
- `POST /api/incidents/analyze`: requiere token, recibe el campo multipart `file` y devuelve el
  resumen JSON. CSV vacío, cabecera incompatible o contenido inválido responde
  `400` con un mensaje que no incluye valores del fichero.
- `GET /api/incidents/results/export`: descarga las métricas agregadas del
  último análisis correcto como CSV y requiere token. Antes de un análisis
  responde `404`.
- `GET /`: informa que el servicio está activo.

En `/docs`, registra un usuario, abre **Authorize** y usa su email como
`username` y su contraseña. Swagger obtiene el token desde `/auth/login` y lo
envía en las rutas protegidas.

## Pruebas

```bash
uv run python -m unittest services.api.test_auth_api -v
uv run python -m unittest services.api.test_incidents_analyzer -v
```

El resumen más reciente vive en memoria del proceso y se reemplaza tras cada
carga correcta; no se persiste el fichero ni sus registros.