from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .config import CLAWFORGE_INTELLIGENCE_AUTOSTART
from . import runtime
from .ui import STATIC_DIR
from .version import __version__
from .web import router


@asynccontextmanager
async def lifespan(_app: FastAPI):
    intelligence = runtime.get_intelligence()
    if CLAWFORGE_INTELLIGENCE_AUTOSTART:
        intelligence.start()
    try:
        yield
    finally:
        if CLAWFORGE_INTELLIGENCE_AUTOSTART:
            intelligence.stop()


app = FastAPI(title="KorbKlar", version=__version__, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.include_router(router)
