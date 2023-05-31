import datetime
import hashlib
import os
import random
import re
from calendar import monthrange
from dataclasses import dataclass
from decimal import Decimal
from functools import wraps
from typing import Tuple, Union
from uuid import UUID

import holidays
import pytz
from django.conf import settings
from django.contrib.sites.models import Site
from django.db import models
from stdnum.de import vat as de_vat
from stdnum.dk.cvr import checksum as stdnum_dk_checksum
from stdnum.dk.cvr import compact as stdnum_compact
from stdnum.exceptions import InvalidChecksum as stdnum_InvalidChecksum
from stdnum.exceptions import InvalidFormat as stdnum_InvalidFormat
from stdnum.exceptions import InvalidLength as stdnum_InvalidLength
from stdnum.exceptions import ValidationError as stdnum_ValidationError
from stdnum.no import vat as no_vat
from stdnum.se import orgnr as se_orgnr
from stdnum.util import isdigits as stdnum_isdigits

from mbase.exceptions import InvalidCRN
from mbase.mlogging import mf_get_logger

logger = mf_get_logger(__name__)


def split_locale(locale_string):
    """
    Split a locale string into its language and country parts.
    Combines data from the ISO-639-1 and ISO-3166-1 standards.
    https://www.andiamo.co.uk/resources/iso-language-codes/
    """
    language = "da"
    country = ""
    if "_" in locale_string:
        language, country = locale_string.split("_", 1)
    elif "-" in locale_string:
        language, country = locale_string.split("-", 1)
    else:
        language = locale_string
    language = language.lower()
    if language not in ["da", "en"]:
        # raise InvalidLocale("The lanuage provided is not supported", language=language)
        logger.warning("Unsupported language", language=language, locale=locale_string)
        language = "en"
    return language, country.upper()


def traverse_path(dictionary, path, original_path=None):
    assert isinstance(path, list), "A list is required for 'path' argument"
    if original_path is None:
        original_path = path

    head, *tail = path

    if head.isdigit() and isinstance(dictionary, list) and len(dictionary) > int(head):
        value = dictionary[int(head)]
    elif head in dictionary:
        value = dictionary.get(head)
    else:
        raise KeyError(f"Key not found for {original_path} at {head}")

    if tail == []:
        return value
    else:
        return traverse_path(value, tail, original_path)


def yield_to_list(fun):
    def wrapped(*args, **kwargs):
        return list(fun(*args, **kwargs))

    return wrapped


def yield_to_set(fun):
    def wrapped(*args, **kwargs):
        return set(fun(*args, **kwargs))

    return wrapped


def yield_to_dict(fun):
    def wrapped(*args, **kwargs):
        return dict(fun(*args, **kwargs))

    return wrapped


def utcmin():
    """
    Earliest possible timestamp in UTC. Used as initial value for some timestamps
    """
    return datetime.datetime.min.replace(tzinfo=pytz.utc)


def utcnow():
    """
    This function ACTUALLY provides a datetime object of UTC with the timezone info set --
    datetime.datetime.utcnow doesn't.
    """
    return datetime.datetime.now(pytz.utc)


def next_business_day(from_date: datetime) -> datetime:
    dk_holidays = holidays.Denmark(years=from_date.year)
    one_day = datetime.timedelta(days=1)
    next_day = from_date + one_day
    while next_day.weekday() in holidays.WEEKEND or next_day in dk_holidays:
        next_day += one_day
    return next_day


def is_business_day(on_date: datetime) -> bool:
    dk_holidays = holidays.Denmark(years=utcnow().year)
    return on_date not in dk_holidays and on_date.weekday() not in holidays.WEEKEND


def next_occurence_of_day(day_no: int, from_date: datetime = None) -> datetime:
    """
    This function tries to provide a datetime object with the next occurence of that day number
    If the day number exceeds the days of the month, it returns the last day of the month
    """
    if not from_date:
        from_date = utcnow()
    if from_date.day >= day_no:
        from_date = from_date + datetime.timedelta(
            days=(monthrange(from_date.year, from_date.month)[1] - from_date.day + 1)
        )
    if day_no > monthrange(from_date.year, from_date.month)[1]:
        from_date = from_date.replace(day=monthrange(from_date.year, from_date.month)[1])
    return from_date


def timestamp(dt: datetime):
    """
    Datetime to UNIX timestamp in milliseconds.
    """
    return round(dt.timestamp() * 1000)


def format_days_ago(target, today=None):
    if today is None:
        today = utcnow()
    target_date = target.date() if isinstance(target, datetime.datetime) else target
    diff = today.date() - target_date
    output = []
    if diff.days == 0:
        output.append("Today")
    elif diff.days == 1:
        output.append("1 day ago")
    elif diff.days > 1 and diff.days < 6:
        output.append(f"{diff.days} days ago")
    else:
        # Fallback for future dates, we default to the actual date
        return target_date.strftime("%d/%m/%y")

    # Changing the timezone to be Copenhagen before displaying it in backoffice (after all calculations are done!)
    if isinstance(target, datetime.datetime):
        tz = pytz.timezone("Europe/Copenhagen")
        target = target.astimezone(tz)
        output.append(target.strftime("%H.%M"))
    return ", ".join(output)


def normalize_crn(crn):
    if not isinstance(crn, str):
        return None
    try:
        crn = extract_cvr(crn, return_normalized=True)
    except InvalidCRN:
        pass

    return crn


