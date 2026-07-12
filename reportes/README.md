# Reportes automáticos de ventas y producción

Este sistema genera un mail comparativo de ventas y producción:

- **Semanal**, todos los lunes: la semana que terminó vs. la misma semana (1ra, 2da, 3ra...) del mes pasado.
- **Mensual**, el 1° de cada mes: el mes que terminó vs. el mes anterior.

## Cómo subir los archivos (lo único manual que queda)

Cada vez que exportes un Excel de Trazal para este reporte, subilo a la carpeta correspondiente
de este repo (botón "Add file" → "Upload files" en GitHub) **respetando el nombre**:

```
reportes/data/semanal/ventas/AAAA-MM-DD_AAAA-MM-DD.xlsx
reportes/data/semanal/produccion/AAAA-MM-DD_AAAA-MM-DD.xlsx
reportes/data/mensual/ventas/AAAA-MM-DD_AAAA-MM-DD.xlsx
reportes/data/mensual/produccion/AAAA-MM-DD_AAAA-MM-DD.xlsx
```

El nombre es **fecha de inicio del período _ fecha de fin del período**, en formato `AAAA-MM-DD`.
El sistema confía en el nombre del archivo (no mira las fechas de adentro del Excel) para saber a qué
semana o mes corresponde.

Ejemplos:
- Semana del 6 al 12 de julio de 2026 → `2026-07-06_2026-07-12.xlsx`
- Mes de julio de 2026 completo → `2026-07-01_2026-07-31.xlsx`

### Rutina de carga sugerida

- **Cada lunes**, antes de las 8am (hora Córdoba): exportar de Trazal ventas y producción de la
  semana anterior (lunes a domingo) y subir ambos archivos con el nombre de ese rango.
- **El último día de cada mes** (o el 1° temprano): exportar de Trazal ventas y producción del mes
  que terminó (día 1 al último día) y subir ambos archivos con el nombre de ese rango.

Si un lunes o un fin de mes no subís el archivo a tiempo, simplemente no vas a recibir ese reporte
(o vas a recibir uno con datos viejos) — no pasa nada grave, subilo cuando puedas y esperá al
próximo envío programado, o pedile a Claude que corra la rutina "a mano" ese día.

## Cómo se arma la comparación

- **Semanal**: la "semana N del mes" se cuenta por orden de aparición dentro del mes (la primera
  semana subida en julio es la "semana 1 de julio", etc.), no por número de semana ISO. Se compara
  contra la semana con el mismo número de orden del mes anterior.
- **Mensual**: se compara directamente contra el mes calendario anterior.
- Si no existe todavía el período de comparación (por ejemplo, recién estás empezando a usar este
  sistema), el mail te avisa que no hay comparación disponible y muestra solo los datos actuales.

## Envío del mail

El envío se hace por Gmail SMTP con una **App Password** (no la contraseña real de la cuenta).
Se genera en https://myaccount.google.com/apppasswords (requiere verificación en 2 pasos activada
en la cuenta de Gmail). La App Password se pasa únicamente por la variable de entorno
`GMAIL_APP_PASSWORD` al momento de ejecutar `enviar_mail.py` — nunca se guarda en este repo.

```
GMAIL_APP_PASSWORD="xxxx xxxx xxxx xxxx" python3 reportes/enviar_mail.py \
  --from joacog500@gmail.com \
  --to joacog500@gmail.com,daniel@laordenweb.com \
  --subject "📊 Reporte semanal La Orden" \
  --html-file reportes/output/ultimo_reporte_semanal.html
```

## Archivos

- `generar_reporte.py`: script que arma el HTML del mail (`python generar_reporte.py --tipo semanal`
  o `--tipo mensual`). Lee los Excel de `data/`, calcula ventas y producción, arma comparativos y
  escribe el resultado en `output/ultimo_reporte_<tipo>.html`.
- `enviar_mail.py`: envía ese HTML por mail vía Gmail SMTP (ver arriba).
- `data/`: acá van los Excel exportados de Trazal, organizados como se explicó arriba.
- `output/`: acá queda el último HTML generado (no hace falta tocarlo).
