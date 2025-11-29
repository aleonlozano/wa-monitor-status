from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_GET
from django.core.paginator import Paginator
from django.db.models import Q, Count, F, FloatField
from django.db.models.functions import Cast
from django.conf import settings
from pathlib import Path

from .models import Campaign, Contact, MonitorResult
from .image_recognition import compare_images
from .whatsapp_service import WhatsAppBaileysService
import json
import csv
import requests


def home(request):
    """Vista principal del panel de monitoreo WhatsApp."""
    # Listas recientes
    campaigns = Campaign.objects.all().order_by('-created_at')[:5]
    contacts = Contact.objects.all().order_by('-created_at')[:5]

    # Estadísticas generales básicas
    stats = {
        'total_campaigns': Campaign.objects.count(),
        'active_campaigns': Campaign.objects.filter(is_active=True).count(),
        'total_contacts': Contact.objects.count(),
        'total_results': MonitorResult.objects.count(),
        'results_cumple': MonitorResult.objects.filter(status='cumple').count(),
        'results_incumple': MonitorResult.objects.filter(status='incumple').count(),
        'results_no_capturado': MonitorResult.objects.filter(status='no_capturado').count(),
    }

    # Estado de conexión con el backend de WhatsApp (Node + Baileys)
    wa_connected = False
    wa_user = None
    wa_error = None
    wa_qr = None

    try:
        wa_service = WhatsAppBaileysService()
        # is_connected devuelve (bool, user_info) según integración actual
        wa_connected, wa_user = wa_service.is_connected()
        # Si no está conectado, intentamos obtener el QR para mostrarlo en el panel
        if not wa_connected:
            wa_qr = wa_service.get_qr_code()
    except Exception as e:
        wa_error = str(e)
        wa_connected = False
        wa_qr = None

    # =========================
    # Estadísticas avanzadas
    # =========================

    # TOP contactos que más han cumplido
    top_contacts_best = (
        MonitorResult.objects.filter(status='cumple')
        .values('contact__id', 'contact__name', 'contact__phone_number')
        .annotate(total_cumple=Count('id'))
        .order_by('-total_cumple')[:5]
    )

    # TOP contactos que menos han cumplido (incumple + no_capturado)
    top_contacts_worst = (
        MonitorResult.objects.filter(status__in=['incumple', 'no_capturado'])
        .values('contact__id', 'contact__name', 'contact__phone_number')
        .annotate(total_bad=Count('id'))
        .order_by('-total_bad')[:5]
    )

    # Conteo para la torta
    status_counts = {'cumple': 0, 'incumple': 0, 'no_capturado': 0}
    for row in (
        MonitorResult.objects.values('status')
        .annotate(total=Count('id'))
    ):
        key = row['status']
        if key in status_counts:
            status_counts[key] = row['total']

    # Campañas con tasa de éxito
    # OJO: asumo que en MonitorResult el FK tiene related_name='results'.
    campaigns_qs = (
        Campaign.objects
        .annotate(
            total_results=Count('results'),
            total_cumple=Count('results', filter=Q(results__status='cumple')),
        )
        .filter(total_results__gt=0)
        .annotate(
            success_rate=Cast(F('total_cumple'), FloatField()) * 100.0 / Cast(F('total_results'), FloatField())
        )
    )

    top_campaigns_best = campaigns_qs.order_by('-success_rate', '-total_results')[:5]
    top_campaigns_worst = campaigns_qs.order_by('success_rate', '-total_results')[:5]

    return render(request, 'monitor/home.html', {
        'campaigns': campaigns,
        'contacts': contacts,
        'stats': stats,
        'wa_connected': wa_connected,
        'wa_user': wa_user,
        'wa_qr': wa_qr,
        'wa_error': wa_error,
        'top_contacts_best': top_contacts_best,
        'top_contacts_worst': top_contacts_worst,
        'status_counts': status_counts,
        'top_campaigns_best': top_campaigns_best,
        'top_campaigns_worst': top_campaigns_worst,
    })

