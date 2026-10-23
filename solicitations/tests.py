from datetime import date
from types import SimpleNamespace

from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomUser
from solicitations.export_utils import (
    apply_row_56_no_do_minimum_rule,
    compute_bid_type_code,
    derive_higher_level_quality_code,
    validate_mandatory_fields,
    validate_profile_compliance,
    validate_row_56_no_do_minimum,
    apply_rows_118_121_quality_labor_remarks_rules,
    record_validation_failure,
    validate_field_formats,
    validate_rfq_matches,
    validate_code_set,
    validate_field_lengths,
    validate_row_32_fob_point,
    validate_row_65_hazmat,
    validate_row_66_hazardous_warning_label,
    validate_rows_52_55_aidc,
)
from solicitations.forms import UserUpdateForm
from solicitations.models import ExportFieldDefinition, GovernmentEmailSolicitation, GovernmentEmailSolicitationHandledBy, NoCageSolicitation, NoCageSolicitationHandledBy, RfqReply, Solicitation, UserExportConfiguration


def blank_values():
    """A 121-position value list with every field empty."""
    return ["" for _ in range(121)]


class ComputeBidTypeCodeTests(TestCase):
    """
    compute_bid_type_code() re-derives row 024 from scratch on every call,
    instead of escalating an existing value one trigger at a time. Each test
    exercises exactly one trigger against an otherwise-clean value list.
    """

    def test_no_triggers_returns_bi(self):
        values = blank_values()
        compute_bid_type_code(values)
        self.assertEqual(values[23], "BI")

    def test_multiple_triggers_still_returns_one_valid_code(self):
        values = blank_values()
        values[27 - 1] = "N"  # Meets Packaging Requirement = N
        values[120 - 1] = "Y"  # Child Labor Certification = Y
        compute_bid_type_code(values)
        self.assertEqual(values[23], "BW")

    def test_zero_quantity_forces_dq_and_wins_over_everything_else(self):
        values = blank_values()
        values[49 - 1] = "0"
        values[120 - 1] = "Y"  # a BW-level trigger present too
        compute_bid_type_code(values)
        self.assertEqual(values[23], "DQ")

    def test_alternate_part_forces_ab(self):
        values = blank_values()
        values[105 - 1] = "P"  # Item Description Indicator
        values[106 - 1] = "2"  # Part Number Offered Code: Alternate Product
        compute_bid_type_code(values)
        self.assertEqual(values[23], "AB")

    def test_days_quote_valid_under_90_on_aidc_solicitation_forces_bw(self):
        values = blank_values()
        values[2 - 1] = "I"
        values[27 - 1] = "45"
        compute_bid_type_code(values)
        self.assertEqual(values[23], "BW")

    def test_packaging_not_met_forces_bw(self):
        values = blank_values()
        values[28 - 1] = "N"
        compute_bid_type_code(values)
        self.assertEqual(values[23], "BW")

    def test_quantity_mismatch_forces_bw(self):
        values = blank_values()
        values[49 - 1] = "50"
        compute_bid_type_code(values, requirement_quantity="100")
        self.assertEqual(values[23], "BW")

    def test_quantity_mismatch_on_aidc_solicitation_does_not_trigger(self):
        # Row 002 = I means quantity is an estimate, not a firm requirement.
        values = blank_values()
        values[2 - 1] = "I"
        values[49 - 1] = "50"
        compute_bid_type_code(values, requirement_quantity="100")
        self.assertEqual(values[23], "BI")

    def test_material_requirements_4_on_aidc_solicitation_forces_bw(self):
        values = blank_values()
        values[2 - 1] = "I"
        values[67 - 1] = "4"
        compute_bid_type_code(values)
        self.assertEqual(values[23], "BW")

    def test_inspection_point_mismatch_forces_bw(self):
        values = blank_values()
        values[36 - 1] = "O"
        compute_bid_type_code(values, requirement_inspection_point="D")
        self.assertEqual(values[23], "BW")

    def test_fob_point_mismatch_forces_bw(self):
        # Row 32 (FOB Point) is marked "May Effect Bid Type: Yes" with the
        # same rule shape as row 36 above.
        values = blank_values()
        values[32 - 1] = "O"
        compute_bid_type_code(values, requirement_fob_point="D")
        self.assertEqual(values[23], "BW")

    def test_higher_level_quality_code_1_forces_bw(self):
        values = blank_values()
        values[117 - 1] = "7"
        values[118 - 1] = "1"
        compute_bid_type_code(values)
        self.assertEqual(values[23], "BW")

    def test_child_labor_yes_forces_bw(self):
        values = blank_values()
        values[120 - 1] = "Y"
        compute_bid_type_code(values)
        self.assertEqual(values[23], "BW")

    def test_quote_remarks_on_negotiated_solicitation_forces_bw(self):
        values = blank_values()
        values[121 - 1] = "Please see attached drawing."
        compute_bid_type_code(values)
        self.assertEqual(values[23], "BW")

    def test_quote_remarks_on_automated_solicitation_are_blanked_not_triggering(self):
        # F/P solicitations are auto-evaluated and can't read free text, so
        # DIBBS requires remarks to be cleared instead of forcing an exception.
        values = blank_values()
        values[2 - 1] = "F"
        values[121 - 1] = "Please see attached drawing."
        compute_bid_type_code(values)
        self.assertEqual(values[23], "BI")
        self.assertEqual(values[121 - 1], "")

    def test_quote_remarks_on_automated_solicitation_kept_when_another_trigger_fires(self):
        values = blank_values()
        values[2 - 1] = "F"
        values[28 - 1] = "N"  # a real exception is already present
        values[121 - 1] = "Please see attached drawing."
        compute_bid_type_code(values)
        self.assertEqual(values[23], "BW")
        self.assertEqual(values[121 - 1], "Please see attached drawing.")

    def test_resets_a_stale_bw_back_to_bi_when_no_trigger_applies(self):
        # This is the defect the canonical function fixes: the old
        # escalate-only helpers could raise row 024 but never lower it again.
        values = blank_values()
        values[24 - 1] = "BW"
        compute_bid_type_code(values)
        self.assertEqual(values[23], "BI")


