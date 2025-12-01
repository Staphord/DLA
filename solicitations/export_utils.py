"""
Utility functions for exporting solicitation data to DLA format text files.
Generates comma-separated text files with 121 fields in exact positions.
"""
import csv
import os
from datetime import datetime
from io import StringIO
from django.conf import settings
from django.db.models import Prefetch
from .models import ExportFieldDefinition, UserExportConfiguration, Solicitation


def get_export_directory():
    """
    Get the directory where export files should be stored.
    Creates the directory if it doesn't exist.

    Returns:
        str: Absolute path to export directory
    """
    # Use MEDIA_ROOT/exports or create exports/ in project root
    if hasattr(settings, 'MEDIA_ROOT') and settings.MEDIA_ROOT:
        export_dir = os.path.join(settings.MEDIA_ROOT, 'exports')
    else:
        # Fallback to project root/exports
        export_dir = os.path.join(settings.BASE_DIR, 'exports')

    # Create directory if it doesn't exist
    os.makedirs(export_dir, exist_ok=True)

    return export_dir


def generate_export_filename(user, prefix='dla_export'):
    """
    Generate a unique filename for export.

    Args:
        user: User object
        prefix: Filename prefix (default: 'dla_export')

    Returns:
        str: Filename with timestamp and username
    """
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    username = user.username.replace(' ', '_')
    return f"{prefix}_{username}_{timestamp}.txt"


def generate_export_line(user, solicitation):
    """
    Generate a single export line for a solicitation with 121 fields.

    Args:
        user: User object for configuration lookup
        solicitation: Solicitation object to export

    Returns:
        String with comma-separated values (121 fields)
    """
    # Get user's export configurations for all 121 fields
    configurations = UserExportConfiguration.objects.filter(
        user=user
    ).select_related('field_definition').order_by('field_definition__position')

    # If user has no configurations, create default ones
    if not configurations.exists():
        create_default_configurations(user)
        configurations = UserExportConfiguration.objects.filter(
            user=user
        ).select_related('field_definition').order_by('field_definition__position')

    # Generate values for all 121 positions
    values = []
    for config in configurations:
        value = config.get_value(solicitation)
        values.append(value)

    # Ensure we have exactly 121 fields
    while len(values) < 121:
        values.append("")

    # Convert to CSV format with proper quoting
    output = StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_ALL)
    writer.writerow(values)

    # Return the line without the trailing newline
    return output.getvalue().strip()


def generate_export_file(user, solicitations):
    """
    Generate complete export file for multiple solicitations.

    Args:
        user: User object for configuration lookup
        solicitations: QuerySet or list of Solicitation objects

    Returns:
        String containing the complete export file content
    """
    lines = []
    for solicitation in solicitations:
        line = generate_export_line(user, solicitation)
        lines.append(line)

    return '\n'.join(lines)


def create_default_configurations(user):
    """
    Create default export configurations for a user.
    Maps common Solicitation and RfqReply fields to export positions.
    Ensures all 121 fields are configured.
    """
    # Get all field definitions - should be exactly 121
    field_definitions = ExportFieldDefinition.objects.all().order_by('position')
    
    if field_definitions.count() != 121:
        # Log warning but continue - user might need to run populate_export_fields
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(
            f"Expected 121 ExportFieldDefinition records, found {field_definitions.count()}. "
            "Run: python manage.py populate_export_fields"
        )

    # Get existing configurations for this user
    existing_configs = UserExportConfiguration.objects.filter(user=user)
    existing_field_ids = set(existing_configs.values_list('field_definition_id', flat=True))

    # Default field mappings for Solicitation (position -> source_field)
    solicitation_mappings = {
        1: 'solicitation',  # Solicitation Number
        5: 'return_by_date',  # Return By Date
        6: 'cage',  # Quoter CAGE Code
        7: 'cage',  # Quote for CAGE Code
        44: '',  # Solicitation Line Number (to be filled per line)
        46: 'pr',  # Purchase Request Number
        47: 'NSN',  # National Stock Number / Part Number
        48: 'unit',  # Unit of Issue
        49: 'quantity',  # Quantity
    }
    
    # Default field mappings for RfqReply (position -> source_field)
    # These will be used when exporting RFQ replies
    rfq_reply_mappings = {
        1: 'solicitation_number',  # Solicitation Number
        5: 'received_date',  # Return By Date (use received_date)
        6: 'user.cage',  # Quoter CAGE Code (from user)
        7: 'user.cage',  # Quote for CAGE Code (from user)
        44: '',  # Solicitation Line Number
        46: '',  # Purchase Request Number
        47: 'nsn',  # National Stock Number / Part Number
        48: 'unit',  # Unit of Issue
        49: 'quantity',  # Quantity
        50: 'unit_price',  # Unit Price
        51: '',  # Delivery Days
    }

    # Create configurations only for missing fields
    configurations = []
    for field_def in field_definitions:
        # Skip if configuration already exists
        if field_def.id in existing_field_ids:
            continue
            
        # Use RfqReply mapping if available, otherwise Solicitation mapping
        source_field = rfq_reply_mappings.get(
            field_def.position, 
            solicitation_mappings.get(field_def.position, '')
        )

        config = UserExportConfiguration(
            user=user,
            field_definition=field_def,
            is_enabled=True,
            source_field=source_field,
            custom_value=''
        )
        configurations.append(config)

    # Bulk create missing configurations
    if configurations:
        UserExportConfiguration.objects.bulk_create(
            configurations, ignore_conflicts=True)


