from django.db import migrations


DEFAULT_TAGS = [
    'Marketing',
    'Social',
    'Blog',
    'Campaign',
    'Product',
    'Support',
    'Internal',
    'News',
]


def seed_tags(apps, schema_editor):
    """Create the default set of tags that every installation ships with."""
    Tag = apps.get_model('shortener', 'Tag')
    db_alias = schema_editor.connection.alias
    for name in DEFAULT_TAGS:
        Tag.objects.using(db_alias).get_or_create(name=name)


def remove_seeded_tags(apps, schema_editor):
    """Reverse migration: remove only the seeded tags."""
    Tag = apps.get_model('shortener', 'Tag')
    db_alias = schema_editor.connection.alias
    Tag.objects.using(db_alias).filter(name__in=DEFAULT_TAGS).delete()


class Migration(migrations.Migration):
    """Data migration: seed initial default tags."""

    dependencies = [
        ('shortener', '0002_module6_schema'),
    ]

    operations = [
        migrations.RunPython(seed_tags, reverse_code=remove_seeded_tags),
    ]
