from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .ui import STATIC_DIR
from .version import __version__
from .web import router


app = FastAPI(title="KorbKlar", version=__version__)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.include_router(router)
