# TrackFlow — web pública (`uis/website`)

Web corporativa del **Hito 1** migrada a **Next.js 16 + TypeScript + Tailwind v4** con componentes reutilizables.

| Ruta | Contenido |
| --- | --- |
| `/` | Hero, servicios, beneficios, contacto, footer y datos estructurados `Organization` (JSON-LD) |
| `/aplicar` | Formulario de aplicación B2B con validación en cliente (mismas reglas que `validation.js` del Hito 1) |

## Ejecutar

```bash
cd uis/website
npm install
npm run dev        # http://localhost:3000
```

Otros scripts: `npm run typecheck`, `npm run lint`, `npm run build`.

## Estructura

```text
app/                 layout público (SiteHeader + SiteFooter), páginas / y /aplicar
components/
  layout/            SiteHeader, SiteFooter
  sections/          HeroSection, ServicesSection, BenefitsSection, ContactSection
  ui/                ButtonLink, Logo, SectionHeading, FeatureCard, FramedImage
  forms/             ApplicationForm (cliente), FormField, Fieldset, FieldError
  seo/               OrganizationJsonLd
content/site.ts      textos, enlaces y datos de empresa (tipados)
lib/application-form.ts  tipos, opciones y validaciones puras del formulario
types/site.ts        interfaces del contenido
```

Para cambiar textos, edita `content/site.ts`; los componentes no contienen copy.
