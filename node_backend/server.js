// server.js - WhatsApp Baileys backend
const {
    default: makeWASocket,
    useMultiFileAuthState,
    DisconnectReason,
    downloadMediaMessage,
    fetchLatestBaileysVersion
} = require('@whiskeysockets/baileys');
const { Boom } = require('@hapi/boom');
const express = require('express');
const fs = require('fs');
const path = require('path');
const axios = require('axios');

const qrcode = require('qrcode-terminal');

// Socket y estado globales
let sock = null;
let qrCode = '';
let isConnecting = false;
let lastQrPrinted = null; // evita imprimir el mismo QR una y otra vez

const app = express();
app.use(express.json());

// Clave: `${phone}:${msgKeyId}` para no mezclar múltiples estados del mismo teléfono
const pendingStatus = new Map();
const STATUS_MEDIA_TIMEOUT_MS = 4000; // 4s entre intentos
const MAX_STATUS_RETRIES = 4;         // número de reintentos de history sync antes de marcar no_capturado

async function scheduleNoMediaFallback(phone, msg) {
    const timestamp = Number(msg.messageTimestamp || Date.now());
    const msgKeyId = msg.key?.id || `tmp-${timestamp}`;
    const pendingKey = `${phone}:${msgKeyId}`;

    const existing = pendingStatus.get(pendingKey);

    // Si ya había un pendiente para este teléfono+mensaje, actualizamos key y timestamp
    if (existing) {
        existing.lastMsgKey = msg.key;
        existing.timestamp = timestamp;
        pendingStatus.set(pendingKey, existing);
        return;
    }

    // Creamos una nueva entrada de seguimiento por teléfono+mensaje
    const entry = {
        phone,
        msgKeyId,
        lastMsgKey: msg.key,
        timestamp,
        retries: 0
    };
    pendingStatus.set(pendingKey, entry);

    const runAttempt = async () => {
        const current = pendingStatus.get(pendingKey);
        if (!current) return;

        if (current.retries >= MAX_STATUS_RETRIES) {
            // Ya hicimos varios intentos de history sync, nos rendimos y marcamos no_capturado
            pendingStatus.delete(pendingKey);
            try {
                await notifyDjango({
                    phone,
                    filepath: null,
                    messageType: 'no_media',
                    timestamp: current.timestamp,
                    no_media: true
                });
                console.log('⚠️ Marcado como no_capturado tras varios intentos para teléfono', phone, 'mensaje', msgKeyId);
            } catch (err) {
                console.error('Error notificando no_media a Django tras varios intentos:', err.message || err);
            }
            return;
        }

        current.retries += 1;
        pendingStatus.set(pendingKey, current);

        // Intento best-effort de history sync si la librería lo soporta
        try {
            if (sock && typeof sock.fetchMessageHistory === 'function') {
                console.log(`🔁 Intentando history sync (reintento ${current.retries}) para estados de`, phone, 'mensaje', msgKeyId);
                await sock.fetchMessageHistory(
                    50,                  // cantidad máxima de mensajes
                    current.lastMsgKey,  // key del mensaje de estado que disparó el no_media
                    current.timestamp    // timestamp de referencia
                );
            } else {
                console.log('sock.fetchMessageHistory no disponible, omitiendo history sync.');
            }
        } catch (err) {
            console.error('Error en fetchMessageHistory (reintento):', err.message || err);
        }

        // Programamos el siguiente intento, si es necesario
        setTimeout(runAttempt, STATUS_MEDIA_TIMEOUT_MS);
    };

    // Primer intento diferido
    setTimeout(runAttempt, STATUS_MEDIA_TIMEOUT_MS);
}

