from decimal import Decimal

from django.core import exceptions
from django.db.utils import IntegrityError
from django.test import TestCase

from . import models
from .fields import Money


class CompositeFieldDescriptorTest(TestCase):
    def test_model_init(self):
        rectangle = models.Rectangle(
            origin=(0, 0),
            width=40,
            height=40,
            fill={
                'red': 134,
                'blue': 244,
                'green': 266
            },
            stroke=None,
            stroke_weight=24
        )
        self.assertEqual(rectangle.origin, (0, 0))
        self.assertEqual(rectangle.origin__x, 0)
        self.assertEqual(rectangle.origin__y, 0)
        self.assertEqual(rectangle.width, 40)
        self.assertEqual(rectangle.height, 40)
        self.assertEqual(rectangle.fill, {
            'red': 134,
            'blue': 244,
            'green': 266,
            'alpha': None
        })
        self.assertEqual(rectangle.fill__red, 134)
        self.assertEqual(rectangle.fill__alpha, None)
        self.assertEqual(rectangle.stroke, None)
        # This is a hidden field, but test it anyway
        self.assertEqual(rectangle.stroke__isnull, True)

        rectangle.save()

    def test_get_set_value(self):
        stock_item = models.StockItem(
            price=Money('AUD', Decimal('4.00'))
        )
        self.assertEqual(stock_item.price, Money('AUD', Decimal('4.00')))
        with self.assertRaises(exceptions.ValidationError):
            stock_item.price = None

    def test_save_restore_value(self):
        stock_item = models.StockItem(price=Money('AUD', Decimal('4.02')))
        stock_item.save()
        db_stock_item = models.StockItem.objects.get(pk=stock_item.pk)
        self.assertEqual(db_stock_item.price, Money('AUD', Decimal('4.02')))

    def test_query_item(self):
        items = [
            models.StockItem(name='item_1',
                             price=Money('EUR', Decimal('4.50'))),
            models.StockItem(name='item_2',
                             price=Money('EUR', Decimal('10.00'))),
            models.StockItem(name='item_3',
                             price=Money('USD', Decimal('12.04')))
        ]
        for item in items:
            item.save()
        item = models.StockItem.objects.filter(price__currency_code='USD').get()
        self.assertEqual(item.price, Money('USD', Decimal('12.04')))
        qs = models.StockItem.objects.filter(
            price__currency_code='EUR',
            price__amount__gt=Decimal('4.00'),
            price__amount__lt=Decimal('13.00')
        ).all()
        self.assertEquals(
            set(item.name for item in qs),
            {'item_1', 'item_2'}
        )

    def test_query_exact(self):
        price = Money('ADF', Decimal('4.45'))
        item = models.StockItem(name='item', price=price)
        item.save()
        fetch_item = models.StockItem.objects.filter(price=price).get()
        self.assertEqual(fetch_item.name, 'item')
        self.assertEqual(fetch_item.price, price)

    def test_query_isnull(self):
        model_cls = models.ModelWithNullCompositeField
        items = [
            model_cls(name='item_1'),
            model_cls(name='item_2', field=(0, 0))
        ]
        for item in items:
            item.save()
        fetch_item = model_cls.objects.filter(field__isnull=True).get()
        self.assertEqual(fetch_item.name, 'item_1')
        fetch_item = model_cls.objects.filter(field__isnull=False).get()
        self.assertEqual(fetch_item.name, 'item_2')

    def test_composite_unique(self):
        model_cls = models.ModelWithUniqueCompositeField
        color = {
            'red': 134,
            'green': 134,
            'blue': 145,
            'alpha': 155
        }
        item = model_cls(name='item_1', field=color)
        item.save()
        item2 = model_cls(name='item_2', field=color)
        with self.assertRaises(IntegrityError):
            item2.save()


