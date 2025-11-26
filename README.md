# WhatsApp status Monitor (Django + Node)

Proyecto de **estudio e investigación** para monitorear historias/estados de WhatsApp usando:

- Backend **Node.js** con **gifted-baileys** (cliente no oficial de WhatsApp Web)
- API REST entre Node y Django
- Panel web en **Django** para:
  - Crear campañas con fotogramas objetivo
  - Registrar contactos
  - Monitorear si los contactos publican estados que coincidan con esos fotogramas
  - Ver y exportar resultados

> ⚠️ Este proyecto es solo para fines educativos. No está asociado a WhatsApp Inc. ni a Meta.

---

## 1. Arquitectura general

Flujo principal:

1. **Baileys detecta una nueva historia/estado**
2. **Descarga la media** (imagen o vídeo) y la guarda en el disco
3. **Notifica a Django** vía `POST /api/process-story/`
4. **Django**:
   - Ubica el contacto y sus campañas activas
   - Compara la historia con los fotogramas de la campaña (ORB features vía OpenCV)
   - Marca el contacto en la campaña como:
     - `cumple` (encontró coincidencia)
     - `incumple` (no coincide)
     - `no_capturado` (Baileys vio que hubo estado pero no logró obtener la media)

### Componentes

- `node_backend/`
  - `server.js`: Servidor Express + cliente Baileys
  - Descarga y almacena medias bajo `status_media/`
  - Expone REST API hacia Django

- `django_whatsapp_monitor/`
  - Proyecto Django (panel de monitoreo)
  - App `monitor`:
    - Modelos: `Campaign`, `Contact`, `MonitorResult`
    - ORB-based `image_recognition.py`
    - Vistas de panel, campañas, contactos, historias y resultados
    - API `process_story` para recibir notificaciones de Node

---

## 2. Requisitos

### Backend Node

- Node.js **>= 18**
- npm

### Backend Django

- Python **3.9.x** (probado en 3.9.6)
- Virtualenv recomendado
- SQLite (por defecto) u otro motor configurado en `settings.py`
- OpenCV y NumPy (para reconocimiento de imágenes)

---

## 3. Instalación

Asumimos que la estructura del proyecto es:

```text
whatsapp_baileys_monitor/
├─ node_backend/
│   └─ server.js
└─ django_whatsapp_monitor/
    ├─ manage.py
    ├─ config/
    └─ monitor/
```

### 3.1. Clonar o descargar

```bash
cd /ruta/donde/quieras
# Clona o copia la carpeta whatsapp_baileys_monitor
```

---

### 3.2. Configurar el backend Node (Baileys)

```bash
cd whatsapp_baileys_monitor/node_backend
npm install
```

Dependencias clave (en `package.json`):

- `"gifted-baileys": "2.0.0"` (fijada para evitar los problemas de conexión)
- `express`
- `axios`
- `qrcode-terminal`
- `@hapi/boom`

> Si tienes problemas, verifica que `gifted-baileys` está en la versión `2.0.0`:

```bash
npm install gifted-baileys@2.0.0
```

#### Arrancar el servidor Node

```bash
cd whatsapp_baileys_monitor/node_backend
node server.js
```

Deberías ver algo como:

```text
🚀 WhatsApp API con Baileys corriendo en http://localhost:3000
...
✅ WhatsApp conectado exitosamente   (una vez emparejado)
```

El servidor expone entre otros:

- `GET  /api/qr`  
- `POST /api/start-session`  
- `GET  /api/status`  
- `POST /api/get-status-stories`  
- `POST /api/post-status`  
- `POST /api/logout`  
- Static: `/media/status/...` (sirve archivos guardados en `status_media/`)

---

### 3.3. Configurar el backend Django

```bash
cd whatsapp_baileys_monitor/django_whatsapp_monitor
python3 -m venv .venv
source .venv/bin/activate   # En macOS / Linux
# o en Windows:
# .venv\Scripts\activate
```

Instala dependencias (si tienes `requirements.txt`):

```bash
pip install -r requirements.txt
```

Si no, instala al menos:

```bash
pip install django==4.2.6
pip install opencv-python
pip install numpy
pip install requests
```

#### Configurar variables de entorno

En `config/settings.py` se utiliza `WHATSAPP_API_URL` para hablar con el backend Node.

Por ejemplo:

```python
WHATSAPP_API_URL = "http://localhost:3000/api"
```

(ajústalo si la URL de tu Node es diferente).

#### Migraciones iniciales

```bash
cd whatsapp_baileys_monitor/django_whatsapp_monitor
python manage.py migrate
```

#### Crear superusuario (para entrar al Admin)

