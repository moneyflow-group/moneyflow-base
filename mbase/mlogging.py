import structlog
from django.conf import settings


def mf_get_logger(name):
    if name is None:
        name = "mlog"
    module_name = name.split(".")[0]
    return structlog.get_logger(f"{settings.SYSTEM_NAME}.{module_name}")
    # return structlog.get_logger(f"{module_name}")
