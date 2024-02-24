# Create your tasks here
import time
import uuid
import logging
from typing import List, Dict
from django.core import signals
from celery import shared_task

from api import manager, models
from api.exceptions import ServiceUnavailable
from api.models.resource import Resource
logger = logging.getLogger(__name__)


@shared_task(
    retry_kwargs={'max_retries': None}
)
def retrieve_resource(resource):
    task_id = uuid.uuid4().hex
    signals.request_started.send(sender=task_id)
    try:
        if not resource.retrieve():
            t = time.time() - resource.created.timestamp()
            if t < 3600:
                retrieve_resource.apply_async(args=(resource, ), countdown=30)
            elif t < 3600 * 12:
                retrieve_resource.apply_async(args=(resource, ), countdown=1800)
    except (Exception, Resource.DoesNotExist) as e:
        signals.got_request_exception.send(sender=task_id)
        if isinstance(e, Resource.DoesNotExist):
            logger.exception("retrieve task not found resource: {}".format(resource.id))
        else:
            raise e
    else:
        signals.request_finished.send(sender=task_id)


@shared_task(
    autoretry_for=(Exception, ),
    retry_backoff=8,
    retry_jitter=True,
    retry_backoff_max=3600,
    retry_kwargs={'max_retries': None}
)
def send_measurements(measurements: List[Dict[str, str]]):
    task_id = uuid.uuid4().hex
    signals.request_started.send(sender=task_id)
    try:
        measurement = manager.Measurement()
        measurement.post(measurements)
    except Exception as e:
        signals.got_request_exception.send(sender=task_id)
        raise e
    else:
        signals.request_finished.send(sender=task_id)


@shared_task(
    autoretry_for=(ServiceUnavailable, ),
    retry_jitter=True,
    retry_kwargs={'max_retries': 3}
)
def scale_app(app, user, structure):
    task_id = uuid.uuid4().hex
    signals.request_started.send(sender=task_id)
    try:
        app.scale(user, structure)
    except Exception as e:
        signals.got_request_exception.send(sender=task_id)
        raise e
    else:
        signals.request_finished.send(sender=task_id)


@shared_task(
    autoretry_for=(ServiceUnavailable, ),
    retry_jitter=True,
    retry_kwargs={'max_retries': 3}
)
def restart_app(app, **kwargs):
    task_id = uuid.uuid4().hex
    signals.request_started.send(sender=task_id)
    try:
        app.restart(**kwargs)
    except Exception as e:
        signals.got_request_exception.send(sender=task_id)
        raise e
    else:
        signals.request_finished.send(sender=task_id)


@shared_task(
    autoretry_for=(ServiceUnavailable, ),
    retry_jitter=True,
    retry_kwargs={'max_retries': 3}
)
def mount_app(app, user, volume, path):
    task_id = uuid.uuid4().hex
    signals.request_started.send(sender=task_id)
    try:
        # merge mount volume path and remove keys if a null value is provided
        for key, value in path.items():
            if value is None:
                if key not in volume.path:
                    continue
                volume.path.pop(key)
            else:
                volume.path[key] = value
        volume.save()
        structure = {}
        for scale_type, replicas in app.structure.items():
            if scale_type in path:
                structure[scale_type] = replicas
        app.mount(user, volume, structure)
    except Exception as e:
        signals.got_request_exception.send(sender=task_id)
        logger.exception(e)
    else:
        signals.request_finished.send(sender=task_id)


@shared_task(
    retry_kwargs={'max_retries': 3}
)
def downstream_model_owner(app, old_owner, new_owner):
    task_id = uuid.uuid4().hex
    signals.request_started.send(sender=task_id)
    try:
        for downstream_model in [
                models.appsettings.AppSettings, models.build.Build, models.config.Config,
                models.domain.Domain, models.release.Release, models.resource.Resource,
                models.tls.TLS, models.service.Service, models.volume.Volume,
                models.gateway.Gateway, models.gateway.Route]:
            downstream_model.objects.filter(owner=old_owner, app=app).update(owner=new_owner)
        app.owner = new_owner
        app.save()
    except Exception as e:
        signals.got_request_exception.send(sender=task_id)
        raise e
    else:
        signals.request_finished.send(sender=task_id)
