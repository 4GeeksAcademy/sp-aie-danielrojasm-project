# ⚛️ Talent Pipeline Tracker

[English](README.md) | Español

Frontend interno desarrollado con **Next.js + TypeScript** para gestionar el pipeline de candidaturas de TrackFlow.

El objetivo de esta aplicación es permitir al equipo de People & Talent visualizar, filtrar y administrar candidatos de forma rápida utilizando una API REST existente.

---

# 🚀 Stack Tecnológico

- Next.js 16 (App Router)
- React 19
- TypeScript 5
- TailwindCSS 4
- ESLint 9

---

# 📦 Instalación

## 1. Entrar en el proyecto

```bash
cd uis/talent-pipeline-tracker
```

---

## 2. Variables de entorno

Crear el archivo `.env.local`:

```bash
NEXT_PUBLIC_TRACKFLOW_API_BASE_URL=https://playground.4geeks.com/tracker/api/v1
```

También se aceptan como fallback:

```bash
NEXT_PUBLIC_API_BASE_URL=https://playground.4geeks.com/tracker/api/v1
NEXT_PUBLIC_API_URL=https://playground.4geeks.com/tracker/api/v1
```

Si no defines ninguna, el cliente usa por defecto:

```bash
http://localhost:3001
```

---

## 3. Instalar dependencias

```bash
npm install
```

---

## 4. Ejecutar el proyecto

```bash
npm run dev
```

Abrir en navegador:

```bash
http://localhost:3000
```

---

# 📁 Estructura del Proyecto

```text
app/
 ├── page.tsx
 ├── candidates/
 │   └── [id]/page.tsx
 ├── layout.tsx
 └── globals.css

components/
 ├── CandidatesListClient.tsx
 ├── CandidateDetailClient.tsx
 └── CandidateForm.tsx

lib/
 └── domain.ts

services/
 └── recordsApi.ts

types/
 └── candidate.ts
```

---

# ✅ Funcionalidades

## 📋 Listado de candidaturas

- Mostrar todos los candidatos.
- Mostrar:
  - Nombre completo
  - Puesto
  - Estado actual
  - Etapa actual
- Buscar por nombre o email.
- Filtrar por estado.
- Filtrar por etapa.
- Navegación sin recarga de página.
- Estados visuales:
  - Loading
  - Success
  - Error

---

## 👤 Detalle del candidato

Mostrar información completa:

- Nombre
- Email
- Teléfono
- Puesto
- LinkedIn
- CV
- Años de experiencia
- Estado
- Etapa
- Fecha de aplicación

Además:

- Actualizar estado (`PATCH /records/:id`)
- Actualizar etapa (`PATCH /records/:id`)
- Ver notas
- Añadir notas
- Eliminar notas

---

## 📝 Gestión de candidaturas

### Crear candidatura

Formulario para registrar nuevos candidatos usando:

```bash
POST /records
```

### Editar candidatura

Formulario para editar candidatos existentes usando:

```bash
PUT /records/:id
```

---

# 🔄 Manejo Asíncrono

Todas las llamadas a la API utilizan:

```bash
async/await
```

Cada operación implementa:

- Estado de carga
- Estado de éxito
- Estado de error

La interfaz se actualiza dinámicamente sin recargar la página.

---

# 🧠 Tipado

El proyecto utiliza TypeScript para definir:

- Candidate
- Note
- Payloads de API
- Formularios
- Filtros

Ejemplo real simplificado:

```ts
export interface Candidate {
  id: string;
  name: string;
  email: string;
  phone: string;
  position: string;
  status: "received" | "in_progress" | "selected" | "discarded";
  stage:
    | "pending"
    | "review"
    | "personal_interview"
    | "technical_interview"
    | "offer_presented";
}
```

---

# 🌐 API

Documentación oficial:

[https://playground.4geeks.com/tracker/api/v1/docs](https://playground.4geeks.com/tracker/api/v1/docs)

Endpoints principales:

```bash
GET    /records
GET    /records/:id
POST   /records
PUT    /records/:id
PATCH  /records/:id

GET    /records/:id/notes
POST   /records/:id/notes
DELETE /records/:id/notes/:note_id
```

---

# 🎯 Objetivos del Proyecto

- Practicar Next.js App Router
- Manejar estado local con React Hooks
- Consumir APIs REST
- Implementar filtros y búsqueda dinámica
- Gestionar formularios en TypeScript
- Trabajar con UI asíncrona
- Organizar aplicaciones escalables

---

# 📌 Requisitos Importantes

- No usar Redux, Zustand ni librerías externas de estado.
- Usar únicamente React Hooks.
- Navegación con App Router.
- Mantener separación clara entre lógica, tipos y componentes.
- Adaptar textos y dominio al contexto de empresa (TrackFlow).
- No exponer valores crudos de `status` y `stage` en la UI: siempre usar etiquetas legibles.

---

# 🧪 Scripts útiles

```bash
npm run dev
npm run lint
npm run build
npm run start
```

---

# ✅ Estado actual

- Lint: OK
- Build: OK
