"""api request/response models."""

import abc
from typing import Dict, Optional, Type, Union, List
from datetime import datetime
import attr
from fastapi import Body, Path, Query, Response
from pydantic import BaseModel, create_model
from pydantic.fields import UndefinedType
from . import descriptions

NumType = Union[int, float]


def _create_request_model(model: Type[BaseModel]) -> Type[BaseModel]:
    """Create a pydantic model for validating request bodies."""
    fields = {}
    for (k, v) in model.__fields__.items():
        # TODO: Filter out fields based on which extensions are present
        field_info = v.field_info
        body = Body(
            None
            if isinstance(field_info.default, UndefinedType)
            else field_info.default,
            default_factory=field_info.default_factory,
            alias=field_info.alias,
            alias_priority=field_info.alias_priority,
            title=field_info.title,
            description=field_info.description,
            const=field_info.const,
            gt=field_info.gt,
            ge=field_info.ge,
            lt=field_info.lt,
            le=field_info.le,
            multiple_of=field_info.multiple_of,
            min_items=field_info.min_items,
            max_items=field_info.max_items,
            min_length=field_info.min_length,
            max_length=field_info.max_length,
            regex=field_info.regex,
            extra=field_info.extra,
        )
        fields[k] = (v.outer_type_, body)
    return create_model(model.__name__, **fields, __base__=model)


@attr.s  # type:ignore
class APIRequest(abc.ABC):
    """Generic API Request base class."""

    @abc.abstractmethod
    def kwargs(self) -> Dict:
        """Transform api request params into format which matches the signature of the endpoint."""
        ...


@attr.s  # type:ignore
class CollectionUri(APIRequest):
    """Delete collection."""

    collectionId: str = attr.ib(default=Path(..., description=descriptions.COLLECTION_ID))

    def kwargs(self) -> Dict:
        """kwargs."""
        return {"id": self.collectionId}


@attr.s
class ItemUri(CollectionUri):
    """Delete item."""

    itemId: str = attr.ib(default=Path(..., description=descriptions.ITEM_ID))
    crs: Optional[str] = attr.ib(default=Query(None, description=descriptions.CRS))

    def kwargs(self) -> Dict:
        """kwargs."""
        return {
            "collection_id": self.collectionId,
            "item_id": self.itemId,
            "crs": self.crs,
        }


@attr.s
class EmptyRequest(APIRequest):
    """Empty request."""

    def kwargs(self) -> Dict:
        """kwargs."""
        return {}


@attr.s
class FilterableRequest:
    crs: Optional[str] = attr.ib(default=Query(None, description=descriptions.CRS))
    limit: int = attr.ib(default=Query(10, description=descriptions.LIMIT))
    pt: Optional[str] = attr.ib(default=Query(None, description=descriptions.PAGING_TOKEN))
    ids: Optional[str] = attr.ib(default=Query(None, description=descriptions.IDS))
    bbox: Optional[str] = attr.ib(default=Query(None, description=descriptions.BBOX))
    bbox_crs: Optional[str] = attr.ib(default=Query(default=None, alias="bbox-crs", description=descriptions.BBOX_CRS))
    datetime: Optional[str] = attr.ib(default=Query(None, description=descriptions.DATETIME))  # TODO: fix types
    filter: Optional[str] = attr.ib(default=Query(None, description=descriptions.FILTER))
    filter_lang: Optional[str] = attr.ib(
        default=Query(default=None, alias="filter-lang", description=descriptions.FILTER_LANG)
    )
    filter_crs: Optional[str] = attr.ib(default=Query(default=None, alias="filter-crs", description=descriptions.FILTER_CRS))


@attr.s
class ItemCollectionUri(CollectionUri, FilterableRequest):
    """Get item collection."""

    def kwargs(self) -> Dict:
        """kwargs."""
        return {
            "id": self.collectionId,
            "ids": self.ids.split(",") if self.ids else self.ids,
            "bbox": self.bbox,
            "bbox_crs": self.bbox_crs,
            "datetime": self.datetime,
            "crs": self.crs,
            "filter": self.filter,
            "filter_lang": self.filter_lang,
            "filter_crs": self.filter_crs,
            "limit": self.limit,
            "pt": self.pt,
        }


@attr.s
class SearchGetRequest(APIRequest, FilterableRequest):
    """GET search request."""

    collections: Optional[str] = attr.ib(default=Query(None, description=descriptions.COLLECTIONS))
    # fields: Optional[str] = attr.ib(default=None)
    sortby: Optional[str] = attr.ib(default=Query(None, description=descriptions.SORTBY))

    def kwargs(self) -> Dict:
        """kwargs."""

        # there is an important semantic difference between request with and empty fields param and not specifying fields at all ("url?fields=" versus "url").
        # In the first case the Fields extension specifies that only a minimal subset of properties should be returned3
        # and in the latter case (no "fields" param specified) all properties should be returned.
        # if self.fields is not None:
        #     fields = self.fields.split(",") if len(self.fields) > 0 else []
        # else:
        #     fields = self.fields
        return {
            "collections": self.collections.split(",")
            if self.collections
            else self.collections,
            "ids": self.ids.split(",") if self.ids else self.ids,
            "bbox": self.bbox.split(",") if self.bbox else self.bbox,
            "bbox_crs": self.bbox_crs,
            "datetime": self.datetime,
            "limit": self.limit,
            "filter": self.filter,
            "filter_lang": self.filter_lang,
            "filter_crs": self.filter_crs,
            # "query": self.query,
            "pt": self.pt,
            # "fields": fields,
            "crs": self.crs,
            "sortby": self.sortby.split(",") if self.sortby else self.sortby,
        }
