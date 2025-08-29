from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from api.models import UserProfile

class Command(BaseCommand):
    help = "Clean up Django users that do not have a corresponding UserProfile in MongoDB"

    def handle(self, *args, **kwargs):
        deleted_count = 0
        for user in User.objects.all():
            if not UserProfile.objects.filter(user_id=str(user.id)).first():
                self.stdout.write(self.style.WARNING(f"Deleting: {user.username} (id={user.id})"))
                user.delete()
                deleted_count += 1

        if deleted_count == 0:
            self.stdout.write(self.style.SUCCESS("✅ No dangling users found."))
        else:
            self.stdout.write(self.style.SUCCESS(f"🗑️ Deleted {deleted_count} dangling users."))
