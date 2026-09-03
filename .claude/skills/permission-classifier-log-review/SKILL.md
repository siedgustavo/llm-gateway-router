---
name: permission-classifier-log-review
description: Revisa la actividad reciente del clasificador de permisos local (gateway/permission_classifier.py) contra el traffic.jsonl real del gateway. Detecta variantes de prompt nuevas/desconocidas que Claude Code pueda haber introducido, mide distribucion de veredictos por variante, encuentra activaciones del fail-safe (backend caido) o fallos de parseo, y deja un resumen fechado en la memoria del proyecto (project_permission_classifier_training.md) para que el conocimiento se acumule sesion a sesion. Usar despues de sesiones largas de claude-routed, o periodicamente para chequear que el clasificador sigue sano.
---

# Revision del log del clasificador de permisos

Este skill parsea `gateway/logs/traffic.jsonl` (vive en `airouter.core.sied.ar`,
accedido via SSH) buscando especificamente la actividad del clasificador de permisos
de auto-mode -- ver `project_permission_classifier_training.md` en la memoria del
proyecto para el contexto completo de por que existe y como esta armado.

## Cuando usarlo

- El usuario pide "revisa el log", "que aprendimos del clasificador", "nutrí la
  memoria con la actividad reciente", o similar.
- Periodicamente, para detectar si Claude Code cambio el formato de sus prompts de
  clasificacion (rompe la deteccion de variante en `permission_classifier.py`).
- Despues de reportes de comportamiento raro (bloqueos de mas, o sospecha de que dejo
  pasar algo que no deberia).

## Pasos

1. **Traer el log reciente** (no todo el archivo, puede ser grande):
   ```bash
   ssh root@airouter.core.sied.ar "tail -n 2000 /opt/llm-gateway-router/gateway/logs/traffic.jsonl" > /tmp/traffic_recent.jsonl
   ```

2. **Filtrar las llamadas al clasificador de permisos.** Dos formas de aparecer en el
   log, revisar ambas:
   - `requested_model` == `qwen2.5-coder:7b` (el backend real que usa
     `permission_classifier.py`) -- estas son las llamadas YA procesadas por el
     microservicio.
   - Mensajes con el texto ancla `"SPECIFIC action under review"` en `claude-sonnet-5`
     o `claude-opus-4-8` -- si aparecen MUCHAS de estas, el redirect no esta
     funcionando (revisar `callbacks.py`: el callback
     `permission_classifier_redirector` tiene que estar en la lista de
     `litellm_settings.callbacks` de `litellm-config.yaml` -- este exacto bug ya paso
     una vez, se desregistro solo en un revert anterior).

3. **Detectar variantes conocidas vs desconocidas.** Para cada entrada filtrada, mirar
   el texto de cierre del ultimo mensaje contra las 5 anclas conocidas (ver tabla en
   `project_permission_classifier_training.md`):
   - `"Grade HARM ONLY — do NOT reduce for user intent. No other text."` → severity_fast
   - `"then respond with <severity>N</severity>, plus <category>"` → severity_thinking
   - `"Block if ANY rule could apply. <block> immediately."` → block_fast
   - `"Use <thinking> before responding with <block>"` → block_thinking
   - `"Subagent has finished and is handing back control"` → block_subagent
   - **Cualquier entrada que NO matchee ninguna de las 5** es una variante nueva --
     esto es lo mas importante que este skill puede encontrar. Guardar el texto
     completo para analizarlo (puede requerir agregar deteccion nueva en
     `permission_classifier.py`).

4. **Medir distribucion de veredictos.** Para las llamadas a `qwen2.5-coder:7b`,
   parsear `response_text` (safe/unsafe + categoria) y contar por categoria. Señales
   de alerta:
   - Un severity/categoria repetido identico muchas veces seguidas con contenido
     DISTINTO (posible signo de que el modelo dejo de discriminar, como paso con
     qwen3-coder:30b sin ejemplos trabajados).
   - Aparicion de `"Local permission classifier unavailable"` o severity=80 sin
     categoria clara -- el fail-safe se activo, algo fallo (ver `docker logs
     llm-gateway-permission-classifier-router` y `docker ps` en octoserver para
     `octofan-llamacpp-permission-classifier` en GPU3).

5. **Spot-check de calidad.** Elegir 3-5 casos al azar del muestreo, mostrar la
   accion real evaluada + el veredicto, y juzgar a ojo si parecen razonables (no hace
   falta ground-truth perfecto, solo detectar sorpresas obvias).

6. **Actualizar la memoria.** Agregar una entrada fechada a la seccion "Log de
   revisiones" al final de `project_permission_classifier_training.md` (crear la
   seccion si no existe) con: fecha, cantidad de llamadas analizadas, variantes
   encontradas (nuevas si las hay), distribucion de veredictos, y cualquier anomalia.
   No reescribir el resto del archivo -- es un apendice que crece con el tiempo.

## Salida esperada

Un resumen conciso al usuario (no todo el detalle crudo) con: cuantas llamadas se
analizaron, si el redirect esta funcionando (0 llamadas colandose a Sonnet real),
variantes nuevas encontradas (si las hay), y cualquier anomalia de veredictos. Si todo
esta sano, decirlo brevemente sin alargar.
