from django.core.exceptions import ValidationError
from django.db import models


SLOT_MINUTES = 30


class Doctor(models.Model):
    name = models.CharField(max_length=255)
    specialty = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return self.name


class WorkingHours(models.Model):

    WEEKDAY_CHOICES = [
        (0, "Monday"),
        (1, "Tuesday"),
        (2, "Wednesday"),
        (3, "Thursday"),
        (4, "Friday"),
        (5, "Saturday"),
        (6, "Sunday"),
    ]

    doctor = models.ForeignKey(Doctor, related_name="working_hours", on_delete=models.CASCADE)
    weekday = models.IntegerField(choices=WEEKDAY_CHOICES)
    start_time = models.TimeField()
    end_time = models.TimeField()

    class Meta:
        ordering = ["weekday", "start_time"]

    def clean(self):
        if self.start_time >= self.end_time:
            raise ValidationError("start_time must be before end_time.")

    def __str__(self):
        return f"{self.doctor.name} - {self.get_weekday_display()} {self.start_time}-{self.end_time}"


class Patient(models.Model):
    name = models.CharField(max_length=255)
    email = models.EmailField(unique=True)

    def __str__(self):
        return self.name


class Appointment(models.Model):
    STATUS_BOOKED = "booked"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (STATUS_BOOKED, "Booked"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    doctor = models.ForeignKey(Doctor, related_name="appointments", on_delete=models.CASCADE)
    patient = models.ForeignKey(Patient, related_name="appointments", on_delete=models.CASCADE)
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_BOOKED)
    cancellation_reason = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["start_time"]
        constraints = [
            # Prevents two BOOKED appointments from occupying the same
            # doctor + start_time. Cancelled appointments are excluded so
            # a freed slot can be rebooked without a unique-key clash.
            models.UniqueConstraint(
                fields=["doctor", "start_time"],
                condition=models.Q(status="booked"),
                name="unique_booked_slot_per_doctor",
            )
        ]

    def __str__(self):
        return f"{self.patient.name} with {self.doctor.name} at {self.start_time}"

    @property
    def is_cancelled(self):
        return self.status == self.STATUS_CANCELLED