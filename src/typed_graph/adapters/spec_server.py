"""Read-only loopback specification reader with one shared revision-aware projection cache."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import html
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

import anyio
import bleach
import uvicorn
from markdown_it import MarkdownIt
from markdown_it.renderer import RendererHTML
from markdown_it.token import Token
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import (
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    Response,
    StreamingResponse,
)
from starlette.routing import Route

from typed_graph.adapters.workspace import WorkspaceRepository
from typed_graph.application.ports import SpecificationSource, SpecificationToken
from typed_graph.application.specification import (
    MarkdownSpecification,
    PresentationProfile,
    SpecificationState,
    _digest,
    project_specification,
)
from typed_graph.architecture import compile_architecture
from typed_graph.architecture.models import PACKAGE_VERSION, Role
from typed_graph.domain.models import StrictModel, dump_wire


class RenderedSpecification(MarkdownSpecification):
    html: str


class ReaderSpecification(RenderedSpecification):
    inspector: RenderedSpecification


def project_reader(
    state: SpecificationState, profile: PresentationProfile | None
) -> ReaderSpecification:
    inspector = render_specification(project_specification(state, profile))
    if state.snapshot.schema_definition.version == PACKAGE_VERSION and any(
        node.type == Role.MODEL for node in state.snapshot.nodes
    ):
        projected = compile_architecture(state)
    else:
        markdown = (
            "# No architecture specification available\n\n"
            "This workspace has no registered architecture model. "
            "Its records are available in Graph inspector.\n"
        )
        projected = MarkdownSpecification(
            revision=state.snapshot.revision,
            assessment_digest=inspector.assessment_digest,
            state_digest=_digest(inspector.state_digest + markdown),
            title="No architecture specification available",
            markdown=markdown,
            outline=[],
            node_count=len(state.snapshot.nodes),
            edge_count=len(state.snapshot.edges),
        )
    rendered = render_specification(projected)
    return ReaderSpecification.model_validate(
        {**dump_wire(rendered), "inspector": dump_wire(inspector)}
    )


class ReaderStatus(StrictModel):
    state: Literal["live", "error"]
    message: str


SAFE_TAGS = frozenset(
    {
        "p",
        "br",
        "hr",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "ul",
        "ol",
        "li",
        "blockquote",
        "pre",
        "code",
        "em",
        "strong",
        "s",
        "a",
        "table",
        "thead",
        "tbody",
        "tr",
        "th",
        "td",
        "span",
        "details",
        "summary",
        "figure",
        "figcaption",
        "div",
    }
)
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'self'; style-src 'self'; "
        "connect-src 'self'; img-src 'none'; base-uri 'none'; "
        "form-action 'none'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
    "Cross-Origin-Resource-Policy": "same-origin",
}


def _image_alt(
    renderer: RendererHTML, tokens: list[Token], index: int, options: Any, env: Any
) -> str:
    return f'<span class="image-description">[Image: {html.escape(tokens[index].content)}]</span>'


def render_specification(specification: MarkdownSpecification) -> RenderedSpecification:
    parser = MarkdownIt("commonmark", {"html": False}).enable("table")
    parser.add_render_rule("image", _image_alt)
    tokens = parser.parse(specification.markdown)
    headings = {entry.line: entry for entry in specification.outline}
    diagrams = {diagram.line: diagram for diagram in specification.diagrams}
    for token in tokens:
        if token.type == "heading_open" and token.map and token.map[0] in headings:
            token.attrSet("id", headings[token.map[0]].id)
        if token.type == "fence" and token.map and token.map[0] in diagrams:
            diagram = diagrams[token.map[0]]
            # Only a generated fence at its exact recorded source position is executable.
            # Identical graph-authored Mermaid elsewhere remains ordinary code.
            if token.info == "mermaid" and token.content.rstrip("\n") == diagram.source:
                token.type = "html_block"
                token.content = (
                    f'<figure data-diagram-id="{html.escape(diagram.id, quote=True)}">'
                    '<div class="diagram-canvas"></div>'
                    f"<figcaption>{html.escape(diagram.title)}</figcaption>"
                    f'<pre class="diagram-source"><code>{html.escape(diagram.source)}</code></pre>'
                    "</figure>"
                )
    insertions: dict[int, list[str]] = {}
    for section in specification.disclosures:
        start = next(
            (
                index
                for index, token in enumerate(tokens)
                if token.type == "heading_open" and token.map and token.map[0] == section.start_line
            ),
            None,
        )
        if start is None:
            continue
        end = next(
            (
                index
                for index, token in enumerate(tokens)
                if token.map and token.map[0] >= section.end_line
            ),
            len(tokens),
        )
        summary_end = next(
            index + 1 for index in range(start + 1, end) if tokens[index].type == "heading_close"
        )
        insertions.setdefault(start, []).append(
            f'<details data-section-id="{html.escape(section.id, quote=True)}"><summary>'
        )
        insertions.setdefault(summary_end, []).append("</summary>")
        # Prepend closers before a following section opener at the same token index.
        insertions.setdefault(end, []).insert(0, "</details>")
    expanded: list[Token] = []
    for index in range(len(tokens) + 1):
        for markup in insertions.get(index, []):
            added = Token("html_block", "", 0)
            added.content = markup
            expanded.append(added)
        if index < len(tokens):
            expanded.append(tokens[index])
    rendered = parser.renderer.render(expanded, parser.options, {})
    safe = bleach.clean(
        rendered,
        tags=SAFE_TAGS,
        attributes={
            "a": ["href", "title"],
            "h1": ["id"],
            "h2": ["id"],
            "h3": ["id"],
            "h4": ["id"],
            "h5": ["id"],
            "h6": ["id"],
            "span": ["class"],
            "details": ["data-section-id"],
            "figure": ["data-diagram-id"],
            "div": ["class"],
            "pre": ["class"],
        },
        protocols={"http", "https", "mailto"},
        strip=True,
    )
    return RenderedSpecification.model_validate({**dump_wire(specification), "html": safe})


class ReaderBoundary(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        host = request.headers.get("host", "")
        try:
            parsed = urlsplit(f"http://{host}")
            port = parsed.port
            valid = (
                parsed.hostname in {"127.0.0.1", "localhost"}
                and not parsed.username
                and not parsed.password
                and not parsed.path
                and not parsed.query
                and not parsed.fragment
                and (port is None or 1 <= port <= 65535)
            )
        except ValueError:
            valid = False
        if not valid:
            return PlainTextResponse("Loopback host required", status_code=403)
        origin = request.headers.get("origin")
        if origin is not None and origin != f"http://{host}":
            return PlainTextResponse("Same-origin access required", status_code=403)
        if request.method not in {"GET", "HEAD"}:
            return PlainTextResponse("Read-only reader", status_code=405)
        response = await call_next(request)
        response.headers.update(SECURITY_HEADERS)
        return response


class SpecificationCache:
    def __init__(
        self,
        repository: SpecificationSource,
        poll_interval: float,
        profile: PresentationProfile | None = None,
    ) -> None:
        self.repository = repository
        self.profile = profile
        self.poll_interval = poll_interval
        self.latest: ReaderSpecification | None = None
        self.generation = 0
        self.status = ReaderStatus(
            state="live", message="Following the latest committed specification"
        )
        self.condition = asyncio.Condition()
        self.token: SpecificationToken | None = None

    async def refresh(self) -> None:
        token = await anyio.to_thread.run_sync(self.repository.specification_token)
        if token == self.token and self.status.state == "live":
            return
        state = await anyio.to_thread.run_sync(self.repository.specification_state)
        rendered = await anyio.to_thread.run_sync(project_reader, state, self.profile)
        async with self.condition:
            self.token = token
            changed = self.latest is None or rendered.state_digest != self.latest.state_digest
            recovering = self.status.state != "live"
            if changed or recovering:
                self.status = ReaderStatus(
                    state="live", message="Following the latest committed specification"
                )
                self.latest = rendered
                self.generation += 1
                self.condition.notify_all()

    async def poll(self) -> None:
        while True:
            await asyncio.sleep(self.poll_interval)
            try:
                await self.refresh()
            except Exception:
                logging.getLogger(__name__).exception("Unable to refresh specification; retrying")
                async with self.condition:
                    if self.status.state != "error":
                        self.status = ReaderStatus(
                            state="error",
                            message=(
                                "Cannot refresh the specification. Showing the last good version; "
                                "retrying automatically."
                            ),
                        )
                        self.generation += 1
                        self.condition.notify_all()

    def current(self) -> ReaderSpecification:
        if self.latest is None:
            raise RuntimeError("Specification cache is not initialized")
        return self.latest

    async def events(self) -> AsyncIterator[str]:
        seen = -1
        document_digest: str | None = None
        status: ReaderStatus | None = None
        while True:
            heartbeat = False
            frames: list[str] = []
            async with self.condition:
                if seen == self.generation:

                    def changed(previous: int = seen) -> bool:
                        return previous != self.generation

                    try:
                        await asyncio.wait_for(self.condition.wait_for(changed), timeout=15)
                    except TimeoutError:
                        heartbeat = True
                current = self.current()
                seen = self.generation
                if current.state_digest != document_digest:
                    payload = json.dumps(dump_wire(current))
                    frames.append(
                        f"id: {current.state_digest}\nevent: specification\ndata: {payload}\n\n"
                    )
                    document_digest = current.state_digest
                if status != self.status:
                    frames.append(
                        f"event: reader-status\ndata: {self.status.model_dump_json()}\n\n"
                    )
                    status = self.status
            if heartbeat:
                yield ": keep-alive\n\n"
            for frame in frames:
                yield frame


def create_app(
    workspace: Path, poll_interval: float = 1.0, profile: PresentationProfile | None = None
) -> Starlette:
    if not 0.05 <= poll_interval <= 60:
        raise ValueError("poll_interval must be between 0.05 and 60 seconds")
    repository = WorkspaceRepository(workspace)
    cache = SpecificationCache(repository, poll_interval, profile)
    assets = Path(__file__).with_name("static")

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        await cache.refresh()
        task = asyncio.create_task(cache.poll())
        try:
            yield
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            repository.close()

    async def index(request: Request) -> Response:
        return HTMLResponse((assets / "index.html").read_text())

    async def javascript(request: Request) -> Response:
        return Response((assets / "app.js").read_text(), media_type="text/javascript")

    async def diagram_javascript(request: Request) -> Response:
        return Response((assets / "reader-diagrams.js").read_text(), media_type="text/javascript")

    async def stylesheet(request: Request) -> Response:
        return Response((assets / "styles.css").read_text(), media_type="text/css")

    async def specification(request: Request) -> Response:
        return JSONResponse(dump_wire(cache.current()))

    async def markdown(request: Request) -> Response:
        return Response(
            cache.current().markdown,
            media_type="text/markdown",
            headers={"Content-Disposition": 'attachment; filename="specification.md"'},
        )

    async def inspector_markdown(request: Request) -> Response:
        return Response(
            cache.current().inspector.markdown,
            media_type="text/markdown",
            headers={"Content-Disposition": 'attachment; filename="graph-inspector.md"'},
        )

    async def events(request: Request) -> Response:
        return StreamingResponse(
            cache.events(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"}
        )

    app = Starlette(
        routes=[
            Route("/", index),
            Route("/app.js", javascript),
            Route("/reader-diagrams.js", diagram_javascript),
            Route("/styles.css", stylesheet),
            Route("/api/specification", specification),
            Route("/specification.md", markdown),
            Route("/inspector.md", inspector_markdown),
            Route("/events", events),
        ],
        lifespan=lifespan,
    )
    app.add_middleware(ReaderBoundary)
    return app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workspace", type=Path)
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--profile", type=Path, help="Typed presentation profile JSON")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be 1..65535")
    profile = (
        PresentationProfile.model_validate_json(args.profile.read_text()) if args.profile else None
    )
    uvicorn.run(
        create_app(args.workspace, profile=profile),
        host="127.0.0.1",
        port=args.port,
        access_log=False,
        timeout_graceful_shutdown=2,
    )


if __name__ == "__main__":
    main()