@require_GET
def wa_status_api(request):
    """
    Endpoint ligero para que el frontend pregunte si WhatsApp ya está conectado.
    Lo usa el modal del QR para decidir cuándo recargar la página.
    """
    try:
        wa_service = WhatsAppBaileysService()
        connected, user = wa_service.is_connected()
        return JsonResponse({'connected': connected})
    except Exception as e:
        return JsonResponse({'connected': False, 'error': str(e)}, status=500)

@require_POST
def wa_start_session(request):
    """
    Dispara en Node /api/start-session para que Baileys prepare un nuevo QR.
    """
    try:
        wa_service = WhatsAppBaileysService()
        wa_service.start_session()
    except Exception:
        # Puedes loguear el error o usar messages si quieres
        pass
    return redirect('home')

@require_POST
def wa_logout(request):
    """
    Cierra/borrra la sesión de WhatsApp en el backend de Baileys
    y redirige de vuelta al home para que se genere un nuevo QR.
    """
    try:
        wa_service = WhatsAppBaileysService()
        wa_service.logout()
    except Exception:
        # Si falla, igual volvemos al home; opcionalmente podrías usar messages
        pass
    return redirect('home')

@csrf_exempt
def process_story(request):
    """
    Endpoint que Node.js llama cuando detecta una nueva historia y la guarda.
    Node envía: { phone, filepath, messageType, timestamp }

    Flujo completo:
    Baileys detecta nueva historia → Descarga imagen → Notifica a Django →
    Django compara con fotogramas (ORB) → Marca contacto como 'Cumple' o 'Pendiente'.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'}, status=405)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON inválido'}, status=400)

    phone = data.get('phone')
    filepath = data.get('filepath')
    message_type = data.get('messageType')
    no_media = data.get('no_media', False)

    if not phone:
        return JsonResponse({'error': 'phone es obligatorio'}, status=400)

    # filepath es obligatorio solo cuando sí hay media; para no_media lo permitimos vacío
    if not filepath and not no_media:
        return JsonResponse({'error': 'filepath es obligatorio cuando no_media es False'}, status=400)

    # Buscar contacto
    try:
        contact = Contact.objects.get(phone_number=phone)
    except Contact.DoesNotExist:
        return JsonResponse({'error': 'Contacto no encontrado'}, status=404)

    # Buscar campañas activas donde está ese contacto
    active_campaigns = Campaign.objects.filter(
        contacts=contact,
        is_active=True
    )

    # Caso en el que Node/Baileys indica que no se pudo obtener media (solo claves, etc.)
    if no_media:
        for campaign in active_campaigns:
            # Si ya existe un resultado previo, respetamos las reglas:
            # - Si está en 'cumple', no lo tocamos.
            # - Si está en 'incumple', tampoco lo degradamos.
            # - Si no existe o estaba en otro estado (no_capturado, pendiente viejo), lo dejamos/ponemos en 'no_capturado'.
            result, created = MonitorResult.objects.get_or_create(
                campaign=campaign,
                contact=contact,
                defaults={
                    'status': 'no_capturado',
                    'detected_frame': None,
                    'story_path': filepath or ''
                }
            )

            if not created:
                if result.status == 'cumple':
                    # No degradar un contacto que ya cumplió
                    continue

                if result.status == 'incumple':
                    # Preferimos mantener un resultado determinístico de incumple
                    continue

                # Para estados anteriores menos determinísticos (no_capturado, pendiente viejo, etc.)
                result.status = 'no_capturado'
                if filepath:
                    result.story_path = filepath
                result.detected_frame = None
                result.save()

        return JsonResponse({'success': True, 'no_media': True})

    for campaign in active_campaigns:
        frame1_match = False
        frame2_match = False

        if campaign.image_frame_1:
            frame1_match = compare_images(filepath, campaign.image_frame_1.path)

        if campaign.image_frame_2:
            frame2_match = compare_images(filepath, campaign.image_frame_2.path)

        # Buscamos si ya existe un resultado previo para esta campaña-contacto
        result, created = MonitorResult.objects.get_or_create(
            campaign=campaign,
            contact=contact,
            defaults={
                'status': 'cumple' if (frame1_match or frame2_match) else 'incumple',
                'detected_frame': 1 if frame1_match else (2 if frame2_match else None),
                'story_path': filepath if (frame1_match or frame2_match) else ''
            }
        )

        # Si se acaba de crear, no hay nada más que hacer
        if created:
            if frame1_match or frame2_match:
                print(f'✅ {contact.name} CUMPLE con campaña {campaign.name} (nuevo resultado)')
            else:
                print(f'❌ {contact.name} INCUMPLE con campaña {campaign.name} (nuevo resultado)')
            continue

        # Si ya existía un resultado previo:
        # Regla principal: si ya estaba en CUMPLE, no lo bajamos nunca
        if result.status == 'cumple':
            # Opcional: si llega otra coincidencia y no teníamos story_path o detected_frame, podemos completar datos
            if (frame1_match or frame2_match) and (not result.story_path or not result.detected_frame):
                result.story_path = result.story_path or filepath
                if not result.detected_frame:
                    result.detected_frame = 1 if frame1_match else 2
                result.save(update_fields=['story_path', 'detected_frame'])
            # No cambiamos el estado
            continue

        # Si NO estaba en cumple (incumple, no_capturado o pendiente viejo):
        if frame1_match or frame2_match:
            # Ahora sí cumple → lo promovemos a CUMPLE
            result.status = 'cumple'
            result.detected_frame = 1 if frame1_match else 2
            result.story_path = filepath
            result.save()
            print(f'✅ {contact.name} CUMPLE con campaña {campaign.name} (actualizado desde {result.status})')
        else:
            # No hay coincidencia, y no estaba en cumple → queda o se actualiza como INCUMPLE
            if result.status != 'incumple':
                result.status = 'incumple'
                result.save(update_fields=['status'])
                print(f'❌ {contact.name} INCUMPLE con campaña {campaign.name} (actualizado)')
            else:
                # Ya era incumple, no hace falta tocar nada
                print(f'❌ {contact.name} sigue INCUMPLE con campaña {campaign.name}')

    return JsonResponse({'success': True})


def contact_stories_view(request, contact_id):
    """Vista para listar historias descargadas de un contacto específico."""
    contact = get_object_or_404(Contact, id=contact_id)
    wa_service = WhatsAppBaileysService()
    stories_data = None
    error = None

    try:
        stories_data = wa_service.get_contact_stories(contact.phone_number)
    except Exception as e:
        error = str(e)
        stories_data = None

    # Normalizar historias: asegurar que tengan URL pública y tamaño opcional
    if stories_data and isinstance(stories_data, dict) and stories_data.get("stories"):
        phone = str(contact.phone_number)

        # BASE_DIR = /root/whatsapp_baileys_monitor/django_whatsapp_monitor
        # status_media_root = /root/whatsapp_baileys_monitor/node_backend/status_media
        status_media_root = Path(settings.BASE_DIR).parent / "node_backend" / "status_media"

        for story in stories_data.get("stories", []):
            filename = story.get("filename")
            if not filename:
                continue

            # URL pública servida por Nginx
            story["url"] = f"/status_media/{phone}/{filename}"

            # Completar tamaño si viene vacío
            if not story.get("size"):
                file_path = status_media_root / phone / filename
                try:
                    story["size"] = file_path.stat().st_size
                except OSError:
                    story["size"] = None

    return render(request, 'monitor/contact_stories.html', {
        'contact': contact,
        'stories_data': stories_data,
        'error': error,
    })


def campaign_detail(request, campaign_id):
    """Detalle de una campaña: lista de contactos y si cumplen o no con los fotogramas."""
    campaign = get_object_or_404(Campaign, id=campaign_id)

    # Contactos asociados a la campaña
    contacts = campaign.contacts.all().order_by('name')

    # Resultados de monitoreo para esa campaña
    results_qs = MonitorResult.objects.filter(
        campaign=campaign
    ).select_related('contact')

    # Indexar resultados por contacto
    results_by_contact = {r.contact_id: r for r in results_qs}

    # Construir una estructura que el template pueda recorrer fácilmente
    contacts_with_status = []
    for c in contacts:
        r = results_by_contact.get(c.id)
        contacts_with_status.append({
            'contact': c,
            'result': r,
        })

    # Estadísticas por estado
    stats = {
        'total_contacts': contacts.count(),
        'cumple': results_qs.filter(status='cumple').count(),
        'incumple': results_qs.filter(status='incumple').count(),
        'no_capturado': results_qs.filter(status='no_capturado').count(),
    }

    return render(request, 'monitor/campaign_detail.html', {
        'campaign': campaign,
        'contacts_with_status': contacts_with_status,
        'stats': stats,
    })


def campaign_export_excel(request, campaign_id):
    """
    Exporta los resultados de una campaña a un CSV compatible con Excel.
    Columnas: Nombre contacto, Teléfono, Estado, Fotograma detectado, Ruta historia.
    """
    campaign = get_object_or_404(Campaign, id=campaign_id)
    results_qs = MonitorResult.objects.filter(
        campaign=campaign
    ).select_related('contact')

    # Preparar respuesta CSV (Excel lo abre sin problema)
    response = JsonResponse({}, status=200)  # placeholder to get the class
    from django.http import HttpResponse
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="campaign_{campaign.id}_results.csv"'

    writer = csv.writer(response)
    writer.writerow([
        'Campaña',
        'Contacto',
        'Teléfono',
        'Estado',
        'Fotograma detectado',
        'Ruta de la historia',
    ])

    for r in results_qs:
        writer.writerow([
            campaign.name,
            r.contact.name if r.contact else '',
            r.contact.phone_number if r.contact else '',
            r.status,
            r.detected_frame or '',
            r.story_path or '',
        ])

    return response


def campaign_list(request):
    """
    Listado de todas las campañas con filtros:
      - q: búsqueda por nombre
      - status: 'all' (por defecto), 'active', 'inactive'
    """
    qs = Campaign.objects.all().order_by('-created_at')

    q = request.GET.get('q', '').strip()
    status = request.GET.get('status', 'all')

    if q:
        qs = qs.filter(name__icontains=q)

    if status == 'active':
        qs = qs.filter(is_active=True)
    elif status == 'inactive':
        qs = qs.filter(is_active=False)

    paginator = Paginator(qs, 25)
    page = paginator.get_page(request.GET.get('page'))

    context = {
        "page_obj": page,
        "search_query": q,
        "status_filter": status,
    }
    return render(request, "monitor/campaign_list.html", context)


def contact_list(request):
    """
    Listado de todos los contactos con filtros:
      - q: búsqueda por nombre o teléfono
      - has_results: 'all' (por defecto), 'with', 'without'
    """
    qs = Contact.objects.all()

    q = request.GET.get('q', '').strip()
    has_results = request.GET.get('has_results', 'all')

    if q:
        qs = qs.filter(
            Q(name__icontains=q) |
            Q(phone_number__icontains=q)
        )

    if has_results == 'with':
        qs = qs.filter(results__isnull=False).distinct()
    elif has_results == 'without':
        qs = qs.filter(results__isnull=True)

    qs = qs.order_by('name')

    paginator = Paginator(qs, 50)
    page = paginator.get_page(request.GET.get('page'))

    context = {
        "page_obj": page,
        "search_query": q,
        "has_results_filter": has_results,
    }
    return render(request, "monitor/contact_list.html", context)