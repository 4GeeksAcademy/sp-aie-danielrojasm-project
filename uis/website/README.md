# Web pública de TrackFlow

## AI Engineering · 4Geeks Academy — `uis/website`

---

Esta es la web corporativa de TrackFlow: la primera impresión que se llevan las marcas de e-commerce que buscan un socio logístico en
Estados Unidos y España. Nació en el **Hito 1** como HTML estático y en el Hito 4 se migró a **Next.js 16, TypeScript y Tailwind v4**,
con componentes React reutilizables y el contenido separado de la presentación.

**Tecnología:** Next.js 16.2.10 · React 19 · TypeScript 5 · Tailwind CSS 4
**Puerto de desarrollo:** 3000

## Rutas

### 🏠 `/` — Inicio

Hero, servicios, beneficios, contacto y footer, con el mismo contenido y la misma identidad visual que el Hito 1 (`slate-950` y `cyan-300`).
Incluye los datos estructurados `Organization` (JSON-LD) para SEO.

---

### 📝 `/aplicar` — Formulario de aplicación B2B

Formulario para las marcas que quieren trabajar con TrackFlow: datos de contacto, de empresa y de operación logística, servicios de
interés y consentimiento. La validación en cliente aplica las mismas reglas que el antiguo `validation.js` del Hito 1, que se eliminó al migrar a Next.js.

---

## Cómo ejecutarla

```bash
cd uis/website
npm install
npm run dev        # http://localhost:3000
```

**Otros scripts:** `npm run typecheck`, `npm run lint` y `npm run build`.

---

## Estructura

- **`app/`** — layout público (`SiteHeader` y `SiteFooter`) y las páginas `/` y `/aplicar`.
- **`components/layout/`** — `SiteHeader` y `SiteFooter`.
- **`components/sections/`** — `HeroSection`, `ServicesSection`, `BenefitsSection` y `ContactSection`.
- **`components/ui/`** — `ButtonLink`, `Logo`, `SectionHeading`, `FeatureCard` y `FramedImage`.
- **`components/forms/`** — `ApplicationForm` (cliente), `FormField`, `Fieldset` y `FieldError`.
- **`components/seo/`** — `OrganizationJsonLd`.
- **`content/site.ts`** — textos, enlaces y datos de empresa, tipados.
- **`lib/application-form.ts`** — tipos, opciones y validaciones puras del formulario.
- **`types/site.ts`** — interfaces del contenido.

**Para cambiar un texto** se edita `content/site.ts`; los componentes no contienen copy.

---

_Documento interno — 4Geeks Academy · AI Engineering Track_
_Interfaz pública de TrackFlow · Hito 1, migrada en el Hito 4_
