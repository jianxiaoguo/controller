"""
Helper functions used by the Drycc server.
"""
import os
import re
import uuid
import time
import base64
import string
import concurrent
import hashlib
import logging
import random
import math
import pkgutil
import inspect
import requests
import importlib
import jsonschema
from copy import deepcopy
from django.db import models
from django.conf import settings
from django.core.cache import cache
from asgiref.sync import sync_to_async
from requests_toolbelt import user_agent
from api import __version__ as drycc_version
from rest_framework.exceptions import ValidationError


logger = logging.getLogger(__name__)


session = None


def get_session():
    global session
    if session is None:
        session = requests.Session()
        session.headers = {
            # https://toolbelt.readthedocs.org/en/latest/user-agent.html#user-agent-constructor
            'User-Agent': user_agent('Drycc Controller', drycc_version),
        }
        # `mount` a custom adapter that retries failed connections for HTTP and HTTPS requests.
        # http://docs.python-requests.org/en/latest/api/#requests.adapters.HTTPAdapter
        session.mount('http://', requests.adapters.HTTPAdapter(max_retries=10))
        session.mount('https://', requests.adapters.HTTPAdapter(max_retries=10))
    return session


def get_scheduler(metadata=None):
    mod = importlib.import_module(settings.SCHEDULER_MODULE)
    metadata = metadata if metadata is not None else {}
    metadata = dict_merge(metadata, {"annotations": {"app.kubernetes.io/managed-by": "drycc"}})
    return mod.SchedulerClient(settings.SCHEDULER_URL, settings.K8S_API_VERIFY_TLS, metadata)


def import_all_models():
    for _, modname, ispkg in pkgutil.iter_modules([
        os.path.join(os.path.dirname(__file__), "models")
    ]):
        if not ispkg:
            mod = __import__(f"api.models.{modname}")
            for subname in dir(mod):
                attr = getattr(mod, subname)
                if inspect.isclass(attr) and issubclass(attr, models.Model):
                    globals()[subname] = attr


def validate_label(value):
    """
    Check that the value follows the kubernetes name constraints
    http://kubernetes.io/v1.1/docs/design/identifiers.html
    """
    match = re.match(r'^[a-z0-9-]+$', value)
    if not match:
        raise ValidationError("Can only contain a-z (lowercase), 0-9 and hyphens")
    validate_reserved_names(value)


def validate_reserved_names(value):
    """A value cannot use some reserved names."""
    for reserved_name_pattern in settings.RESERVED_NAME_PATTERNS:
        if re.match(reserved_name_pattern, value):
            raise ValidationError('{} is a reserved name.'.format(value))


def random_string(num):
    return ''.join(
        [random.choice(string.ascii_lowercase) for i in range(num)])


def generate_app_name():
    """Return a randomly-generated memorable name."""
    return "{}-{}".format(random_string(6), random_string(8))


def dict_diff(dict1, dict2):
    """
    Returns the added, changed, and deleted items in dict1 compared with dict2.

    :param dict1: a python dict
    :param dict2: an earlier version of the same python dict
    :return: a new dict, with 'added', 'changed', and 'removed' items if
             any were found.

    >>> d1 = {1: 'a'}
    >>> dict_diff(d1, d1)
    {}
    >>> d2 = {1: 'a', 2: 'b'}
    >>> dict_diff(d2, d1)
    {'added': {2: 'b'}}
    >>> d3 = {2: 'B', 3: 'c'}
    >>> expected = {'added': {3: 'c'}, 'changed': {2: 'B'}, 'deleted': {1: 'a'}}
    >>> dict_diff(d3, d2) == expected
    True
    """
    diff = {}
    set1, set2 = set(dict1), set(dict2)
    # Find items that were added to dict2
    diff['added'] = {k: dict1[k] for k in (set1 - set2)}
    # Find common items whose values differ between dict1 and dict2
    diff['changed'] = {
        k: dict1[k] for k in (set1 & set2) if dict1[k] != dict2[k]
    }
    # Find items that were deleted from dict2
    diff['deleted'] = {k: dict2[k] for k in (set2 - set1)}
    return {k: diff[k] for k in diff if diff[k]}


def fingerprint(key):
    """
    Return the fingerprint for an SSH Public Key
    """
    key = base64.b64decode(key.strip().split()[1].encode('ascii'))
    fp_plain = hashlib.md5(key).hexdigest()
    return ':'.join(a + b for a, b in zip(fp_plain[::2], fp_plain[1::2]))