class Rows52To55AidcRuleTests(TestCase):
    def test_value_flagged_when_not_aidc_solicitation(self):
        values = blank_values()
        values[2 - 1] = "F"
        for position in (52, 53, 54, 55):
            values[position - 1] = "100"
        error_positions = {position for position, _message in validate_rows_52_55_aidc(values)}
        self.assertEqual(error_positions, {52, 53, 54, 55})

    def test_values_accepted_when_aidc_solicitation(self):
        values = blank_values()
        values[2 - 1] = "I"
        for position in (52, 53, 54, 55):
            values[position - 1] = "100"
        self.assertEqual(validate_rows_52_55_aidc(values), [])

    def test_validate_requires_values_when_aidc_solicitation(self):
        values = blank_values()
        values[2 - 1] = "I"
        error_positions = {position for position, _message in validate_rows_52_55_aidc(values)}
        self.assertEqual(error_positions, {52, 53, 54, 55})

    def test_validate_passes_when_not_aidc_solicitation_and_blank(self):
        values = blank_values()
        values[2 - 1] = "F"
        self.assertEqual(validate_rows_52_55_aidc(values), [])


class ReviewFixRegressionTests(TestCase):
    def test_blank_child_labor_is_not_defaulted_to_n(self):
        values = blank_values()
        apply_rows_118_121_quality_labor_remarks_rules(values)
        self.assertEqual(values[119], "")

    def test_code_set_accepts_informational_only_free_trade_code(self):
        self.assertEqual(validate_code_set(69, "I"), "")
        self.assertEqual(validate_code_set(69, "B"), "")

    def test_code_set_rejects_unknown_code(self):
        self.assertTrue(validate_code_set(29, "XYZ"))
        self.assertTrue(validate_code_set(2, "X"))
        self.assertEqual(validate_code_set(2, ""), "")

    def test_field_length_over_maximum_is_flagged(self):
        values = blank_values()
        values[6 - 1] = "ABCDEF"
        self.assertEqual([p for p, _m in validate_field_lengths(values, {6: 5})], [6])

    def test_field_length_within_maximum_passes(self):
        values = blank_values()
        values[6 - 1] = "ABCDE"
        self.assertEqual(validate_field_lengths(values, {6: 5}), [])

    def _form_errors(self, cleaned):
        from django.forms.utils import ErrorDict
        form = UserUpdateForm()
        form.cleaned_data = dict(cleaned)
        form._errors = ErrorDict()
        form.clean()
        return set(form._errors.keys())

    def test_profile_cage_must_be_five_characters(self):
        errors = self._form_errors({'cage': 'ABCDEF', 'contract_number': '', 'agreement_type': '', 'agreement_expiry': None})
        self.assertIn('cage', errors)

    def test_profile_boa_requires_contract_number_and_expiry(self):
        errors = self._form_errors({'cage': '', 'contract_number': '', 'agreement_type': 'BOA', 'agreement_expiry': None})
        self.assertEqual(errors, {'contract_number', 'agreement_expiry'})

    def test_profile_nap_must_not_have_contract_or_expiry(self):
        errors = self._form_errors({'cage': '', 'contract_number': 'X1', 'agreement_type': 'NAP', 'agreement_expiry': date(2030, 1, 1)})
        self.assertEqual(errors, {'contract_number', 'agreement_expiry'})

    def test_profile_valid_boa_passes(self):
        errors = self._form_errors({'cage': '1ABC2', 'contract_number': 'SPE7-26-A-0001', 'agreement_type': 'BOA', 'agreement_expiry': date(2030, 1, 1)})
        self.assertEqual(errors, set())


