import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    """
    Module 6 schema changes:
      - Tag model
      - URL model expanded (owner, click_count, is_active, expires_at,
        title, description, favicon, tags M2M, created_at, updated_at)
      - Click model (full analytics logging)
    """

    dependencies = [
        ('shortener', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # ---- Tag -------------------------------------------------------
        migrations.CreateModel(
            name='Tag',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=50, unique=True)),
            ],
            options={'ordering': ['name']},
        ),

        # ---- Expand URL ------------------------------------------------
        migrations.AddField(
            model_name='url',
            name='custom_alias',
            field=models.CharField(blank=True, max_length=50, null=True, unique=True),
        ),
        migrations.AddField(
            model_name='url',
            name='owner',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='urls',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name='url',
            name='is_active',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='url',
            name='expires_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='url',
            name='click_count',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='url',
            name='title',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name='url',
            name='description',
            field=models.CharField(blank=True, max_length=500, null=True),
        ),
        migrations.AddField(
            model_name='url',
            name='favicon',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name='url',
            name='tags',
            field=models.ManyToManyField(blank=True, related_name='urls', to='shortener.tag'),
        ),
        migrations.AddField(
            model_name='url',
            name='created_at',
            field=models.DateTimeField(auto_now_add=True, db_index=True,
                                       default=django.utils.timezone.now),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='url',
            name='updated_at',
            field=models.DateTimeField(auto_now=True),
        ),
        migrations.AlterModelOptions(
            name='url',
            options={'ordering': ['-created_at']},
        ),

        # ---- Click model -----------------------------------------------
        migrations.CreateModel(
            name='Click',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name='ID')),
                ('clicked_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('ip_address', models.GenericIPAddressField(blank=True, null=True)),
                ('city', models.CharField(blank=True, max_length=100, null=True)),
                ('country', models.CharField(blank=True, max_length=100, null=True)),
                ('user_agent', models.TextField(blank=True, null=True)),
                ('referrer', models.URLField(blank=True, null=True)),
                ('url', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='click_set',
                    to='shortener.url',
                )),
            ],
            options={'ordering': ['-clicked_at']},
        ),
    ]
