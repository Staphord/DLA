"""
Management command to extract and populate validation choices from index.html
into the ExportFieldDefinition model's predefined_choices field.
"""
import re
import json
from html import unescape
from django.core.management.base import BaseCommand
from solicitations.models import ExportFieldDefinition


class Command(BaseCommand):
    help = 'Extract validation choices from index.html and populate predefined_choices field'

    def extract_valid_codes(self, validation_text):
        """Extract valid codes from validation text like 'Valid X codes: Y - Yes, N - No'"""
        codes = []
        
        # First, unescape HTML entities
        validation_text = unescape(validation_text)
        
        # Pattern: "Valid ... codes:" followed by code-description pairs
        # The codes are typically separated by <br> tags
        valid_pattern = r'Valid\s+[^:]+codes?:\s*(.*?)(?:<br><br>|$)'
        match = re.search(valid_pattern, validation_text, re.IGNORECASE | re.DOTALL)
        
        if match:
            codes_text = match.group(1)
            
            # Split by <br> tags to get individual code lines
            # Pattern: CODE - Description<br> or CODE - Description\n
            # Handle both <br> and newline separators
            code_lines = re.split(r'<br>|</br>', codes_text)
            
            seen_codes = set()
            for line in code_lines:
                line = line.strip()
                if not line:
                    continue
                
                # Pattern: CODE - Description
                # CODE can be 1-10 characters (alphanumeric)
                # Description can contain spaces, parentheses, etc.
                code_pattern = r'^([A-Z0-9]{1,10})\s*-\s*(.+)$'
                code_match = re.match(code_pattern, line, re.IGNORECASE)
                
                if code_match:
                    code = code_match.group(1).strip().upper()
                    desc = code_match.group(2).strip()
                    
                    # Skip if we've seen this code already
                    if code in seen_codes:
                        continue
                    seen_codes.add(code)
                    
                    # Clean up description - remove extra whitespace
                    desc = re.sub(r'\s+', ' ', desc).strip()
                    
                    if desc:
                        codes.append({
                            'value': code,
                            'label': f"{code} - {desc}"
                        })
        
        # If no codes found with the main pattern, try a more flexible approach
        if not codes and 'Valid' in validation_text and 'codes:' in validation_text:
            # Extract everything after "codes:"
            after_valid = validation_text.split('codes:')[-1]
            # Remove HTML tags but keep structure
            after_valid = re.sub(r'<[^>]+>', '\n', after_valid)
            
            # Look for patterns like "CODE - Description" on separate lines
            flexible_pattern = r'([A-Z0-9]{1,10})\s*-\s*([^\n]+)'
            additional_matches = re.finditer(flexible_pattern, after_valid, re.IGNORECASE | re.MULTILINE)
            
            seen_codes = set()
            for match in additional_matches:
                code = match.group(1).strip().upper()
                desc = match.group(2).strip()
                
                if code in seen_codes or len(code) == 0:
                    continue
                seen_codes.add(code)
                
                desc = re.sub(r'\s+', ' ', desc).strip()
                # Skip if description is too short (likely not a real code)
                if desc and len(desc) > 1:
                    codes.append({
                        'value': code,
                        'label': f"{code} - {desc}"
                    })
        
        return codes

    def parse_html(self):
        """Parse index.html and extract validation choices for each field"""
        try:
            with open('index.html', 'r', encoding='utf-8') as f:
                html = f.read()
        except FileNotFoundError:
            self.stdout.write(self.style.ERROR('index.html not found in current directory'))
            return {}
        
        rows = re.findall(r'<tr[^>]*>.*?</tr>', html, re.DOTALL)
        
        field_choices = {}
        for row in rows:
            # Extract row number
            row_match = re.search(r'#r(\d+)', row)
            if not row_match:
                continue
            
            row_num = int(row_match.group(1))
            
            # Extract column name
            col_match = re.search(r'<td headers="h3">(.*?)</td>', row, re.DOTALL)
            col_name = ''
            if col_match:
                col_name = re.sub(r'<[^>]+>', '', unescape(col_match.group(1))).strip()
            
            # Extract validation
            validation_match = re.search(r'<td headers="h7">(.*?)</td>', row, re.DOTALL)
            if validation_match:
                validation_text = validation_match.group(1)
                
                # Extract valid codes
                codes = self.extract_valid_codes(validation_text)
                if codes:
                    field_choices[row_num] = {
                        'column_name': col_name,
                        'choices': codes
                    }
        
        return field_choices

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Extracting validation choices from index.html...'))
        
        field_choices = self.parse_html()
        
        if not field_choices:
            self.stdout.write(self.style.WARNING('No validation choices found in index.html'))
            return
        
        self.stdout.write(self.style.SUCCESS(f'Found {len(field_choices)} fields with validation choices'))
        
        # Update ExportFieldDefinition records
        updated_count = 0
        for position, data in field_choices.items():
            try:
                field_def = ExportFieldDefinition.objects.get(position=position)
                
                # Convert choices to JSON
                choices_json = json.dumps(data['choices'], indent=2)
                
                # Update predefined_choices field
                field_def.predefined_choices = choices_json
                field_def.save()
                
                updated_count += 1
                self.stdout.write(
                    self.style.SUCCESS(
                        f'Updated position {position:03d} ({data["column_name"]}): '
                        f'{len(data["choices"])} choices'
                    )
                )
            except ExportFieldDefinition.DoesNotExist:
                self.stdout.write(
                    self.style.WARNING(
                        f'ExportFieldDefinition with position {position} not found. Skipping.'
                    )
                )
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(
                        f'Error updating position {position}: {str(e)}'
                    )
                )
        
        self.stdout.write(
            self.style.SUCCESS(
                f'\nSuccessfully updated {updated_count} field definitions with validation choices.'
            )
        )