class FullCoverageRuleTests(TestCase):
    def test_return_by_date_must_be_mm_dd_yyyy(self):
        values = blank_values()
        values[5 - 1] = "13/45/2026"
        self.assertEqual([p for p, _m in validate_field_formats(values)], [5])
        values[5 - 1] = "05/31/2026"
        self.assertEqual(validate_field_formats(values), [])

    def test_line_number_must_be_four_digits(self):
        values = blank_values()
        values[44 - 1] = "1"
        self.assertEqual([p for p, _m in validate_field_formats(values)], [44])
        values[44 - 1] = "0001"
        self.assertEqual(validate_field_formats(values), [])

    def test_purchase_request_must_be_ten_digits(self):
        values = blank_values()
        values[46 - 1] = "70184"
        self.assertEqual([p for p, _m in validate_field_formats(values)], [46])
        values[46 - 1] = "7018468781"
        self.assertEqual(validate_field_formats(values), [])

    def test_days_quote_valid_under_90_for_type_i_is_flagged(self):
        values = blank_values()
        values[2 - 1] = "I"
        values[27 - 1] = "60"
        self.assertEqual([p for p, _m in validate_field_formats(values)], [27])
        values[2 - 1] = "F"
        self.assertEqual(validate_field_formats(values), [])

    def test_rfq_match_flags_mismatched_solicitation_number(self):
        values = blank_values()
        values[1 - 1] = "SPE7L126T9999"
        sol = SimpleNamespace(solicitation="SPE7L1-26-T-6061", set_aside_code="N", deliver_fob="D",
                              inspection_point="D", solicitation_line_number="0001",
                              purchase_request_number="7018468781", pr=None, NSN="1234-56-789-0123",
                              part_number=None, unit="EA", higher_level_quality_indicator="N",
                              return_by_date="05/31/2026")
        positions = {p for p, _m in validate_rfq_matches(values, sol)}
        self.assertIn(1, positions)

    def test_rfq_match_passes_when_values_agree(self):
        values = blank_values()
        values[1 - 1] = "SPE7L126T6061"
        values[3 - 1] = "N"
        values[5 - 1] = "05/31/2026"
        values[32 - 1] = "D"
        values[36 - 1] = "D"
        values[44 - 1] = "0001"
        values[46 - 1] = "7018468781"
        values[47 - 1] = "1234567890123"
        values[48 - 1] = "EA"
        values[117 - 1] = "N"
        sol = SimpleNamespace(solicitation="SPE7L1-26-T-6061", set_aside_code="N", deliver_fob="DESTINATION",
                              inspection_point="DESTINATION", solicitation_line_number="0001",
                              purchase_request_number="7018468781", pr=None, NSN="1234-56-789-0123",
                              part_number=None, unit="EA", higher_level_quality_indicator="N",
                              return_by_date="05/31/2026")
        positions = {p for p, _m in validate_rfq_matches(values, sol)}
        self.assertFalse(positions & {1, 3, 5, 32, 36, 44, 46, 47, 48, 117})

    def test_uncaptured_rfq_indicators_always_flagged(self):
        positions = {p for p, _m in validate_rfq_matches(blank_values(), None)}
        self.assertTrue({4, 62, 68, 69, 77, 105} <= positions)

    def test_quantity_variance_above_rfq_permission_forces_bw(self):
        values = blank_values()
        values[2 - 1] = "F"
        values[24 - 1] = "BI"
        values[96 - 1] = "15"
        compute_bid_type_code(values, requirement_variance_plus="10", requirement_variance_minus="10")
        self.assertEqual(values[23], "BW")

    def test_quantity_variance_within_rfq_permission_keeps_bi(self):
        values = blank_values()
        values[2 - 1] = "F"
        values[96 - 1] = "5"
        compute_bid_type_code(values, requirement_variance_plus="10", requirement_variance_minus="10")
        self.assertEqual(values[23], "BI")


class ValidationFailureTests(TestCase):
    def test_internal_failure_is_reported_as_blocking_error(self):
        missing_fields = []
        record_validation_failure(missing_fields, "Row 49", ValueError("boom"))
        self.assertEqual(len(missing_fields), 1)
        self.assertEqual(missing_fields[0]['position'], 0)
        self.assertIn("boom", missing_fields[0]['column_name'])


class Row32FobPointTests(TestCase):
    def test_accepts_d_and_o(self):
        self.assertEqual(validate_row_32_fob_point("D"), "")
        self.assertEqual(validate_row_32_fob_point("O"), "")

    def test_rejects_other_codes_and_blank(self):
        self.assertTrue(validate_row_32_fob_point("X"))
        self.assertTrue(validate_row_32_fob_point(""))


