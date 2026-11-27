from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Build the dashboard summary for every active organization, or for one with --org."

    def add_arguments(self, parser):
        parser.add_argument("--org", type=int, help="Build only this organization id.")

    def handle(self, *args, **options):
        from tables.services.dashboard.report import build_all_reports, build_report

        if options["org"]:
            report = build_report(options["org"])
            self.stdout.write(f"Built org {report.org_id} at {report.built_at:%Y-%m-%d %H:%M:%S}")
            return
        built, failed = build_all_reports()
        self.stdout.write(f"Built {len(built)} organizations.")
        if failed:
            self.stderr.write(f"Failed: {', '.join(map(str, failed))}")
