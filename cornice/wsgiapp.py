import os
from collections import defaultdict

from webob.exc import HTTPNotFound, HTTPMethodNotAllowed
from pyramid.config import Configurator

from pyramid.authorization import ACLAuthorizationPolicy

from pyramid.view import view_config
#from pyramid.interfaces import IRoutesMapper
import venusian

from cornice.resources import Root
from cornice.config import Config

_METHODS = ('GET', 'POST', 'PUT', 'DELETE', 'HEAD')


def add_apidoc(config, pattern, docstring, renderer):
    apidocs = config.registry.settings.setdefault('apidocs', {})
    info = apidocs.setdefault(pattern, {})
    info['docstring'] = docstring
    info['renderer'] = renderer


class Service(object):
    def __init__(self, **kw):
        self.defined_methods = []
        self.route_pattern = kw.pop('path')
        self.route_name = self.route_pattern
        self.renderer = kw.pop('renderer', 'json')
        self.kw = kw
        self._catchall_set = False

    def _refresh_catchall(self, config, method):
        # registring the method
        if method not in self.defined_methods:
            self.defined_methods.append(method)

        # updating or creatin the 405 route for this pattern
        mapper = config.get_routes_mapper()

        if not self._catchall_set:
            # adding a catchall for all *other* methods
            methods = list(_METHODS)
            methods.remove(method)
            config.add_route(self.route_name, self.route_pattern)
            config.add_view(view=self._not_allowed,
                            route_name=self.route_name,
                            request_method=methods)

            self._catchall_set = True
        else:
            # updating by removing the defined method from the 405
            config.commit()   # XXX not sure what's the impact here
            route = config.get_routes_mapper().routes[self.route_name]

            # here we want to update the 405 pattern
            #
            pass

    def _not_allowed(self, request):
        # not declared, let's 405
        res = HTTPMethodNotAllowed()
        res.allow = self.methods.keys()
        raise res

    def api(self, **kw):
        method = kw.pop('method', 'GET')
        api_kw = {}
        #self.methods[method]
        api_kw.update(kw)

        if 'renderer' not in api_kw:
            api_kw['renderer'] = self.renderer

        def _api(func):
            _api_kw = api_kw.copy()
            docstring = func.__doc__

            def callback(context, name, ob):
                config = context.config.with_package(info.module)
                route_name = self.route_name
                config.add_apidoc((self.route_pattern, method),
                                   docstring, self.renderer)
                config.add_view(view=ob, route_name=self.route_name,
                                **_api_kw)
                self._refresh_catchall(config, method)

            info = venusian.attach(func, callback, category='pyramid')

            if info.scope == 'class':
                # if the decorator was attached to a method in a class, or
                # otherwise executed at class scope, we need to set an
                # 'attr' into the settings if one isn't already in there
                if 'attr' not in kw:
                    kw['attr'] = func.__name__

            kw['_info'] = info.codeinfo   # fbo "action_method"
            return func
        return _api


@view_config(route_name='apidocs', renderer='apidocs.mako')
def apidocs(request):
    routes = []
    for k, v in request.registry.settings['apidocs'].items():
        routes.append((k, v))
    return {'routes': routes}


HERE = os.path.dirname(__file__)


def get_config(request):
    return request.registry.settings.get('config')


def heartbeat(request):
    # checks the server's state -- if wrong, return a 503 here
    return 'OK'


def manage(request):
    ## if it's not a local call, this does not exist

    # XXX protect with new auth APIs
    #if not is_local(request):
    #    raise HTTPNotFound()

    # now let's see if the config allows the debug mode
    config = get_config(request)
    if (not config.has_option('global', 'debug') or
        not config.get('global', 'debug')):
        raise HTTPNotFound()

    # local + activated
    return {'config': config}


def main(package=None):
    def _main(global_config, **settings):
        config_file = global_config['__file__']
        config_file = os.path.abspath(
                        os.path.normpath(
                        os.path.expandvars(
                            os.path.expanduser(
                            config_file))))

        settings['config'] = config = Config(config_file)
        conf_dir, _ = os.path.split(config_file)

        authz_policy = ACLAuthorizationPolicy()
        config = Configurator(root_factory=Root, settings=settings,
                              authorization_policy=authz_policy)

        # add auth via repoze.who
        # eventually the app will have to do this explicitly
        config.include("cornice.auth.whoauth")

        # adding default views: __heartbeat__, __apis__
        config.add_route('heartbeat', '/__heartbeat__',
                        renderer='string',
                        view='cornice.wsgiapp.heartbeat')

        config.add_route('manage', '/__config__',
                        renderer='config.mako',
                        view='cornice.wsgiapp.manage')

        config.add_static_view('static', 'cornice:static', cache_max_age=3600)
        config.add_directive('add_apidoc', add_apidoc)
        config.add_route('apidocs', '/__apidocs__')
        config.scan()
        config.scan(package=package)
        return config.make_wsgi_app()
    return _main


def make_main(package=None):
    """Factory to build apps."""
    return main(package)
