from django.contrib import admin

from .models import Appointment, Doctor, Patient, WorkingHours


@admin.register(Doctor)
class DoctorAdmin(admin.ModelAdmin):
    list_display = ["id", "name", "specialty"]


@admin.register(WorkingHours)
class WorkingHoursAdmin(admin.ModelAdmin):
    list_display = ["id", "doctor", "weekday", "start_time", "end_time"]
    list_filter = ["weekday", "doctor"]


@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = ["id", "name", "email"]


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = ["id", "doctor", "patient", "start_time", "status"]
    list_filter = ["status", "doctor"]