def dict_merge(origin, merge):
    """
    Recursively merges dict's. not just simple a["key"] = b["key"], if
    both a and b have a key who's value is a dict then dict_merge is called
    on both values and the result stored in the returned dictionary.
    Also handles merging lists if they occur within the dict
    """
    if not isinstance(merge, dict):
        return merge

    result = deepcopy(origin)
    for key, value in merge.items():
        if key in result and isinstance(result[key], dict):
            result[key] = dict_merge(result[key], value)
        else:
            if isinstance(value, list):
                if key not in result:
                    result[key] = value
                else:
                    # merge lists without leaving potential duplicates
                    # result[key] = list(set(result[key] + value))  # changes the order as well
                    for item in value:
                        if item in result[key]:
                            continue

                        result[key].append(item)
            else:
                result[key] = deepcopy(value)
    return result


def apply_tasks(tasks):
    """
    run a group of tasks async
    Requires the tasks arg to be a list of functools.partial()
    """
    if not tasks:
        return

    executor = concurrent.futures.ThreadPoolExecutor(settings.DRYCC_APPLY_TASKS)
    for future, callback in [(executor.submit(task[0]), task[1]) for task in tasks]:
        future.add_done_callback(callback)
        error = future.exception()
        if error is not None:
            raise error
    executor.shutdown(wait=True)


def unit_to_bytes(size):
    """
    size: str
    where unit in K, M, G, T convert to B
    """
    if size[-2:-1].isalpha() and size[-1].isalpha():
        size = size[:-1]
    if size[-1].isalpha():
        size = size.upper()
    _ = float(size[:-1])
    if size[-1] == 'K':
        _ *= math.pow(1024, 1)
    elif size[-1] == 'M':
        _ *= math.pow(1024, 2)
    elif size[-1] == 'G':
        _ *= math.pow(1024, 3)
    elif size[-1] == 'G':
        _ *= math.pow(1024, 3)
    elif size[-1] == 'T':
        _ *= math.pow(1024, 4)
    elif size[-1] == 'P':
        _ *= math.pow(1024, 5)
    return round(_)


def validate_json(value, schema, raise_exception=jsonschema.ValidationError):
    if value is not None:
        try:
            jsonschema.validate(value, schema)
        except jsonschema.ValidationError as e:
            raise raise_exception("could not validate {}: {}".format(value, e.message))
    return value


class CacheLock(object):

    def __init__(self, key):
        self.key = key
        self.value = uuid.uuid4().hex

    def acquire(self, blocking=True, timeout=120):
        value = None
        for _ in range(timeout):
            value = cache.get_or_set(self.key, self.value, timeout)
            if not blocking or value == self.value:
                break
            time.sleep(1)
        return value == self.value

    def release(self):
        value = cache.get(self.key, None)
        if value != self.value:
            return
        cache.delete(self.key)


class DeployLock(CacheLock):

    def __init__(self, app_id):
        self.ptypes_key = f"app:deploy:procfile:types:{app_id}"
        super(DeployLock, self).__init__(f"app:deploy:lock:{app_id}")

    def locked(self, ptypes):
        value = cache.get(self.ptypes_key, [])
        locked_ptypes = []
        for ptype in ptypes:
            if ptype in value:
                locked_ptypes.append(ptype)
        return locked_ptypes

    def acquire(self, ptypes, force=False):
        try:
            if super(DeployLock, self).acquire():
                value = cache.get(self.ptypes_key, [])
                if not force and len(self.locked(ptypes)) > 0:
                    return False
                value.extend(ptypes)
                value = list(set(value))
                cache.set(self.ptypes_key, value, timeout=3600)
                return True
        finally:
            super(DeployLock, self).release()
        return False

    def release(self, ptypes):
        try:
            if super(DeployLock, self).acquire():
                value = cache.get(self.ptypes_key, [])
                if value is None:
                    return
                for ptype in ptypes:
                    if ptype in value:
                        value.remove(ptype)
                cache.set(self.ptypes_key, value)
        finally:
            super(DeployLock, self).release()


class SyncIterToAsyncIter(object):

    def __init__(self, iter_content):
        self.iter_content = iter_content

    def __aiter__(self):
        return self

    async def __anext__(self):
        @sync_to_async
        def async_next():
            try:
                return next(self.iter_content)
            except StopIteration:
                raise StopAsyncIteration
        return await async_next()


iter_to_aiter = SyncIterToAsyncIter


if __name__ == "__main__":
    import doctest
    doctest.testmod()
