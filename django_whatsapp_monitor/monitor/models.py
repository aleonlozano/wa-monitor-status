from django.db import models

class Contact(models.Model):
    name = models.CharField(max_length=255)
    phone_number = models.CharField(max_length=20, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.phone_number})"


class Campaign(models.Model):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    image_frame_1 = models.ImageField(upload_to='campaign_frames/', blank=True, null=True)
    image_frame_2 = models.ImageField(upload_to='campaign_frames/', blank=True, null=True)
    contacts = models.ManyToManyField(Contact, related_name='campaigns', blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class MonitorResult(models.Model):
    STATUS_CHOICES = [
        ('pendiente', 'Pendiente'),
        ('cumple', 'Cumple'),
        ('incumple', 'Incumple'),
        ('no_capturado', 'No capturado'),
    ]

    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name='results')
    contact = models.ForeignKey(Contact, on_delete=models.CASCADE, related_name='results')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pendiente')
    detected_frame = models.IntegerField(blank=True, null=True)
    story_path = models.CharField(max_length=500, blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('campaign', 'contact')

    def __str__(self):
        return f"{self.contact} - {self.campaign} ({self.status})"
