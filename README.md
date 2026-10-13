# Conga 8290 → Tuya Local

Dos resultados: **perfil YAML de Tuya Local** y **ID + local_key** del robot.
Recuperación puntual desde Python, sin Android/root, Frida ni proyecto Tuya IoT.
Después, Home Assistant se comunica por LAN mediante Tuya Local, protocolo **3.3**.

## Requisitos

- Targets: **macOS, Linux o Docker Linux**, Python **3.12/3.13** y dependencias.
- **Linux amd64/x86_64 es compatible**: Unicorn emula las librerías ARM64 del
  APK; no hace falta procesador ARM. Windows queda fuera del alcance.
- Cuenta de la app Cecotec con email/contraseña e Internet para la recuperación.
- XAPK compatible de Cecotec **1.2.9**, aportado localmente. Esta versión acepta
  únicamente el APK y librerías cuyos hashes están fijados en el código.
- Tuya Local instalado en Home Assistant para utilizar el YAML.

El APK/XAPK y las librerías propietarias **no se distribuyen en este repo**. El
importador extrae únicamente los tres recursos necesarios, verifica sus SHA-256
y los deja en `artifacts/`, ignorado por Git. No sube ni ejecuta el APK en Android;
las rutinas ARM64 seleccionadas se emulan localmente y con límites en Unicorn.
No descargues una versión cualquiera: un recurso distinto falla cerrado.

## Instalar y preparar

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python recover_key.py --xapk /ruta/Cecotec_1.2.9_APKPure.xapk --check
```

Este check es offline: no pide cuenta ni hace login. La importación solo se necesita
una vez; no reemplaza archivos existentes que no coincidan.

## Obtener ID + clave

```sh
.venv/bin/python recover_key.py
```

País (España por defecto: 34) y email **visibles**. Contraseña con **asteriscos**,
sin eco ni almacenamiento. No hay frase de confirmación ni flags adicionales de
aprobación: **ejecutar este comando realiza un login nuevo**. Puede generar una
alerta de dispositivo desconocido o afectar la sesión abierta de la app Cecotec.

El script permite seleccionar casa y Conga 8290 entre los dispositivos de esa
cuenta. Si solo hay uno, lo selecciona automáticamente. No requiere captura antigua
ni conocer previamente el ID o la clave. No admite otros productos por similitud
de nombre. Hace un token, un login y **dos LISTs como máximo**, sin reintentos,
logout, pairing ni comandos del robot. CAPTCHA/MFA/bloqueo detienen el proceso.

Solo guarda el dispositivo seleccionado en un archivo nuevo:

```text
private/robot-connection-<fecha>.json
```

Campos: `id` y `local_key`. Archivo **0600**, carpeta **0700**. No se imprimen la
clave, la contraseña, tokens, RSA, sesiones ni respuestas completas. El email puede
quedar visible en tu terminal porque así se solicita. No compartir el JSON privado,
incluso en un repo privado.

### Parámetros de cuenta (opcionales)

```sh
.venv/bin/python recover_key.py -c 34 -u usuario@example.com
# Admitido, pero menos seguro; sustituir los valores localmente:
.venv/bin/python recover_key.py -c 34 -u usuario@example.com -p 'CONTRASEÑA'
```

Alias largos: `--country`, `--user` y `--password`. `-c` es el prefijo telefónico,
sin `+` ni `00`, no un código ISO. Si falta algún parámetro, se pregunta localmente.
**`-p` expone la contraseña en el historial y argumentos del proceso; en Docker,
también en metadatos del contenedor**. El script no imprime ni guarda estos valores,
pero no puede ocultarlos al sistema. Se recomienda `-c`/`-u` con el prompt de
contraseña enmascarada. Los parámetros de cuenta no se aceptan con `--check`, ni
la contraseña con `--token-only`. Si hay varias casas/robots, se pide selección
interactiva incluso cuando se especifican todas las credenciales.

Para comprobar únicamente token/RSA, sin contraseña ni login:

```sh
.venv/bin/python recover_key.py --token-only
```

## Docker (Linux amd64, también desde Docker Desktop en Mac)

La imagen contiene solo Python, dependencias, helpers y YAML. El XAPK, recursos
extraídos y resultados privados van en **bind mounts**, nunca en la imagen.
Desde la carpeta del repo:

```sh
docker build -t conga8290-key .
mkdir -p artifacts private
chmod 700 artifacts private

