from datetime import datetime, timedelta

from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Appointment, Doctor, Patient
from .serializers import (
    AppointmentCancelSerializer,
    AppointmentCreateSerializer,
    AppointmentRescheduleSerializer,
    AppointmentSerializer,
)
from .services import BookingError, get_available_slots, validate_slot

# Bonus requirement: bookings must be made at least 1 hour before the slot.
MIN_LEAD_TIME = timedelta(hours=1)

ERROR_CODE_STATUS = {
    "invalid_duration": status.HTTP_400_BAD_REQUEST,
    "past_slot": status.HTTP_400_BAD_REQUEST,
    "too_soon": status.HTTP_400_BAD_REQUEST,
    "outside_working_hours": status.HTTP_422_UNPROCESSABLE_ENTITY,
    "slot_taken": status.HTTP_409_CONFLICT,
}


def _error_response(exc: BookingError):
    http_status = ERROR_CODE_STATUS.get(exc.code, status.HTTP_400_BAD_REQUEST)
    return Response({"detail": exc.message, "code": exc.code}, status=http_status)


class DoctorAvailabilityView(APIView):
    """GET /doctors/{id}/availability?date=YYYY-MM-DD"""

    def get(self, request, doctor_id):
        doctor = get_object_or_404(Doctor, id=doctor_id)

        date_param = request.query_params.get("date")
        if not date_param:
            return Response(
                {"detail": "Query parameter 'date' (YYYY-MM-DD) is required.", "code": "missing_date"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        date = parse_date(date_param)
        if date is None:
            return Response(
                {"detail": "Invalid date format, expected YYYY-MM-DD.", "code": "invalid_date"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        slots = get_available_slots(doctor, date)
        return Response(
            {
                "doctor": doctor.id,
                "date": str(date),
                "available_slots": [
                    {"start_time": s.isoformat(), "end_time": e.isoformat()} for s, e in slots
                ],
            }
        )


class AppointmentCreateView(APIView):
    """POST /appointments"""

    def post(self, request):
        serializer = AppointmentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        doctor = serializer.validated_data["doctor"]
        patient = serializer.validated_data["patient"]
        start_time = serializer.validated_data["start_time"]
        if timezone.is_naive(start_time):
            start_time = timezone.make_aware(start_time)
        end_time = start_time + timedelta(minutes=30)

        try:
            validate_slot(doctor, start_time, end_time, min_lead_time=MIN_LEAD_TIME)
        except BookingError as exc:
            return _error_response(exc)

        appointment = Appointment.objects.create(
            doctor=doctor,
            patient=patient,
            start_time=start_time,
            end_time=end_time,
            status=Appointment.STATUS_BOOKED,
        )
        return Response(AppointmentSerializer(appointment).data, status=status.HTTP_201_CREATED)


class AppointmentCancelView(APIView):
    """PATCH /appointments/{id}/cancel"""

    def patch(self, request, appointment_id):
        appointment = get_object_or_404(Appointment, id=appointment_id)
        serializer = AppointmentCancelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        if appointment.status == Appointment.STATUS_CANCELLED:
            return Response(
                {"detail": "Appointment is already cancelled.", "code": "already_cancelled"},
                status=status.HTTP_409_CONFLICT,
            )

        appointment.status = Appointment.STATUS_CANCELLED
        appointment.cancellation_reason = serializer.validated_data["reason"]
        appointment.save(update_fields=["status", "cancellation_reason", "updated_at"])
        return Response(AppointmentSerializer(appointment).data)


class AppointmentRescheduleView(APIView):
    """PATCH /appointments/{id}/reschedule"""

    def patch(self, request, appointment_id):
        appointment = get_object_or_404(Appointment, id=appointment_id)
        serializer = AppointmentRescheduleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        if appointment.status == Appointment.STATUS_CANCELLED:
            return Response(
                {"detail": "Cannot reschedule a cancelled appointment.", "code": "already_cancelled"},
                status=status.HTTP_409_CONFLICT,
            )

        new_start = serializer.validated_data["start_time"]
        if timezone.is_naive(new_start):
            new_start = timezone.make_aware(new_start)
        new_end = new_start + timedelta(minutes=30)

        try:
            validate_slot(
                appointment.doctor,
                new_start,
                new_end,
                exclude_appointment_id=appointment.id,
                min_lead_time=MIN_LEAD_TIME,
            )
        except BookingError as exc:
            return _error_response(exc)

        appointment.start_time = new_start
        appointment.end_time = new_end
        appointment.save(update_fields=["start_time", "end_time", "updated_at"])
        return Response(AppointmentSerializer(appointment).data)


class PatientAppointmentsView(APIView):
    """GET /patients/{id}/appointments - bonus endpoint."""

    def get(self, request, patient_id):
        patient = get_object_or_404(Patient, id=patient_id)
        appointments = Appointment.objects.filter(
            patient=patient,
            status=Appointment.STATUS_BOOKED,
            start_time__gte=timezone.now(),
        ).order_by("start_time")
        return Response(AppointmentSerializer(appointments, many=True).data)