class Row66HazardousWarningLabelTests(TestCase):
    def test_accepts_blank_and_codes_1_to_7(self):
        self.assertEqual(validate_row_66_hazardous_warning_label(""), "")
        for code in "1234567":
            self.assertEqual(validate_row_66_hazardous_warning_label(code), "")

    def test_rejects_unknown_code(self):
        self.assertTrue(validate_row_66_hazardous_warning_label("8"))


class Row65HazmatRuleTests(TestCase):
    def test_blank_is_flagged_not_defaulted(self):
        values = blank_values()
        self.assertTrue(validate_row_65_hazmat(values[65 - 1]))
        self.assertEqual(values[65 - 1], "")

    def test_validate_rejects_invalid_code(self):
        self.assertTrue(validate_row_65_hazmat("Maybe"))

    def test_validate_accepts_n_and_y(self):
        self.assertEqual(validate_row_65_hazmat("N"), "")
        self.assertEqual(validate_row_65_hazmat("Y"), "")

    def test_validate_requires_a_value(self):
        self.assertTrue(validate_row_65_hazmat(""))


class Row56NoDoMinimumRuleTests(TestCase):
    """Template pair this repo didn't have a test for before."""

    def test_blanked_when_not_aidc_solicitation(self):
        values = blank_values()
        values[2 - 1] = "F"
        values[56 - 1] = "Y"
        apply_row_56_no_do_minimum_rule(values)
        self.assertEqual(values[56 - 1], "")

    def test_validate_requires_y_or_n_when_aidc_solicitation(self):
        self.assertTrue(validate_row_56_no_do_minimum("", "I"))
        self.assertEqual(validate_row_56_no_do_minimum("Y", "I"), "")

    def test_validate_requires_blank_when_not_aidc_solicitation(self):
        self.assertTrue(validate_row_56_no_do_minimum("Y", "F"))
        self.assertEqual(validate_row_56_no_do_minimum("", "F"), "")


class ValidateMandatoryFieldsSmokeTest(TestCase):
    """
    validate_mandatory_fields() is the validator now wired into the real
    export call sites (previously dead code). This is a smoke test that it
    runs end-to-end against real DB objects (exercising the field_defs
    dict-lookup fix) rather than a full field-by-field fixture.
    """

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username="dla-test-vendor",
            password="test-pass-12345",
            email="vendor@example.com",
            companyName="Test Vendor Inc",
            phone="5555550100",
            address="123 Test St",
        )
        self.solicitation = Solicitation.objects.create(
            cage="1A2B3",
            nomenclature="Test Widget",
            quantity="10",
            NSN="1234-56-789-0123",
            issued_date="01/01/2026",
            return_by_date="02/01/2026",
        )

    def test_incomplete_reply_is_flagged_invalid_with_missing_fields(self):
        rfq_reply = RfqReply.objects.create(user=self.user)
        is_valid, missing_fields = validate_mandatory_fields(self.user, rfq_reply)
        self.assertFalse(is_valid)
        self.assertTrue(len(missing_fields) > 0)
        self.assertTrue(all("position" in field for field in missing_fields))


