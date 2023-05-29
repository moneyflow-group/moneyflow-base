import datetime
import os

import pytest  # NOQA
import pytz

from base.exceptions import InvalidCRN
from mbase.utils import (
    extract_cvr,
    format_days_ago,
    generate_anonymized_erp_company_id,
    normalize_crn,
)


class TestHelpers:
    @pytest.mark.parametrize("cvr", ["12341234", "DK12341234", "DK-12341234", "12 34 56 78", "000633040", "ABC"])
    def test_invalid_cvr(self, cvr, responses):
        with pytest.raises(InvalidCRN):
            extract_cvr(cvr)

    @pytest.mark.parametrize("cvr", ["00063304", "DK00063304", "DK-00063304", "00 06 33 04", "00063304."])
    def test_valid_cvr(self, cvr, responses):
        assert extract_cvr(cvr) == "00063304"

    @pytest.mark.parametrize(
        "cvr",
        [
            "5567528285",
            "SE5567528285",
            "SE-5567528285",
            "55 6752 8285",
            "5567528285.",
            "SE-556752-8285",  # Multiple hyphen
            "SE556752828501",  # VAT number with '01' postfix
            "SE556752 -8285",  # Space in the middle
        ],
    )
    def test_valid_se_cvr(self, cvr, responses):
        assert extract_cvr(cvr) == "5567528285"

    @pytest.mark.parametrize(
        "cvr",
        [
            "243130914",
            "DE243130914",
            "DE-243130914",
            "24 313 0914",
            "243130914.",
            "SE-243130-914",  # Multiple hyphen
            "SE24313 -0914",  # Space in the middle
        ],
    )
    def test_valid_de_cvr(self, cvr, responses):
        assert extract_cvr(cvr) == "243130914"

    def test_normalize_crn(self, responses):

        # Passes mod-11 test, and becomes a Danish CVR
        assert normalize_crn("00063304") == "DK00063304"
        assert normalize_crn("DK00063304") == "DK00063304"
        assert normalize_crn("DK-00063304") == "DK00063304"
        assert normalize_crn("00 06 33 04") == "DK00063304"

        # Passes Luhn test, and becomes a Swedish CVR
        assert normalize_crn("5567528285") == "SE5567528285"
        assert normalize_crn("SE5567528285") == "SE5567528285"
        assert normalize_crn("SE-5567528285") == "SE5567528285"
        assert normalize_crn("55 67 52 82 85") == "SE5567528285"

        # Fails mod-11 and other tests, so they are ignored
        assert normalize_crn("12341234") == "12341234"
        assert normalize_crn("000633040") == "000633040"
        assert normalize_crn("ABC") == "ABC"
        assert normalize_crn("SE123412341234") == "SE123412341234"

    def test_format_days_ago(self):
        # TODO: Test more variation of Hours and Minutes

        # test with timezone Europe/Copenhagen
        tz = pytz.timezone("Europe/Copenhagen")
        today = datetime.datetime.today().astimezone(tz)
        ten_day_ago = today - datetime.timedelta(days=10)
        time = today.strftime("%H.%M")
        test_targets = {
            today: f"Today, {time}",
            # Does not handle summertime shifts correct (18:36 minus one day gets 19:36)
            # today - datetime.timedelta(days=1): f"1 day ago, {time}",
            # today - datetime.timedelta(days=2): f"2 days ago, {time}",
            ten_day_ago: f"{ten_day_ago.strftime('%d/%m/%y')}",
            today.date(): "Today",
            today.date() - datetime.timedelta(days=1): "1 day ago",
            today.date() - datetime.timedelta(days=2): "2 days ago",
            ten_day_ago.date(): f"{ten_day_ago.strftime('%d/%m/%y')}",
        }
        for target, formatted_target in test_targets.items():
            assert formatted_target == format_days_ago(target)

    def test_generate_anonymized_erp_company_id(self):
        erp_company_id = generate_anonymized_erp_company_id()
        assert len(erp_company_id) == 15
        assert erp_company_id.startswith("ANON-")