async function processStatusMessage(msg, options = {}) {
    if (!msg || msg.key?.remoteJid !== 'status@broadcast') {
        return;
    }

    console.log('🔔 Nueva historia detectada!');
    console.log('De:', msg.key.participant);

    if (!msg.message) return;

    const sender = msg.key.participant || msg.key.remoteJid || '';
    const phone = sender.replace('@s.whatsapp.net', '');
    const timestamp = Number(msg.messageTimestamp || Date.now());

    const container = msg.message;
    let effectiveType = null;

    // 1) viewOnceMessageV2 (dentro viene imageMessage o videoMessage)
    if (container.viewOnceMessageV2 && container.viewOnceMessageV2.message) {
        const inner = container.viewOnceMessageV2.message;
        if (inner.imageMessage) {
            effectiveType = 'imageMessage';
        } else if (inner.videoMessage) {
            effectiveType = 'videoMessage';
        }
    }
    // 2) image/video al mismo nivel que senderKeyDistributionMessage
    else if (container.imageMessage) {
        effectiveType = 'imageMessage';
    } else if (container.videoMessage) {
        effectiveType = 'videoMessage';
    }

    // Para logs, seguimos viendo el “primer key” pero sólo como referencia
    const firstKey = Object.keys(container)[0];
    console.log(
        'Tipo bruto (primer key):',
        firstKey,
        'Tipo efectivo:',
        effectiveType || firstKey,
        'Teléfono:',
        phone,
        options.fromHistory ? '(from history)' : ''
    );

    const msgKeyId = msg.key?.id || `tmp-${timestamp}`;
    const pendingKey = `${phone}:${msgKeyId}`;
    const isMedia =
        effectiveType === 'imageMessage' ||
        effectiveType === 'videoMessage';

    if (isMedia) {
        // Si llega media real, cancelamos cualquier pendiente de no_media para este teléfono+mensaje
        if (pendingStatus.has(pendingKey)) {
            pendingStatus.delete(pendingKey);
        }

        try {
            const buffer = await downloadMediaMessage(
                msg,
                'buffer',
                {},
                {
                    logger: console,
                    reuploadRequest: sock?.updateMediaMessage
                }
            );

            let extension = (effectiveType === 'imageMessage') ? 'jpg' : 'mp4';
            const filename = `${timestamp}_${phone}.${extension}`;
            const statusDir = path.join(__dirname, 'status_media', phone);

            if (!fs.existsSync(statusDir)) {
                fs.mkdirSync(statusDir, { recursive: true });
            }

            const filepath = path.join(statusDir, filename);
            fs.writeFileSync(filepath, buffer);

            console.log(`✅ Historia guardada: ${filepath}`);
            console.log(
                '   Detalle captura OK -> phone:',
                phone,
                'tipo:',
                effectiveType,
                'timestamp:',
                timestamp
            );

            await notifyDjango({
                phone,
                filepath,
                messageType: effectiveType,
                timestamp
            });
        } catch (error) {
            console.error('Error descargando historia:', error);
        }
    } else {
        // Mensaje de estado sin media directa: aquí sí usamos el fallback
        console.log('Tipo de estado no soportado aún (sin media directa):', firstKey);
        try {
            console.log(
                'Payload crudo de msg.message para análisis:',
                JSON.stringify(msg.message, null, 2)
            );
        } catch (e) {
            console.log('No se pudo serializar msg.message:', e.message || e);
        }
        await scheduleNoMediaFallback(phone, msg);
    }
}

// Servir las medias de estados como archivos estáticos
// Ej: http://localhost:3000/media/status/573001234567/1699999999999_573001234567.jpg
app.use('/media/status', express.static(path.join(__dirname, 'status_media')));

// ========== CONEXIÓN A WHATSAPP ==========

