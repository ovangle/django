from django.db.models.fields import *
from django.db.models.fields.composite import CompositeField


class ColorField(CompositeField):
    red = PositiveSmallIntegerField()
    green = PositiveSmallIntegerField()
    blue = PositiveSmallIntegerField()
    alpha = PositiveSmallIntegerField(null=True)


class PointField(CompositeField):
    x = FloatField()
    y = FloatField()

    def value_from_dict(self, value):
        if value is None:
            return None
        return (value['x'], value['y'])

    def value_to_dict(self, value):
        if value is None:
            return None
        if isinstance(value, tuple):
            return {
                'x': value[0],
                'y': value[1]
            }


class Money(object):
    def __init__(self, currency_code, amount):
        self.currency_code = currency_code
        self.amount = amount

    def __eq__(self, other):
        return (
            isinstance(other, Money)
            and other.currency_code == self.currency_code
            and other.amount == self.amount
        )


class MoneyField(CompositeField):
    """
    A field with arguments for the subfields
    """
    currency_code = CharField(max_length=3)
    amount = DecimalField()

    def __init__(self, amount_max_digits, amount_decimal_places=None, **kwargs):
        super(MoneyField, self).__init__(**kwargs)
        self.amount.decimal_places = amount_decimal_places
        self.amount.max_digits = amount_max_digits

    def deconstruct(self):
        name, path, args, kwargs = super(MoneyField, self).deconstruct()
        kwargs['amount_decimal_places'] = self.amount.decimal_places
        kwargs['amount_max_digits'] = self.amount.max_digits

    def value_from_dict(self, value):
        if value is None:
            return value
        return Money(**value)

    def value_to_dict(self, value):
        if value is None:
            return None
        return {
            'currency_code': value.currency_code,
            'amount': value.amount
        }
