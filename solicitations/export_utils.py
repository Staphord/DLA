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
    Maps common Solicitation fields to export positions.
    """
    # Get all field definitions
    field_definitions = ExportFieldDefinition.objects.all().order_by('position')

    # Default field mappings (position -> source_field)
    default_mappings = {
        1: 'solicitation',  # Solicitation Number
        5: 'return_by_date',  # Return By Date
        6: 'cage',  # Quoter CAGE Code
        7: 'cage',  # Quote for CAGE Code
        44: '',  # Solicitation Line Number (to be filled per line)
        46: 'pr',  # Purchase Request Number
        47: 'NSN',  # National Stock Number / Part Number
        48: 'unit',  # Unit of Issue
        49: 'quantity',  # Quantity
        # Add more mappings as needed
    }

    # Create configurations for all fields
    configurations = []
    for field_def in field_definitions:
        source_field = default_mappings.get(field_def.position, '')

        config = UserExportConfiguration(
            user=user,
            field_definition=field_def,
            is_enabled=True,
            source_field=source_field,
            custom_value=''
        )
        configurations.append(config)

    # Bulk create all configurations
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