async function connectToWhatsApp() {
    const { state, saveCreds } = await useMultiFileAuthState('auth_baileys');
    const { version } = await fetchLatestBaileysVersion();

    sock = makeWASocket({
        auth: state,
        version,
        browser: ['Django Monitor', 'Chrome', '10.0']
    });

    // Actualizar QR
    sock.ev.on('connection.update', (update) => {
        const { connection, lastDisconnect, qr } = update;

        if (qr && qr !== lastQrPrinted) {
            lastQrPrinted = qr;
            qrCode = qr;
            console.log('QR Code actualizado (escanéalo en tu celular).');
            qrcode.generate(qr, { small: true });
        }

        if (connection === 'close') {
            const statusCode = (lastDisconnect?.error instanceof Boom)
                ? lastDisconnect.error.output.statusCode
                : 0;

            const isConflict = statusCode === DisconnectReason.conflict || statusCode === 440;
            const isLoggedOut = statusCode === DisconnectReason.loggedOut;
            const is405 = statusCode === 405;

            console.log(
                'Conexión cerrada, statusCode:',
                statusCode,
                'conflict:',
                isConflict,
                'loggedOut:',
                isLoggedOut
            );

            // Limpiamos el socket en memoria
            sock = null;

            if (is405) {
                // 405 suele indicar un problema de versión / handshake a nivel de servidor.
                // No intentamos reconectar en bucle, dejamos que el operador revise versión y reinicie.
                console.error(
                    '⚠️ Recibido statusCode 405 (Connection Failure). ' +
                    'Revisa que estés usando la última versión de @whiskeysockets/baileys y vuelve a iniciar el proceso.'
                );
                return;
            }

            if (isConflict) {
                // Caso típico: "stream:error conflict type=replaced"
                // Otro cliente (teléfono, web u otro Baileys) reemplazó esta sesión.
                // No reconectamos automáticamente para evitar loops.
                console.warn('Sesión de WhatsApp reemplazada por otro cliente. No se reconecta automáticamente.');
                return;
            }

            if (!isLoggedOut) {
                // Cierre inesperado que NO es logout ni conflicto -> intentamos reconectar de forma controlada
                console.log('Intentando reconectar tras cierre no esperado...');
                ensureConnection().catch(err => console.error('Error reconectando:', err));
            } else {
                // loggedOut: se cerró sesión desde el teléfono / se invalidaron credenciales
                console.log('Sesión cerrada (logged out). Esperando acción manual (nuevo QR / start-session).');
            }

        } else if (connection === 'open') {
            console.log('✅ WhatsApp conectado exitosamente');
        }
    });

    sock.ev.on('creds.update', saveCreds);

    // ========== MONITOREO AUTOMÁTICO DE ESTADOS ==========
    sock.ev.on('messages.upsert', async (m) => {
        const messages = m.messages || [];
        for (const msg of messages) {
            await processStatusMessage(msg, { fromHistory: false, upsertType: m.type });
        }
    });

    // Procesar actualizaciones de mensajes (por si un status se completa con media después)
    sock.ev.on('messages.update', async (updates) => {
        try {
            for (const { key, update } of updates) {
                if (!update?.message) {
                    continue;
                }
                if (key?.remoteJid !== 'status@broadcast') {
                    continue;
                }

                const syntheticMsg = {
                    key,
                    message: update.message,
                    messageTimestamp: update.messageTimestamp || Date.now()
                };

                console.log('♻️ messages.update para status. key.id:', key.id);
                await processStatusMessage(syntheticMsg, { fromHistory: false, upsertType: 'update' });
            }
        } catch (err) {
            console.error('Error procesando messages.update:', err);
        }
    });

    // También procesar mensajes históricos que lleguen por history sync
    sock.ev.on('messaging-history.set', async ({ messages = [], syncType }) => {
        try {
            console.log('📚 messaging-history.set recibido. syncType:', syncType, 'total mensajes:', messages.length);
            for (const msg of messages) {
                if (msg?.key?.remoteJid === 'status@broadcast') {
                    console.log('   • Mensaje de status en history.set. key.id:', msg.key.id, 'timestamp:', msg.messageTimestamp);
                }
                await processStatusMessage(msg, { fromHistory: true, syncType });
            }
        } catch (err) {
            console.error('Error procesando messaging-history.set:', err);
        }
    });
}

// Helper para asegurar conexión evitando múltiples llamadas simultáneas
async function ensureConnection() {
    // Si ya hay un socket con usuario, no hacemos nada
    if (sock && sock.user) {
        return;
    }
    // Evitar llamadas concurrentes a connectToWhatsApp
    if (isConnecting) {
        return;
    }
    isConnecting = true;
    try {
        await connectToWhatsApp();
    } catch (err) {
        console.error('Error en ensureConnection:', err);
    } finally {
        isConnecting = false;
    }
}

// Notificar a Django cuando hay nueva historia
async function notifyDjango(data) {
    try {
        await axios.post('http://localhost:8000/api/process-story/', data);
        console.log('Django notificado sobre nueva historia');
    } catch (error) {
        console.error('Error notificando a Django:', error.message);
    }
}

ensureConnection().catch(err => console.error('Error inicial conectando a WhatsApp:', err));

// ========== ENDPOINTS API ==========

