# AGENTS.md - Guia Operativa del Monorepo TrackFlow

## 1) Proposito del agente
Este monorepo sostiene la transformacion digital que TrackFlow Tech impulsa en las operaciones logisticas de los dos paises. Todo cambio tiene que contribuir a uno o varios de estos objetivos de negocio:

- Mas visibilidad de la operacion en tiempo real.
- Menos tareas manuales y menos errores.
- Mejor experiencia para clientes B2B y B2C.
- Decisiones mejor respaldadas por datos.
- Capacidad de escalar y de operar 24/7.

Si no queda claro como una tarea ayuda a estos objetivos, hay que replantearla antes de implementarla.

## 2) Lectura obligatoria al iniciar cada sesion
Antes de proponer cambios o escribir codigo, el agente lee estos archivos en el siguiente orden:

1. memory-bank/projectbrief.md
2. memory-bank/techContext.md
3. memory-bank/progress.md
4. Las reglas de `.agents/rules/` cuyo alcance cubra los archivos que se van a tocar:
   - `monorepo-structure.md` (siempre activa): donde vive cada tipo de codigo y como se importa `src/`.
   - `nextjs-uis.md` (archivos de `uis/`): convenciones de las apps Next.js.
   - `business-logic.md` (a peticion del agente): reglas para reutilizar o cambiar la logica de `src/`.

Las tareas repetibles estan en `.agents/skills/`. Antes de cada commit o PR se usa la skill `.agents/skills/delivery-checklist/SKILL.md`, que comprueba este flujo con evidencias.

Para que sirve esta lectura:

- Ajustar la solucion al contexto real de la empresa.
- Respetar las restricciones tecnicas y la arquitectura del monorepo.
- No repetir trabajo ya hecho ni duplicar esfuerzos frente al estado actual.

Si alguno de estos archivos no existe o esta desactualizado, el agente lo informa y propone actualizarlo antes de seguir con cambios grandes.

## 3) Flujo obligatorio antes de cada commit
Este flujo no se puede omitir. Se ejecuta paso a paso, en orden, y queda documentado en el mensaje de trabajo o en el PR.

### Paso 1 - Validacion de contexto y alcance
- Revisar el objetivo funcional y como afecta a las operaciones de TrackFlow.
- Confirmar a que hito pertenece el cambio (hoy: Hito 4 en curso).
- Identificar los modulos afectados y sus dependencias.

### Paso 2 - Verificacion tecnica local
- Ejecutar `npm run verify` desde la raiz (tipos de `src/`, tipos, lint y build de `uis/website` y `uis/backoffice`); tiene que terminar sin errores. Si se toco `uis/talent-pipeline-tracker`, ejecutar tambien `npm run lint` y `npm run build` dentro de esa app.
- Arrancar con `npm run dev` la app afectada y comprobar que las rutas modificadas responden sin errores.
- Comprobar que siguen funcionando los flujos clave del dominio (listado, detalle, estado/etapa, notas en la app activa).
- Revisar los errores de consola y los estados de carga/error de la UI cuando aplique.

### Paso 3 - Revision de impacto de negocio
- Comprobar que el cambio mejora al menos una metrica o capacidad operativa.
- Asegurar que no empeora la trazabilidad, la observabilidad ni la consistencia de los datos.
- Confirmar que sigue siendo compatible con la futura evolucion hacia APIs de inventario, tracking y devoluciones.

### Paso 4 - Actualizacion de memoria del proyecto
- Reflejar en memory-bank/progress.md el estado real del avance.
- Si se tomaron decisiones de arquitectura o aparecieron restricciones nuevas, actualizar memory-bank/techContext.md.
- Si cambian el alcance de negocio, los stakeholders o las prioridades, actualizar memory-bank/projectbrief.md.

### Paso 5 - Revision de diff y limpieza final
- Revisar los cambios para detectar ediciones accidentales fuera del alcance.
- Quitar codigo temporal, logs de depuracion y textos de relleno.
- Comprobar que nombres, tipos y contratos son coherentes.

### Paso 6 - Commit trazable
- Escribir el commit con un formato claro: area + accion + objetivo.
- Incluir una referencia breve al impacto esperado en TrackFlow.

## 4) Rutas protegidas: no modificar sin confirmacion explicita
Antes de tocar estas rutas hace falta la confirmacion explicita del usuario o del responsable tecnico:

- CONTEXT.md
- memory-bank/projectbrief.md
- memory-bank/techContext.md
- src/** (logica de negocio del Hito 2: se importa desde `uis/`, no se copia ni se cambia su comportamiento sin permiso)
- uis/talent-pipeline-tracker/** (Hito 3 entregado)
- packages/shared/package.json
- packages/shared/types/index.ts

Tambien hace falta confirmacion explicita para:

- Borrar o renombrar carpetas de primer nivel del monorepo.
- Hacer cambios masivos de estructura en uis, services, packages, data o workflows.
- Cualquier cambio que modifique los contratos compartidos entre las apps de `uis/` y el paquete shared.

## 5) Politicas de implementacion para TrackFlow

### 5.1 Priorizacion funcional
Dar prioridad a las tareas con impacto directo en:

- Operacion de almacen: inventario, alertas y flujo de pedidos.
- Ultima milla: tracking unificado y buena asignacion de carrier.
- Logistica inversa: tiempos y consistencia del proceso de devoluciones.
- CX: tiempos de respuesta y menos consultas atendidas a mano.
- Direccion: indicadores fiables y siempre al dia.

### 5.2 Calidad minima esperada
- Todo cambio tiene en cuenta los estados de carga, exito y error.
- No acoplar sin necesidad la UI, los servicios y los tipos.
- Mantener un tipado claro y contratos consistentes.
- Preferir componentes y utilidades reutilizables.

### 5.3 Observabilidad y trazabilidad
- Toda integracion nueva incluye logging que sirva para dar soporte.
- Los errores de API deben ser comprensibles y permitir actuar.
- No dejar flujos que fallen en silencio sin avisar al usuario interno.

## 6) Buenas practicas para mantener actualizado el memory-bank

### Frecuencia
- Actualizarlo al terminar una tarea relevante o antes de cada commit importante.
- Si hubo decisiones significativas, no esperar al final del sprint.

### Reglas de contenido
- Redactar resumenes cortos, concretos y verificables.
- Dejar constancia de decisiones, riesgos y proximos pasos accionables.
- Evitar el tono promocional o las frases ambiguas.
- Mantener coherentes entre si projectbrief, techContext y progress.

### Criterios por archivo
- projectbrief.md: solo cambios de negocio, objetivos o stakeholders.
- techContext.md: arquitectura, restricciones, integraciones y decisiones tecnicas.
- progress.md: estado real, hitos, bloqueos y siguiente accion prioritaria.

### Anti-patrones a evitar
- Dar un hito por terminado sin evidencia tecnica.
- Copiar el mismo contenido en los tres archivos.
- Dejar tareas abiertas sin fecha o sin siguiente paso.

## 7) Definicion de listo para merge
Un cambio se puede mergear cuando:

- Ha pasado el flujo pre-commit completo.
- No modifica rutas protegidas sin autorizacion.
- Sigue alineado con los objetivos de TrackFlow.
- Deja el memory-bank actualizado segun su impacto real.
- Otro agente puede entenderlo y continuarlo sin necesitar contexto adicional.
