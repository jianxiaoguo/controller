# Generated by Django 4.2.16 on 2024-11-12 02:14

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0016_remove_route_port_remove_route_ptype_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='config',
            name='values_refs',
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
