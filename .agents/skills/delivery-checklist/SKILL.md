---
name: delivery-checklist
description: Ejecuta la checklist de entrega del monorepo TrackFlow antes de un commit o PR y produce un informe de verificación con evidencias. Úsala siempre que vayas a hacer commit, abrir un PR o dar una tarea por terminada.
---

# Skill: delivery-checklist

## Objetivo (único)

Demostrar, con evidencias reproducibles, que un cambio del monorepo TrackFlow cumple el flujo de entrega de `AGENTS.md` §2 **antes**
de hacer commit o abrir un PR.

No escribe features ni corrige código: si un criterio falla, se detiene y lo reporta.

## Cuándo usarla

- Antes de cada `git commit` (paso obligatorio de `AGENTS.md`).
- Antes de abrir un Pull Request o de decir "terminado".
- Tras resolver conflictos de merge.

## Inputs

| Input | Obligatorio | Ejemplo | De dónde sale |
| --- | --- | --- | --- |
| `task_summary` | Sí | "Migrar la web del Hito 1 a Next.js" | Petición del desarrollador |
| `base_ref` | No (por defecto `main`) | `main`, `origin/hito-4` | Rama contra la que se compara el diff |
| `affected_apps` | No (se deduce del diff) | `uis/website`, `uis/backoffice` | `git diff --name-only <base_ref>...HEAD` + cambios sin commit |
| `routes_to_check` | No (por defecto `/` de cada app afectada) | `/`, `/aplicar` | Rutas creadas o modificadas |
| `protected_changes_approved` | No (por defecto ninguna) | `src/utils/transformations.ts` | Confirmación explícita del desarrollador en la conversación |

## Procedimiento

1. **Alcance del diff**
   - `git status --short` y `git diff --stat <base_ref>` (incluye cambios sin commit).
   - Clasifica cada archivo: tarea / generado (lockfile tras `npm install` pedido) / ajeno. Revierte o pregunta por los ajenos.
   - Cruza la lista con "Zonas protegidas" de `AGENTS.md`. Cualquier coincidencia que no esté en `protected_changes_approved` → **parar**.
2. **Rama**: `git branch --show-current` no puede ser `main`.
3. **Verificación estática**: `npm run verify` desde la raíz. Guarda la cola de la salida (últimas ~20 líneas).
4. **Reglas del monorepo** (de `.agents/rules/monorepo-structure.md`):
   - `git ls-files uis | grep -E "app/api/|route\.ts$"` → vacío.
   - `git grep -nE "export function (selectBestCarrier|calculateShippingCost|scoreCarrierForShipment|validateProduct)" -- uis` → vacío.
5. **Verificación en ejecución**: para cada app afectada, `npm run dev` en segundo plano; espera a `Ready`; pide cada ruta de
   `routes_to_check` (`curl -s -o /dev/null -w "%{http_code}"` o `Invoke-WebRequest`); revisa el log del servidor; detén el proceso.
6. **Etiquetas**: en el HTML servido del backoffice, sin `<script>`, no aparece ningún valor crudo de dominio
   (`In transit`, `Same-day`, `Low stock`, `Out of stock`, `in_progress`, `personal_interview`).
7. **Banco de memoria**: `git diff --name-only <base_ref>` incluye `memory-bank/progress.md` con una entrada nueva y fechada. Si el cambio
   toca stack, puertos, comandos o decisiones, también `memory-bank/techContext.md`.
8. **Informe**: emite el bloque de salida de abajo. Solo si todos los criterios están en ✅ se puede hacer commit/PR.

## Output esperado

```markdown
## Delivery checklist — <task_summary>
Rama: <rama> · Base: <base_ref> · Apps: <affected_apps>

| # | Criterio | Resultado | Evidencia |
|---|----------|-----------|-----------|
| 1 | Diff limitado a la tarea, sin zonas protegidas no aprobadas | ✅/❌ | `git diff --stat` resumido |
| 2 | Rama distinta de main | ✅/❌ | nombre de rama |
| 3 | `npm run verify` exit 0 | ✅/❌ | últimas líneas |
| 4 | Sin APIs en uis/ ni lógica del Hito 2 copiada | ✅/❌ | salida de los grep (vacía) |
| 5 | Rutas responden 200 en `npm run dev` | ✅/❌ | `ruta → código` |
| 6 | Sin valores crudos de dominio en la UI | ✅/❌ | recuento = 0 |
| 7 | `memory-bank/progress.md` actualizado | ✅/❌ | línea añadida |

Veredicto: LISTO PARA COMMIT | BLOQUEADO (<criterio>)
```

## Criterios de aceptación (verificables)

- [ ] El informe contiene las 7 filas y cada una tiene evidencia literal (comando + salida), no una afirmación.
- [ ] `npm run verify` terminó con código de salida `0` en esta misma ejecución (no reutilizar resultados anteriores).
- [ ] Cada ruta de `routes_to_check` devolvió HTTP `200` con `npm run dev` y el log del servidor no contiene `Error` ni `⨯`.
- [ ] Los dos `grep` del paso 4 devuelven 0 líneas.
- [ ] El HTML servido del backoffice (sin `<script>`) contiene 0 apariciones de los valores crudos del paso 6.
- [ ] `git diff --name-only <base_ref>` incluye `memory-bank/progress.md`.
- [ ] Ningún archivo de "Zonas protegidas" aparece en el diff salvo los listados en `protected_changes_approved`.
- [ ] La rama actual no es `main`.
- [ ] El veredicto es `LISTO PARA COMMIT` solo si todos los criterios anteriores se cumplen; en otro caso es `BLOQUEADO` con el motivo.
- [ ] Los procesos de `npm run dev` lanzados por la skill se han detenido al terminar.
