# Django WhatsApp Monitor (Baileys + ORB)

Proyecto Django que recibe notificaciones del backend Node.js (Baileys) cuando se detectan nuevas historias de WhatsApp y ejecuta el flujo:

Baileys detecta nueva historia → Descarga imagen → Notifica a Django →
Django compara con fotogramas (ORB) → Marca contacto como "Cumple" o "Pendiente".

La comparación de imágenes se hace con ORB (features locales), lo que es más robusto
frente a texto añadido, pequeñas variaciones y reencuadres leves.

## Requisitos

- Python 3.10+
- Virtualenv recomendado
- Node backend corriendo en `http://localhost:3000`

## Instalación

```bash
cd django_whatsapp_monitor
python -m venv .venv
source .venv/bin/activate  # En Windows: .venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser  # Opcional, para usar el admin
```

## Ejecución

```bash
python manage.py runserver
```

## Flujo

1. Levanta el backend Node (Baileys) en `../node_backend`:
   ```bash
   cd ../node_backend
   npm install
   node server.js
   ```

   Escanea el QR que sale en consola con tu WhatsApp (Dispositivos vinculados).

2. Levanta Django:
   ```bash
   cd django_whatsapp_monitor
   source .venv/bin/activate
   python manage.py runserver
   ```

3. Entra al admin (`/admin`) y crea:
   - Contactos (`Contact`) con `name` y `phone_number` (formato internacional sin +, ej: `573001234567`).
   - Campañas (`Campaign`) con `image_frame_1` y/o `image_frame_2` y márcalas como activas, asociando contactos.

4. Cuando uno de esos contactos publique historias en WhatsApp (y te tenga agregado):
   - Baileys detectará el estado.
   - Guardará la media en `node_backend/status_media/<phone>/`.
   - Llamará a `http://localhost:8000/api/process-story/`.
   - Django comparará la historia con los fotogramas de la campaña usando ORB (`compare_images`).
   - Actualizará `MonitorResult` con estado `cumple` o `pendiente` según el `min_match_ratio` definido.

5. Puedes ver las historias descargadas para un contacto en:
   ```
   /contact/<contact_id>/stories/
   ```
