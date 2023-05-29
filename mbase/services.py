import sys
from typing import Type
from mbase.logging import mf_get_logger
import dramatiq

logger = mf_get_logger(__name__)

is_pytest = "pytest" in sys.argv[0]


class MethodWrapper(object):
    def __init__(self, actor, observers, method_name, *args, **kwargs):
        self.actor: Type[BaseObserver] = actor
        self.observers = observers
        self.method_name: str = method_name
        self.args = args
        self.kwargs = kwargs

    def __str__(self):
        return f"{self.actor}.{self.method_name}({self.args}, {self.kwargs} ({self.observers})"


@dramatiq.actor(max_retries=1)
def message_handler(mw: MethodWrapper):
    obj: BaseObserver = mw.actor()
    obj.observers = mw.observers
    try:
        func = getattr(obj, mw.method_name)
        func(*mw.args, **mw.kwargs)
    except Exception as e:
        logger.error("message_handler: Exception", exc_info=True)


class Dispatcher(object):
    """
    Class for dispatching events to all observers on a class
    """
    def __init__(self, owner):
        self._owner: Type[ObservableMixin] = owner
        self._observers: set(Type[BaseObserver]) = set()

    class Method(object):
        def __init__(self, owner, dispatcher, method):
            self.owner: Type[ObservableMixin] = owner
            self.dispatcher: Dispatcher = dispatcher
            self.method: str = method

        def __call__(self, *args, **kwargs):
            for observer in self.dispatcher._observers:
                try:
                    if is_pytest:
                        message_handler(MethodWrapper(observer, None, self.method, *args, **kwargs))
                    else:
                        message_handler.send(MethodWrapper(observer, None, self.method, *args, **kwargs))
                except Exception as e:
                    logger.error("Dispatcher: Exception", exception=e)

    def _add_observer(self, observer):
        self._observers.add(observer)

    def __getattr__(self, name):
        if isinstance(name, str) and name[:2] == name[-2:] == "__":
            # skip non-existing dunder method lookups
            raise AttributeError(name)
        if name == "add_observer":
            raise AttributeError("add_obserer called directly on dispatcher")
        if name.startswith("_"):
            return getattr(self, name)
        for observer in self._observers:
            if not getattr(observer, name, None):
                logger.debug(f"{name} method not in {observer}")
        return self.Method(self._owner, self, name)


class BaseService(object):
    """
    All Services should inherit this
    """


class BaseObserver(object):
    """
    All abstract observers should inherit this
    """


class ObservableMixin(object):
    """
    To be added to a Service which emits observer methodccalls
    """

    @classmethod
    def add_observer(cls, observer):
        if not issubclass(observer, BaseObserver):
            raise BaseException(f"Class {observer} is not an instance of BaseObserver")
        if not getattr(cls, "observers", None):
            cls.observers = Dispatcher(cls)
        cls.observers._add_observer(observer)
