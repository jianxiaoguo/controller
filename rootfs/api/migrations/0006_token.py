# Generated by Django 4.2.10 on 2024-04-30 02:02

import api.utils
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import functools
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0005_config_typed_values'),
    ]

    operations = [
        migrations.CreateModel(
            name='Token',
            fields=[
                ('uuid', models.UUIDField(auto_created=True, default=uuid.uuid4, editable=False, primary_key=True, serialize=False, unique=True, verbose_name='UUID')),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('updated', models.DateTimeField(auto_now=True)),
                ('key', models.CharField(max_length=128, unique=True, verbose_name='Key')),
                ('alias', models.CharField(blank=True, default='', max_length=32, verbose_name='Alias')),
                ('oauth', models.JSONField(validators=[functools.partial(api.utils.validate_json, *(), **{'schema': {'$schema': 'http://json-schema.org/schema#', 'properties': {'access_token': {'type': 'string'}, 'expires_in': {'type': 'integer'}, 'refresh_token': {'type': 'string'}, 'scope': {'type': 'string'}, 'token_type': {'type': 'string'}}, 'required': ['access_token', 'expires_in', 'token_type', 'scope', 'refresh_token'], 'type': 'object'}})])),
                ('owner', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'abstract': False,
            },
        ),
    ]
