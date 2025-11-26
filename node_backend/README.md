# Backend Node.js (Baileys)

Este backend usa `gifted-baileys` para:

- Conectarse a WhatsApp Web.
- Detectar nuevas historias/estados de tus contactos.
- Descargar las imágenes/videos de esas historias.
- Notificar a Django para procesar la historia.

## Requisitos

- Node.js 18+
- Una cuenta de WhatsApp en tu celular (para escanear el QR).

## Instalación

```bash
cd node_backend
npm install
```

## Ejecución

```bash
node server.js
```

En la primera ejecución:
- Se mostrará un QR en consola.
- Abre WhatsApp en tu celular → Dispositivos vinculados → Vincular dispositivo → Escanea el QR.

Cuando tus contactos publiquen historias (y te tengan agregado), el backend descargará las medias en `status_media/` y llamará al endpoint de Django `http://localhost:8000/api/process-story/`.
