from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from sqlalchemy.ext.asyncio import async_sessionmaker
from .config import settings
from .database import Base, engine as default_engine, make_engine, get_db
from .models import cnn_model, db_models
from .routers import predict, safety
from .safety import models
from .safety.sessions import Runtime


def create_app(config=settings, engine=None):
    db_engine = engine if engine is not None else (default_engine if config is settings else make_engine(config.DATABASE_URL))
    factory = async_sessionmaker(db_engine, expire_on_commit=False)

    @asynccontextmanager
    async def lifespan(app):
        # Create missing tables only. Existing rows/files are never reset or dropped.
        async with db_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        app.state.safety = Runtime(config, factory)
        await app.state.safety.start()
        try:
            yield
        finally:
            await app.state.safety.close()
            await db_engine.dispose()

    app = FastAPI(lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ALLOW_ORIGINS, allow_credentials=False,
                       allow_methods=['GET', 'POST', 'PATCH', 'DELETE', 'OPTIONS'],
                       allow_headers=['Content-Type', 'X-Safety-Capability', 'X-Session-Capability', 'X-EmotionLens-Client'])

    @app.middleware('http')
    async def local_requests(request: Request, call_next):
        origin = request.headers.get('origin')
        if origin and origin not in config.CORS_ALLOW_ORIGINS:
            return JSONResponse({'detail': 'Origin is not approved for this local app'}, status_code=403)
        if request.headers.get('sec-fetch-site') == 'cross-site' and not origin:
            return JSONResponse({'detail': 'Cross-site request rejected'}, status_code=403)
        limit = 6 * 1024 * 1024 if request.url.path == '/predict' else 64 * 1024
        try:
            length = int(request.headers.get('content-length', '0'))
        except ValueError:
            return JSONResponse({'detail': 'Invalid Content-Length'}, status_code=400)
        if length < 0 or length > limit:
            return JSONResponse({'detail': 'Request payload too large'}, status_code=413)
        # Streaming bodies also have a limit, including requests without Content-Length.
        if request.method in ('POST', 'PATCH', 'PUT'):
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > limit:
                    return JSONResponse({'detail': 'Request payload too large'}, status_code=413)
            request._body = bytes(body)
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    app.add_middleware(TrustedHostMiddleware, allowed_hosts=config.ALLOWED_HOSTS)
    app.include_router(predict.router)
    app.include_router(safety.router)

    if db_engine is not default_engine:
        async def local_db():
            async with factory() as db:
                yield db
        app.dependency_overrides[get_db] = local_db

    @app.get('/health')
    async def health():
        rt = app.state.safety
        return {'status': 'ok', 'model_loaded': cnn_model.model_loaded(),
                'expression': {'loaded': cnn_model.model_loaded(), 'configured': bool(config.MODEL_PATH), 'optional': True},
                'safety': {'ready': rt.detector.ready, 'qualified': rt.detector.qualified, 'reason': rt.detector.reason}}

    return app


app = create_app()