def export_solicitations_to_file(user, solicitations, file_path=None, filename=None):
    """
    Export solicitations to a text file.

    Args:
        user: User object for configuration lookup
        solicitations: QuerySet or list of Solicitation objects
        file_path: Full path where to save the export file (optional)
        filename: Just the filename (will be saved in exports directory) (optional)

    Returns:
        dict: {
            'count': Number of solicitations exported,
            'file_path': Full path to the exported file,
            'filename': Name of the exported file
        }
    """
    content = generate_export_file(user, solicitations)

    # Determine the file path
    if file_path:
        # Use provided full path
        full_path = file_path
    elif filename:
        # Use provided filename in exports directory
        export_dir = get_export_directory()
        full_path = os.path.join(export_dir, filename)
    else:
        # Generate automatic filename in exports directory
        export_dir = get_export_directory()
        filename = generate_export_filename(user)
        full_path = os.path.join(export_dir, filename)

    # Ensure directory exists
    os.makedirs(os.path.dirname(full_path), exist_ok=True)

    # Write the file
    with open(full_path, 'w', encoding='utf-8') as f:
        f.write(content)

    return {
        'count': len(solicitations),
        'file_path': full_path,
        'filename': os.path.basename(full_path)
    }


def generate_export_line_for_rfq_reply(user, rfq_reply):
    """
    Generate a single export line for an RFQ reply with 121 fields.

    Args:
        user: User object for configuration lookup
        rfq_reply: RfqReply object to export

    Returns:
        String with comma-separated values (121 fields), all quoted
    """
    # Get user's export configurations for all 121 fields
    configurations = UserExportConfiguration.objects.filter(
        user=user
    ).select_related('field_definition').order_by('field_definition__position')

    # If user has no configurations, create default ones
    if not configurations.exists():
        create_default_configurations(user)
        configurations = UserExportConfiguration.objects.filter(
            user=user
        ).select_related('field_definition').order_by('field_definition__position')

    # Generate values for all 121 positions
    values = []
    for config in configurations:
        value = config.get_value(rfq_reply)
        values.append(value)

    # Ensure we have exactly 121 fields
    while len(values) < 121:
        values.append("")
    
    # Truncate to exactly 121 fields if somehow we have more
    if len(values) > 121:
        values = values[:121]

    # Convert to CSV format with proper quoting (all fields quoted like sample.txt)
    output = StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_ALL, lineterminator='')
    writer.writerow(values)
    
    # Get the line and ensure it's complete
    line = output.getvalue()
    
    # Verify we have exactly 120 commas (for 121 fields)
    comma_count = line.count(',')
    if comma_count != 120:
        # If we don't have the right number of commas, something went wrong
        # Rebuild the line manually to ensure completeness
        quoted_values = [f'"{str(v)}"' for v in values]
        line = ','.join(quoted_values)
    
    return line


def generate_export_file_for_rfq_replies(user, rfq_replies):
    """
    Generate complete export file for multiple RFQ replies.

    Args:
        user: User object for configuration lookup
        rfq_replies: QuerySet or list of RfqReply objects

    Returns:
        String containing the complete export file content
    """
    lines = []
    for rfq_reply in rfq_replies:
        line = generate_export_line_for_rfq_reply(user, rfq_reply)
        # Verify line has exactly 121 fields (120 commas)
        comma_count = line.count(',')
        if comma_count != 120:
            # If line is incomplete, pad with empty fields
            current_fields = line.split(',')
            while len(current_fields) < 121:
                current_fields.append('""')
            line = ','.join(current_fields)
        lines.append(line)

    # Join with newlines and ensure file ends with newline
    content = '\n'.join(lines)
    if content and not content.endswith('\n'):
        content += '\n'
    return content


def export_rfq_replies_to_file(user, rfq_replies, file_path=None, filename=None):
    """
    Export RFQ replies to a text file.

    Args:
        user: User object for configuration lookup
        rfq_replies: QuerySet or list of RfqReply objects
        file_path: Full path where to save the export file (optional)
        filename: Just the filename (will be saved in exports directory) (optional)

    Returns:
        dict: {
            'count': Number of RFQ replies exported,
            'file_path': Full path to the exported file,
            'filename': Name of the exported file
        }
    """
    content = generate_export_file_for_rfq_replies(user, rfq_replies)

    # Determine the file path
    if file_path:
        # Use provided full path
        full_path = file_path
    elif filename:
        # Use provided filename in exports directory
        export_dir = get_export_directory()
        full_path = os.path.join(export_dir, filename)
    else:
        # Generate automatic filename in exports directory
        export_dir = get_export_directory()
        filename = generate_export_filename(user, prefix='rfq_replies_export')
        full_path = os.path.join(export_dir, filename)

    # Ensure directory exists
    os.makedirs(os.path.dirname(full_path), exist_ok=True)

    # Write the file
    with open(full_path, 'w', encoding='utf-8') as f:
        f.write(content)

    return {
        'count': len(rfq_replies) if hasattr(rfq_replies, '__len__') else rfq_replies.count(),
        'file_path': full_path,
        'filename': os.path.basename(full_path)
    }


def get_user_field_mapping(user):
    """
    Get user's current field mapping configuration.

    Args:
        user: User object

    Returns:
        Dictionary with position as key and configuration details as value
    """
    configurations = UserExportConfiguration.objects.filter(
        user=user
    ).select_related('field_definition').order_by('field_definition__position')

    mapping = {}
    for config in configurations:
        mapping[config.field_definition.position] = {
            'column_name': config.field_definition.column_name,
            'field_type': config.field_definition.field_type,
            'is_enabled': config.is_enabled,
            'source_field': config.source_field,
            'custom_value': config.custom_value,
            'default_value': config.field_definition.default_value,
        }

    return mapping
