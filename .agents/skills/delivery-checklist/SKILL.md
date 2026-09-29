---
name: delivery-checklist
description: Ejecuta la checklist de entrega del monorepo TrackFlow antes de un commit o PR y produce un informe de verificación con evidencias. Úsala siempre que vayas a hacer commit, abrir un PR o dar una tarea por terminada.
---

# Skill: delivery-checklist

## AI Engineering · 4Geeks Academy — Skill de agente de código

---

**Objetivo (único):** demostrar, con evidencias reproducibles, que un cambio del monorepo TrackFlow cumple el flujo de entrega de `AGENTS.md`
**antes** de hacer commit o abrir un PR.

La skill no escribe features ni corrige código: si un criterio falla, se detiene y lo reporta. Existe porque, como pidió el tech lead,
"nada de agentes que escriban código sin pasar por el proceso de entrega", y porque lo que no se puede verificar no vale.

## Cuándo usarla

- **Antes de cada `git commit`** — es el paso obligatorio de `AGENTS.md`.
- **Antes de abrir un Pull Request** o de dar una tarea por terminada.
- **Después de resolver conflictos** de merge.

---

## Inputs

### 📝 `task_summary` — obligatorio

Resumen de la tarea tal como la pidió el desarrollador. Ejemplo: "Migrar la web del Hito 1 a Next.js".

---

### 🌿 `base_ref` — opcional (por defecto, `main`)

Rama contra la que se compara el diff. Ejemplos: `main`, `origin/hito-4`.

---

### 🖥️ `affected_apps` — opcional (se deduce del diff)

Apps afectadas, como `uis/website` o `uis/backoffice`. Se obtienen de `git diff --name-only <base_ref>...HEAD` más los cambios sin commit.

---

### 🔗 `routes_to_check` — opcional (por defecto, `/` de cada app afectada)

Rutas creadas o modificadas. Ejemplos: `/`, `/aplicar`.

---

### 🔒 `protected_changes_approved` — opcional (por defecto, ninguno)

Archivos protegidos que el desarrollador autorizó explícitamente en la conversación. Ejemplo: `src/utils/transformations.ts`.

---

## Procedimiento

1. **Alcance del diff.** Ejecutar `git status --short` y `git diff --stat <base_ref>` (incluye los cambios sin commit). Clasificar cada archivo
   como parte de la tarea, generado (un lockfile tras un `npm install` pedido) o ajeno; revertir o preguntar por los ajenos. Cruzar la lista
   con las rutas protegidas de `AGENTS.md` (sección 4): cualquier coincidencia que no esté en `protected_changes_approved` detiene la skill.
2. **Rama.** `git branch --show-current` no puede ser `main`.
3. **Verificación estática.** Ejecutar `npm run verify` desde la raíz y guardar las últimas ~20 líneas de la salida.
4. **Reglas del monorepo** (de `.agents/rules/monorepo-structure.md`). `git ls-files uis | grep -E "app/api/|route\.ts$"` debe salir vacío, y
   `git grep -nE "export function (selectBestCarrier|calculateShippingCost|scoreCarrierForShipment|validateProduct)" -- uis` también.
5. **Verificación en ejecución.** Para cada app afectada, arrancar `npm run dev` en segundo plano, esperar a `Ready`, pedir cada ruta de
   `routes_to_check` (`curl -s -o /dev/null -w "%{http_code}"` o `Invoke-WebRequest`), revisar el log del servidor y detener el proceso.
6. **Etiquetas.** En el HTML servido por el backoffice, sin `<script>`, no aparece ningún valor crudo de dominio (`In transit`, `Same-day`,
   `Low stock`, `Out of stock`, `in_progress`, `personal_interview`).
7. **Banco de memoria.** `git diff --name-only <base_ref>` incluye `memory-bank/progress.md` con una entrada nueva y fechada. Si el cambio
   toca stack, puertos, comandos o decisiones, incluye también `memory-bank/techContext.md`.
8. **Informe.** Emitir el bloque de salida. Solo si todos los criterios están en ✅ se puede hacer commit o abrir el PR.

---

## Output esperado

```markdown
## Delivery checklist — <task_summary>
Rama: <rama> · Base: <base_ref> · Apps: <affected_apps>

| # | Criterio | Resultado | Evidencia |
|---|----------|-----------|-----------|
| 1 | Diff limitado a la tarea, sin rutas protegidas no aprobadas | ✅/❌ | `git diff --stat` resumido |
| 2 | Rama distinta de main | ✅/❌ | nombre de rama |
| 3 | `npm run verify` exit 0 | ✅/❌ | últimas líneas |
| 4 | Sin APIs en uis/ ni lógica del Hito 2 copiada | ✅/❌ | salida de los grep (vacía) |
| 5 | Rutas responden 200 en `npm run dev` | ✅/❌ | `ruta → código` |
| 6 | Sin valores crudos de dominio en la UI | ✅/❌ | recuento = 0 |
| 7 | `memory-bank/progress.md` actualizado | ✅/❌ | línea añadida |

Veredicto: LISTO PARA COMMIT | BLOQUEADO (<criterio>)
```

---

## Criterios de aceptación

Todos son verificables sin juicio subjetivo:

- [ ] El informe tiene las 7 filas y cada una lleva evidencia literal (comando y salida), no una afirmación.
- [ ] `npm run verify` terminó con código `0` en esta misma ejecución (no vale reutilizar resultados anteriores).
- [ ] Cada ruta de `routes_to_check` devolvió HTTP `200` con `npm run dev`, y el log del servidor no contiene `Error` ni `⨯`.
- [ ] Los dos `grep` del paso 4 devuelven 0 líneas.
- [ ] El HTML servido por el backoffice (sin `<script>`) contiene 0 apariciones de los valores crudos del paso 6.
- [ ] `git diff --name-only <base_ref>` incluye `memory-bank/progress.md`.
- [ ] Ningún archivo de las rutas protegidas aparece en el diff, salvo los listados en `protected_changes_approved`.
- [ ] La rama actual no es `main`.
- [ ] El veredicto es `LISTO PARA COMMIT` solo si se cumplen todos los criterios anteriores; si no, es `BLOQUEADO` con el motivo.
- [ ] Los procesos de `npm run dev` que lanzó la skill quedan detenidos al terminar.

---

_Documento interno — 4Geeks Academy · AI Engineering Track_
_Skill reutilizable en cada entrega de los próximos hitos_
