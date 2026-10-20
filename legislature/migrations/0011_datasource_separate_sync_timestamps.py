from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("legislature", "0010_historicaldeputysync"),
    ]

    operations = [
        migrations.AddField(
            model_name="datasource",
            name="last_parliamentarians_synced_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="datasource",
            name="last_votings_synced_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
