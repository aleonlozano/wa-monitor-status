from django.contrib import admin, messages
from django.urls import path
from django.shortcuts import render, redirect
from io import TextIOWrapper
import csv

from .models import Contact, Campaign, MonitorResult

@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    list_display = ('name', 'phone_number')
    search_fields = ('name', 'phone_number')
    change_list_template = "admin/monitor/contact/change_list.html"  # para añadir el botón

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "import/",
                self.admin_site.admin_view(self.import_contacts),
                name="monitor_contact_import",
            ),
        ]
        return custom_urls + urls

    def import_contacts(self, request):
        """
        Vista del admin para importar contactos desde un CSV.
        """
        if request.method == "POST":
            csv_file = request.FILES.get("file")
            if not csv_file:
                messages.error(request, "Debes subir un archivo CSV.")
                return redirect("admin:monitor_contact_changelist")

            # Intentamos leer el CSV como UTF-8
            try:
                wrapper = TextIOWrapper(csv_file.file, encoding="utf-8")
                reader = csv.DictReader(wrapper)
            except Exception as e:
                messages.error(request, f"Error leyendo el CSV: {e}")
                return redirect("admin:monitor_contact_changelist")

            created = 0
            updated = 0
            skipped = 0

            for row in reader:
                # Soportar nombres de columna comunes
                name = (
                        row.get("name")
                        or row.get("Name")
                        or row.get("nombre")
                        or row.get("Nombre")
                )
                phone = (
                        row.get("phone_number")
                        or row.get("phone")
                        or row.get("Phone")
                        or row.get("telefono")
                        or row.get("Teléfono")
                        or row.get("Telefono")
                )

                if not phone or not name:
                    skipped += 1
                    continue

                phone = str(phone).strip()
                name = str(name).strip()

                if not phone:
                    skipped += 1
                    continue

                obj, created_flag = Contact.objects.get_or_create(
                    phone_number=phone,
                    defaults={"name": name},
                )

                if created_flag:
                    created += 1
                else:
                    # Actualizamos nombre si cambió
                    if obj.name != name and name:
                        obj.name = name
                        obj.save()
                        updated += 1

            messages.success(
                request,
                f"Importación completada. Nuevos: {created}, Actualizados: {updated}, Omitidos: {skipped}",
            )
            return redirect("admin:monitor_contact_changelist")

        # GET → mostramos formulario de subida
        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "title": "Importar contactos desde CSV",
        }
        return render(request, "admin/monitor/contact/import_contacts.html", context)


@admin.register(Campaign)
class CampaignAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_active', 'created_at')
    list_filter = ('is_active',)
    search_fields = ('name',)
    filter_horizontal = ('contacts',)


@admin.register(MonitorResult)
class MonitorResultAdmin(admin.ModelAdmin):
    list_display = ('campaign', 'contact', 'status', 'detected_frame', 'updated_at')
    list_filter = ('status', 'campaign')
    search_fields = ('campaign__name', 'contact__name', 'contact__phone_number')
