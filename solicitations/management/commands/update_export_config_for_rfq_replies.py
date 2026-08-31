"""
Management command to update existing export configurations with RfqReply source field mappings.
"""
from django.core.management.base import BaseCommand
from solicitations.models import UserExportConfiguration, ExportFieldDefinition


class Command(BaseCommand):
    help = 'Update export configurations with RfqReply source field mappings'

    def handle(self, *args, **options):
        self.stdout.write('Updating export configurations with RfqReply source field mappings...')
        
        # RfqReply field mappings (position -> source_field)
        rfq_reply_mappings = {
            1: 'solicitation_number',  # Solicitation Number
            5: 'received_date',  # Return By Date (use received_date)
            6: 'user.cage',  # Quoter CAGE Code (from user)
            7: 'user.cage',  # Quote for CAGE Code (from user)
            47: 'nsn',  # National Stock Number / Part Number
            48: 'unit',  # Unit of Issue
            49: 'quantity',  # Quantity
            50: 'unit_price',  # Unit Price
            51: '',  # Delivery Days (not in RfqReply)
        }
        
        updated_count = 0
        
        # Get all field definitions
        for position, source_field in rfq_reply_mappings.items():
            try:
                field_def = ExportFieldDefinition.objects.get(position=position)
                
                # Update all user configurations for this field
                configs = UserExportConfiguration.objects.filter(
                    field_definition=field_def
                )
                
                for config in configs:
                    # Only update if source_field is empty and custom_value is empty
                    # This preserves user's custom values
                    if not config.source_field and not config.custom_value:
                        config.source_field = source_field
                        config.save()
                        updated_count += 1
                
                self.stdout.write(
                    self.style.SUCCESS(
                        f'Updated position {position:03d} ({field_def.column_name}): '
                        f'{configs.count()} configurations'
                    )
                )
            except ExportFieldDefinition.DoesNotExist:
                self.stdout.write(
                    self.style.WARNING(f'Field definition for position {position} not found')
                )
        
        self.stdout.write(
            self.style.SUCCESS(f'\nUpdated {updated_count} export configurations with source field mappings.')
        )

