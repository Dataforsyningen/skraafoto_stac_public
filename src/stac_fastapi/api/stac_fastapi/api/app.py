"""fastapi app creation."""
from typing import Any, Callable, Dict, List, Optional, Type, Union, Tuple

import attr
from brotli_asgi import BrotliMiddleware
from fastapi import APIRouter, FastAPI
from fastapi.openapi.models import OpenAPI
from fastapi.openapi.utils import get_openapi
from fastapi.params import Depends
from fastapi.openapi.docs import (
    get_redoc_html,
    get_swagger_ui_html,
    get_swagger_ui_oauth2_redirect_html,
)
from pydantic import BaseModel
from stac_fastapi.api.openapi.openapi import get_openapi_handler
from stac_pydantic import Collection, Item, ItemCollection
from stac_pydantic.api import ConformanceClasses, LandingPage, Search
from stac_pydantic.api.collections import Collections
from stac_pydantic.version import STAC_VERSION
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response

from stac_fastapi.api import descriptions
from stac_fastapi.api.errors import DEFAULT_STATUS_CODES, add_exception_handlers
from stac_fastapi.api.models import (
    APIRequest,
    CollectionUri,
    EmptyRequest,
    ItemCollectionUri,
    ItemUri,
    SearchGetRequest,
    _create_request_model,
)
from stac_fastapi.api.routes import (
    Scope,
    add_route_dependencies,
    create_async_endpoint,
    create_sync_endpoint,
)

# from stac_fastapi.api.openapi import VndResponse
class VndResponse(JSONResponse):
    media_type = "application/vnd.oai.openapi+json;version=3.0"


from stac_fastapi.api.routes import create_async_endpoint, create_sync_endpoint

# TODO: make this module not depend on `stac_fastapi.extensions`
from stac_fastapi.extensions.core import FieldsExtension
from stac_fastapi.types.config import ApiSettings, Settings
from stac_fastapi.types.core import AsyncBaseCoreClient, BaseCoreClient
from stac_fastapi.types.extension import ApiExtension
from stac_fastapi.types.search import STACSearch