# Preparación offline: sustituir /ruta/... por el XAPK local compatible.
docker run --rm --network none --log-driver none --read-only \
  --user "$(id -u):$(id -g)" --tmpfs /tmp \
  --mount "type=bind,src=$(pwd)/artifacts,dst=/app/artifacts" \
  --mount "type=bind,src=/ruta/Cecotec_1.2.9_APKPure.xapk,dst=/input/app.xapk,readonly" \
  conga8290-key --xapk /input/app.xapk --check

# Recuperación interactiva: un login nuevo, sin comandos del robot.
docker run --rm -it --log-driver none --read-only \
  --user "$(id -u):$(id -g)" --tmpfs /tmp \
  --mount "type=bind,src=$(pwd)/artifacts,dst=/app/artifacts,readonly" \
  --mount "type=bind,src=$(pwd)/private,dst=/app/private" \
  conga8290-key
```

`-it` es necesario si hay prompts. Añadir `-c 34 -u EMAIL` después del nombre de
imagen para evitar esos prompts; `-p` se admite pero se desaconseja. `--user` antes
del nombre de imagen es el UID/GID Docker, no el email Cecotec. No usar
`--privileged`, red host ni publicar puertos. No ejecutar estas instrucciones con
`sudo`: los archivos deben pertenecer a tu usuario. La recuperación necesita salida
HTTPS; la preparación y las pruebas se ejecutan sin acceso cloud.

Para probar la imagen sin cuenta ni APK:

```sh
docker build --target tests -t conga8290-tests .
```

## Configurar Tuya Local

1. Instalar `make-all/tuya-local` en HA (por ejemplo mediante HACS).
2. Copiar `cecotec_conga8290_vacuum.yaml` a:
   `/config/custom_components/tuya_local/devices/cecotec_conga8290_vacuum.yaml`.
3. Recargar/reiniciar HA según el flujo de instalación de Tuya Local.
4. Configurar el robot con su IP LAN, el `id` y la `local_key` recuperados; protocolo
   **3.3**. El script no obtiene la IP ni cambia automáticamente HA.

Conservar una copia del perfil: una actualización HACS puede sobrescribirlo.
Evitar otro cliente LAN simultáneo mientras HA mantenga la conexión del robot.

## Estado y límites

Empaquetado verificado offline: **65 pruebas** en macOS (Python 3.12), Linux
amd64 (Python 3.13) y Docker Linux amd64 (Python 3.13). Bootstrap real con recursos
compatibles en Mac y Docker, sin red ni autenticación. La imagen Docker se probó
como usuario no root, filesystem raíz de solo lectura y recursos en bind mounts.
Docker Desktop en Mac no se ejecutó durante esta validación.

El login OEM-UI y la recuperación cloud se verificaron con esta cuenta/modelo/APK;
la clave coincide con la captura original. El YAML fue cargado en HA y se verificó
lectura LAN 3.3. El selector empaquetado y los prompts se prueban offline con datos
sintéticos: las pruebas no hacen otro login real. Los controles físicos, mapas,
habitaciones, otras cuentas/regiones/APKs y operación prolongada sin Internet no
están validados. Este repo es una herramienta puntual, no un daemon ni integración
cloud permanente. Python no garantiza borrado seguro de secretos en RAM.

## Pruebas

```sh
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
```

No necesitan APK, cuenta, robot ni Home Assistant. No incluyen capturas personales,
investigación Android ni dumps. `.gitignore` protege archivos de credenciales y
recursos locales; aun así, revisar siempre los archivos antes de publicar.
