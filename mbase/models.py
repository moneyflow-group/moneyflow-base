import crypt
import sys
import uuid
from decimal import Decimal, DecimalException

from babel.numbers import format_decimal
from crum import get_current_user
from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
from django.contrib.contenttypes.models import ContentType
from django.contrib.postgres.fields import ArrayField
from django.core.validators import MaxLengthValidator, MaxValueValidator, MinLengthValidator, MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from mbase.eventlog import Event  # NOQA
from mbase.exceptions import MFValidationError
from mbase.future import Future  # NOQA
from mbase.logging import mf_get_logger

logger = mf_get_logger(__name__)


class BaseModel(models.Model):
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
    modified_at = models.DateTimeField(_("Modified"), auto_now=True, editable=False)
    modified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="%(app_label)s_%(class)s_modified_by_set",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        default=None,
    )

    events = GenericRelation("base.Event")

    def log_kwargs(self, prefix):
        return {
            f"{prefix}_id": self.id,
            f"{prefix}_created_by": self.created_by,
            f"{prefix}_created_at": self.created_at,
            f"{prefix}_modified_at": self.modified_at,
            f"{prefix}_modified_by": self.modified_by,
        }

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        user = get_current_user()
        if isinstance(user, get_user_model()):
            if self._state.adding:
                self.created_by = user
            self.modified_by = user

        super().save(*args, **kwargs)

    def set_field(self, k, v, force=False):
        if not force and k not in self.api_editable_fields:
            raise MFValidationError(
                f"'{k}' kwargs didn't match the allowed fields: {', '.join(self.api_editable_fields)}"
            )

        setattr(self, k, v)

    def api_dict(self):
        return {field: self.base_company.crn if field == "crn" else getattr(self, field) for field in self.api_fields}

    def __str__(self):
        return f"{self.__class__.__name__} [{self.id}]"


class WORMBaseModel(BaseModel):
    def save(self, *args, worm_safe=False, **kwargs):
        if not (self._state.adding or ("migrate" in sys.argv and worm_safe)):  # primary key already set, object exists
            raise MFValidationError("This model only support write once and cannot be updated again.")
        super().save(*args, **kwargs)

    def delete(self, using=None, keep_parents=False):
        raise MFValidationError("This model does not support deleting.")

    class Meta:
        abstract = True


class StrictCharField(models.CharField):
    empty_strings_allowed = False


class EventSubscription(BaseModel):
    """
    User subscription on type of event
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    event_type = models.CharField(max_length=70, db_index=True, default="")
    active = models.BooleanField(default=True)

    NOTIFICATION_TARGET_USER = "USER"
    NOTIFICATION_TARGET_SLACK_CHANNEL = "SLACK_CHANNEL"
    NOTIFICATION_TARGET_CHOICES = (
        (NOTIFICATION_TARGET_USER, ("User")),
        (NOTIFICATION_TARGET_SLACK_CHANNEL, ("Slack Channel")),
    )
    notification_target = models.CharField(
        max_length=255, choices=NOTIFICATION_TARGET_CHOICES, default=NOTIFICATION_TARGET_SLACK_CHANNEL
    )


class ChoiceFieldDescription(models.Model):
    model = models.CharField(max_length=255)
    field = models.CharField(max_length=255)
    value = models.CharField(max_length=255)
    description = models.CharField(max_length=255)

    @classmethod
    def get_field_option_data(cls, field, model_name) -> list:
        fdict = field.__dict__
        return [
            {"model": model_name, "field": fdict["name"], "value": choice[0], "description": choice[1]}
            for choice in fdict["choices"]
        ]

    @classmethod
    def get_model_choice_fields(cls, model) -> list:
        result = []
        model_name = model._meta.__dict__["model_name"]
        for field in model._meta.get_fields():
            if "choices" not in field.__dict__ or not field.__dict__["choices"]:
                continue
            result.extend(cls.get_field_option_data(field=field, model_name=model_name))
        return result

    @classmethod
    def get_choice_fields_data(cls):
        return [i for model in apps.get_models() for i in cls.get_model_choice_fields(model=model)]

    @classmethod
    def update_model(cls):
        cls.objects.all().delete()
        cls.objects.bulk_create([cls(**i) for i in cls.get_choice_fields_data()])
