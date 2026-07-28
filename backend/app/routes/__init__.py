def register_blueprints(app, csrf):
    from importlib import import_module
    for name in ('settings', 'datasets', 'training', 'studio', 'setup', 'scrape', 'ollama'):
        # These blueprints are part of the shipped application.  Let import
        # failures abort startup so a broken transitive dependency cannot turn
        # into an apparently healthy server with missing endpoints.
        mod = import_module(f'app.routes.{name}')
        app.register_blueprint(mod.bp)
