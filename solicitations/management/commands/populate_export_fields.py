"""
Django management command to populate ExportFieldDefinition from index.html
"""
from django.core.management.base import BaseCommand
from solicitations.models import ExportFieldDefinition
from bs4 import BeautifulSoup
import os


class Command(BaseCommand):
    help = 'Populate ExportFieldDefinition table from index.html'

    def add_arguments(self, parser):
        parser.add_argument(
            '--file',
            type=str,
            default='index.html',
            help='Path to index.html file (default: index.html in project root)'
        )

    def handle(self, *args, **options):
        file_path = options['file']
        
        if not os.path.exists(file_path):
            self.stdout.write(self.style.ERROR(f'File not found: {file_path}'))
            return
        
        self.stdout.write(f'Reading field definitions from {file_path}...')
        
        # Parse HTML file
        with open(file_path, 'r', encoding='utf-8') as f:
            html_content = f.read()
        
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Find all table rows (skip header row)
        rows = soup.find_all('tr', valign='top')
        
        created_count = 0
        updated_count = 0
        
        for row in rows:
            try:
                cells = row.find_all('td')
                if len(cells) < 8:
                    continue
                
                # Extract data from cells
                position_text = cells[0].get_text(strip=True)
                quote_level = cells[1].get_text(strip=True)
                column_name = cells[2].get_text(strip=True)
                max_length_text = cells[3].get_text(strip=True)
                input_code = cells[4].get_text(strip=True)
                definition = cells[5].get_text(strip=True)
                validation = cells[6].get_text(strip=True)
                default_value = cells[7].get_text(strip=True)
                
                # May affect bid type (if column 9 exists)
                may_affect_bid_type = False
                if len(cells) > 8:
                    bid_type_text = cells[8].get_text(strip=True)
                    may_affect_bid_type = 'Yes' in bid_type_text or 'yes' in bid_type_text
                
                # Parse position number
                try:
                    position = int(position_text)
                except ValueError:
                    continue
                
                # Parse max length
                try:
                    max_length = int(max_length_text)
                except ValueError:
                    max_length = 0
                
                # Map input code to field type
                field_type_map = {
                    'Mandatory': 'mandatory',
                    'Conditional': 'conditional',
                    'Optional': 'optional',
                    '': 'reserved',
                }
                field_type = field_type_map.get(input_code, 'optional')
                
                # Check if RESERVED
                if 'RESERVED' in column_name.upper():
                    field_type = 'reserved'
                
                # Map quote level
                quote_level_map = {
                    'Header': 'header',
                    'Line': 'line',
                    'Product': 'product',
                }
                quote_level_value = quote_level_map.get(quote_level, '')
                
                # Create or update field definition
                field_def, created = ExportFieldDefinition.objects.update_or_create(
                    position=position,
                    defaults={
                        'column_name': column_name,
                        'quote_level': quote_level_value,
                        'field_type': field_type,
                        'max_length': max_length,
                        'definition': definition,
                        'validation_rules': validation,
                        'default_value': default_value,
                        'may_affect_bid_type': may_affect_bid_type,
                    }
                )
                
                if created:
                    created_count += 1
                    self.stdout.write(f'  [+] Created field {position:03d}: {column_name}')
                else:
                    updated_count += 1
                    self.stdout.write(f'  [~] Updated field {position:03d}: {column_name}')
                
            except Exception as e:
                self.stdout.write(self.style.WARNING(f'  [!] Error processing row: {str(e)}'))
                continue
        
        self.stdout.write(self.style.SUCCESS(
            f'\nCompleted! Created: {created_count}, Updated: {updated_count}'
        ))
        
        # Show summary
        total_fields = ExportFieldDefinition.objects.count()
        mandatory_count = ExportFieldDefinition.objects.filter(field_type='mandatory').count()
        conditional_count = ExportFieldDefinition.objects.filter(field_type='conditional').count()
        optional_count = ExportFieldDefinition.objects.filter(field_type='optional').count()
        reserved_count = ExportFieldDefinition.objects.filter(field_type='reserved').count()
        
        self.stdout.write(f'\nTotal fields in database: {total_fields}')
        self.stdout.write(f'  - Mandatory: {mandatory_count}')
        self.stdout.write(f'  - Conditional: {conditional_count}')
        self.stdout.write(f'  - Optional: {optional_count}')
        self.stdout.write(f'  - Reserved: {reserved_count}')