class ProfileComplianceTests(TestCase):
    def make_user(self, **overrides):
        profile = dict(
            is_as9100_certified=False, as9100_expiry=None,
            is_iso_9001_certified=False, iso_9001_expiry=None,
            is_as9003_certified=False, as9003_expiry=None,
            is_jcp_certified=False, jcp_expiry=None,
            is_qsl_certified=False, qsl_expiry=None,
            is_qpl_certified=False, qpl_expiry=None,
            is_qml_certified=False, qml_expiry=None,
            contract_number='', agreement_expiry=None,
        )
        profile.update(overrides)
        return SimpleNamespace(**profile)

    def make_values(self, **positions):
        values = ["" for _ in range(121)]
        for position, value in positions.items():
            values[int(position.lstrip('p')) - 1] = value
        return values

    def test_blank_118_filled_with_matching_current_certification(self):
        user = self.make_user(is_as9100_certified=True, as9100_expiry=date(2099, 1, 1))
        values = self.make_values(p117='8')
        derive_higher_level_quality_code(values, user)
        self.assertEqual(values[117], '8')

    def test_blank_118_becomes_none_when_certification_expired(self):
        user = self.make_user(is_as9100_certified=True, as9100_expiry=date(2000, 1, 1))
        values = self.make_values(p117='8')
        derive_higher_level_quality_code(values, user)
        self.assertEqual(values[117], '1')

    def test_existing_118_is_not_overwritten(self):
        user = self.make_user(is_as9100_certified=True, as9100_expiry=date(2099, 1, 1))
        values = self.make_values(p117='8', p118='2')
        derive_higher_level_quality_code(values, user)
        self.assertEqual(values[117], '2')

    def test_118_claiming_expired_certification_is_an_error(self):
        user = self.make_user(is_iso_9001_certified=True, iso_9001_expiry=date(2000, 1, 1))
        errors = validate_profile_compliance(user, self.make_values(p117='7', p118='7'))
        self.assertIn(118, [position for position, _ in errors])

    def test_118_claiming_current_certification_passes(self):
        user = self.make_user(is_iso_9001_certified=True, iso_9001_expiry=date(2099, 1, 1))
        errors = validate_profile_compliance(user, self.make_values(p117='7', p118='7'))
        self.assertEqual(errors, [])

    def test_qualification_cage_requires_current_qpl_qml_or_qsl(self):
        values = self.make_values(p112='1ABC2')
        none_current = validate_profile_compliance(self.make_user(), values)
        self.assertIn(112, [position for position, _ in none_current])
        qpl_current = self.make_user(is_qpl_certified=True, qpl_expiry=date(2099, 1, 1))
        self.assertEqual(validate_profile_compliance(qpl_current, values), [])

    def test_qpl_without_expiry_is_not_current(self):
        user = self.make_user(is_qpl_certified=True, qpl_expiry=None)
        errors = validate_profile_compliance(user, self.make_values(p112='1ABC2'))
        self.assertIn(112, [position for position, _ in errors])

    def test_agreement_requires_unexpired_date_and_contract_number(self):
        expired = self.make_user(contract_number='SPE1', agreement_expiry=date(2000, 1, 1))
        errors = validate_profile_compliance(expired, self.make_values(p29='BOA'))
        self.assertIn(31, [position for position, _ in errors])
        valid = self.make_user(contract_number='SPE1', agreement_expiry=date(2099, 1, 1))
        self.assertEqual(validate_profile_compliance(valid, self.make_values(p29='BOA')), [])

    def test_nap_agreement_is_not_checked(self):
        user = self.make_user()
        self.assertEqual(validate_profile_compliance(user, self.make_values(p29='NAP')), [])


class GetValuePositionThreeSetAsideTests(TestCase):
    """
    Regression coverage for a confirmed active defect found during the full
    121-field spec audit: extractSolicitations.py hardcodes is_set_aside=True
    on every scraped row regardless of the real solicitation, and get_value()
    used to trust that boolean (True -> "A"), so every solicitation without a
    detected set-aside clause exported field 3 as "A" (8(a) Set-Aside) instead
    of "N" (Unrestricted) - the spec's own stated default for a blank
    requirement. Position 3 now fully owns its value and never trusts a bare
    True.
    """

    def setUp(self):
        ExportFieldDefinition.ensure_all_fields_exist()
        self.user = CustomUser.objects.create_user(
            username="set-aside-test-vendor",
            password="test-pass-12345",
            email="set-aside-vendor@example.com",
            companyName="Test Vendor Inc",
            phone="5555550100",
            address="123 Test St",
        )
        field_def = ExportFieldDefinition.objects.get(position=3)
        self.config = UserExportConfiguration.objects.create(
            user=self.user, field_definition=field_def, is_enabled=True
        )

    def _solicitation(self, is_set_aside, set_aside_code=""):
        return Solicitation.objects.create(
            cage="1A2B3",
            nomenclature="Test Widget",
            quantity="10",
            NSN="1234-56-789-0123",
            issued_date="01/01/2026",
            return_by_date="02/01/2026",
            is_set_aside=is_set_aside,
            set_aside_code=set_aside_code,
        )

    def test_hardcoded_true_with_no_detected_clause_does_not_export_as_a(self):
        solicitation = self._solicitation(is_set_aside=True, set_aside_code="")
        self.assertEqual(self.config.get_value(solicitation), "")

    def test_explicit_false_exports_as_n(self):
        solicitation = self._solicitation(is_set_aside=False, set_aside_code="")
        self.assertEqual(self.config.get_value(solicitation), "N")

    def test_detected_set_aside_code_wins_regardless_of_boolean(self):
        solicitation = self._solicitation(is_set_aside=True, set_aside_code="L")
        self.assertEqual(self.config.get_value(solicitation), "L")


