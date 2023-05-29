import inspect
import pickle
import re
import sys
import time
import traceback
import uuid
from collections import namedtuple
from functools import wraps

import dramatiq
import periodiq
from django.conf import settings
from django.db import models
from dramatiq import RateLimitExceeded as DramatiqRateLimitExceeded
from dramatiq import Retry as DramatiqRetry
from dramatiq import pipeline as dramatiq_pipeline
from dramatiq.brokers.stub import StubBroker
from dramatiq.errors import Retry
from dramatiq.middleware import Middleware, Prometheus
from dramatiq.rate_limits.backends import RedisBackend
from dramatiq.rate_limits.backends.stub import StubBackend as RateStubBackend
from dramatiq.results import Results
from dramatiq.results.backends import StubBackend as ResultsStubBackend
from mbase.exceptions import BaseException as _BaseException
from mbase.utils import utcnow
from mbase.logging import mf_get_logger

logger = mf_get_logger(__name__)

is_pytest = "pytest" in sys.argv[0]


if is_pytest:
    DEFAULT_WAIT = 5_000  # Timeout in milliseconds
    actor_defaults = settings.DRAMATIQ_ACTOR_DEFAULTS
    actor_defaults["min_backoff"] = 100
    _broker = dramatiq.get_broker()
    _broker.flush_all()
    _broker.close()
    del _broker

    broker = StubBroker()
    broker.emit_after("process_boot")

    rate_backend = RateStubBackend()
    result_backend = ResultsStubBackend()
    broker.add_middleware(Results(backend=result_backend))
    broker.add_middleware(periodiq.PeriodiqMiddleware())
    broker.add_middleware(dramatiq.middleware.AgeLimit())
    broker.add_middleware(dramatiq.middleware.TimeLimit())
    broker.add_middleware(dramatiq.middleware.Callbacks())
    # FutureRetriesMiddleware is added at the bottom of this file

    dramatiq.set_broker(broker)
else:
    DEFAULT_WAIT = 30_000  # Timeout in milliseconds
    actor_defaults = settings.DRAMATIQ_ACTOR_DEFAULTS

    broker = dramatiq.get_broker()
    # FutureRetriesMiddleware is added at the bottom of this file
    rate_backend = RedisBackend(url=settings.DRAMATIQ_REDIS_URL)

    for m in broker.middleware:
        if isinstance(m, dramatiq.results.middleware.Results):
            result_backend = m.backend
            break
    else:
        raise Exception("Couldn't locate backend middleware!")


class FutureException(_BaseException):
    pass


class FutureCapturedException(FutureException):
    pass


