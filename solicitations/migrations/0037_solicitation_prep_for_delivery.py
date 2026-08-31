from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('solicitations', '0036_bidreferencetemplate'),
    ]

    operations = [
        migrations.AddField(
            model_name='solicitation',
            name='prep_for_delivery',
            field=models.TextField(blank=True),
        ),
    ]
