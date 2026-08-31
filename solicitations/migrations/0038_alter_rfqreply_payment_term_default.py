from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('solicitations', '0037_solicitation_prep_for_delivery'),
    ]

    operations = [
        migrations.AlterField(
            model_name='rfqreply',
            name='payment_term',
            field=models.CharField(blank=True, default='', max_length=20),
        ),
    ]
