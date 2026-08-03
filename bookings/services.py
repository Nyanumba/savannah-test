from datetime import datetime, timedelta

from django.utils import timezone

from .models import SLOT_MINUTES, Appointment


class BookingError(Exception):
   

    def __init__(self, message, code="invalid"):
        super().__init__(message)
        self.message = message
        self.code = code


def get_available_slots(doctor, date):
    
    weekday = date.weekday()
    windows = doctor.working_hours.filter(weekday=weekday)

    booked_starts = set(
        Appointment.objects.filter(
            doctor=doctor,
            status=Appointment.STATUS_BOOKED,
            start_time__date=date,
        ).values_list("start_time", flat=True)
    )

    slots = []
    for window in windows:
        current = timezone.make_aware(datetime.combine(date, window.start_time))
        window_end = timezone.make_aware(datetime.combine(date, window.end_time))
        step = timedelta(minutes=SLOT_MINUTES)

        while current + step <= window_end:
            slot_end = current + step
            if current not in booked_starts and current >= timezone.now():
                slots.append((current, slot_end))
            current = slot_end

    return slots


def slot_falls_within_working_hours(doctor, start_time, end_time):
    weekday = start_time.weekday()
    return doctor.working_hours.filter(
        weekday=weekday,
        start_time__lte=start_time.time(),
        end_time__gte=end_time.time(),
    ).exists()


def validate_slot(doctor, start_time, end_time, exclude_appointment_id=None,
                   min_lead_time=None):
    
    if end_time - start_time != timedelta(minutes=SLOT_MINUTES):
        raise BookingError(
            f"Appointments must be exactly {SLOT_MINUTES} minutes long.",
            code="invalid_duration",
        )

    now = timezone.now()
    lead_time = min_lead_time or timedelta(0)
    if start_time < now + lead_time:
        if start_time < now:
            raise BookingError("Cannot book a slot in the past.", code="past_slot")
        raise BookingError(
            f"Appointments must be booked at least {int(lead_time.total_seconds() // 60)} "
            "minutes in advance.",
            code="too_soon",
        )

    if not slot_falls_within_working_hours(doctor, start_time, end_time):
        raise BookingError(
            "Requested slot falls outside the doctor's working hours.",
            code="outside_working_hours",
        )

    clash = Appointment.objects.filter(
        doctor=doctor,
        start_time=start_time,
        status=Appointment.STATUS_BOOKED,
    )
    if exclude_appointment_id:
        clash = clash.exclude(id=exclude_appointment_id)
    if clash.exists():
        raise BookingError("This slot is already booked.", code="slot_taken")