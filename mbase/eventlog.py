from typing import Union, Type
import uuid
from typing import Callable
from dataclasses import dataclass
from crum import get_current_user

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.db.models import JSONField, QuerySet
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from mbase.exceptions import MFValidationError
from mbase.utils import get_site_absolute_url, utcnow

from mbase.exceptions import DuplicateEvent
from mbase.mlogging import mf_get_logger


logger = mf_get_logger(__name__)

# NoneType is not in py3.9 (labs), hack it
NoneType = type(None)

@dataclass
class EventType:
    """Event"""
    base: object = None
    name: str = ""
    label: str = ""
    formatter: Union[Callable, str] = NoneType

    def __str__(self):
        return self.name


# Should be renamed to EventLog
class Event(models.Model):
    """
    Event types are set on the Event class on load
    """

    id = models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True)
    created_at = models.DateTimeField(_("Created At"), auto_now_add=True, editable=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="%(app_label)s_%(class)s_created_by_set",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        default=None,
    )

    type = models.CharField(max_length=70, db_index=True)
    timestamp = models.DateTimeField(default=timezone.now, db_index=True)
    content_type = models.ForeignKey(ContentType, null=True, on_delete=models.CASCADE)
    object_id = models.UUIDField(null=True)
    content_object = GenericForeignKey("content_type", "object_id")
    extra = JSONField(default=dict, encoder=DjangoJSONEncoder)
    sender = models.CharField(max_length=50, null=True, blank=True)

    class Meta:
        ordering = ["-timestamp", "-id"]
        index_together = ["object_id", "content_type"]

    def __str__(self):
        return f"{self.type} ({self.created_by})"

    EVENTS = {}

    def get_label(self):
        return self.EVENTS[self.type].label

    def get_description(self, *, format: bool = True):
        if self.type not in self.EVENTS:
            return self.type

        formatter = self.EVENTS[self.type].formatter

        if not format:
            return self.extra.get("note", "") if self.extra else self.get_label()

        if formatter is NoneType:
            return self.type

        if isinstance(formatter, str):
            if len(formatter) > 0:
                return formatter
            elif self.extra:
                return self.extra.get("note", "")
            else:
                return self.get_label()
        desc = formatter(self)
        if desc:
            return desc
        elif self.extra:
            return self.extra.get("note", "")
        else:
            return self.get_label()

    def get_link(self):
        if hasattr(self.content_object, "get_absolute_url"):
            return get_site_absolute_url() + self.content_object.get_absolute_url()
        return None

    def save(self, *args, **kwargs):
        if not self._state.adding:  # primary key already set, object exists
            raise MFValidationError("This model only support write once and cannot be updated again.")
        super().save(*args, **kwargs)

    def delete(self, using=None, keep_parents=False):
        raise MFValidationError("This model does not support deleting.")


def notify_subscribers(event):
    from message_service.services import SlackService
    from utils.models import EventSubscription
    from configuration_manager.utils import SystemConf

    logger.debug(f"Event [{event.type}]", type=event.type)

    for subscription in EventSubscription.objects.filter(event_type=event.type, active=True):
        if subscription.notification_target == EventSubscription.NOTIFICATION_TARGET_SLACK_CHANNEL:
            if event.get_link():
                text = f"Event: <{event.get_link()}|{event.get_label()}> - {event.get_description(format=False)}"
            else:
                text = f"Event: {event.get_label()} - {event.get_description(format=False)}"
            SlackService().send_message(channel=SystemConf().SLACK_CHANNEL, text=text)
        else:
            logger.error(
                "Notification target invalid", subscription_id=subscription.id, target=subscription.notification_target
            )


def event_log(*, event_type: EventType, obj: object = None, extra: dict = {}, sender: str = None) -> Event:
    """
    Log an event

    :param event_type: The event type
    :param obj: The object that the event is related to
    :param extra: Extra data to be stored in the event, descriptions go in "note"
    :param sender: The sender context of the event, ie: ONBOARDING
    """
    content_type = None
    object_id = None
    if obj:
        content_type = ContentType.objects.get_for_model(obj)
        object_id = obj.pk

    user = get_current_user()
    if not isinstance(user, get_user_model()):
        user = None

    event = Event.objects.create(
        type=event_type.name, created_by=user, extra=extra, content_type=content_type, object_id=object_id, timestamp=utcnow(), sender=sender
    )

    notify_subscribers(event)

    logger.info(f"Event [{event_type.name}]", event_type=event_type.name, baseevent=event_type.base.__name__)

    return event


def events_get_for_object(*, obj: object) -> QuerySet[Event]:
    """
    Retrieve all events for a specific object
    """
    return Event.objects.filter(object_id=obj.pk, content_type=ContentType.objects.get_for_model(obj))


def events_get_for_object_queryset(*, queryset: QuerySet) -> QuerySet[Event]:
    if not queryset:
        return Event.objects.none()
    object_ids = queryset.values_list("pk", flat=True)
    content_type = ContentType.objects.get_for_model(queryset[0])
    return events_get_for_object_ids(object_ids=object_ids, content_type=content_type)


def events_get_for_object_ids(*, object_ids: list[str], content_type: ContentType) -> QuerySet[Event]:
    return Event.objects.filter(object_id__in=object_ids, content_type=content_type)


def key_information_formatter(*, text: str) -> str:
    """
    Formatter to Highlight the text
    """
    return f"<span class='key-information'>{text}</span>"

def event_type_lookup(*, name: str="") -> EventType:
    return Event.EVENTS[name]

class BaseEvent:
    @classmethod
    def event_type_add(cls, name: str = "", label: str = "", formatter: Union[Callable, str] = NoneType) -> EventType:
        event_type = EventType(name=name, label=label, formatter=formatter)
        setattr(cls, name, event_type)
    
    @staticmethod
    def ready():
        pass


class EventRegistry:  # Today: Event.EVENTS
    BASEEVENTS = []

    @staticmethod
    def register(baseevent: Type[BaseEvent]):
        for name in baseevent.__dict__:
            event_type = baseevent.__dict__[name]
            if isinstance(event_type, EventType):
                event_type.name = name
                event_type.base = baseevent
                if not event_type.label:
                    event_type.label = " ".join([t.lower() for t in name.split('_')]).capitalize()
                if event_type.name in Event.EVENTS:
                    raise DuplicateEvent("Duplicate event declaration '{}.{}' also in '{}'".format(event_type.base, event_type.name, Event.EVENTS[event_type.name].base))
                Event.EVENTS[event_type.name] = event_type
        EventRegistry.BASEEVENTS.append(baseevent)
