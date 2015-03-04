from .models import Rectangle

from django.db.models.fields.composite import Subfield
from django.test import TestCase

class SubfieldTest(TestCase):

    def setUp(self):
        self.rectangle_fields = Rectangle._meta.get_fields()

    def get_field(self, model_cls, name):
        assert hasattr(model_cls, '_meta')
        return model_cls._meta.get_field(name)

    def get_subfield(self, model_cls, composite_field_name, subfield_name):
        composite_field = self.get_field(model_cls, composite_field_name)
        return composite_field._all_subfields[subfield_name]

    def test_subfield_basic(self):
        subfield = self.get_subfield(Rectangle, 'fill', 'blue')
        self.assertFalse(subfield.auto_created)
        for field in Rectangle._meta.get_fields(include_hidden=True):
            if field is subfield:
                break
        else:
            self.fail('Subfield fill_blue not in model._meta fields')

    def test_auto_created_field(self):
        isnull_subfield = self.get_subfield(Rectangle, 'stroke', 'isnull')
        self.assertEqual(isnull_subfield.name, 'stroke__isnull')
        self.assertTrue(isnull_subfield.hidden)

    def test_attname_column(self):
        subfield = self.get_subfield(Rectangle, 'fill', 'blue')
        self.assertEqual(
            subfield.get_attname_column(),
            ('fill__blue', 'fill__blue')
        )

    def test_subfield_ordering(self):
        # A subfield should be larger than its owning field
        fill_field = self.get_field(Rectangle, 'fill')
        fill__blue_field = self.get_subfield(Rectangle, 'fill', 'blue')

        # The creation_counter should be the same as the owning field
        self.assertEqual(
            fill_field.creation_counter,
            fill__blue_field.creation_counter)
        # so the subfield should be greater than the field.
        self.assertGreater(fill__blue_field, fill_field)

        # A subfield should be smaller than the following field
        self.assertLess(fill_field, self.get_field(Rectangle, 'stroke'))

        fill__red_field = self.get_subfield(Rectangle, 'fill', 'red')
        fill__green_field = self.get_subfield(Rectangle, 'fill', 'green')

        # A subfield should compare less than the next field in it's field
        # definition
        self.assertLess(fill__red_field , fill__green_field)
        self.assertLess(fill__green_field, fill__blue_field)












