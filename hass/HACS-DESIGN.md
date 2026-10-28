# HACS: mapa + limpieza por habitaciones — diseño

Estado: **esqueleto listo** (`hass/custom_components/conga_map/`), sin probar en HA
(HA no está en esta máquina). El backend es el binario estático `native/conga`
(`make arm64` para HA/Raspberry 64).

## Decisión (análisis de los 3 candidatos)

| Candidato | Veredicto |
|---|---|
| `oven-lab/tuya_cloud_map_extractor` | ❌ Requiere proyecto **Tuya IoT Open API** (client_id/secret) — la vía cloud que este repo evita. Sin mantener. |
| `cornguo/tuya-vacuum-maps` | ⚠️ Concepto perfecto (switches por habitación + passes + botón, y ya envía comandos vía **tuya_local**) pero su fuente de mapa es la API cloud Tuya IoT. **No forkear: su patrón se copió** en `conga_map`. |
| `lovelace-xiaomi-vacuum-map-card` | ✅ **Reutilizar tal cual** (frontend). Soporta `map_source: camera` genérico, selección ROOM y servicios custom → click en habitación = limpiar. |

## Arquitectura final

```
robot ──LAN──► conga binary ──cloud OEM──► S3 ──► PNG + rooms JSON
                ▲                                      │
tuya_local.yaml ┘ (initlan)                HA custom integration conga_map
                                                  │ camera.conga_map + switch Room*
                                                  ▼
                                    xiaomi-vacuum-map-card (click rooms)
```

- **(a) Datos de tuya_local**: la integración lee `/config/tuya_local.yaml`
  directamente (está en el mismo host que HA) vía `conga initlan`. Cero pasos
  manuales tras instalar.
- **(b) Mapa + click**: `camera.conga_map` (PNG del binario) + la card Xiaomi
  con `calibration_points` que el binario ya exporta (`--json`).

## Instalación (HA)

1. `make arm64` → copia `native/conga-linux-arm64` a `/config/conga` (chmod +x)
2. Provisiona UNA vez en cualquier máquina con el XAPK y la cuenta:
   `conga extract app.xapk && conga login -email … && conga initlan …`
   → copia el `native.json` resultante a `/config/conga-config.json`
3. Copia `hass/custom_components/conga_map` a `/config/custom_components/`
4. Ajustes → Integraciones → añadir **Conga Map** (rutas por defecto ok)
5. Reinicia; el primer mapa tarda ~1 min (get_both + subida + descarga)

## Dashboard (click en habitaciones)

```yaml
type: custom:xiaomi-vacuum-map-card
entity: vacuum.conga_8290          # la entidad de tuya_local
map_source:
  camera: camera.conga_map
calibration_source:
  calibration_points:              # exportados por `conga getmap --json`
    - vacuum: { x: -685, y: -1125 }
      map:    { x: 0,    y: 0 }
    - vacuum: { x: -685, y: 1350 }
      map:    { x: 0,    y: 252 }
    - vacuum: { x: 275,  y: -1125 }
      map:    { x: 180,  y: 0 }
map_modes:
  - template: vacuum_clean_zone
  - name: Limpiar habitaciones
    selection_type: ROOM
    service: conga_map.roomclean
    data:
      rooms: "{{ selection }}"
      passes: 1
```

(`vacuum_clean_zone` requiere enviar zonas crudas por DP4 — no soportado por
el robot; el modo ROOM es el camino bueno. La card dibuja el contorno de la
habitación clicada y llama a `conga_map.roomclean`.)

## Pendiente cuando haya HA delante

- [ ] Probar el config flow + primera descarga real
- [ ] La card espera coordenadas de zonas por habitación: exportar bounding-box
      por habitación en `--json` (ya tengo los píxeles por sala en el decoder)
- [ ] Relocalizar el pose (DP15 cmd 0x39) encima del mapa en vivo → P2P/live
      queda fuera; el PNG se refresca bajo demanda
- [ ] `conga roomclean` probado con IDs reales 1-7 (requiere permiso — mueve el robot)
