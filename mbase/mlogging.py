import structlog
# from django.conf import settings


def mf_get_logger(name):
    if name is None:
        name = "mlog"
    module_name = name.split(".")[0]
    # return structlog.get_logger(f"{settings.SYSTEM_NAME}.{module_name}")
    return structlog.get_logger(f"{module_name}")


def trace_logging(*included_safe_kwargs):
    """
    Usage: Decorate your function with
     @trace_logging("is_payer", "amount")

    Automatically included are safelisted arguments and arguments ending in _id and _crn
    """

    def decorator(function):
        logger = mf_get_logger(f"{function.__module__}")

        @wraps(function)
        def wrapper(*args, **kwargs):
            logger.debug(f"{function.__name__}:begin", **_safe_trace_kwargs(kwargs, included_safe_kwargs))
            result = function(*args, **kwargs)
            logger.debug(f"{function.__name__}:done", **_safe_trace_kwargs(kwargs, included_safe_kwargs))
            return result

        return wrapper

    return decorator


