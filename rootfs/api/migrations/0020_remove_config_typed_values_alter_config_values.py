# Generated by Django 4.2.16 on 2024-11-06 06:22

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0019_migration_config_values_and_typed_values'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='config',
            name='typed_values',
        ),
        migrations.AlterField(
            model_name='config',
            name='values',
            field=models.JSONField(blank=True, default=list),
        ),
    ]