@attr.s
class StacApi:
    """StacApi factory.

    Factory for creating a STAC-compliant FastAPI application.  After instantation, the application is accessible from
    the `StacApi.app` attribute.

    Attributes:
        settings:
            API settings and configuration, potentially using environment variables.
            See https://pydantic-docs.helpmanual.io/usage/settings/.
        client:
            A subclass of `stac_api.clients.BaseCoreClient`.  Defines the application logic which is injected
            into the API.
        extensions:
            API extensions to include with the application.  This may include official STAC extensions as well as
            third-party add ons.
        exceptions:
            Defines a global mapping between exceptions and status codes, allowing configuration of response behavior on
            certain exceptions (https://fastapi.tiangolo.com/tutorial/handling-errors/#install-custom-exception-handlers).
        app:
            The FastAPI application, defaults to a fresh application.
    """

    settings: ApiSettings = attr.ib()
    client: Union[AsyncBaseCoreClient, BaseCoreClient] = attr.ib()
    extensions: List[ApiExtension] = attr.ib(default=attr.Factory(list))
    exceptions: Dict[Type[Exception], int] = attr.ib(
        default=attr.Factory(lambda: DEFAULT_STATUS_CODES)
    )
    app: FastAPI = attr.ib(
        default=attr.Factory(
            lambda self: FastAPI(openapi_url=self.settings.openapi_url),
            takes_self=True,
        )
    )
    router: APIRouter = attr.ib(default=attr.Factory(APIRouter))
    title: str = attr.ib(default="stac-fastapi")
    api_version: str = attr.ib(default="0.1")
    stac_version: str = attr.ib(default=STAC_VERSION)
    description: str = attr.ib(default="stac-fastapi")
    search_request_model: Type[Search] = attr.ib(default=STACSearch)
    response_class: Type[Response] = attr.ib(default=JSONResponse)
    middlewares: List = attr.ib(default=attr.Factory(lambda: [BrotliMiddleware]))
    route_dependencies: List[Tuple[List[Scope], List[Depends]]] = attr.ib(default=[])

    def get_extension(self, extension: Type[ApiExtension]) -> Optional[ApiExtension]:
        """Get an extension.

        Args:
            extension: extension to check for.

        Returns:
            The extension instance, if it exists.
        """
        for ext in self.extensions:
            if isinstance(ext, extension):
                return ext
        return None

    def _create_endpoint(
        self, func: Callable, request_type: Union[Type[APIRequest], Type[BaseModel]]
    ) -> Callable:
        """Create a FastAPI endpoint."""
        if isinstance(self.client, AsyncBaseCoreClient):
            return create_async_endpoint(
                func, request_type, response_class=self.response_class
            )
        elif isinstance(self.client, BaseCoreClient):
            return create_sync_endpoint(
                func, request_type, response_class=self.response_class
            )
        raise NotImplementedError

    def register_landing_page(self):
        """Register landing page (GET /).

        Returns:
            None
        """
        self.router.add_api_route(
            name="Landing Page",
            path="/",
            response_model=LandingPage
            if self.settings.enable_response_models
            else None,
            response_class=self.response_class,
            response_model_exclude_unset=False,
            response_model_exclude_none=True,
            methods=["GET"],
            endpoint=self._create_endpoint(self.client.landing_page, EmptyRequest),
            description=descriptions.LANDING_PAGE
        )

    def register_conformance_classes(self):
        """Register conformance classes (GET /conformance).

        Returns:
            None
        """
        self.router.add_api_route(
            name="Conformance Classes",
            path="/conformance",
            response_model=ConformanceClasses
            if self.settings.enable_response_models
            else None,
            response_class=self.response_class,
            response_model_exclude_unset=True,
            response_model_exclude_none=True,
            methods=["GET"],
            endpoint=self._create_endpoint(self.client.conformance, EmptyRequest),
            description=descriptions.CONFORMANCECLASSES
        )

    def register_get_item(self):
        """Register get item endpoint (GET /collections/{collectionId}/items/{itemId}).

        Returns:
            None
        """
        self.router.add_api_route(
            name="Get Item",
            path="/collections/{collectionId}/items/{itemId}",
            response_model=Item if self.settings.enable_response_models else None,
            response_class=self.response_class,
            response_model_exclude_unset=True,
            response_model_exclude_none=True,
            methods=["GET"],
            endpoint=self._create_endpoint(self.client.get_item, ItemUri),
            description=descriptions.GET_ITEM
        )

    def register_post_search(self):
        """Register search endpoint (POST /search).

        Returns:
            None
        """
        search_request_model = _create_request_model(self.search_request_model)
        fields_ext = self.get_extension(FieldsExtension)
        self.router.add_api_route(
            name="Search",
            path="/search",
            response_model=(ItemCollection if not fields_ext else None)
            if self.settings.enable_response_models
            else None,
            response_class=self.response_class,
            response_model_exclude_unset=True,
            response_model_exclude_none=True,
            methods=["POST"],
            endpoint=self._create_endpoint(
                self.client.post_search, search_request_model
            ),
            description=descriptions.POST_SEARCH
        )

    def register_get_search(self):
        """Register search endpoint (GET /search).

        Returns:
            None
        """
        fields_ext = self.get_extension(FieldsExtension)
        self.router.add_api_route(
            name="Search",
            path="/search",
            response_model=(ItemCollection if not fields_ext else None)
            if self.settings.enable_response_models
            else None,
            response_class=self.response_class,
            response_model_exclude_unset=True,
            response_model_exclude_none=True,
            methods=["GET"],
            endpoint=self._create_endpoint(self.client.get_search, SearchGetRequest),
            description=descriptions.GET_SEARCH
        )

    def register_get_collections(self):
        """Register get collections endpoint (GET /collections).

        Returns:
            None
        """
        self.router.add_api_route(
            name="Get Collections",
            path="/collections",
            response_model=Collections
            if self.settings.enable_response_models
            else None,
            response_class=self.response_class,
            response_model_exclude_unset=True,
            response_model_exclude_none=True,
            methods=["GET"],
            endpoint=self._create_endpoint(self.client.all_collections, EmptyRequest),
            description=descriptions.GET_COLLECTIONS
        )

    def register_get_collection(self):
        """Register get collection endpoint (GET /collection/{collectionId}).

        Returns:
            None
        """
        self.router.add_api_route(
            name="Get Collection",
            path="/collections/{collectionId}",
            response_model=Collection if self.settings.enable_response_models else None,
            response_class=self.response_class,
            response_model_exclude_unset=True,
            response_model_exclude_none=True,
            methods=["GET"],
            endpoint=self._create_endpoint(self.client.get_collection, CollectionUri),
            description=descriptions.GET_COLLECTION
        )

    def register_get_item_collection(self):
        """Register get item collection endpoint (GET /collection/{collectionId}/items).

        Returns:
            None
        """
        self.router.add_api_route(
            name="Get ItemCollection",
            path="/collections/{collectionId}/items",
            response_model=ItemCollection
            if self.settings.enable_response_models
            else None,
            response_class=self.response_class,
            response_model_exclude_unset=True,
            response_model_exclude_none=True,
            methods=["GET"],
            endpoint=self._create_endpoint(
                self.client.item_collection, ItemCollectionUri
            ),
            description=descriptions.GET_ITEM_COLLECTION
        )

    def register_core(self):
        """Register core STAC endpoints.

            GET /
            GET /conformance
            GET /collections
            GET /collections/{collectionId}
            GET /collections/{collectionId}/items
            GET /collection/{collectionId}/items/{itemId}
            GET /search
            POST /search

        Injects application logic (StacApi.client) into the API layer.

        Returns:
            None
        """
        self.register_landing_page()
        self.register_conformance_classes()
        self.register_get_item()
        self.register_post_search()
        self.register_get_search()
        self.register_get_collections()
        self.register_get_collection()
        self.register_get_item_collection()

    def customize_openapi(self) -> Optional[Dict[str, Any]]:
        """Customize openapi schema."""
        if self.app.openapi_schema:
            return self.app.openapi_schema

        openapi_schema = get_openapi(
            title=self.title, version=self.api_version, routes=self.app.routes
        )

        self.app.openapi_schema = openapi_schema

        return self.app.openapi_schema

    def add_health_check(self):
        """Add a health check."""
        mgmt_router = APIRouter()

        @mgmt_router.get("/_mgmt/ping")
        async def ping():
            """Liveliness/readiness probe."""
            return {"message": "PONG"}

        self.app.include_router(mgmt_router, tags=["Liveliness/Readiness"])

    def add_route_dependencies(
        self, scopes: List[Scope], dependencies=List[Depends]
    ) -> None:
        """Add custom dependencies to routes."""
        return add_route_dependencies(self.app.router.routes, scopes, dependencies)

    # Before initialization of StacAPI we change the setup method of FastAPI
    # to change the responsetype of openapi from JsonResponse to OAFeat compliant
    # VndResponse. Afaik this is the only way to do it.

    def __attrs_pre_init__(self):
        def setup(self) -> None:

            self.add_route(
                "/ogc/openapi.json",
                get_openapi_handler(self),
                include_in_schema=False,
            )
            if self.openapi_url:
                urls = (server_data.get("url") for server_data in self.servers)
                server_urls = {url for url in urls if url}

                async def openapi(req: Request) -> VndResponse:
                    root_path = req.scope.get("root_path", "").rstrip("/")
                    if root_path not in server_urls:
                        if root_path and self.root_path_in_servers:
                            self.servers.insert(0, {"url": root_path})
                            server_urls.add(root_path)

                    # This is the response we have changed
                    if (
                        "application/vnd.oai.openapi;version=3.0"
                        in req.headers["accept"]
                    ):
                        return VndResponse(self.openapi())
                    else:
                        return JSONResponse(self.openapi())

                self.add_route(self.openapi_url, openapi, include_in_schema=False)

            if self.openapi_url and self.docs_url:

                async def swagger_ui_html(req: Request) -> HTMLResponse:
                    root_path = req.scope.get("root_path", "").rstrip("/")
                    token = req.query_params.get("token")

                    openapi_url = root_path + self.openapi_url
                    oauth2_redirect_url = self.swagger_ui_oauth2_redirect_url

                    if oauth2_redirect_url:
                        oauth2_redirect_url = root_path + oauth2_redirect_url
                    if token:
                        openapi_url = openapi_url + f"?token={token}"
                    return get_swagger_ui_html(
                        openapi_url=openapi_url,
                        title=self.title + " - Swagger UI",
                        oauth2_redirect_url=oauth2_redirect_url,
                        init_oauth=self.swagger_ui_init_oauth,
                    )

                self.add_route(self.docs_url, swagger_ui_html, include_in_schema=False)

                if self.swagger_ui_oauth2_redirect_url:

                    async def swagger_ui_redirect(req: Request) -> HTMLResponse:
                        return get_swagger_ui_oauth2_redirect_html()

                    self.add_route(
                        self.swagger_ui_oauth2_redirect_url,
                        swagger_ui_redirect,
                        include_in_schema=False,
                    )

            if self.openapi_url and self.redoc_url:

                async def redoc_html(req: Request) -> HTMLResponse:
                    root_path = req.scope.get("root_path", "").rstrip("/")
                    openapi_url = root_path + self.openapi_url
                    return get_redoc_html(
                        openapi_url=openapi_url, title=self.title + " - ReDoc"
                    )

                self.add_route(self.redoc_url, redoc_html, include_in_schema=False)

        # override the setup function on the FastAPI class
        FastAPI.setup = setup

    def __attrs_post_init__(self):
        """Post-init hook.

        Responsible for setting up the application upon instantiation of the class.

        Returns:
            None
        """
        # inject settings
        self.client.extensions = self.extensions
        self.client.stac_version = self.stac_version
        self.client.title = self.title
        self.client.description = self.description

        fields_ext = self.get_extension(FieldsExtension)
        if fields_ext:
            self.settings.default_includes = fields_ext.default_includes

        Settings.set(self.settings)
        self.app.state.settings = self.settings

        # Register core STAC endpoints
        self.register_core()
        self.app.include_router(self.router)

        # register extensions
        for ext in self.extensions:
            ext.register(self.app)

        # add health check
        self.add_health_check()

        # register exception handlers
        add_exception_handlers(self.app, status_codes=self.exceptions)

        # customize openapi
        # self.app.openapi = self.customize_openapi

        # add middlewares
        for middleware in self.middlewares:
            self.app.add_middleware(middleware)

        # customize route dependencies
        for scopes, dependencies in self.route_dependencies:
            self.add_route_dependencies(scopes=scopes, dependencies=dependencies)