def localize_crn(crn, *, country: str = None):
    if not isinstance(crn, str):
        return None
    if not country:
        country = "DK"
    if country in crn[:2]:
        return crn
    else:
        return f"{country}{crn}"


def is_anon_crn(crn):
    return crn.startswith("SHA256")


def is_anon_erp_company_id(company_id):
    return company_id.startswith("SHA256")


def normalize_account(bank_reg: str = "", bank_account: str = "") -> Tuple[str, str]:
    if bank_reg is None:
        bank_reg = ""
    bank_string = (bank_reg + bank_account).replace("-", "").replace(" ", "")
    reg_no = bank_string[:4]
    account_no = bank_string[4:]
    padding = "0" * (10 - len(account_no))
    account_no = padding + account_no
    return reg_no, account_no


class dk_vat:
    # NOTE: Modified version of stdnum validator to support leading 0
    # https://github.com/arthurdejong/python-stdnum/blob/master/stdnum/dk/cvr.py
    @classmethod
    def is_valid(cls, number):
        """Check if the number provided is a valid VAT number. This checks the
        length, formatting and check digit."""
        try:
            return bool(cls.validate(number))
        except stdnum_ValidationError:
            return False

    @classmethod
    def validate(cls, number):
        """Check if the number provided is a valid VAT number. This checks the
        length, formatting and check digit."""
        number = stdnum_compact(number)
        if not stdnum_isdigits(number) or (settings.STAGE == "prod" and number[0] == "0"):
            raise stdnum_InvalidFormat()
        if len(number) != 8:
            raise stdnum_InvalidLength()
        if stdnum_dk_checksum(number) != 0:
            raise stdnum_InvalidChecksum()
        return number

    compact = stdnum_compact


def extract_cvr(cvr, _country_code: bool = False, return_normalized=False):
    # Only process strings
    if not isinstance(cvr, str):
        t = type(cvr)
        raise InvalidCRN(f"CVR is of type {t}, expected str", cvr=cvr)

    for character in "-:+_ .":
        cvr = cvr.replace(character, "")

    cvr_match = re.match(r"^(DK|SE|NO|DE)?(\d{8,10})(?:01)?$", cvr)
    if cvr_match is None:
        raise InvalidCRN("Invalid format for CVR", cvr=cvr)
    else:
        cvr = cvr_match.groups()[1]

    for prefix, validator in [("DK", dk_vat), ("SE", se_orgnr), ("DE", de_vat), ("NO", no_vat)]:
        if validator.is_valid(cvr):
            compacted = validator.compact(cvr)
            if return_normalized:
                cvr = f"{prefix}{compacted}"
            else:
                cvr = compacted
            country_code = prefix
            break
    else:
        raise InvalidCRN("Invalid format for CVR", cvr=cvr)

    if _country_code:
        return cvr, country_code
    return cvr


@yield_to_dict
def namedtuple_as_dict(namedtuple):
    for k, v in namedtuple._asdict().items():
        if hasattr(v, "_asdict"):  # Is a namedtuple
            v = namedtuple_as_dict(v)
        yield (k, v)


class ModelToDict:
    @yield_to_dict
    def to_dict(self, depth=0, annotated_fields=[]):
        # annotated fields are not included in the _meta.fields, but stored as simple properties.
        # using annotated_fields will allow requesting specific properties while ignoring Django's
        # internal properties that are irrelevant.
        fields = [f.name for f in self.__class__._meta.fields] + annotated_fields
        for f in fields:
            field_value = getattr(self, f)

            # Recurse models
            if isinstance(field_value, ModelToDict) and depth > 0:
                field_value = field_value.to_dict(depth=depth - 1)
            # Add types to convert to string
            elif isinstance(field_value, (UUID, Decimal, datetime.date, models.Model)):
                field_value = str(field_value)
            yield (f, field_value)


def to_snakecase(string):
    s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", string)
    result = re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1).lower()
    return result


def get_site_absolute_url():
    current_site = Site.objects.get_current()
    site_protocol = "http" if current_site.domain.split(":")[0] == "localhost" else "https"
    return f"{site_protocol}://{current_site}"


def hash_crn(crn: str) -> Union[str, None]:
    if crn is not None:
        normalized_crn = normalize_crn(crn=crn)
        return "SHA256" + hashlib.sha256(normalized_crn.encode("utf-8")).hexdigest()
    return None


def hash_erp_company_id(erp_company_id: str) -> Union[str, None]:
    if erp_company_id is not None:
        return "SHA256" + hashlib.sha256(erp_company_id.encode("utf-8")).hexdigest()
    return None


def generate_anonymized_erp_company_id():
    numbers = "1234567890"
    erp_company_id = "ANON-" + "".join(random.choices(numbers, k=10))
    return erp_company_id


def _safe_trace_kwargs(kwargs, included_safe_kwargs):
    # To avoid changing data types of arguments in our logging database,
    # we only log values we are sure to be of a certain type, or specifically included.
    return dict(
        [
            (k, v)
            for k, v in kwargs.items()
            if k.endswith("_id") or k.endswith("_crn") or k in list(included_safe_kwargs)
        ]
    )


def yield_list_chunks(lst, chunk_size: int):
    for i in range(0, len(lst), chunk_size):
        yield lst[i : i + chunk_size]  # NOQA
