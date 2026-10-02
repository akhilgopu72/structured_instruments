"""si serve [--port 8001] - Start FastAPI server."""
import typer


def serve(
    port: int = typer.Option(8001, "--port", "-p", help="Port to serve on"),
):
    """Start the FastAPI server."""
    import uvicorn

    from structured_instruments.api.app import app

    uvicorn.run(app, host="0.0.0.0", port=port)