```bash
python manage.py createsuperuser
```

#### Arrancar el servidor Django

```bash
python manage.py runserver
```

Panel accesible en:

- Home del monitor: `http://127.0.0.1:8000/`
- Admin Django: `http://127.0.0.1:8000/admin/`

---

## 4. Flujo de uso

### 4.1. Emparejar WhatsApp (Baileys)

1. Asegúrate de que **Node está corriendo** (`node server.js`).
2. En el home de Django (`/`), verás una card con el **estado de WhatsApp**:
   - Si no hay sesión conectada, tendrás un botón para **iniciar sesión / generar QR**.
3. Al usar ese botón, Django llama al backend Node (`/api/start-session`), y este:
   - Inicializa una sesión Baileys
   - Genera un QR
4. Django obtiene el QR vía `GET /api/qr` y lo muestra (ventana flotante).
5. Escanea el QR desde tu WhatsApp → se conecta la sesión.
6. El card de estado cambia a “WhatsApp conectado” y muestra info básica del usuario.

#### Cerrar sesión

- Desde el panel, botón “Cerrar sesión / Logout”.
- Django llama a `POST /api/logout` en Node.
- Node:
  - Hace `sock.logout()`
  - Elimina la carpeta `auth_baileys` (para forzar nuevo emparejamiento la próxima vez).
  - Limpia el socket y el QR.

---

## 5. Modelos principales

### Contact

- `name`
- `phone_number` (sin sufijo `@s.whatsapp.net`, solo número, ej: `573001234567`)

Puedes crearlos:

- Desde **Django Admin**
- Desde el panel (según las vistas que tengas habilitadas)

### Campaign

- `name`
- `description`
- `is_active`
- `image_frame_1` (fotograma objetivo 1)
- `image_frame_2` (fotograma objetivo 2)
- `contacts` (ManyToMany con `Contact`)

La campaña define **qué fotogramas** vamos a buscar en las historias de los contactos asociados.

### MonitorResult

Relaciona:

- `campaign`
- `contact`
- `status`:
  - `cumple` → al menos una historia coincidió con algún fotograma
  - `incumple` → se procesó media pero no coincidió
  - `no_capturado` → Baileys detectó estado pero no logró obtener la media (por timeout, expiración, etc.)
- `detected_frame` (1 o 2 si coincidió específicamente con `image_frame_1` o `image_frame_2`)
- `story_path` (ruta local del archivo de historia procesada)

Reglas importantes:

- Si un contacto ya está en `cumple` para una campaña, **no se revierte** a otro estado automáticamente.
- Si estaba `incumple` o `no_capturado` y en una ejecución posterior **sí hay coincidencia**, se actualiza a `cumple`.

---

## 6. Monitoreo de estados (Baileys)

En `server.js`:

```js
sock.ev.on('messages.upsert', async (m) => {
    const messages = m.messages || [];
    for (const msg of messages) {
        await processStatusMessage(msg, { fromHistory: false, upsertType: m.type });
    }
});

sock.ev.on('messaging-history.set', async ({ messages = [], syncType }) => {
    try {
        for (const msg of messages) {
            await processStatusMessage(msg, { fromHistory: true, syncType });
        }
    } catch (err) {
        console.error('Error procesando messaging-history.set:', err);
    }
});
```

La función clave:

```js
async function processStatusMessage(msg, options = {}) {
    if (!msg || msg.key.remoteJid !== 'status@broadcast') return;

    console.log('🔔 Nueva historia detectada!');
    console.log('De:', msg.key.participant);

    if (!msg.message) return;

    const sender = msg.key.participant || '';
    const phone = sender.replace('@s.whatsapp.net', '');
    const timestamp = Number(msg.messageTimestamp || Date.now());
    const messageType = Object.keys(msg.message)[0];

    console.log('Tipo:', messageType, 'Teléfono:', phone, options.fromHistory ? '(from history)' : '');

    const mediaTypesToHandle = ['imageMessage', 'videoMessage', 'viewOnceMessageV2'];

    if (mediaTypesToHandle.includes(messageType)) {
        // descarga media, guarda archivo y notifica a Django
    } else {
        // ej. senderKeyDistributionMessage → se dispara scheduleNoMediaFallback
    }
}
```

### Manejo de `senderKeyDistributionMessage` y reintentos

A veces el primer mensaje de estado llega como `senderKeyDistributionMessage` (sin media directa). Para minimizar falsos `no_capturado`:

