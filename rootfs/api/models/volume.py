import logging
from django.db import models, transaction
from django.conf import settings
from jsonfield import JSONField
from api.utils import unit_to_bytes
from api.exceptions import DryccException, ServiceUnavailable, AlreadyExists
from api.models import UuidAuditedModel, validate_label
from scheduler import KubeException

logger = logging.getLogger(__name__)


class Volume(UuidAuditedModel):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL,
                              on_delete=models.PROTECT)
    app = models.ForeignKey('App', on_delete=models.CASCADE)
    name = models.CharField(max_length=63, validators=[validate_label])
    size = models.CharField(max_length=128)
    path = JSONField(default={}, blank=True)

    class Meta:
        get_latest_by = 'created'
        unique_together = (('app', 'name'),)
        ordering = ['-created']

    def __str__(self):
        return self.name

    @transaction.atomic
    def save(self, *args, **kwargs):
        # Attach volume, updates k8s
        if self.created == self.updated:
            self.attach()
        # Save to DB
        return super(Volume, self).save(*args, **kwargs)

    @transaction.atomic
    def delete(self, *args, **kwargs):
        if self.path:
            raise DryccException("the volume is not unmounted")
        # Deatch volume, updates k8s
        self.detach()
        # Delete from DB
        return super(Volume, self).delete(*args, **kwargs)

    @staticmethod
    def _get_size(size):
        """ Format volume limit value """
        if size[-2:-1].isalpha() and size[-1].isalpha():
            size = size[:-1]

        if size[-1].isalpha():
            size = size.upper() + "i"
        return size

    def attach(self):
        try:
            self._scheduler.pvc.get(self.app.id, self.name)
            err = "Volume {} already exists in this namespace".format(self.name)  # noqa
            self.log(err, logging.INFO)
            raise AlreadyExists(err)
        except KubeException as e:
            logger.info(e)
            try:
                kwargs = {
                    "size": self._get_size(self.size),
                    "storage_class": settings.DRYCC_APP_STORAGE_CLASS,
                }
                self._scheduler.pvc.create(self.app.id, self.name, **kwargs)
            except KubeException as e:
                msg = 'There was a problem creating the volume ' \
                      '{} for {}'.format(self.name, self.app_id)
                raise ServiceUnavailable(msg) from e

    def detach(self):
        try:
            # We raise an exception when a volume doesn't exist
            self._scheduler.pvc.get(self.app.id, self.name)
            self._scheduler.pvc.delete(self.app.id, self.name)
        except KubeException as e:
            raise ServiceUnavailable("Could not delete volume {} for application \
                {}".format(self.name, self.app_id)) from e  # noqa

    def log(self, message, level=logging.INFO):
        """Logs a message in the context of this service.

        This prefixes log messages with an application "tag" that the customized
        drycc-logspout will be on the lookout for.  When it's seen, the message-- usually
        an application event of some sort like releasing or scaling, will be considered
        as "belonging" to the application instead of the controller and will be handled
        accordingly.
        """
        logger.log(level, "[{}]: {}".format(self.id, message))

    def to_measurements(self, timestamp: float):
        return [{
            "name": self.name,
            "app_id": str(self.app_id),
            "owner_id": str(self.owner_id),
            "size": unit_to_bytes(self.size),
            "timestamp": "%f" % timestamp
        }]
