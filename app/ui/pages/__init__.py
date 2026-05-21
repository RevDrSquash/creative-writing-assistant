"""NiceGUI page modules.

Importing this package registers all @ui.page routes.
"""

from app.ui.pages import index as index
from app.ui.pages import models as models
from app.ui.pages import settings as settings
from app.ui.pages import workspace as workspace

__all__ = ["index", "models", "settings", "workspace"]
