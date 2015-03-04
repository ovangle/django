from django.core import exceptions
from django.db import models
from django.db.models.fields.composite import CompositeField
from .fields import ColorField, PointField, MoneyField


class Rectangle(models.Model):
    origin = PointField()
    width = models.IntegerField()
    height = models.IntegerField()
    fill = ColorField()
    stroke = ColorField(null=True)

    stroke_weight = models.IntegerField()


class StockItem(models.Model):
    name = models.CharField(max_length=32)
    price = MoneyField(amount_decimal_places=4, amount_max_digits=6)


class ModelWithNullCompositeField(models.Model):
    name = models.CharField(max_length=32)
    field = PointField(null=True)


class ModelWithUniqueCompositeField(models.Model):
    name = models.CharField(max_length=32)
    field = ColorField(unique=True)


class ModelWithCompositePrimaryKey(models.Model):
    id = ColorField(primary_key=True)


class ModelWithIndexedCompositeField(models.Model):
    color = ColorField(db_index=True)


class ModelWithInlineCompositeField(models.Model):
    a = CompositeField(
        fields=[
            ('aa', models.CharField(max_length=32)),
            ('ab', models.IntegerField()),
        ]
    )


class ModelWithInvalidFields():
    try:
        field = ColorField(fields=[('extra_field')])
    except exceptions.FieldError as e:
        pass

    try:
        field2 = CompositeField(
            fields=[('invalid_char_(#)_in_field_name', models.BooleanField())]
        )
    except exceptions.FieldError as e:
        pass
