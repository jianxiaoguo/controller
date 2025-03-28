"""
The **api** Django app presents a RESTful web API for interacting with the **drycc** system.
"""
from .settings.celery import app as celery_app

__version__ = 'canary'
__all__ = ('celery_app',)
