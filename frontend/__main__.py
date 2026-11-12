"""Allow `python -m frontend` to launch the app."""
from .app import NexTorApp

app = NexTorApp()
app.run()
