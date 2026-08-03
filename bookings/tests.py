from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from bookings.models import Appointment, Doctor, Patient, WorkingHours


def next_weekday_at(weekday, hour, minute=0):
    """Return an aware datetime for the next occurrence of `weekday`
    (0=Monday) at the given time, at least 2 days out so lead-time
    checks never flake in tests."""
    now = timezone.now()
    days_ahead = (weekday - now.weekday()) % 7
    if days_ahead < 2:
        days_ahead += 7
    target_date = (now + timedelta(days=days_ahead)).date()
    return timezone.make_aware(
        timezone.datetime.combine(target_date, timezone.datetime.min.time())
    ) + timedelta(hours=hour, minutes=minute)


class BookingSetupMixin:
    def setUp(self):
        self.doctor = Doctor.objects.create(name="Dr. Wanjiru", specialty="General")
        self.patient = Patient.objects.create(name="Jane Doe", email="jane@example.com")
        self.other_patient = Patient.objects.create(name="John Smith", email="john@example.com")
        for wd in range(7):
            WorkingHours.objects.create(
                doctor=self.doctor, weekday=wd, start_time="09:00", end_time="12:00"
            )
        self.slot_start = next_weekday_at(0, 9, 0)


class AvailabilityTests(BookingSetupMixin, APITestCase):
    def test_availability_lists_free_slots(self):
        url = reverse("doctor-availability", args=[self.doctor.id])
        response = self.client.get(url, {"date": str(self.slot_start.date())})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["available_slots"]), 6)

    def test_booked_slot_excluded_from_availability(self):
        Appointment.objects.create(
            doctor=self.doctor,
            patient=self.patient,
            start_time=self.slot_start,
            end_time=self.slot_start + timedelta(minutes=30),
        )
        url = reverse("doctor-availability", args=[self.doctor.id])
        response = self.client.get(url, {"date": str(self.slot_start.date())})
        starts = [s["start_time"] for s in response.data["available_slots"]]
        self.assertNotIn(self.slot_start.isoformat(), starts)
        self.assertEqual(len(response.data["available_slots"]), 5)


class AppointmentCreateTests(BookingSetupMixin, APITestCase):
    def test_book_valid_slot_succeeds(self):
        url = reverse("appointment-create")
        response = self.client.post(url, {
            "doctor": self.doctor.id,
            "patient": self.patient.id,
            "start_time": self.slot_start.isoformat(),
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Appointment.objects.count(), 1)

    def test_double_booking_rejected(self):
        Appointment.objects.create(
            doctor=self.doctor, patient=self.patient,
            start_time=self.slot_start, end_time=self.slot_start + timedelta(minutes=30),
        )
        url = reverse("appointment-create")
        response = self.client.post(url, {
            "doctor": self.doctor.id,
            "patient": self.other_patient.id,
            "start_time": self.slot_start.isoformat(),
        })
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data["code"], "slot_taken")

    def test_booking_outside_working_hours_rejected(self):
        outside = self.slot_start.replace(hour=20, minute=0)
        url = reverse("appointment-create")
        response = self.client.post(url, {
            "doctor": self.doctor.id,
            "patient": self.patient.id,
            "start_time": outside.isoformat(),
        })
        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
        self.assertEqual(response.data["code"], "outside_working_hours")

    def test_booking_in_the_past_rejected(self):
        past = timezone.now() - timedelta(days=1)
        url = reverse("appointment-create")
        response = self.client.post(url, {
            "doctor": self.doctor.id,
            "patient": self.patient.id,
            "start_time": past.isoformat(),
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], "past_slot")

    def test_booking_within_lead_time_rejected(self):
        soon = timezone.now() + timedelta(minutes=15)
        url = reverse("appointment-create")
        response = self.client.post(url, {
            "doctor": self.doctor.id,
            "patient": self.patient.id,
            "start_time": soon.isoformat(),
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], "too_soon")


class AppointmentCancelTests(BookingSetupMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.appointment = Appointment.objects.create(
            doctor=self.doctor, patient=self.patient,
            start_time=self.slot_start, end_time=self.slot_start + timedelta(minutes=30),
        )

    def test_cancel_succeeds_and_frees_slot(self):
        url = reverse("appointment-cancel", args=[self.appointment.id])
        response = self.client.patch(url, {"reason": "Feeling better"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.status, Appointment.STATUS_CANCELLED)

        rebook_url = reverse("appointment-create")
        response = self.client.post(rebook_url, {
            "doctor": self.doctor.id,
            "patient": self.other_patient.id,
            "start_time": self.slot_start.isoformat(),
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_cancel_already_cancelled_errors(self):
        url = reverse("appointment-cancel", args=[self.appointment.id])
        self.client.patch(url, {"reason": "first cancel"}, format="json")
        response = self.client.patch(url, {"reason": "second cancel"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data["code"], "already_cancelled")


class AppointmentRescheduleTests(BookingSetupMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.appointment = Appointment.objects.create(
            doctor=self.doctor, patient=self.patient,
            start_time=self.slot_start, end_time=self.slot_start + timedelta(minutes=30),
        )

    def test_reschedule_to_free_slot_succeeds(self):
        new_start = self.slot_start + timedelta(minutes=30)
        url = reverse("appointment-reschedule", args=[self.appointment.id])
        response = self.client.patch(url, {"start_time": new_start.isoformat()}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.start_time, new_start)

    def test_reschedule_original_slot_becomes_available(self):
        new_start = self.slot_start + timedelta(minutes=30)
        url = reverse("appointment-reschedule", args=[self.appointment.id])
        self.client.patch(url, {"start_time": new_start.isoformat()}, format="json")

        rebook_url = reverse("appointment-create")
        response = self.client.post(rebook_url, {
            "doctor": self.doctor.id,
            "patient": self.other_patient.id,
            "start_time": self.slot_start.isoformat(),
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_reschedule_cancelled_appointment_rejected(self):
        self.appointment.status = Appointment.STATUS_CANCELLED
        self.appointment.save()
        new_start = self.slot_start + timedelta(minutes=30)
        url = reverse("appointment-reschedule", args=[self.appointment.id])
        response = self.client.patch(url, {"start_time": new_start.isoformat()}, format="json")
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_reschedule_into_taken_slot_rejected(self):
        taken_start = self.slot_start + timedelta(minutes=30)
        Appointment.objects.create(
            doctor=self.doctor, patient=self.other_patient,
            start_time=taken_start, end_time=taken_start + timedelta(minutes=30),
        )
        url = reverse("appointment-reschedule", args=[self.appointment.id])
        response = self.client.patch(url, {"start_time": taken_start.isoformat()}, format="json")
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data["code"], "slot_taken")


class PatientAppointmentsTests(BookingSetupMixin, APITestCase):
    def test_lists_only_upcoming_booked_appointments(self):
        Appointment.objects.create(
            doctor=self.doctor, patient=self.patient,
            start_time=self.slot_start, end_time=self.slot_start + timedelta(minutes=30),
        )
        past_start = timezone.now() - timedelta(days=5)
        past_appt = Appointment.objects.create(
            doctor=self.doctor, patient=self.patient,
            start_time=past_start, end_time=past_start + timedelta(minutes=30),
        )
        url = reverse("patient-appointments", args=[self.patient.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        returned_ids = [a["id"] for a in response.data]
        self.assertNotIn(past_appt.id, returned_ids)