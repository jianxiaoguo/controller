import logging
import string
import copy
import json
import uuid
from django.db import models, transaction
from django.conf import settings
from django.contrib.auth import get_user_model
from api.utils import unit_to_bytes, validate_label
from api.exceptions import DryccException, ServiceUnavailable, AlreadyExists
from scheduler import KubeException
from .base import UuidAuditedModel

User = get_user_model()
logger = logging.getLogger(__name__)


class Volume(UuidAuditedModel):
    TYPE_CHOICES = (
        ("csi", "container storage interface"),
        ("nfs", "network file system"),
        ("oss", "object storage service file"),
    )
    owner = models.ForeignKey(User, on_delete=models.PROTECT)
    app = models.ForeignKey('App', on_delete=models.CASCADE)
    name = models.CharField(max_length=63, validators=[validate_label])
    size = models.CharField(default='0G', max_length=128)
    path = models.JSONField(default=dict)
    type = models.CharField(default=TYPE_CHOICES[0][0], choices=TYPE_CHOICES)
    readonly = models.BooleanField(default=False)
    parameters = models.JSONField(default=dict)

    @property
    def pv_name(self):
        return f"{self.app.id}:{self.type}:{self.name}"

    @property
    def access_mode(self):
        return "ReadOnlyMany" if self.readonly else "ReadWriteMany"

    @transaction.atomic
    def save(self, *args, **kwargs):
        if self.type not in settings.DRYCC_VOLUME_CLAIM_TEMPLATE:
            raise DryccException('Volume type %s is not supported.')
        # Attach volume, updates k8s
        if self.created == self.updated:
            if self.type in settings.DRYCC_VOLUME_TEMPLATE:
                self._create_pv()
            self._create_pvc()
        # check path
        self.check_path()
        # Save to DB
        return super(Volume, self).save(*args, **kwargs)

    @transaction.atomic
    def delete(self, *args, **kwargs):
        # Deatch volume, updates k8s
        if self.type in settings.DRYCC_VOLUME_TEMPLATE:
            self._delete_pv()
        self._delete_pvc()
        # Delete from DB
        return super(Volume, self).delete(*args, **kwargs)

    @transaction.atomic
    def expand(self, size):
        if self.type == "csi":
            if unit_to_bytes(size) < unit_to_bytes(self.size):
                raise DryccException('Shrink volume is not supported.')
            self.size = size
            self.save()
            try:
                kwargs = {
                    "size": self._format_size(self.size),
                    "storage_class": settings.DRYCC_APP_STORAGE_CLASS,
                }
                self.scheduler().pvc.patch(self.app.id, self.name, **kwargs)
            except KubeException as e:
                msg = 'There was a problem expand the volume ' \
                        '{} for {}'.format(self.name, self.app_id)
                raise ServiceUnavailable(msg) from e
        else:
            raise DryccException(f'{self.type} volume is not support expand.')

    def log(self, message, level=logging.INFO):
        """Logs a message in the context of this service.

        This prefixes log messages with an application "tag" that the customized
        drycc-logspout will be on the lookout for.  When it's seen, the message-- usually
        an application event of some sort like releasing or scaling, will be considered
        as "belonging" to the application instead of the controller and will be handled
        accordingly.
        """
        logger.log(level, "[{}]: {}".format(self.app.id, message))

    def to_measurements(self, timestamp: float):
        return [{
            "app_id": str(self.app_id),
            "owner": self.owner_id,
            "name": self.type,
            "type": "volume",
            "unit": "bytes",
            "usage": unit_to_bytes(self.size),
            "kwargs": {
                "name": self.name,
            },
            "timestamp": int(timestamp)
        }]

    def __str__(self):
        return self.name

    @staticmethod
    def _format_size(size):
        """ Format volume limit value """
        if size[-2:-1].isalpha() and size[-1].isalpha():
            size = size[:-1]

        if size[-1].isalpha():
            size = size.upper() + "i"
        return size

    def check_path(self, path=None):
        other_volumes = self.app.volume_set.exclude(name=self.name)
        type_paths = {}  # {'type1':[path1,path2], tyep2:[path3,path4]}
        for _ in other_volumes:
            for k, v in _.path.items():
                if k not in type_paths:
                    type_paths[k] = [v]
                else:
                    type_paths[k].append(v)
        items = path.items() if path else self.path.items()
        repeat_path = [v for k, v in items if v in type_paths.get(k, [])]
        if repeat_path:
            msg = "path {} is used by another volume".format(','.join(repeat_path))
            self.log(msg, logging.ERROR)
            raise DryccException(msg)

    def _create_pv(self):
        try:
            self.scheduler().pv.get(self.pv_name)
            err = "Volume {} already exists".format(self.pv_name)
            self.log(err, logging.INFO)
            raise AlreadyExists(err)
        except KubeException as e:
            logger.info(e)
            try:
                kwds = copy.deepcopy(self.parameters)
                kwds.update({
                    "volume_claim_name": self.name,
                    "namespace": self.app,
                    "access_mode": self.access_mode,
                    "volume_handle": "%s" % uuid.uuid4(),
                })
                t = string.Template(json.dumps(settings.DRYCC_VOLUME_TEMPLATE.get(self.type)))
                self.scheduler().pv.create(
                    self.app.id, self.pv_name, **json.loads(t.safe_substitute(**kwds)))
            except KubeException as e:
                msg = 'There was a problem creating the volume ' \
                      '{} for {}'.format(self.pv_name, self.app_id)
                raise ServiceUnavailable(msg) from e

    def _create_pvc(self):
        try:
            self.scheduler().pvc.get(self.app.id, self.name)
            err = "Volume claim {} already exists in this namespace".format(self.name)
            self.log(err, logging.INFO)
            raise AlreadyExists(err)
        except KubeException as e:
            logger.info(e)
            try:
                kwds = copy.deepcopy(self.parameters)
                kwds.update({
                    "size": self._format_size(self.size),
                    "volume_name": self.pv_name,
                    "access_mode": self.access_mode,
                    "storage_class": settings.DRYCC_APP_STORAGE_CLASS,
                })
                t = string.Template(
                    json.dumps(settings.DRYCC_VOLUME_CLAIM_TEMPLATE.get(self.type)))
                self.scheduler().pvc.create(
                    self.app.id, self.name, **json.loads(t.safe_substitute(**kwds)))
            except KubeException as e:
                msg = 'There was a problem creating the volume claim ' \
                      '{} for {}'.format(self.name, self.app_id)
                raise ServiceUnavailable(msg) from e

    def _delete_pv(self):
        try:
            # We raise an exception when a volume doesn't exist
            self.scheduler().pv.get(self.pv_name)
            self.scheduler().pv.delete(self.pv_name)
        except KubeException as e:
            raise ServiceUnavailable("Could not delete volume {} for application \
                {}".format(self.name, self.app_id)) from e  # noqa

    def _delete_pvc(self):
        try:
            # We raise an exception when a volume doesn't exist
            self.scheduler().pvc.get(self.app.id, self.name)
            self.scheduler().pvc.delete(self.app.id, self.name)
        except KubeException as e:
            raise ServiceUnavailable("Could not delete volume {} for application \
                {}".format(self.name, self.app_id)) from e  # noqa

    class Meta:
        get_latest_by = 'created'
        unique_together = (('app', 'name'),)
        ordering = ['-created']
