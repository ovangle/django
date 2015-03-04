import collections
import copy
import re
from itertools import chain
from operator import itemgetter

from django.core import checks, exceptions
from django.db.models.fields import Field, BooleanField
from django.db.models.lookups import Exact, LessThan
from django.utils.functional import cached_property
from django.utils import six


class CompositeFieldBase(type):
    def __new__(cls, name, bases, attrs):
        new_class = super(CompositeFieldBase, cls).__new__(
            cls, name, bases, attrs
        )
        subfields = {}
        for attr_name, attr in attrs.items():
            if isinstance(attr, Field):
                subfields[attr_name] = attr
        if subfields:
            new_class._cls_subfields = subfields
        return new_class


class CompositeField(six.with_metaclass(CompositeFieldBase, Field)):
    # Field flags
    composite = True

    def __init__(self, fields=None, **kwargs):
        super(CompositeField, self).__init__(**kwargs)
        self.descriptor = CompositeFieldDescriptor(self)

        if hasattr(self, '_cls_subfields'):
            # Copy the subfields defined on the class to the current instance
            subfields = self._cls_subfields
        elif fields is not None:
            subfields = dict(fields)
        else:
            raise exceptions.FieldError(
                'Cannot provide both static and inline composite fields'
            )

        for name, field in subfields.items():
            if not re.match(r'[_a-zA-Z][_a-zA-Z0-9]*', name):
                raise exceptions.FieldError(
                    'field name %s is not a valid python identifier'
                    % name
                )
            field.name = name

        subfields = {
            field_name: Subfield(copy.deepcopy(field), self)
            for field_name, field in subfields.items()
        }

        # Having a null value for a composite field is different from having
        # a null value for any of it's subfields.
        # Always add this extra hidden, auto_created subfield
        if not 'isnull' in subfields:
            field = BooleanField(name='isnull', default=self.null)
            field.hidden = True

            subfields['isnull'] = Subfield(field, self)

        # Make sure subfields in self._subfields are ordered by field
        # and ordered by creation
        self._all_subfields = collections.OrderedDict(
            sorted(subfields.items(), key=itemgetter(1))
        )

    @cached_property
    def _subfields(self):
        return collections.OrderedDict(
            (name, field)
            for name, field in self._all_subfields.items()
            if not field.hidden
        )

    def get_lookup_constraint(self, query, alias, targets, sources,
                              lookups, raw_value):
        from django.db.models.sql.where import AND
        constraint_class = query.where_class
        root_constraint = constraint_class()

        isnull_field = self._all_subfields['isnull']
        value_not_null = Exact(isnull_field.get_col(alias), False)

        if lookups[0] in self._subfields:
            # We could be looking at a nested lookup of one of the subfields
            subfield = self._subfields[lookups[0]]
            lookup = query.build_lookup(
                lookups[1:] or ['exact'], subfield.get_col(alias), raw_value
            )
            # Doing a lookup for a specific subfield should require the compisite
            # value to not be None
            root_constraint.add(value_not_null, AND)
            root_constraint.add(lookup, AND)
            return root_constraint

        if len(lookups) > 1:
            raise exceptions.FieldError(
                '%s is not a subfield of %s' % (lookups[0], self)
            )
        lookup_type = lookups[0]

        if lookup_type == 'isnull':
            condition = Exact(isnull_field.get_col(alias), raw_value)
            root_constraint.add(condition, AND)
        elif lookup_type == 'exact' and raw_value is None:
            condition = Exact(isnull_field.get_col(alias), True)
            root_constraint.add(condition, AND)
        elif lookup_type == 'exact':
            value = self.value_to_dict(raw_value)
            root_constraint.add(value_not_null, AND)
            for name, field in self._subfields.items():
                if name not in value:
                    continue
                condition = Exact(
                    field.get_col(alias),
                    field.get_prep_value(value[name])
                )
                root_constraint.add(condition, AND)
        else:
            raise TypeError('Composite field got invalid lookup: %s')
        return root_constraint

    def db_type(self, connection):
        # A composite field has no database type as it is a colleciton of
        # multiple database columns that share a common
        return None

    def get_attname_column(self):
        return self.get_attname(), None

    def get_subfield(self, field_name):
        try:
            return self._subfields[field_name]
        except KeyError:
            raise exceptions.FieldDoesNotExist(
                '%s has no field named %r' % (self.composite_field, field_name))

    def get_subfields(self):
        from django.db.models.options import make_immutable_fields_list
        return make_immutable_fields_list("%s.get_subfields" % self,
                                          self._subfields.values())

    def contribute_to_class(self, cls, name, virtual_only=False):
        super(CompositeField, self).contribute_to_class(
            cls, name, virtual_only=True
        )

        setattr(cls, self.attname, self.descriptor)

        add_fields = all(
            base._meta.abstract or self not in base._meta.fields
            for base in cls._meta.get_parent_list()
        )
        if add_fields:
            for field_name, field in self._all_subfields.items():
                field.contribute_to_class(cls, field_name, virtual_only=False)

        if self.unique and not self.primary_key:
            cls._meta.unique_together.append(tuple(
                '%s__%s' % (self.name, subfield_name)
                for subfield_name in self._subfields.keys()
            ))

        if self.db_index:
            cls._meta.index_together.append(tuple(
                '%s__%s' % (self.name, subfield_name)
                for subfield_name in self._subfields.keys()
            ))

    def to_python(self, value):
        raise NotImplementedError()

    def value_to_string(self, value):
        raise NotImplementedError()

    def get_prep_value(self, value):
        raise NotImplementedError()

    def value_to_dict(self, value):
        """
        Returns the value as a dict mapping subfield names to their respective
        values.

        Subclasses should override this method
        """
        return value

    def value_from_dict(self, value):
        """
        Converts the value from a dict mapping subfield names to their respective
        values into a python object

        Subclasses should override this method
        """
        if not isinstance(value, collections.Mapping):
            raise TypeError('Not a dict-like object: {0}'.format(value))
        return value

    def pre_save(self, model_instance, add):
        return self.value_from_object(model_instance)

    def __deepcopy__(self, memodict):
        obj = super(CompositeField, self).__deepcopy__(memodict)
        for subfield_name, subfield in self._subfields.items():
            field_copy = copy.deepcopy(subfield.field, memodict)
            obj._subfields[subfield_name] = Subfield(field_copy, obj)
        return obj

    def check(self, **kwargs):
        return chain(
            super(CompositeField, self).check(**kwargs),
            self._check_no_db_column(),
            self._check_no_default(),
            chain.from_iterable(subfield.check(**kwargs)
                                for subfield in self._subfields.values),
        )

    def _check_no_db_column(self):
        if self.db_column is not None:
            yield checks.Error(
                'CompositeField cannot declare a db_column',
                hint='Declare db_columns on the subfields of the composite '
                     'field, or initialize the composite field with db_column '
                     'arguments for the specific subfields',
                obj=self,
                code='fields.E401'
            )

    def _check_no_default(self):
        if self.has_default():
            yield checks.Error(
                'Cannot provide a default value for a composite field',
                hint='Declare default values for each of the subfields of the'
                     'composite field, or declare null=True',
                obj=self,
                code='fields.402'
            )

    def _check_nullable_composite_field(self):
        if self.null and self.db_index:
            yield checks.Error(
                'An indexed composite field cannot be nullable',
                hint="Set 'null=True' or 'db_index=False' on the field",
                obj=self,
                code='fields.403'
            )
        if self.null and self.unique:
            yield checks.Error(
                'A unique composite field cannot be nullable',
                hint=("Set 'null=True', 'unique=False' or 'primary_key=False' "
                      "on the field"),
                obj = self,
                code='fields.404'
            )

    def get_field_value(self, model_instance, use_default=True):
        """
        Get the current value for the composite field.
        Returns None or a dict of subfield names to their current values.

        Subclasses of composite field should override this method.
        """
        if self.null:
            isnull_field = self._all_subfields['isnull']
            if isnull_field.get_field_value(model_instance, use_default=True):
                return None
        value = {
            name: field.get_field_value(model_instance, use_default=use_default)
            for name, field in self._subfields.items() if name != 'isnull'
        }
        return self.value_from_dict(value)

    def set_field_value(self, model_instance, value):
        """
        Set the current value of the composite field.
        Value should either be None or a mapping of subfield names to
        values.

        If any subfield does not exist as a value in the mapping, the subfield
        value will not be set.

        Subclasses of composite field should override this method.
        """
        value = self.value_to_dict(value)

        if not self.null and value in self.empty_values:
            raise exceptions.ValidationError(
                'Field \'%s\' cannot be None' % self,
                code='null'
            )
        isnull_field = self._all_subfields['isnull']
        isnull_field.set_field_value(model_instance, value is None)
        if value not in self.empty_values:
            for name, field in self._subfields.items():
                if name not in value:
                    continue
                field.set_field_value(model_instance, value[name])


