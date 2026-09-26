# ⚛️ Talent Pipeline Tracker

English | [Español](README.es.md)

Internal frontend built with **Next.js + TypeScript** to manage TrackFlow's talent pipeline.

The goal of this app is to help the People & Talent team quickly visualize, filter, and manage candidates using an existing REST API.

---

# 🚀 Tech Stack

- Next.js 16 (App Router)
- React 19
- TypeScript 5
- TailwindCSS 4
- ESLint 9

---

# 📦 Setup

## 1. Enter the project folder

```bash
cd uis/talent-pipeline-tracker
```

---

## 2. Environment variables

Create a `.env.local` file:

```bash
NEXT_PUBLIC_TRACKFLOW_API_BASE_URL=https://playground.4geeks.com/tracker/api/v1
```

Fallback variables are also supported:

```bash
NEXT_PUBLIC_API_BASE_URL=https://playground.4geeks.com/tracker/api/v1
NEXT_PUBLIC_API_URL=https://playground.4geeks.com/tracker/api/v1
```

If none are defined, the API client defaults to:

```bash
http://localhost:3001
```

---

## 3. Install dependencies

```bash
npm install
```

---

## 4. Run the project

```bash
npm run dev
```

Open in the browser:

```bash
http://localhost:3000
```

---

# 📁 Project Structure

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

# ✅ Features

## 📋 Candidate list

- Display all candidates.
- Show:
	- Full name
	- Position
	- Current status
	- Current stage
- Search by name or email.
- Filter by status.
- Filter by stage.
- Client-side navigation without full page reload.
- Visual states:
	- Loading
	- Success
	- Error

---

## 👤 Candidate detail

Show full information:

- Name
- Email
- Phone
- Position
- LinkedIn
- CV
- Years of experience
- Status
- Stage
- Application date

Also:

- Update status (`PATCH /records/:id`)
- Update stage (`PATCH /records/:id`)
- View notes
- Add notes
- Delete notes

---

## 📝 Candidate management

### Create candidate

Form to register new candidates using:

```bash
POST /records
```

### Edit candidate

Form to edit existing candidates using:

```bash
PUT /records/:id
```

---

# 🔄 Async Handling

All API calls use:

```bash
async/await
```

Each operation implements:

- Loading state
- Success state
- Error state

The UI updates dynamically without full page reloads.

---

# 🧠 Typing

The project uses TypeScript to define:

- Candidate
- Note
- API payloads
- Forms
- Filters

Simplified real example:

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

Official docs:

[https://playground.4geeks.com/tracker/api/v1/docs](https://playground.4geeks.com/tracker/api/v1/docs)

Main endpoints:

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

# 🎯 Project Goals

- Practice Next.js App Router
- Manage local state with React Hooks
- Consume REST APIs
- Implement filters and dynamic search
- Build TypeScript forms
- Work with async UI states
- Organize scalable app structure

---

# 📌 Important Requirements

- Do not use Redux, Zustand, or external state libraries.
- Use React Hooks only.
- Use App Router navigation.
- Keep clear separation between logic, types, and components.
- Keep domain language aligned with TrackFlow context.
- Do not expose raw `status` and `stage` API values in UI: always use human-readable labels.

---

# 🧪 Useful Scripts

```bash
npm run dev
npm run lint
npm run build
npm run start
```

---

# ✅ Current Status

- Lint: OK
- Build: OK

