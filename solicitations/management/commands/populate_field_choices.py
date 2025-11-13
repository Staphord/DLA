"""
Management command to populate predefined choices for export fields.
"""
import json
from django.core.management.base import BaseCommand
from solicitations.models import ExportFieldDefinition


class Command(BaseCommand):
    help = 'Populate predefined choices for export fields that have dropdown options'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Populating predefined choices for export fields...'))
        
        # Define fields with predefined choices
        field_choices = {
            3: {  # Small Business Set Aside Indicator
                'choices': [
                    {'value': '', 'label': '-- Select --'},
                    {'value': 'Y', 'label': 'Y - Small Business Set-Aside'},
                    {'value': 'H', 'label': 'H - HUBZone Set-Aside'},
                    {'value': 'R', 'label': 'R - Service Disabled Veteran-Owned Small Business (SDVOSB) Set-Aside'},
                    {'value': 'L', 'label': 'L - Woman Owned Small Business (WOSB) Set-Aside'},
                    {'value': 'A', 'label': 'A - 8a Set-Aside'},
                    {'value': 'E', 'label': 'E - Economically Disadvantaged Woman Owned Small Business (EDWOSB) Set-Aside'},
                    {'value': 'N', 'label': 'N - Unrestricted/Not Set-Aside'},
                ]
            },
            2: {  # Solicitation Type Indicator
                'choices': [
                    {'value': '', 'label': '-- Select --'},
                    {'value': 'F', 'label': 'F - Fast Auto Evaluation'},
                    {'value': 'I', 'label': 'I - Automated Indefinite Delivery Contract (AIDC)'},
                    {'value': 'P', 'label': 'P - Auto Evaluation'},
                ]
            },
            4: {  # Additional Clause Fill-Ins Indicator
                'choices': [
                    {'value': '', 'label': '-- Select --'},
                    {'value': 'N', 'label': 'N - No'},
                    {'value': 'Y', 'label': 'Y - Yes'},
                ]
            },
            13: {  # Small Business and Other Contractor Representations Code
                'choices': [
                    {'value': '', 'label': '-- Select --'},
                    {'value': 'A', 'label': 'A - Large Business/Other Business'},
                    {'value': 'B', 'label': 'B - Small Business'},
                    {'value': 'C', 'label': 'C - Nonprofit Institution'},
                    {'value': 'E', 'label': 'E - Educational Institution (other than HBCU or Minority)'},
                    {'value': 'F', 'label': 'F - Historically Black College or University (HBCU)'},
                    {'value': 'G', 'label': 'G - JWOD Participating Nonprofit Agency'},
                    {'value': 'M', 'label': 'M - Small Disadvantaged Business'},
                    {'value': 'P', 'label': 'P - Minority Institution (other than HBCU)'},
                    {'value': 'X', 'label': 'X - Intragovernmental'},
                ]
            },
            18: {  # Joint Venture
                'choices': [
                    {'value': '', 'label': '-- Select --'},
                    {'value': 'JV', 'label': 'JV - Is a Joint Venture that complies with 13 CFR Part 121.103(h) and 13 CFR Part 125'},
                    {'value': 'JN', 'label': 'JN - Is not a Joint Venture that complies with 13 CFR Part 121.103(h) and 13 CFR Part 125'},
                ]
            },
            21: {  # Affirmative Action Compliance Code
                'choices': [
                    {'value': '', 'label': '-- Select --'},
                    {'value': 'Y6', 'label': 'Y6 - Developed and on File'},
                    {'value': 'N6', 'label': 'N6 - Not Developed and Not on File'},
                    {'value': 'NH', 'label': 'NH - No Previous Contracts Subject to Requirements'},
                    {'value': 'NA', 'label': 'NA - Not Applicable'},
                ]
            },
            22: {  # Previous Contracts and Compliance Reports Code
                'choices': [
                    {'value': '', 'label': '-- Select --'},
                    {'value': 'Y4', 'label': 'Y4 - Participated and Filed'},
                    {'value': 'Y5', 'label': 'Y5 - Participated and Not Filed'},
                    {'value': 'N4', 'label': 'N4 - Not Participated'},
                    {'value': 'NA', 'label': 'NA - Not Applicable'},
                ]
            },
            23: {  # Alternate Disputes Resolution
                'choices': [
                    {'value': '', 'label': '-- Select --'},
                    {'value': 'Y', 'label': 'Y - Yes'},
                    {'value': 'N', 'label': 'N - No'},
                ]
            },
        }
        
        updated_count = 0
        
        for position, data in field_choices.items():
            try:
                field_def = ExportFieldDefinition.objects.get(position=position)
                field_def.predefined_choices = json.dumps(data['choices'])
                field_def.save()
                updated_count += 1
                self.stdout.write(
                    self.style.SUCCESS(
                        f'  ✓ Updated field {position:03d}: {field_def.column_name} '
                        f'({len(data["choices"])} choices)'
                    )
                )
            except ExportFieldDefinition.DoesNotExist:
                self.stdout.write(
                    self.style.WARNING(f'  ✗ Field {position:03d} not found')
                )
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f'  ✗ Error updating field {position:03d}: {str(e)}')
                )
        
        self.stdout.write(
            self.style.SUCCESS(f'\n✓ Successfully updated {updated_count} fields with predefined choices')
        )

