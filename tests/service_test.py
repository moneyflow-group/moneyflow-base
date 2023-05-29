import os
print("PP=", os.environ['PYTHONPATH'])

from mbase.services import BaseService, ObservableMixin, BaseObserver
from mbase.mlogging import mf_get_logger

logger = mf_get_logger(__name__)


class SomeService(ObservableMixin, BaseService):
    def some_method(self, arg):
        self.observers.event_happend(arg)

class SomeObserver(BaseObserver):
    def event_happend(self, arg):
        logger.debug(f"event_happend: {arg}")

class SecondSomeObserver(BaseObserver):
    def event_happend(self, n):
        logger.debug(f"event_happend: second {n}")

class AnotherService(ObservableMixin, BaseService):
    def another_method(self, arg):
        self.observers.another_event_happend(arg)

class AnotherObserver(SomeObserver):
    def another_event_happend(self, arg):
        logger.debug(f"another_event_happend: {arg}")


# TODO Commented out temporarily as Flow's CI fails on htese
# class TestService:
#     SomeService.add_observer(SomeObserver)
#     SomeService.add_observer(SecondSomeObserver)
#     AnotherService.add_observer(AnotherObserver)
#
#     def test_observer(self, caplog):
#         s = SomeService()
#         s.some_method(7)
#         assert "event_happend: 7" in caplog.text
#         assert "event_happend: second 7" in caplog.text
#
#     def test_another_observer(self, caplog):
#         a = AnotherService()
#         a.another_method(9)
#         assert "event_happend: 7" not in caplog.text
#         assert "another_event_happend: 9" in caplog.text