class FutureRetry(FutureException):
    def __init__(self, *args, delay=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.delay = delay


class FutureRetryRateLimiter(FutureRetry):
    pass


class FutureTimeout(FutureException):
    pass


class FutureExpired(FutureException):
    pass


class FutureNotReady(FutureRetry):
    pass


class FutureError(FutureException):
    pass


def wait_multiple(*args, timeout=DEFAULT_WAIT):
    assert all(
        map(lambda x: isinstance(x, Future), args)
    ), f"Only arguments of type Future is supported. Got: {list(map(type, args))}"

    return [f.wait(timeout=timeout) for f in args]


def future_chain(*future_preps):
    """
    Creates a series of tasks, where all intermediate results are discarded.
    """
    for p in future_preps:
        if not isinstance(p, FuturePrepped):
            raise FutureException("Not all supplied futures for chain were prepped")
    pipeline = dramatiq_pipeline(
        [
            p.func.message_with_options(args=p.args, kwargs=p.kwargs, pipe_ignore=True, **p.options)
            for p in future_preps
        ]
    ).run()
    future = Future(func=pipeline, _message_type=Future.DRAMATIQ_PIPELINE)
    future.save()
    return future


_queue_name_re = re.compile(r"[a-zA-Z_][a-zA-Z0-9._-]*")


def dramatiq_backoff(retries, options, jitter=True):
    _, backoff_delay = dramatiq.common.compute_backoff(
        retries, factor=options["min_backoff"], max_backoff=options["max_backoff"], jitter=jitter,
    )  # Steal Dramatiqs way of calculating backoff delays.
    return backoff_delay


def future(
    fn=None,
    *,
    persistent=False,
    retries_from_minutes=None,
    queue_name=settings.FUTURE_QUEUE_DEFAULT,
    priority=settings.FUTURE_PRIORITY_DEFAULT,
    **options,
):
    """
    Modded version of dramatiq.actor decorator
    """

    for k, v in actor_defaults.items():
        if k not in options:
            options[k] = v

    if retries_from_minutes:
        max_retries = 0
        acc_time = 0
        while acc_time < retries_from_minutes * 60 * 1000:
            acc_time += dramatiq_backoff(max_retries, jitter=False, options=options)
            max_retries += 1
        options["max_retries"] = max_retries

    def decorator(func):
        @wraps(func)
        def fn(*args, **kwargs):
            try:
                return ("Ok", func(*args, **kwargs))
            except FutureRetry:
                raise
            except DramatiqRetry as ex:
                raise FutureRetry(f"Raising FutureRetry. {ex.__class__.__name__}: {ex}")
            except DramatiqRateLimitExceeded as ex:
                raise FutureRetryRateLimiter(f"Raising FutureRetryRateLimiter. {ex.__class__.__name__}: {ex}")
            except Exception as ex:
                tb = traceback.format_exc()
                logger.error(f"Error in Future: {ex}, {tb}", exc_info=True)
                return ("Error", (ex, tb))

        if not _queue_name_re.fullmatch(queue_name):
            raise ValueError(
                "Queue names must start with a letter or an underscore followed "
                "by any number of letters, digits, dashes or underscores."
            )

        invalid_options = set(options) - broker.actor_options
        if invalid_options:
            invalid_options_list = ", ".join(invalid_options)
            raise ValueError(
                (
                    "The following actor options are undefined: %s. "
                    "Did you forget to add a middleware to your Broker?"
                )
                % invalid_options_list
            )

        return dramatiq.Actor(
            fn, actor_name=fn.__name__, queue_name=queue_name, priority=priority, broker=broker, options=options,
        )

    if fn is None:
        return lambda fn: FutureWrapper(decorator(fn), persistent, options)
    return FutureWrapper(decorator(fn), persistent, options)


def unpack_result_tuple(result_tuple, message_type=None, do_raise=True):
    if message_type == Future.CELERY_TASK:
        # Old Celery format
        return result_tuple

    ret_code, ret_val = result_tuple
    if ret_code == "Ok":
        return ret_val
    elif ret_code == "Error":
        if do_raise:
            if isinstance(ret_val, tuple):
                # Support new errors with traceback data
                ret_val, _tb = ret_val
            raise ret_val
        else:
            return ret_val
    else:
        raise FutureException(f"Illegal format for return code: {ret_code}")


FuturePrepped = namedtuple("FuturePrepped", "func args kwargs options")


class FutureWrapper:
    def __init__(self, func, persistent, options):
        self._func = func
        self._persistent = persistent
        self._obj = None
        self.options = options

    def __get__(self, obj, type=None):
        # Python doesn't supply the instance object when calling a decorated method.
        # We circumvent this, by changing the __get__ to record the instance, as Python will always call this method
        # before getting an instance attribute -- in this case a method.
        # For example:
        # >>> a = A()
        # >>> a.b()
        # Will behind the scene do this:
        # c = A.__get__(a)
        # A.b(c)

        self._obj = obj
        return self

    def __call__(self, *args, **kwargs):
        # Running synchronuously

        # Simulate retry behavior of Dramatiq
        max_retries = self.options.get("max_retries", -1)
        max_age = self.options.get("max_age", None)
        t0 = time.time()
        retries = 0
        while True:
            raised_exception = None
            try:
                if self._obj is None:
                    # If the object has not been captured in __get__, it is not an instance method,
                    # and we just call it.
                    return unpack_result_tuple(self._func(*args, **kwargs))
                else:
                    # If the object _has_ been captured in __get__, it _is_ an instance method, and
                    # we add self.obj to the call
                    return unpack_result_tuple(self._func(self._obj, *args, **kwargs))
            except (FutureRetry, FutureRetryRateLimiter, DramatiqRateLimitExceeded, DramatiqRetry) as ex:
                backoff_delay = dramatiq_backoff(retries, options=self.options)
                logger.debug(f"Future retrying: {retries}", func=self._func, backoff_delay=backoff_delay)
                time.sleep(backoff_delay / 1000)
                raised_exception = ex

            t1 = time.time()
            if max_age is not None and ((t1 - t0) * 1000) > max_age:
                raise FutureExpired(
                    "Result couldn't be produced within max_age constraints.", inner_exception=raised_exception
                )
            if max_retries is not None and max_retries - retries == 0:
                raise FutureExpired(
                    "Result couldn't be produced within max_retries constraints.", inner_exception=raised_exception
                )
            retries += 1

        raise FutureError("Call-loop escaped without exception!")

    def prep(self, *args, **kwargs):
        """
        Used to prepare the arguments for the future. Useful for chain, group, pipeline
        """
        if self._obj is not None:
            args = [self._obj] + list(args)
        return FuturePrepped(self._func, args, kwargs, self.options)

    def send(self, *args, **kwargs):
        # Deploying to Dramatiq
        if not self._persistent:
            delay = kwargs.pop("_future_task_delay", None)
            logger.debug("Non persistent future", func=self._func, args=args)
            if self._obj is None:
                return self._func.send_with_options(args=args, delay=delay, kwargs=kwargs)
            args = [self._obj] + list(args)
            return self._func.send_with_options(args=args, delay=delay, kwargs=kwargs)

        future = Future.objects.create(func=self._func, _message_type=Future.DRAMATIQ_TASK)
        if self._obj is None:
            # If the object has not been captured in __get__, it is not an instance method, and we just send it.
            future.send(*args, **kwargs)
        else:
            # If the object _has_ been captured in __get__, it _is_ an instance method, and we add self.obj to the send
            future.send(self._obj, *args, **kwargs)
        future.save()
        return future


class Future(models.Model):  # design-checker: skip
    """
    This class provides a wrapper around every request made through the connection manager system.
    """

    id = models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True)
    celery_id = models.UUIDField(null=True)
    serialized_message = models.BinaryField(null=True)

    CELERY_TASK = "CELERY_TASK"
    DRAMATIQ_TASK = "DRAMATIQ_TASK"
    DRAMATIQ_PIPELINE = "DRAMATIQ_PIPELINE"
    MESSAGE_TYPES = (
        (CELERY_TASK, "Celery Task"),
        (DRAMATIQ_TASK, "Dramatiq Task"),
        (DRAMATIQ_PIPELINE, "Dramatiq Pipeline"),
    )
    _message_type = models.CharField(null=True, max_length=255, choices=MESSAGE_TYPES, default=DRAMATIQ_TASK)
    _value = models.BinaryField(null=True)
    traceback = models.TextField(null=True)
    start_time = models.DateTimeField(default=utcnow, db_index=True)  # We sort by start_time in Django admin
    end_time = models.DateTimeField(null=True)
    # Just for debugging
    caller = models.TextField(null=True)
    func_args = models.TextField(null=True)
    func_kwargs = models.TextField(null=True)

    def __init__(self, *args, func=None, **kwargs):
        super().__init__(*args, **kwargs)

        self._func = func
        self._message = None

        if self.done:
            # We already ran the function. The object is being loaded from the database
            pass
        self._deserialize_message()

    def _deserialize_message(self):
        if self.serialized_message is None:
            return

        # Reopening previous Future session
        if self._message_type == self.DRAMATIQ_PIPELINE:
            reconstructed_pipeline = dramatiq_pipeline([])
            reconstructed_pipeline.messages = [
                dramatiq.Message.decode(data=d) for d in pickle.loads(self.serialized_message)
            ]
            self._message = reconstructed_pipeline
        elif self._message_type == self.DRAMATIQ_TASK:
            self._message = dramatiq.Message.decode(data=self.serialized_message)
        else:
            raise FutureException(f"Unable to send message type: {self._message_type}")

    def __getstate__(self):
        getstate = super().__getstate__()
        getstate.pop("_func", None)
        getstate.pop("_message", None)
        return getstate

    def __setstate__(self, data):
        super().__setstate__(data)
        self._deserialize_message()

    def send(self, *args, _future_task_delay=None, **kwargs):
        # Deploying to Dramatiq
        try:
            self.func_args = ", ".join([str(a) for a in args])
            self.func_kwargs = ", ".join([f"{k}: {v}" for k, v in kwargs.items()])
            for stack_frame in inspect.stack():
                if (
                    stack_frame.filename.startswith("/code/") or stack_frame.filename.startswith("/project/code/")
                ) and "future.py" not in stack_frame.filename:
                    self.caller = (
                        f"Called from:\n"
                        f"{stack_frame.filename}:{stack_frame.lineno}\n"
                        f"Parent function: {stack_frame.function}\n"
                        f'Function: {"".join([s.strip() for s in stack_frame.code_context])}'
                    )
                    break
        except:  # NOQA
            logger.warning("Failed to get caller for Future", caller_stack=inspect.stack())

        if self._message_type == self.DRAMATIQ_PIPELINE:
            message = self._func.run()
            # Extract inner messages in dramatiq.pipeline, as we can't pickle the broker inside the object
            self.serialized_message = pickle.dumps([m.encode() for m in message.messages])
        elif self._message_type == self.DRAMATIQ_TASK:
            message = self._func.send_with_options(args=args, kwargs=kwargs, delay=_future_task_delay)
            self.serialized_message = message.encode()
        else:
            raise FutureException(f"Unable to send message type: {self._message_type}")

        self._message = message
        self.save()

    @property
    def execution_time(self):
        return 0
        # if self.endtime is None:
        #     raise FutureNotReady("The end time hasn't been recorded. This will happen automatically on .wait()")
        # else:
        #     return self.start_time - self.end_time

    @property
    def done(self):
        # self._value is only None if we have no result. A result of None would be serialized with pickle.
        return self._value is not None

    def wait(self, timeout=DEFAULT_WAIT):
        if not self.done:
            try:
                if timeout <= 0:
                    value = self._message.get_result(block=False)
                else:
                    value = self._message.get_result(block=True, timeout=timeout)
            except dramatiq.results.errors.ResultMissing:
                raise FutureNotReady("The result wasn't immediately ready")
            except dramatiq.results.errors.ResultTimeout:
                raise FutureTimeout(
                    "Dramatiq ResultTimeout."
                    + (" Did you remember to use the fixture 'future_worker_broker'?" if is_pytest else "")
                )
            except dramatiq.results.errors.ResultFailure as ex:
                if ex.orig_exc_type == "Exception" and ex.orig_exc_msg == "unknown":
                    value = ("Error", FutureExpired("Unidentifiable exception. Interpreted as 'max_age' reached."))
                elif ex.orig_exc_type == "FutureRetry" or ex.orig_exc_type == "FutureRetryRateLimiter":
                    # FutureRetry is special, as this is one we wrap in the future-decorator
                    # We change it to FutureExpired, as FutureRetry is just a signalling exception internally
                    value = (
                        "Error",
                        FutureExpired(
                            "Result couldn't be produced within max_retries constraints.",
                            inner_exception=ex.orig_exc_msg,
                        ),
                    )
                else:
                    value = ("Error", FutureCapturedException(str(ex)))

            self._value = pickle.dumps(value)
            self.traceback = self.get_traceback()
            self.save()

        return self.value

    @property
    def _success(self):
        if self._value is None:
            raise FutureNotReady("The Dramatiq result hasn't been fetched yet. Use .wait().")
        code, _ = pickle.loads(self._value)
        return code == "Ok"

    def get_traceback(self):
        res = unpack_result_tuple(pickle.loads(self._value), self._message_type, do_raise=False)
        if isinstance(res, tuple):
            return res[1]
        return None

    @property
    def value(self):
        if not self.done:
            raise FutureNotReady("The Dramatiq result hasn't been fetched yet. Use .wait().")

        return unpack_result_tuple(pickle.loads(self._value), self._message_type)

    @property
    def value_or_none(self):
        try:
            # Returns what is immediately ready
            return self.wait(timeout=0)
        except BaseException:  # We don't want any error to propagate
            return None

    @property
    def short_caller(self):
        if self.caller is None:
            return "-"
        return self.caller.splitlines()[-1].split(":", 1)[-1]


