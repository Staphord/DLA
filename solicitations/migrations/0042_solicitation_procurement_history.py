# Generated manually for procurement_history field

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('solicitations', '0041_alter_solicitation_is_set_aside'),
    ]

    operations = [
        migrations.AddField(
            model_name='solicitation',
            name='procurement_history',
            field=models.JSONField(blank=True, default=list, help_text='List of procurement history records with CAGE, Contract Number, Quantity, Unit Cost, AWD Date, and Surplus Material'),
        ),
    ]

