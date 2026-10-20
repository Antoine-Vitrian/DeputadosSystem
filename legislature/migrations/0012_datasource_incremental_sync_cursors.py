from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("legislature", "0011_datasource_separate_sync_timestamps"),
    ]

    operations = [
        migrations.AddField(
            model_name="datasource",
            name="projects_synced_through",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="datasource",
            name="votings_synced_through",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="datasource",
            name="expenses_synced_through",
            field=models.DateField(blank=True, null=True),
        ),
    ]
