"""stac_fastapi.types.search module.

# TODO: replace with stac-pydantic
"""
from datetime import datetime
from geojson_pydantic.geometries import (
    GeometryCollection,
    LineString,
    MultiLineString,
    MultiPoint,
    MultiPolygon,
    Point,
    Polygon,
    _GeometryBase,
)
from pydantic.datetime_parse import parse_datetime
from stac_pydantic.api.extensions.sort import SortExtension

import logging
from typing import Any, Dict, List, Optional, Set, Union, Tuple
from pydantic import (
    BaseModel,
    Field,
    ValidationError,
    conint,
    root_validator,
    validator,
)
from pydantic.error_wrappers import ErrorWrapper

# from stac_pydantic.api.extensions.fields import FieldsExtension as FieldsBase
from stac_pydantic.shared import BBox
from stac_fastapi.types.config import Settings
from stac_fastapi.sqlalchemy.config import (
    BaseQueryables,
    SkraafotosProperties,
)

from pygeofilter.parsers.cql_json import parse as parse_json
import pygeofilter.parsers.cql_json as pgf_cql_json
from pygeofilter import ast

from stac_fastapi.extensions.core.crs import CrsExtension

# Be careful: https://github.com/samuelcolvin/pydantic/issues/1423#issuecomment-642797287
NumType = Union[float, int]


class Queryables:
    base_queryables = [q.value for q in BaseQueryables]
    collections = {
        "skraafotos2017": SkraafotosProperties,
        "skraafotos2019": SkraafotosProperties,
        "skraafotos2021": SkraafotosProperties,
        # "test-collection": SkraafotosProperties,
    }

    @classmethod
    def get_queryable(cls, name):
        if name in BaseQueryables._value2member_map_:
            return BaseQueryables(name)
        for c in cls.collections.values():
            if name in c._value2member_map_:
                return c(name)

    @classmethod
    def get_queryable_properties_intersection(
        cls, collection_ids: List = []
    ) -> Tuple[List, List]:
        if len(collection_ids) == 0:
            collection_ids = (
                cls.collections.keys()
            )  # empty defaults to intersection across all collections
        all_queryables = []
        for collection in collection_ids:
            if collection in cls.collections:
                all_queryables.append(
                    [
                        q.value
                        for q in cls.collections[collection]
                        if q not in cls.base_queryables
                    ]
                )

        shared_queryables = (
            set.intersection(*[set(x) for x in all_queryables])
            if len(all_queryables) > 0
            else set()
        )
        return cls.base_queryables, list(shared_queryables)

    @classmethod
    def get_all_queryables(cls) -> List[str]:
        all_queryables = cls.base_queryables
        for collection in cls.collections.values():
            all_queryables = all_queryables + [q.value for q in collection]
        return list(set(all_queryables))


class FieldsExtension(BaseModel):
    """FieldsExtension.

    Attributes:
        include: set of fields to include.
        exclude: set of fields to exclude.
    """

    include: Optional[Set[str]] = set()
    exclude: Optional[Set[str]] = set()

    @staticmethod
    def _get_field_dict(fields: Optional[Set[str]]) -> Dict:
        """Pydantic include/excludes notation.

        Internal method to create a dictionary for advanced include or exclude of pydantic fields on model export
        Ref: https://pydantic-docs.helpmanual.io/usage/exporting_models/#advanced-include-and-exclude
        """
        field_dict = {}
        for field in fields or []:
            if "." in field:
                parent, key = field.split(".")
                if parent not in field_dict:
                    field_dict[parent] = {key}
                else:
                    field_dict[parent].add(key)
            else:
                field_dict[field] = ...  # type:ignore
        return field_dict

    @property
    def filter_fields(self) -> Dict:
        """Create pydantic include/exclude expression.

        Create dictionary of fields to include/exclude on model export based on the included and excluded fields passed
        to the API
        Ref: https://pydantic-docs.helpmanual.io/usage/exporting_models/#advanced-include-and-exclude
        """
        # Always include default_includes, even if they
        # exist in the exclude list.
        include = (self.include or set()) - (self.exclude or set())
        include |= Settings.get().default_includes or set()

        return {
            "include": self._get_field_dict(include),
            "exclude": self._get_field_dict(self.exclude),
        }