// Obtener QR Code (para mostrarlo si quisieras en Django)
app.get('/api/qr', async (req, res) => {
    try {
        const hasUser = !!(sock && sock.user);

        // Sólo intentamos conectar si:
        // - No hay usuario conectado
        // - No tenemos un QR ya generado
        // - Y no estamos ya en medio de un intento de conexión
        if (!hasUser && !qrCode && !isConnecting) {
            await ensureConnection();
        }
    } catch (err) {
        console.error('Error en ensureConnection desde /api/qr:', err);
    }

    res.json({ qr: qrCode || null });
});
// Iniciar o reiniciar sesión de WhatsApp (bajo demanda desde el panel Django)
app.post('/api/start-session', async (req, res) => {
    try {
        // Si ya está conectado, simplemente devolvemos estado
        if (sock && sock.user) {
            return res.json({ success: true, alreadyConnected: true });
        }

        // Limpiar QR previo
        qrCode = '';

        await ensureConnection();

        return res.json({ success: true, started: true });
    } catch (error) {
        console.error('Error en /api/start-session:', error);
        return res.status(500).json({ error: error.message });
    }
});


// Verificar conexión
app.get('/api/status', (req, res) => {
    const connected = !!(sock && sock.user);
    res.json({
        connected,
        user: sock?.user || null
    });
});

// Enviar mensaje (opcional)
app.post('/api/send-message', async (req, res) => {
    const { phone, message } = req.body;

    if (!phone || !message) {
        return res.status(400).json({ error: 'phone y message son obligatorios.' });
    }

    try {
        const jid = `${phone}@s.whatsapp.net`;
        await sock.sendMessage(jid, { text: message });
        res.json({ success: true });
    } catch (error) {
        res.status(500).json({ error: error.message });
    }
});

// Obtener lista de historias/estados guardados localmente para un teléfono
app.post('/api/get-status-stories', async (req, res) => {
    const { phone } = req.body;

    if (!phone) {
        return res.status(400).json({ error: 'phone es obligatorio.' });
    }

    try {
        const jid = `${phone}@s.whatsapp.net`;
        const [exists] = await sock.onWhatsApp(jid);

        if (!exists?.exists) {
            return res.status(404).json({ error: 'Contacto no encontrado en WhatsApp' });
        }

        const statusDir = path.join(__dirname, 'status_media', phone);
        let stories = [];

        if (fs.existsSync(statusDir)) {
            const files = fs.readdirSync(statusDir);
            stories = files.map((filename) => {
                const fullPath = path.join(statusDir, filename);
                const stats = fs.statSync(fullPath);
                return {
                    filename,
                    path: fullPath,
                    url: `/media/status/${phone}/${filename}`,
                    size: stats.size,
                    mtime: stats.mtime
                };
            });
        }

        res.json({
            success: true,
            phone,
            stories
        });

    } catch (error) {
        console.error('Error en get-status-stories:', error);
        res.status(500).json({ error: error.message });
    }
});

// Publicar una historia/estado propio (opcional)
app.post('/api/post-status', async (req, res) => {
    const { message, imageUrl } = req.body;

    try {
        if (imageUrl) {
            const response = await axios.get(imageUrl, { responseType: 'arraybuffer' });
            const buffer = Buffer.from(response.data);

            await sock.sendMessage('status@broadcast', { image: buffer, caption: message });
        } else {
            await sock.sendMessage('status@broadcast', { text: message });
        }

        res.json({ success: true, message: 'Historia publicada' });
    } catch (error) {
        res.status(500).json({ error: error.message });
    }
});

app.post('/api/logout', async (req, res) => {
    try {
        if (sock) {
            try {
                await sock.logout();
            } catch (e) {
                console.error('Error en sock.logout():', e.message);
            }
        }

        const authPath = path.join(__dirname, 'auth_baileys');
        if (fs.existsSync(authPath)) {
            fs.rmSync(authPath, { recursive: true, force: true });
            console.log('Carpeta auth_baileys eliminada para forzar nuevo emparejamiento.');
        }

        // Opcional: limpiar variables en memoria
        qrCode = '';
        sock = null;

        res.json({ success: true });
    } catch (error) {
        console.error('Error en /api/logout:', error);
        res.status(500).json({ error: error.message });
    }
});

app.listen(3000, () => {
    console.log('🚀 WhatsApp API con Baileys corriendo en http://localhost:3000');
});
