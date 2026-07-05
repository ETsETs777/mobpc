"""Entry point for mobpc Windows agent."""

import uvicorn

from server.app import create_app
from server.config import settings

app = create_app()

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.reload,
        log_level="info",
    )