class Subfield(Field):

    # Attributes to set on the subfield, rather than the field that is being
    # wrapped by the subfield.
    _subfield_attributes = {
        'field',
        'composite_field',
    }

    def __init__(self, field, composite_field):
        self.field = field
        self.composite_field = composite_field

    def deconstruct(self):
        name, path, args, kwargs = super(Subfield, self).deconstruct()
        return name, path, [], {'field': self.field.deconstruct()}

    @cached_property
    def creation_counter(self):
        return self.composite_field.creation_counter

    @cached_property
    def subfield_creation_counter(self):
        # Use the order of creation of the wrapped fields to determine
        # the subfield's creation order.
        return self.field.creation_counter

    @property
    def hidden(self):
        return self.field.hidden

    def _get_name(self):
        name = '%s__%s' % (self.composite_field.name, self.field.name)
        if name == 'amount__price':
            assert False
        return name

    def _set_name(self, value):
        if not '__' in value:
            raise ValueError('Invalid name for composite field')
        composite_name, subfield_name = value.split('__', 1)
        self.composite_field.name = composite_name
        self.field.name = subfield_name

    name = property(_get_name, _set_name)

    @property
    def null(self):
        return self.composite_field.null or self.field.null

    @property
    def editable(self):
        return self.composite_field.editable and self.field.editable

    def db_type(self, connection):
        return self.field.db_type(connection)

    def get_attname(self):
        return self.name

    def __getattr__(self, attr):
        """
        Delegate calls to any attributes which may be present on the wrapped
        and not overriden here
        """
        return getattr(self.field, attr)

    def __setattr__(self, attr, value):
        if attr in self.__dict__ or attr in self._subfield_attributes:
            self.__dict__[attr] = value
        else:
            setattr(self.field, attr, value)

    def contribute_to_class(self, cls, name, virtual_only=False):
        super(Subfield, self).contribute_to_class(
            cls, name, virtual_only=virtual_only
        )

    def clone(self):
        name, path, args, kwargs = self.deconstruct()

    def check(self, **kwargs):
        ## Checks are performed on the wrapped field
        return chain(
            self.field.check(**kwargs),
            self._check_not_relation_field(),
            self._check_not_composite_field(),
            self._check_not_primary_key(),
        )

    def _check_field_name(self):
        for err in super(Subfield, self)._check_field_name():
            yield err
        if self.name == 'isnull' and not self.auto_created:
            yield checks.Error(
                '\'isnull\' is a reserved name for a subfield',
                obj=self,
                code='fields.E402'
            )

    def _check_not_primary_key(self):
        if self.primary_key:
            yield checks.Error(
                'A subfield of a composite field cannot be a primary key',
                hint='Set primary_key=False on the field, or make the '
                     'composite field a primary key',
                obj=self,
                code='fields.E403')

    def _check_not_relation_field(self):
        if self.is_relation:
            yield checks.Error(
                'A subfield of a composite field cannot be a relation',
                hint=None,
                obj=self.field,
                code='fields.E404'
            )

    def _check_not_composite_field(self):
        if self.composite:
            yield checks.Error(
                'A subfield of a composite field cannot be a composite field',
                hint=None,
                obj=self.field,
                code='fields.E405'
            )

    def __copy__(self):
        raise NotImplementedError()

    def __str__(self):
        ## Return app_label.model_name.field_name.subfield_name
        return '%s.%s' % (str(self.composite_field), self.name)


class CompositeFieldDescriptor(object):
    def __init__(self, composite_field):
        self.composite_field = composite_field

    def __get__(self, obj, type=None):
        return self.composite_field.get_field_value(obj, use_default=True)

    def __set__(self, obj, value):
        return self.composite_field.set_field_value(obj, value)
