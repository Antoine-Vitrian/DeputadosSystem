from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("legislature", "0009_project_text_summary"),
    ]

    operations = [
        migrations.CreateModel(
            name="HistoricalDeputySync",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("year", models.PositiveSmallIntegerField(unique=True)),
                ("deputy_count", models.PositiveIntegerField(default=0)),
                ("synced_at", models.DateTimeField(auto_now=True)),
            ],
        ),
    ]
