from rest_framework import serializers

from .models import Appointment, Doctor, Patient, WorkingHours


class WorkingHoursSerializer(serializers.ModelSerializer):
    class Meta:
        model = WorkingHours
        fields = ["id", "weekday", "start_time", "end_time"]


class DoctorSerializer(serializers.ModelSerializer):
    working_hours = WorkingHoursSerializer(many=True, read_only=True)

    class Meta:
        model = Doctor
        fields = ["id", "name", "specialty", "working_hours"]


class PatientSerializer(serializers.ModelSerializer):
    class Meta:
        model = Patient
        fields = ["id", "name", "email"]


class AppointmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Appointment
        fields = [
            "id", "doctor", "patient", "start_time", "end_time",
            "status", "cancellation_reason", "created_at", "updated_at",
        ]
        read_only_fields = ["status", "end_time", "created_at", "updated_at"]


class AppointmentCreateSerializer(serializers.Serializer):
    doctor = serializers.PrimaryKeyRelatedField(queryset=Doctor.objects.all())
    patient = serializers.PrimaryKeyRelatedField(queryset=Patient.objects.all())
    start_time = serializers.DateTimeField()


class AppointmentCancelSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500)


class AppointmentRescheduleSerializer(serializers.Serializer):
    start_time = serializers.DateTimeField()


class AvailableSlotSerializer(serializers.Serializer):
    start_time = serializers.DateTimeField()
    end_time = serializers.DateTimeField()