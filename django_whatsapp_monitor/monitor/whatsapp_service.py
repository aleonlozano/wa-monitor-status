import requests
from django.conf import settings

class WhatsAppBaileysService:
    def __init__(self):
        self.base_url = settings.WHATSAPP_API_URL  # ej: http://localhost:3000/api

    def start_session(self):
        """
        Pide al backend Node (Baileys) que inicie/reinicie la sesión
        y genere un nuevo flujo de QR bajo demanda.
        """
        url = f"{self.base_url}/start-session"
        resp = requests.post(url, timeout=5)
        resp.raise_for_status()
        return resp.json()

    def get_qr_code(self):
        """Obtiene el QR en texto (string) para debug o para mostrarlo con otra librería."""
        response = requests.get(f"{self.base_url}/qr", timeout=5)
        response.raise_for_status()
        return response.json().get('qr')

    def is_connected(self):
        """Verifica si WhatsApp está conectado"""
        response = requests.get(f"{self.base_url}/status", timeout=5)
        response.raise_for_status()
        data = response.json()
        return data.get('connected', False), data.get('user')

    def send_message(self, phone, message):
        """Envía mensaje a un contacto (opcional en este flujo)"""
        response = requests.post(
            f"{self.base_url}/send-message",
            json={'phone': phone, 'message': message},
            timeout=10
        )
        response.raise_for_status()
        return response.json()

    def get_contact_stories(self, phone):
        """Consulta las historias ya descargadas (lista de archivos/URLs)."""
        response = requests.post(
            f"{self.base_url}/get-status-stories",
            json={'phone': phone},
            timeout=10
        )
        response.raise_for_status()
        return response.json()

    def post_status(self, message, image_url=None, background_color='#0000FF'):
        """Publica una historia/estado propio (opcional)."""
        response = requests.post(
            f"{self.base_url}/post-status",
            json={
                'message': message,
                'imageUrl': image_url,
                'backgroundColor': background_color
            },
            timeout=10
        )
        response.raise_for_status()
        return response.json()

    def logout(self):
        """
        Pide al backend Node (Baileys) que cierre/borrre la sesión.
        """
        url = f"{self.base_url}/logout"
        resp = requests.post(url, timeout=5)
        resp.raise_for_status()
        return resp.json()