class STACSearch(BaseModel):
    """Search model."""

    # Parameter from stac_pydantic.api.Search are written into this class so we can control which parameters to expose
    ids: Optional[List[str]]
    bbox: Optional[BBox]
    intersects: Optional[
        Union[
            Point,
            MultiPoint,
            LineString,
            MultiLineString,
            Polygon,
            MultiPolygon,
            GeometryCollection,
        ]
    ]
    datetime: Optional[str]
    sortby: Optional[List[SortExtension]]

    # Make collections optional, default to searching all collections if none are provided
    collections: Optional[List[str]] = None

    # field and query parameters are omitted since query is no longer used, and FieldExtension is disabled for now
    # field: Optional[FieldsExtension] = Field(None, alias="fields")
    # query: Optional[Dict[Queryables, Dict[Operator, Any]]]

    # Override crs extension with supported crs
    crs: Optional[str] = None
    bbox_crs: Optional[str] = Field(alias="bbox-crs")
    pt: Optional[str] = None
    limit: Optional[conint(gt=0, le=1000)] = 10
    filter_crs: Optional[str] = Field(
        "http://www.opengis.net/def/crs/OGC/1.3/CRS84", alias="filter-crs"
    )
    filter_lang: Optional[str] = Field("cql-json", alias="filter-lang")
    filter: Optional[Any]
    filter_fields: Optional[List[str]] = None

    class Config:
        """Configures the pydantic model to allow populating it by field names (in addition to aliases)

        We use the alias to specify what the param should be called in the API. BUT the aliases
        are NOT VALID python names so we cannot use them for populating the instance"""

        allow_population_by_field_name = True

    @classmethod
    def add_filter_crs(cls, data, crs):
        """Add filter-crs to geometry objects in filter

        Args:
            data: The data to recursively traverse.

        Returns:
            None.
        """

        if isinstance(data, list):
            for val in data:
                cls.add_filter_crs(val, crs)
        elif isinstance(data, dict):
            if data.get("type") in (
                "Polygon",
                "LineString",
                "Point",
                "MultiPolygon",
                "MultiLineString",
                "MultiPoint",
            ):
                data["crs"] = crs
            else:
                for key, value in data.items():
                    cls.add_filter_crs(value, crs)

    @classmethod
    def inOrderFieldCollect_rec(cls, expr) -> list:
        """Collect all properties from the given expression

        Args:
            expr: The abstract syntax tree to traverse.

        Returns:
            A list of properties.
        """

        res = []
        if expr:
            if type(expr) == ast.Attribute:
                res.append(expr.name)
                return res
            if type(expr) == ast.Not:
                res = cls.inOrderFieldCollect_rec(expr.sub_node)
            if hasattr(expr, "lhs"):
                res = cls.inOrderFieldCollect_rec(expr.lhs)
            if hasattr(expr, "rhs"):
                res = res + cls.inOrderFieldCollect_rec(expr.rhs)
        return res

    @classmethod
    def validate_filter_fields(cls, expr, valid_fields):
        """Validate fields in filter expression

        Args:
            expr: The abstract syntax tree to traverse.
            valid_fields: A list of valid fields to check against

        Returns:
            None.
        """

        res = list(set(cls.inOrderFieldCollect_rec(expr)))
        for field_name in res:
            if field_name not in valid_fields:
                raise ValidationError(
                    [
                        ErrorWrapper(
                            ValueError(f"Cannot search on field: {field_name}"),
                            "STACSearch",
                        )
                    ],
                    STACSearch,
                )
        return res

    @classmethod
    def inOrderOpsCollect_rec(cls, expr, pgf_ops) -> list:
        """Collect all operations from the given expression

        Args:
            expr: The abstract syntax tree to traverse.

        Returns:
            A list of operations.
        """

        res = []
        if expr:
            if type(expr) in pgf_ops.values():
                res.append(expr.op.name.lower())
            if type(expr) == ast.Not:
                res = res + cls.inOrderOpsCollect_rec(expr.sub_node, pgf_ops)
            if hasattr(expr, "lhs"):
                res = res + cls.inOrderOpsCollect_rec(expr.lhs, pgf_ops)
            if hasattr(expr, "rhs"):
                res = res + cls.inOrderOpsCollect_rec(expr.rhs, pgf_ops)
        return res

    @classmethod
    def validate_filter_ops(cls, expr, valid_ops):
        """Validate oeprations in filter expression

        Args:
            expr: The abstract syntax tree to traverse.
            valid_ops: A list of valid ops to check against

        Returns:
            None.
        """

        pgf_ops = {
            **pgf_cql_json.parser.COMPARISON_MAP,
            **pgf_cql_json.parser.SPATIAL_PREDICATES_MAP,
            **pgf_cql_json.parser.TEMPORAL_PREDICATES_MAP,
            **pgf_cql_json.parser.ARRAY_PREDICATES_MAP,
            **pgf_cql_json.parser.ARITHMETIC_MAP,
        }
        res = list(set(cls.inOrderOpsCollect_rec(expr, pgf_ops)))
        for op in res:
            if op == "ge":
                op = "gte"  # because of inconsistent namings in pygeofilter - uses op names 'ge', 'le' in ast but 'gte', 'lte' in their cql-json parser
            if op == "le":
                op = "lte"
            if op not in valid_ops:
                raise ValidationError(
                    [
                        ErrorWrapper(
                            ValueError(f"Unsupported operation: {expr}"),
                            "STACSearch",
                        )
                    ],
                    STACSearch,
                )

    @validator("bbox_crs")
    def validate_bbox_crs(cls, bbox_crs):
        if bbox_crs:
            crs_extension = CrsExtension()
            if bbox_crs in crs_extension.crs:
                return bbox_crs
            else:
                raise ValidationError(
                    [
                        ErrorWrapper(
                            ValueError(
                                f"'{bbox_crs}' is not a supported bbox-crs. Currently supported crs are: {crs_extension.crs}"
                            ),
                            "STACSearch",
                        )
                    ],
                    STACSearch,
                )

    @validator("crs")
    def validate_crs(cls, crs):
        if crs:
            crs_extension = CrsExtension()
            if crs in crs_extension.crs:
                return crs
            else:
                raise ValidationError(
                    [
                        ErrorWrapper(
                            ValueError(
                                f"'{crs}' is not a supported crs. Currently supported crs are: {crs_extension.crs}"
                            ),
                            "STACSearch",
                        )
                    ],
                    STACSearch,
                )

    @validator("filter_crs")
    def validate_filter_crs(cls, filter_crs):
        if filter_crs:
            crs_extension = CrsExtension()
            if filter_crs in crs_extension.crs:
                return filter_crs
            else:
                raise ValidationError(
                    [
                        ErrorWrapper(
                            ValueError(
                                f"'{filter_crs}' is not a supported filter-crs. Currently supported crs are: {crs_extension.crs}"
                            ),
                            "STACSearch",
                        )
                    ],
                    STACSearch,
                )

    # Override the bbox validator because it only works for WGS84
    @validator("bbox")
    def validate_bbox(cls, v: BBox, values, **kwargs):
        if v and "intersects" in values and values["intersects"]:
            raise ValueError("intersects and bbox parameters are mutually exclusive")

        if v:
            # Validate order
            if len(v) == 4:
                xmin, ymin, xmax, ymax = v
            else:
                xmin, ymin, min_elev, xmax, ymax, max_elev = v
                if max_elev < min_elev:
                    raise ValueError(
                        "Maximum elevation must greater than minimum elevation"
                    )

            if xmax < xmin:
                raise ValueError(
                    "Maximum longitude must be greater than minimum longitude"
                )

            if ymax < ymin:
                raise ValueError(
                    "Maximum longitude must be greater than minimum longitude"
                )

            # Validate against WGS84
            # Turn this off.. :-)
            # if xmin < -180 or ymin < -90 or xmax > 180 or ymax > 90:
            #    raise ValueError("Bounding box must be within (-180, -90, 180, 90)")

        return v

    @root_validator(pre=False)
    def validate_filter(cls, values: Dict) -> Dict:
        """Validate filter fields."""
        if "filter" in values and values["filter"]:
            # Validate filter-lang
            if "filter_lang" in values and values["filter_lang"] != "cql-json":
                raise ValidationError(
                    [
                        ErrorWrapper(
                            ValueError(
                                f"'{values['filter_lang']}' is not a supported filter-language. Currently supported languages are: cql-json"
                            ),
                            "STACSearch",
                        )
                    ],
                    STACSearch,
                )

            # Validate filter-crs
            if "filter_crs" in values and values["filter_crs"]:
                crs_extension = CrsExtension()
                if values["filter_crs"] in crs_extension.crs:
                    # Convert the URI crs to a SRID
                    values["filter_crs"] = crs_extension.epsg_from_crs(
                        values["filter_crs"]
                    )
                elif values["filter_crs"] in [
                    str(crs_extension.epsg_from_crs(x)) for x in crs_extension.crs
                ]:
                    values["filter_crs"] = int(values["filter_crs"])
                else:
                    # SRID was given
                    raise ValidationError(
                        [
                            ErrorWrapper(
                                ValueError(
                                    f"filter-crs must be a supported CRS. Currently supported crs are:\n"
                                    + ",\n".join(crs_extension.crs)
                                    + "\n"
                                ),
                                "STACSearch",
                            )
                        ],
                        STACSearch,
                    )
                # add filter-crs to filter if crs is not 4326 - hack in order to pass crs to pygeofilter through the geojson
                if values["filter_crs"] != 4326:
                    cls.add_filter_crs(values["filter"], values["filter_crs"])

            # Validate filter
            try:
                ast = parse_json(values["filter"])  # pygeofilter cql-json parse
            except Exception as e:
                raise ValidationError(
                    [
                        ErrorWrapper(
                            ValueError(f"The input cql-json could not be parsed"),
                            "STACSearch",
                        )
                    ],
                    STACSearch,
                )
            if not ast:
                raise ValidationError(
                    [
                        ErrorWrapper(
                            ValueError(f"The input cql-json could not be parsed"),
                            "STACSearch",
                        )
                    ],
                    STACSearch,
                )
            if "collections" in values and values["collections"]:
                (
                    base_queryables,
                    collection_queryables,
                ) = Queryables.get_queryable_properties_intersection(
                    values["collections"]
                )
                valid_fields = base_queryables + collection_queryables
            else:
                (
                    base_queryables,
                    collection_queryables,
                ) = Queryables.get_queryable_properties_intersection()
                valid_fields = base_queryables + collection_queryables

            # full list of operations supported in pygeofiler
            valid_ops = {
                **pgf_cql_json.parser.COMPARISON_MAP,
                **pgf_cql_json.parser.SPATIAL_PREDICATES_MAP,
                **pgf_cql_json.parser.TEMPORAL_PREDICATES_MAP,
                # **pgf_cql_json.parser.ARRAY_PREDICATES_MAP,
                **pgf_cql_json.parser.ARITHMETIC_MAP,
            }
            remove_ops = []  # operations we don't want to expose eg. ["meets", "metby"]
            for op in remove_ops:
                if op in valid_ops:
                    del valid_ops[op]
            values["filter_fields"] = cls.validate_filter_fields(ast, valid_fields)
            cls.validate_filter_ops(ast, valid_ops)
            values["filter"] = ast

        return values

    # from stac_pydantic.api.Search
    @property
    def start_date(self) -> Optional[datetime]:
        values = self.datetime.split("/")
        if len(values) == 1:
            return None
        if values[0] == ".." or values[0] == "":
            return None
        return parse_datetime(values[0])

    # from stac_pydantic.api.Search
    @property
    def end_date(self) -> Optional[datetime]:
        values = self.datetime.split("/")
        if len(values) == 1:
            return parse_datetime(values[0])
        if values[1] == ".." or values[1] == "":
            return None
        return parse_datetime(values[1])

    # from stac_pydantic.api.Search
    @validator("intersects")
    def validate_spatial(cls, v, values):
        if v and "bbox" in values and values["bbox"]:
            raise ValueError("intersects and bbox parameters are mutually exclusive")
        return v

    # from stac_pydantic.api.Search
    @validator("datetime")
    def validate_datetime(cls, v):
        if "/" in v:
            values = v.split("/")
        else:
            # Single date is interpreted as end date
            values = ["..", v]

        dates = []
        for value in values:
            if value == ".." or value == "":
                dates.append("..")
                continue
            # NOTE: Per [ABNF] and ISO8601, the "T" and "Z" characters in this
            # syntax may alternatively be lower case "t" or "z" respectively.
            # So we have to replace "t" and "z" with their uppercase counterparts.
            value = value.replace("z", "Z").replace("t", "T")
            parse_datetime(value)
            dates.append(value)

        if ".." not in dates:
            if parse_datetime(dates[0]) > parse_datetime(dates[1]):
                raise ValueError(
                    "Invalid datetime range, must match format (begin_date, end_date)"
                )

        return v

    # from stac_pydantic.api.Search
    @property
    def spatial_filter(self) -> Optional[_GeometryBase]:
        """Return a geojson-pydantic object representing the spatial filter for the search request.

        Check for both because the ``bbox`` and ``intersects`` parameters are mutually exclusive.
        """
        if self.bbox:
            return Polygon(
                coordinates=[
                    [
                        [self.bbox[0], self.bbox[3]],
                        [self.bbox[2], self.bbox[3]],
                        [self.bbox[2], self.bbox[1]],
                        [self.bbox[0], self.bbox[1]],
                        [self.bbox[0], self.bbox[3]],
                    ]
                ]
            )
        if self.intersects:
            return self.intersects
        return
