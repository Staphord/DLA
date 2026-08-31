from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('solicitations', '0010_rename_solicitatio_user_id_31fd40_idx_solicitatio_user_id_fc6f7c_idx'),
    ]

    operations = [
        migrations.CreateModel(
            name='OEMImportJob',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(choices=[('queued', 'Queued'), ('running', 'Running'), ('completed', 'Completed'), ('error', 'Error')], default='queued', max_length=20)),
                ('original_filename', models.CharField(blank=True, default='', max_length=255)),
                ('file_path', models.TextField(blank=True, default='')),
                ('failed_download_url', models.TextField(blank=True, default='')),
                ('error_message', models.TextField(blank=True, default='')),
                ('processed', models.PositiveIntegerField(default=0)),
                ('total', models.PositiveIntegerField(default=0)),
                ('added_active', models.PositiveIntegerField(default=0)),
                ('updated_active', models.PositiveIntegerField(default=0)),
                ('disabled', models.PositiveIntegerField(default=0)),
                ('skipped', models.PositiveIntegerField(default=0)),
                ('errors', models.PositiveIntegerField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='oem_import_jobs', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'indexes': [models.Index(fields=['user', 'status', 'created_at'], name='solicitatio_user_id_2d9d4f_idx')],
            },
        ),
    ]

