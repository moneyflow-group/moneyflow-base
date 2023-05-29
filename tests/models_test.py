# from unittest import mock

# import pytest
# from django.db import connection
# from django.db.models.base import ModelBase
# from django.db.utils import ProgrammingError
# from rest_framework.exceptions import ValidationError
# from utils.models import WORMBaseModel

# TODO: Seems to block tests on PRs
# def prepare_to_test_abstract_base_class(abstract_base_model_to_test):
#     """Sets up an abstract base class as a concrete class to enable testing
#     its internals.

#     inspired by: https://stackoverflow.com/questions/4281670/django-best-way-to-unit-test-an-abstract-model/
#         51146819#51146819
#     """
#     base_model = ModelBase(
#         "Base", (abstract_base_model_to_test,), {"__module__": abstract_base_model_to_test.__module__}
#     )
#     try:
#         with connection.schema_editor() as schema_editor:
#             schema_editor.create_model(base_model)
#     except ProgrammingError:
#         pass

#     return base_model.objects.create()


# @pytest.mark.django_db
# class TestBaseWORMModel:
#     def test_worm_model_cant_save_by_default(self):
#         worm_model = prepare_to_test_abstract_base_class(WORMBaseModel)

#         with pytest.raises(ValidationError):
#             worm_model.save()

#     def test_worm_model_can_save_with_migrate_and_worm_safe_override(self):
#         worm_model = prepare_to_test_abstract_base_class(WORMBaseModel)

#         with mock.patch("utils.models.sys") as mock_sys:
#             mock_sys.argv = ("migrate",)

#             worm_model.save(worm_safe=True)

#             with pytest.raises(ValidationError):
#                 worm_model.save(worm_safe=False)

#         with pytest.raises(ValidationError):
#             worm_model.save(worm_safe=True)

#         with pytest.raises(ValidationError):
#             worm_model.save(worm_safe=False)
