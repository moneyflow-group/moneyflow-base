"""
Central conftest file. All fixtures in this file will be available for all other tests.
"""


from unittest import mock

import pytest
from django.conf import settings
from django.core.management import call_command
from django.utils.translation import activate

@pytest.fixture(scope="module")
def django_db_setup(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock():
        call_command("loaddata", "credit_limit_initial_setup.json")

@pytest.fixture(autouse=True)
def set_default_language():
    activate("en")