class NoCageSolicitationPageTests(TestCase):
    """
    Covers the no-CAGE manual-handling page end to end: the model's identity
    constraint, and the actual views (list, mark-handled toggle, CSV export)
    rather than just the scraper's raw SQL.

    reverse() includes the FORCE_SCRIPT_NAME prefix (e.g. /DLA), which in
    this project only nginx strips in production; the test client has no
    reverse proxy in front of it, so _path() strips it here instead.
    """

    def _path(self, url_name, *args):
        from django.conf import settings
        path = reverse(f'solicitations:{url_name}', args=args)
        prefix = (settings.FORCE_SCRIPT_NAME or '').rstrip('/')
        if prefix and path.startswith(prefix):
            path = path[len(prefix):] or '/'
        return path

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username="no-cage-test-user",
            password="test-pass-12345",
            email="no-cage-user@example.com",
            companyName="Test Vendor Inc",
            phone="5555550100",
            address="123 Test St",
        )
        self.other_user = CustomUser.objects.create_user(
            username="no-cage-other-user",
            password="test-pass-12345",
            email="no-cage-other@example.com",
            companyName="Other Vendor Inc",
            phone="5555550101",
            address="456 Test Ave",
        )
        self.client.force_login(self.user)
        self.record = NoCageSolicitation.objects.create(
            nsn="5306009998888",
            nomenclature="TEST NO-CAGE WIDGET",
            solicitation="SPE7L1-26-T-NOCAGE1",
            quantity="12",
            purchase_request="7018499999",
            issued_date="10/01/2026",
            return_by_date="11/01/2026",
        )

    def test_same_nsn_and_solicitation_cannot_be_inserted_twice(self):
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            NoCageSolicitation.objects.create(
                nsn=self.record.nsn, solicitation=self.record.solicitation,
            )

    def test_list_view_shows_active_record_by_default(self):
        response = self.client.get(self._path('no-cage-solicitations'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.record.nsn)
        self.assertContains(response, self.record.solicitation)

    def test_list_view_hides_active_record_from_handled_tab(self):
        response = self.client.get(self._path('no-cage-solicitations') + '?show=handled')
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, self.record.nsn)

    def test_search_matches_nsn(self):
        response = self.client.get(self._path('no-cage-solicitations') + f'?q={self.record.nsn}')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.record.nsn)

    def test_search_excludes_non_matching_records(self):
        response = self.client.get(self._path('no-cage-solicitations') + '?q=NO-SUCH-VALUE')
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, self.record.nsn)

    def test_mark_handled_creates_a_row_for_only_that_user(self):
        url = self._path('mark-no-cage-handled', self.record.pk)
        response = self.client.post(url, {'next': self._path('no-cage-solicitations')})
        self.assertEqual(response.status_code, 302)
        handling = NoCageSolicitationHandledBy.objects.get(solicitation=self.record)
        self.assertEqual(handling.user, self.user)
        self.assertIsNotNone(handling.handled_at)

    def test_list_page_next_field_carries_the_force_script_name_prefix(self):
        """
        request.get_full_path() reflects what Django itself received, which in
        production has /DLA already stripped by nginx. A hidden "next" field
        built from it would redirect to a prefix-less URL nginx won't route.
        The field must be built via {% url %} (which always includes
        FORCE_SCRIPT_NAME) instead, so the redirect lands on a URL nginx can serve.
        """
        from django.conf import settings
        response = self.client.get(self._path('no-cage-solicitations'))
        prefix = (settings.FORCE_SCRIPT_NAME or '').rstrip('/')
        self.assertIn(f'name="next" value="{prefix}/solicitations/no-cage-solicitations/"',
                       response.content.decode('utf-8'))

    def test_marking_handled_twice_toggles_back_to_unhandled(self):
        url = self._path('mark-no-cage-handled', self.record.pk)
        self.client.post(url)
        self.assertTrue(NoCageSolicitationHandledBy.objects.filter(
            solicitation=self.record, user=self.user).exists())

        self.client.post(url)
        self.assertFalse(NoCageSolicitationHandledBy.objects.filter(
            solicitation=self.record, user=self.user).exists())

    def test_one_user_marking_handled_does_not_affect_another_user(self):
        """
        The core requirement this model was built for: "handled" is scoped
        to the user who clicked it. Another user must still see the record
        as active, with no cross-contamination either direction.
        """
        self.client.post(self._path('mark-no-cage-handled', self.record.pk))

        # The user who marked it handled no longer sees it as active.
        my_active = self.client.get(self._path('no-cage-solicitations'))
        self.assertNotContains(my_active, self.record.nsn)
        my_handled = self.client.get(self._path('no-cage-solicitations') + '?show=handled')
        self.assertContains(my_handled, self.record.nsn)

        # A second user still sees it as active, and has nothing handled.
        self.client.force_login(self.other_user)
        their_active = self.client.get(self._path('no-cage-solicitations'))
        self.assertContains(their_active, self.record.nsn)
        their_handled = self.client.get(self._path('no-cage-solicitations') + '?show=handled')
        self.assertNotContains(their_handled, self.record.nsn)

        # The second user marking it handled doesn't touch the first user's status.
        self.client.post(self._path('mark-no-cage-handled', self.record.pk))
        self.assertEqual(
            NoCageSolicitationHandledBy.objects.filter(solicitation=self.record).count(), 2)
        self.assertTrue(NoCageSolicitationHandledBy.objects.filter(
            solicitation=self.record, user=self.user).exists())
        self.assertTrue(NoCageSolicitationHandledBy.objects.filter(
            solicitation=self.record, user=self.other_user).exists())

    def test_export_csv_contains_the_record(self):
        response = self.client.get(self._path('export-no-cage-solicitations'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv')
        body = response.content.decode('utf-8')
        self.assertIn(self.record.nsn, body)
        self.assertIn(self.record.purchase_request, body)

    def test_export_csv_handled_filter_excludes_active_record(self):
        response = self.client.get(self._path('export-no-cage-solicitations') + '?show=handled')
        self.assertEqual(response.status_code, 200)
        body = response.content.decode('utf-8')
        self.assertNotIn(self.record.nsn, body)

    def test_export_csv_is_scoped_to_the_requesting_user(self):
        """Another user's handled export must not include a record only I handled."""
        self.client.post(self._path('mark-no-cage-handled', self.record.pk))
        self.client.force_login(self.other_user)
        their_handled_export = self.client.get(
            self._path('export-no-cage-solicitations') + '?show=handled')
        self.assertNotIn(self.record.nsn, their_handled_export.content.decode('utf-8'))

    def test_detail_view_shows_full_record(self):
        response = self.client.get(self._path('no-cage-detail', self.record.pk))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.record.nsn)
        self.assertContains(response, self.record.purchase_request)
        self.assertContains(response, "Needs Action")

    def test_detail_view_reflects_my_handled_status_only(self):
        self.client.post(self._path('mark-no-cage-handled', self.record.pk))
        mine = self.client.get(self._path('no-cage-detail', self.record.pk))
        self.assertContains(mine, "you marked this handled on")

        self.client.force_login(self.other_user)
        theirs = self.client.get(self._path('no-cage-detail', self.record.pk))
        self.assertNotContains(theirs, "you marked this handled on")

    def test_list_row_no_longer_shows_purchase_request(self):
        """Purchase Request moved to the detail page; the list row should not print it."""
        response = self.client.get(self._path('no-cage-solicitations'))
        self.assertNotContains(response, self.record.purchase_request)


class GovernmentEmailSolicitationPageTests(TestCase):
    """
    Covers the government-email manual-handling page end to end, mirroring
    NoCageSolicitationPageTests: the model's identity constraint, and the
    actual views (list, mark-handled toggle, CSV export).
    """

    def _path(self, url_name, *args):
        from django.conf import settings
        path = reverse(f'solicitations:{url_name}', args=args)
        prefix = (settings.FORCE_SCRIPT_NAME or '').rstrip('/')
        if prefix and path.startswith(prefix):
            path = path[len(prefix):] or '/'
        return path

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username="gov-email-test-user",
            password="test-pass-12345",
            email="gov-email-user@example.com",
            companyName="Test Vendor Inc",
            phone="5555550102",
            address="123 Test St",
        )
        self.other_user = CustomUser.objects.create_user(
            username="gov-email-other-user",
            password="test-pass-12345",
            email="gov-email-other@example.com",
            companyName="Other Vendor Inc",
            phone="5555550103",
            address="456 Test Ave",
        )
        self.client.force_login(self.user)
        self.record = GovernmentEmailSolicitation.objects.create(
            nsn="5306009997777",
            cage="1AB23",
            email="buyer@army.mil",
            organization_name="US ARMY DEPOT",
            nomenclature="TEST GOV-EMAIL WIDGET",
            part_number="PN-12345",
            solicitation="SPE7L1-26-T-GOVEMAIL1",
            quantity="8",
            purchase_request="7018488888",
            issued_date="10/01/2026",
            return_by_date="11/01/2026",
        )

    def test_same_identity_cannot_be_inserted_twice(self):
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            GovernmentEmailSolicitation.objects.create(
                nsn=self.record.nsn, cage=self.record.cage,
                part_number=self.record.part_number, return_by_date=self.record.return_by_date,
                solicitation="SPE7L1-26-T-GOVEMAIL2",
            )

    def test_list_view_shows_active_record_by_default(self):
        response = self.client.get(self._path('government-email-solicitations'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.record.nsn)
        self.assertContains(response, self.record.cage)

    def test_list_view_hides_active_record_from_handled_tab(self):
        response = self.client.get(self._path('government-email-solicitations') + '?show=handled')
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, self.record.nsn)

    def test_search_matches_cage(self):
        response = self.client.get(self._path('government-email-solicitations') + f'?q={self.record.cage}')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.record.nsn)

    def test_search_excludes_non_matching_records(self):
        response = self.client.get(self._path('government-email-solicitations') + '?q=NO-SUCH-VALUE')
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, self.record.nsn)

    def test_mark_handled_creates_a_row_for_only_that_user(self):
        url = self._path('mark-government-email-handled', self.record.pk)
        response = self.client.post(url, {'next': self._path('government-email-solicitations')})
        self.assertEqual(response.status_code, 302)
        handling = GovernmentEmailSolicitationHandledBy.objects.get(solicitation=self.record)
        self.assertEqual(handling.user, self.user)
        self.assertIsNotNone(handling.handled_at)

    def test_list_page_next_field_carries_the_force_script_name_prefix(self):
        """Same FORCE_SCRIPT_NAME redirect bug as the no-CAGE list page (see that test)."""
        from django.conf import settings
        response = self.client.get(self._path('government-email-solicitations'))
        prefix = (settings.FORCE_SCRIPT_NAME or '').rstrip('/')
        self.assertIn(f'name="next" value="{prefix}/solicitations/government-email-solicitations/"',
                       response.content.decode('utf-8'))

    def test_marking_handled_twice_toggles_back_to_unhandled(self):
        url = self._path('mark-government-email-handled', self.record.pk)
        self.client.post(url)
        self.assertTrue(GovernmentEmailSolicitationHandledBy.objects.filter(
            solicitation=self.record, user=self.user).exists())

        self.client.post(url)
        self.assertFalse(GovernmentEmailSolicitationHandledBy.objects.filter(
            solicitation=self.record, user=self.user).exists())

    def test_one_user_marking_handled_does_not_affect_another_user(self):
        """
        Same requirement as the no-CAGE feature: "handled" is scoped to the
        user who clicked it, with no cross-contamination either direction.
        """
        self.client.post(self._path('mark-government-email-handled', self.record.pk))

        my_active = self.client.get(self._path('government-email-solicitations'))
        self.assertNotContains(my_active, self.record.nsn)
        my_handled = self.client.get(self._path('government-email-solicitations') + '?show=handled')
        self.assertContains(my_handled, self.record.nsn)

        self.client.force_login(self.other_user)
        their_active = self.client.get(self._path('government-email-solicitations'))
        self.assertContains(their_active, self.record.nsn)
        their_handled = self.client.get(self._path('government-email-solicitations') + '?show=handled')
        self.assertNotContains(their_handled, self.record.nsn)

        self.client.post(self._path('mark-government-email-handled', self.record.pk))
        self.assertEqual(
            GovernmentEmailSolicitationHandledBy.objects.filter(solicitation=self.record).count(), 2)
        self.assertTrue(GovernmentEmailSolicitationHandledBy.objects.filter(
            solicitation=self.record, user=self.user).exists())
        self.assertTrue(GovernmentEmailSolicitationHandledBy.objects.filter(
            solicitation=self.record, user=self.other_user).exists())

    def test_export_csv_contains_the_record(self):
        response = self.client.get(self._path('export-government-email-solicitations'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv')
        body = response.content.decode('utf-8')
        self.assertIn(self.record.nsn, body)
        self.assertIn(self.record.email, body)

    def test_export_csv_handled_filter_excludes_active_record(self):
        response = self.client.get(self._path('export-government-email-solicitations') + '?show=handled')
        self.assertEqual(response.status_code, 200)
        body = response.content.decode('utf-8')
        self.assertNotIn(self.record.nsn, body)

    def test_export_csv_is_scoped_to_the_requesting_user(self):
        """Another user's handled export must not include a record only I handled."""
        self.client.post(self._path('mark-government-email-handled', self.record.pk))
        self.client.force_login(self.other_user)
        their_handled_export = self.client.get(
            self._path('export-government-email-solicitations') + '?show=handled')
        self.assertNotIn(self.record.nsn, their_handled_export.content.decode('utf-8'))

    def test_detail_view_shows_full_record(self):
        response = self.client.get(self._path('government-email-detail', self.record.pk))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.record.nsn)
        self.assertContains(response, self.record.email)
        self.assertContains(response, self.record.organization_name.title())
        self.assertContains(response, self.record.purchase_request)
        self.assertContains(response, "Needs Action")

    def test_detail_view_reflects_my_handled_status_only(self):
        self.client.post(self._path('mark-government-email-handled', self.record.pk))
        mine = self.client.get(self._path('government-email-detail', self.record.pk))
        self.assertContains(mine, "you marked this handled on")

        self.client.force_login(self.other_user)
        theirs = self.client.get(self._path('government-email-detail', self.record.pk))
        self.assertNotContains(theirs, "you marked this handled on")

    def test_list_row_no_longer_shows_email_or_purchase_request(self):
        """Email/Purchase Request moved to the detail page; the list row should not print them."""
        response = self.client.get(self._path('government-email-solicitations'))
        self.assertNotContains(response, self.record.email)
        self.assertNotContains(response, self.record.purchase_request)
