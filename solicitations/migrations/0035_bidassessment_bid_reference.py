from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('solicitations', '0034_add_estimated_profit_to_bid_assessment'),
    ]

    operations = [
        migrations.AddField(
            model_name='bidassessment',
            name='bid_reference',
            field=models.CharField(blank=True, max_length=50, null=True),
        ),
    ]
