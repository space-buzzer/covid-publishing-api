"""This is where we create a function for initiating the application, which is
later on used at the very top level stories.py module to initiate the
application with a specific config file"""

# Flask Imports
from flask import Flask
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy

# For the database
db = SQLAlchemy()
migrate = Migrate()

def create_app(config):
    app = Flask(__name__)

    app.config.from_object(config)
    config.init_app(app)

    db.init_app(app)
    migrate.init_app(app, db)

    # Register our API blueprint
    from app.api import api as api_blueprint
    app.register_blueprint(api_blueprint, url_prefix='/api/v1')

    return app