class FutureRetriesMiddleware(Middleware):
    """
    Modified version of Dramatiq Retries middleware
    """

    def __init__(self, *, max_retries=20, min_backoff=None, max_backoff=None, retry_when=None):
        self.max_retries = max_retries
        self.min_backoff = min_backoff or actor_defaults["min_backoff"]
        self.max_backoff = max_backoff or actor_defaults["max_backoff"]
        self.retry_when = retry_when

    @property
    def actor_options(self):
        return {
            "max_retries",
            "min_backoff",
            "max_backoff",
            "retry_when",
            "throws",
        }

    def after_process_message(self, broker, message, *, result=None, exception=None):
        if exception is None:
            return
        message.options["traceback"] = traceback.format_exc(limit=30)

        actor = broker.get_actor(message.actor_name)
        throws = message.options.get("throws") or actor.options.get("throws")
        if throws and isinstance(exception, throws):
            logger.debug("Aborting message %r.", message.message_id)
            message.fail()
            return

        retries_rate_limit = message.options.setdefault("retries_rate_limit", 0)
        retries = message.options.setdefault("retries", 0)
        max_retries = message.options.get("max_retries") or actor.options.get("max_retries", self.max_retries)

        retry_when = actor.options.get("retry_when", self.retry_when)
        if (
            retry_when is not None
            and not retry_when(retries, exception)
            or retry_when is None
            and max_retries is not None
            and retries >= max_retries
        ):
            logger.warning("Retries exceeded for message %r.", message.message_id)
            message.fail()
            return

        delay = None
        if isinstance(exception, Retry) or isinstance(exception, FutureRetry):
            if isinstance(exception, FutureRetryRateLimiter):
                # These count towards the backoff delay, but not the maximum number of retries.
                message.options["retries_rate_limit"] += 1
            else:
                message.options["retries"] += 1

            if exception.delay is not None:
                delay = exception.delay
            else:
                min_backoff = message.options.get("min_backoff") or actor.options.get("min_backoff", self.min_backoff)
                max_backoff = message.options.get("max_backoff") or actor.options.get("max_backoff", self.max_backoff)
                max_backoff = min(max_backoff, actor_defaults["max_backoff"])

                # Apply regular backoff delay
                _, regular_backoff_delay = dramatiq.common.compute_backoff(
                    retries, factor=min_backoff, max_backoff=max_backoff,
                )

                # TODO: Possibly apply delay depending on the number of enqueued and reenqueued tasks

                multiplier = 1 if is_pytest else 25
                # If rate-limited, we need to dramatically increase the backoff delay to avoid thrashing.
                _, ratelimit_backoff_delay = dramatiq.common.compute_backoff(
                    retries_rate_limit,
                    factor=min_backoff * multiplier,  # Atm. this will become 6,25 seconds
                    max_backoff=max_backoff * multiplier,  # Atm. this will become 25 minutes
                )

                delay = regular_backoff_delay + ratelimit_backoff_delay

        logger.debug("Retrying message by reenqueueing it with a delay", message_id=message.message_id, delay=delay)
        broker.enqueue(message, delay=delay)


broker.add_middleware(FutureRetriesMiddleware())