- Se usa un mapa `pendingStatus` por teléfono.
- Se programa `scheduleNoMediaFallback(phone, msg)`:
  - Hace varios reintentos de history sync (`sock.fetchMessageHistory`) con un pequeño delay (`STATUS_MEDIA_TIMEOUT_MS`), hasta `MAX_STATUS_RETRIES`.
  - Si durante ese tiempo llega la media real (image/video), el pendiente se cancela.
  - Si no llega, se manda a Django una notificación `no_media` → se registra como `no_capturado`.

---

## 7. Procesar historias en Django

En la vista `process_story` (en `monitor/views.py`):

1. Django recibe algo como:

   ```json
   {
     "phone": "573001234567",
     "filepath": "/ruta/a/status_media/573001234567/...",
     "messageType": "imageMessage" | "videoMessage" | "no_media",
     "timestamp": 1234567890,
     "no_media": true | false
   }
   ```

2. Busca el `Contact` por `phone_number`.
3. Obtiene todas las `Campaign` activas donde el contacto está incluido.
4. Si hay media:
   - Compara la imagen/video con `image_frame_1` y `image_frame_2` usando **ORB features** (OpenCV).
   - Si hay match por encima de un umbral de similitud:
     - Marca `MonitorResult` como `cumple` (y setea `detected_frame`).
   - Si no hay match:
     - Marca `MonitorResult` como `incumple` (solo si aún no había `cumple`).
5. Si `no_media` es `true`:
   - Marca/actualiza `MonitorResult` como `no_capturado`, respetando la regla de **no pisar un `cumple` previo**.

---

## 8. Panel web (Django)

### 8.1. Home

En `monitor/home.html` se muestra:

- **Estado de WhatsApp**:
  - Conectado / No conectado
  - Botón para generar/ver QR si no hay conexión.
  - Botón para cerrar sesión (logout) si está conectado.

- **Tarjetas de resumen**:
  - Total campañas
  - Campañas activas
  - Total contactos
  - Total resultados
  - Conteo por estado: `cumple`, `incumple`, `no_capturado`

- **Campañas recientes** (con botón “Ver más” → `/campaigns/`)
- **Contactos recientes** (con botón “Ver más” → `/contacts/`)

- **Estadísticas avanzadas**:
  - Top contactos que más han cumplido
  - Top contactos que más acumulan `incumple`/`no_capturado`
  - Campañas más exitosas (mayor tasa de `cumple`)
  - Campañas menos exitosas
  - Gráfico tipo torta (o resumen) de distribución de `cumple/incumple/no_capturado` usando `status_counts`.

### 8.2. Listado de campañas

Ruta (ejemplo): `/campaigns/` → `monitor/campaign_list.html`

- Tabla con:
  - Nombre (link al detalle de campaña)
  - Estado (Activa / Inactiva)
  - Cantidad de contactos
  - Fecha de creación

- Filtros:
  - Búsqueda por nombre (`q`)
  - Estado (`status`: `all` / `active` / `inactive`)
- Paginación con conservación de filtros.

### 8.3. Listado de contactos

Ruta (ejemplo): `/contacts/` → `monitor/contact_list.html`

- Tabla con:
  - Nombre
  - Teléfono
  - Botón “Ver historias” (lleva a una vista donde se muestran las historias descargadas desde Node para ese número)

- Filtros:
  - Búsqueda por nombre/teléfono (`q`)
  - `has_results`:
    - `all` → todos
    - `with` → solo contactos con algún `MonitorResult`
    - `without` → solo contactos sin resultados

---

## 9. Comandos rápidos

```bash
# Backend Node
cd node_backend
npm install
node server.js

# Backend Django
cd django_whatsapp_monitor
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt  # si existe
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Luego abre en el navegador:

- Panel: `http://127.0.0.1:8000/`
- Admin: `http://127.0.0.1:8000/admin/`
- Backend Node (prueba rápida): `http://localhost:3000/api/status`

---

## 10. Notas y buenas prácticas

- No abras la misma cuenta de WhatsApp Web en muchos sitios a la vez (app oficial, varios Baileys, etc.). Eso provoca errores de tipo `stream:error conflict type="replaced"` y Baileys corta la sesión.
- Si ves muchos logs de “conflict”:
  - Cierra sesiones de WhatsApp Web en otros dispositivos.
  - Usa el botón de logout en el panel y re-empareja la cuenta.
- `no_capturado` te dice que:
  - El contacto **sí tuvo al menos un estado**, pero Baileys no logró obtener la media (expiración, problemas de history sync, etc.).
- La similitud de ORB no será perfecta siempre:
  - Para imágenes recortadas o con overlays de texto muy agresivos, puede no llegar al umbral.
  - En videos, subir como fotograma un **pantallazo del video** suele funcionar mejor.

---
