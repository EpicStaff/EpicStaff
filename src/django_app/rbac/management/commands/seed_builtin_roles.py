from django.core.exceptions import ImproperlyConfigured
from django.core.management.base import BaseCommand, CommandError

from rbac.access.builtin_roles import BuiltInRoleSeeder


class Command(BaseCommand):
    help = "Reconcile the built-in roles in the database with rbac/access/builtin_roles.json."

    def handle(self, *args, **options):
        try:
            result = BuiltInRoleSeeder().seed()
        except ImproperlyConfigured as error:
            raise CommandError(str(error)) from error

        for warning in result.warnings:
            self.stderr.write(self.style.WARNING(warning))
        if not result.changes:
            self.stdout.write(self.style.SUCCESS("Built-in roles up to date."))
            return
        for change in result.changes:
            self.stdout.write(change)
        self.stdout.write(
            self.style.SUCCESS(f"Built-in roles updated: {len(result.changes)} change(s).")
        )
