from django.core.management.base import BaseCommand

from bookings.models import Doctor, Patient, WorkingHours


class Command(BaseCommand):
    help = "Seed the database with 5 demo doctors (Mon-Fri, 9am-5pm) and 2 demo patients."

    def handle(self, *args, **options):
        if Doctor.objects.exists():
            self.stdout.write(self.style.WARNING("Doctors already exist - skipping seed."))
            return

        specialties = ["General Practice", "Pediatrics", "Dermatology", "Cardiology", "Dentistry"]
        for i, specialty in enumerate(specialties, start=1):
            doctor = Doctor.objects.create(name=f"Dr. Demo {i}", specialty=specialty)
            for weekday in range(0, 5):  # Monday-Friday
                WorkingHours.objects.create(
                    doctor=doctor, weekday=weekday, start_time="09:00", end_time="17:00"
                )

        Patient.objects.create(name="Jane Doe", email="jane.doe@example.com")
        Patient.objects.create(name="John Smith", email="john.smith@example.com")

        self.stdout.write(self.style.SUCCESS("Seeded 5 doctors and 2 patients."))