"""
Central conftest file. All fixtures in this file will be available for all other tests.
"""


from unittest import mock

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.utils.translation import activate
from testfixtures import Replace
from utils.conftest import *  # NOQA
from utils.test_tools_flow import USER_EMAIL, USER_PASSWORD

import django
django.setup()

@pytest.fixture(scope="module")
def django_db_setup(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock():
        call_command("loaddata", "credit_limit_initial_setup.json")


# @pytest.fixture
# def company(django_db_blocker):
#     with django_db_blocker.unblock():
#         erp_company_id = "".join([random.choice("123456789") for _ in range(7)])
#         crn = random_cvr_mod11()
#         with mock.patch("account_service.services.BaseCompanyService._spawn_assessment"):
#             company = CompanyService().company_create(
#                 erp_company_id=erp_company_id, crn=crn, platform=PLATFORM_ECONOMIC
#             )
#         company.api_key = "fake-api-key"
#         company.save()
#         yield company
#         company.delete()


@pytest.fixture
def valid_user():
    call_command("loaddata", "permission_fixture.json")
    user = get_user_model().objects.create_user(email=USER_EMAIL)
    user.set_password(USER_PASSWORD)
    user.is_staff = True
    user.groups.add(Group.objects.get(name="Backoffice Viewer"))
    user.save()
    yield user
    user.delete()


# @pytest.fixture
# def valid_backoffice_admin_user(django_db_blocker):
#     with django_db_blocker.unblock():
#         call_command("loaddata", "permission_fixture.json")
#         user = get_user_model().objects.create_user(email="admin@test.com")
#         user.set_password(USER_PASSWORD)
#         user.is_staff = True
#         user.groups.add(Group.objects.get(name="Backoffice Admin"))
#         user.save()
#         yield user
#         user.delete()


@pytest.fixture(scope="module")
def default_email_templates(django_db_blocker):
    with django_db_blocker.unblock():
        call_command("loaddata", "default_email_templates.json")


@pytest.fixture(scope="function", autouse=True)
def config_manager(django_db_blocker):
    with django_db_blocker.unblock():
        call_command("loaddata", "initial_config.json")


@pytest.fixture(scope="function", autouse=True)
def system_user(django_db_blocker):
    with django_db_blocker.unblock():
        call_command("loaddata", "system_user.json")


@pytest.fixture(scope="function", autouse=True)
def receipt_templates(django_db_blocker):
    with django_db_blocker.unblock():
        call_command("loaddata", "receipt_templates.json")


@pytest.fixture(scope="function", autouse=True)
def default_fund(django_db_blocker):
    with django_db_blocker.unblock():
        call_command("loaddata", "default_fund.json")


@pytest.fixture(autouse=True)
def verify_nemid_cert(monkeypatch):
    # Several tests expect NemID certification verification, so monkeypatch this to allow tests to run with
    # local settings
    monkeypatch.setattr(settings, "NEMID_VERIFY_CERT", True)


# @pytest.fixture(autouse=True)
# def mock_spawn_assessment(request):
#     """
#     Mock out insurance report creation by default. To enable it, set a pytest mark `insurance_report_enable`
#     """
#     m = mock.Mock()
#     if request.node.get_closest_marker("spawn_assessment"):
#         yield None
#     else:
#         with Replace("account_service.services.BaseCompanyService._spawn_assessment", m):
#             yield m


@pytest.fixture(autouse=True)
def mock_insurance_report_create(request):
    """
    Mock out insurance report creation by default. To enable it, set a pytest mark `insurance_report_enable`
    """
    m = mock.Mock()
    if request.node.get_closest_marker("insurance_report_enable"):
        yield None
    else:
        with Replace("risk_service.services.InsuranceService.insurance_report_create", m):
            yield m


@pytest.fixture()
def mock_create_customer_case():
    m = mock.Mock()
    with Replace("asset_service.models.CustomerService", m):
        yield m


@pytest.fixture(autouse=True)
def set_default_language():
    activate("en")
