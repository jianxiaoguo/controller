import json
import logging
from django.conf import settings
from django.db import models
from api import influxdb
from api.models.release import Release
from api.models import UuidAuditedModel
from api.utils import unit_to_bytes, unit_to_millicpu
from api.exceptions import DryccException, UnprocessableEntity


logger = logging.getLogger(__name__)


class Config(UuidAuditedModel):
    """
    Set of configuration values applied as environment variables
    during runtime execution of the Application.
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    app = models.ForeignKey('App', on_delete=models.CASCADE)
    values = models.JSONField(default=dict, blank=True)
    memory = models.JSONField(default=dict, blank=True)
    lifecycle_post_start = models.JSONField(default=dict, blank=True)
    lifecycle_pre_stop = models.JSONField(default=dict, blank=True)
    cpu = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(default=dict, blank=True)
    registry = models.JSONField(default=dict, blank=True)
    healthcheck = models.JSONField(default=dict, blank=True)
    termination_grace_period = models.JSONField(default=dict, blank=True)

    class Meta:
        get_latest_by = 'created'
        ordering = ['-created']
        unique_together = (('app', 'uuid'),)

    def __str__(self):
        return "{}-{}".format(self.app.id, str(self.uuid)[:7])

    def _migrate_legacy_healthcheck(self):
        """
        Get all healthchecks options together for use in scheduler
        """
        # return if no legacy healthcheck is found
        if 'HEALTHCHECK_URL' not in self.values.keys():
            return

        path = self.values.get('HEALTHCHECK_URL', '/')
        timeout = int(self.values.get('HEALTHCHECK_TIMEOUT', 50))
        delay = int(self.values.get('HEALTHCHECK_INITIAL_DELAY', 50))
        period_seconds = int(self.values.get('HEALTHCHECK_PERIOD_SECONDS', 10))
        success_threshold = int(self.values.get('HEALTHCHECK_SUCCESS_THRESHOLD', 1))
        failure_threshold = int(self.values.get('HEALTHCHECK_FAILURE_THRESHOLD', 3))

        self.healthcheck['web/cmd'] = {}
        self.healthcheck['web/cmd']['livenessProbe'] = {
            'initialDelaySeconds': delay,
            'timeoutSeconds': timeout,
            'periodSeconds': period_seconds,
            'successThreshold': success_threshold,
            'failureThreshold': failure_threshold,
            'httpGet': {
                'path': path,
            }
        }

        self.healthcheck['web/cmd']['readinessProbe'] = {
            'initialDelaySeconds': delay,
            'timeoutSeconds': timeout,
            'periodSeconds': period_seconds,
            'successThreshold': success_threshold,
            'failureThreshold': failure_threshold,
            'httpGet': {
                'path': path,
            }
        }

        # Unset all the old values
        self.values = {k: v for k, v in self.values.items() if not k.startswith('HEALTHCHECK_')}

    def get_healthcheck(self):
        if('livenessProbe' in self.healthcheck.keys() or
           'readinessProbe' in self.healthcheck.keys()):
            return {'web/cmd': self.healthcheck}
        return self.healthcheck

    def set_registry(self):
        # lower case all registry options for consistency
        self.registry = {key.lower(): value for key, value in self.registry.copy().items()}

        # PORT must be set if private registry is being used
        if self.registry and self.values.get('PORT', None) is None:
            # only thing that can get past post_save in the views
            raise DryccException(
                'PORT needs to be set in the config '
                'when using a private registry')

    def set_tags(self, previous_config):
        """verify the tags exist on any nodes as labels"""
        if not self.tags:
            if settings.DRYCC_DEFAULT_CONFIG_TAGS:
                try:
                    tags = json.loads(settings.DRYCC_DEFAULT_CONFIG_TAGS)
                    self.tags = tags
                except json.JSONDecodeError as e:
                    logger.exception(e)
                    return
            else:
                return

        # Get all nodes with label selectors
        nodes = self._scheduler.node.get(labels=self.tags).json()
        if nodes['items']:
            return

        labels = ['{}={}'.format(key, value) for key, value in self.tags.items()]
        message = 'No nodes matched the provided labels: {}'.format(', '.join(labels))

        # Find out if there are any other tags around
        old_tags = getattr(previous_config, 'tags')
        if old_tags:
            old = ['{}={}'.format(key, value) for key, value in old_tags.items()]
            new = set(labels) - set(old)
            if new:
                message += ' - Addition of {} is the cause'.format(', '.join(new))

        raise DryccException(message)

    def set_healthcheck(self, previous_config):
        data = getattr(previous_config, 'healthcheck', {}).copy()
        new_data = getattr(self, 'healthcheck', {}).copy()
        # update the config data for healthcheck if they are not
        # present for per proctype
        # TODO: This is required for backward compatibility and can be
        # removed in next major version change.
        if 'livenessProbe' in data.keys() or 'readinessProbe' in data.keys():
            data = {'web/cmd': data.copy()}
        if 'livenessProbe' in new_data.keys() or 'readinessProbe' in new_data.keys():  # noqa
            new_data = {'web/cmd': new_data.copy()}

        # remove config keys if a null value is provided
        for key, value in new_data.items():
            if value is None:
                # error if unsetting non-existing key
                if key not in data:
                    raise UnprocessableEntity('{} does not exist under {}'.format(key, 'healthcheck'))  # noqa
                data.pop(key)
            else:
                for probeType, probe in value.items():
                    if probe is None:
                        # error if unsetting non-existing key
                        if key not in data or probeType not in data[key].keys():
                            raise UnprocessableEntity('{} does not exist under {}'.format(key, 'healthcheck'))  # noqa
                        data[key].pop(probeType)
                    else:
                        if key not in data:
                            data[key] = {}
                        data[key][probeType] = probe
        setattr(self, 'healthcheck', data)

    def save(self, **kwargs):
        """merge the old config with the new"""
        try:
            # Get config from the latest available release
            try:
                previous_config = self.app.release_set.filter(failed=False).latest().config
            except Release.DoesNotExist:
                # If that doesn't exist then fallback on app config
                # usually means a totally new app
                previous_config = self.app.config_set.latest()

            for attr in ['cpu', 'memory', 'tags', 'registry', 'values',
                         'lifecycle_post_start', 'lifecycle_pre_stop',
                         'termination_grace_period']:
                data = getattr(previous_config, attr, {}).copy()
                new_data = getattr(self, attr, {}).copy()

                # remove config keys if a null value is provided
                for key, value in new_data.items():
                    if value is None:
                        # error if unsetting non-existing key
                        if key not in data:
                            raise UnprocessableEntity('{} does not exist under {}'.format(key, attr))  # noqa
                        data.pop(key)
                    else:
                        data[key] = value
                setattr(self, attr, data)
            self.set_healthcheck(previous_config)
            self._migrate_legacy_healthcheck()
            self.set_registry()
            self.set_tags(previous_config)
        except Config.DoesNotExist:
            self.set_tags({'tags': {}})

        return super(Config, self).save(**kwargs)

    def to_measurements(self, timestamp: float):
        assert len(set(self.memory.keys()).difference(self.cpu.keys())) == 0
        stop = int(timestamp)
        start = stop - (stop % 3600)
        records = {}
        app_id, owner_id = str(self.app_id), str(self.owner_id)
        for record in influxdb.query_container_count([app_id, ], start, stop):
            container_type = record["container_name"].replace(f"{app_id}-", "", 1)
            if container_type not in records:
                records[container_type] = []
            records[container_type].append(record)
        cpu_measurements = [{
            "app_id": app_id,
            "user_id": owner_id,
            "name": container_type,
            "type": "CPU",
            "unit": "MILLI",
            "usage": unit_to_millicpu(
                self.cpu.get(container_type)) * len(records.get(container_type, [])),
            "timestamp": "%f" % timestamp
        } for container_type in self.cpu.keys()]
        memory_measurements = [{
            "app_id": app_id,
            "user_id": owner_id,
            "name": container_type,
            "type": "MEMORY",
            "unit": "BYTES",
            "usage": unit_to_bytes(
                self.memory.get(container_type)) * len(records.get(container_type, [])),
            "timestamp": "%f" % timestamp
        } for container_type in self.memory.keys()]
        return cpu_measurements + memory_measurements
