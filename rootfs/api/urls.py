"""
URL routing patterns for the Drycc REST API.
"""
from django.conf import settings
from django.urls import include, re_path
from rest_framework.routers import DefaultRouter
from social_core.utils import setting_name
from api import views


router = DefaultRouter(trailing_slash=False)
extra = getattr(settings, setting_name('TRAILING_SLASH'), True) and '/' or ''

# Add the generated REST URLs and login/logout endpoint
app_urlpatterns = [
    re_path(r'^', include(router.urls)),
    re_path(r'auth/login/?$', views.AuthLoginView.as_view({"post": "login"})),
    re_path(r'auth/token/?$', views.AuthTokenView.as_view({"post": "token"})),
    re_path(r'auth/token/(?P<key>[-_\w]+)/?$', views.AuthTokenView.as_view({"get": "token"})),
    # limits
    re_path(
        r'^limits/specs/?$',
        views.LimitSpecViewSet.as_view({'get': 'list'})),
    re_path(
        r'^limits/plans/?$',
        views.LimitPlanViewSet.as_view({'get': 'list'})),
    re_path(
        r'^limits/plans/(?P<id>[-.\w]+)/?$',
        views.LimitPlanViewSet.as_view({'get': 'retrieve'})),
    # application release components
    re_path(
        r"^apps/(?P<id>{})/build/?$".format(settings.APP_URL_REGEX),
        views.BuildViewSet.as_view({'get': 'retrieve', 'post': 'create'})),
    re_path(
        r"^apps/(?P<id>{})/config/?$".format(settings.APP_URL_REGEX),
        views.ConfigViewSet.as_view({'get': 'retrieve', 'post': 'create'})),
    re_path(
        r"^apps/(?P<id>{})/releases/v(?P<version>[0-9]+)/?$".format(settings.APP_URL_REGEX),
        views.ReleaseViewSet.as_view({'get': 'retrieve'})),
    re_path(
        r"^apps/(?P<id>{})/releases/deploy/?$".format(settings.APP_URL_REGEX),
        views.ReleaseViewSet.as_view({'post': 'deploy'})),
    re_path(
        r"^apps/(?P<id>{})/releases/rollback/?$".format(settings.APP_URL_REGEX),
        views.ReleaseViewSet.as_view({'post': 'rollback'})),
    re_path(
        r"^apps/(?P<id>{})/releases/?$".format(settings.APP_URL_REGEX),
        views.ReleaseViewSet.as_view({'get': 'list'})),
    # list/delete pods
    re_path(
        r"^apps/(?P<id>{})/pods/?$".format(settings.APP_URL_REGEX),
        views.PodViewSet.as_view({'get': 'list', 'delete': 'delete'})),
    # describe pod
    re_path(
        r"^apps/(?P<id>{})/pods/(?P<name>{})/describe/?$".format(
            settings.APP_URL_REGEX, settings.NAME_REGEX),
        views.PodViewSet.as_view({'get': 'describe'})),
    # restart deployment/ptype's pods
    re_path(
        r"^apps/(?P<id>{})/ptypes/restart/?$".format(settings.APP_URL_REGEX),
        views.PtypeViewSet.as_view({'post': 'restart'})),
    # clean old k8s resource
    re_path(
        r"^apps/(?P<id>{})/ptypes/clean/?$".format(settings.APP_URL_REGEX),
        views.PtypeViewSet.as_view({'post': 'clean'})),
    # scale ptype replcas
    re_path(
        r"^apps/(?P<id>{})/ptypes/scale/?$".format(settings.APP_URL_REGEX),
        views.PtypeViewSet.as_view({'post': 'scale'})),
    # list ptypes
    re_path(
        r"^apps/(?P<id>{})/ptypes/?$".format(settings.APP_URL_REGEX),
        views.PtypeViewSet.as_view({'get': 'list'})),
    # describe ptypes
    re_path(
        r"^apps/(?P<id>{})/ptypes/(?P<name>{})/describe/?$".format(
            settings.APP_URL_REGEX, settings.NAME_REGEX),
        views.PtypeViewSet.as_view({'get': 'describe'})),
    # list events
    re_path(
        r"^apps/(?P<id>{})/events/?$".format(settings.APP_URL_REGEX),
        views.EventViewSet.as_view({'get': 'list'})),
    # application domains
    re_path(
        r"^apps/(?P<id>{})/domains/(?P<domain>{})/?$".format(
            settings.APP_URL_REGEX, settings.DOMAIN_URL_REGEX),
        views.DomainViewSet.as_view({'delete': 'destroy'})),
    re_path(
        r"^apps/(?P<id>{})/domains/?$".format(settings.APP_URL_REGEX),
        views.DomainViewSet.as_view({'post': 'create', 'get': 'list'})),
    # application services
    re_path(
        r"^apps/(?P<id>{})/services/?$".format(settings.APP_URL_REGEX),
        views.ServiceViewSet.as_view({'post': 'create_or_update',
                                     'get': 'list', 'delete': 'delete'})),
    # application actions
    re_path(
        r"^apps/(?P<id>{})/run/?$".format(settings.APP_URL_REGEX),
        views.AppViewSet.as_view({'post': 'run'})),
    # application settings
    re_path(
        r"^apps/(?P<id>{})/settings/?$".format(settings.APP_URL_REGEX),
        views.AppSettingsViewSet.as_view({'get': 'retrieve', 'post': 'create'})),
    # application TLS settings
    re_path(
        r"^apps/(?P<id>{})/tls/?$".format(settings.APP_URL_REGEX),
        views.TLSViewSet.as_view({'get': 'retrieve', 'post': 'create'})),
    # application volumes
    re_path(
        r"^apps/(?P<id>{})/volumes/?$".format(settings.APP_URL_REGEX),
        views.AppVolumesViewSet.as_view({'get': 'list', 'post': 'create'})),
    re_path(
        r"^apps/(?P<id>{})/volumes/(?P<name>{})/?$".format(
            settings.APP_URL_REGEX, settings.NAME_REGEX),
        views.AppVolumesViewSet.as_view(
            {'get': 'retrieve', 'patch': 'expand', 'delete': 'destroy'})),
    re_path(
        r"^apps/(?P<id>{})/volumes/(?P<name>{})/path/?$".format(
            settings.APP_URL_REGEX, settings.NAME_REGEX),
        views.AppVolumesViewSet.as_view({'patch': 'path'})),
    # application filer
    re_path(
        r"^apps/(?P<id>{})/volumes/(?P<name>{})/client/?$".format(
            settings.APP_URL_REGEX, settings.NAME_REGEX),
        views.AppFilerClientViewSet.as_view({'get': 'list', 'post': 'create'})),
    re_path(
        r"^apps/(?P<id>{})/volumes/(?P<name>{})/client/(?P<path>[\S]+)$".format(
            settings.APP_URL_REGEX, settings.NAME_REGEX),
        views.AppFilerClientViewSet.as_view({'get': 'retrieve', 'delete': 'destroy'})),
    # application resources
    re_path(r"^resources/services/?$", views.AppResourcesViewSet.as_view({'get': 'services'})),
    re_path(
        r"^resources/services/(?P<id>[-_ \.\d\w]+)/plans/?$",
        views.AppResourcesViewSet.as_view({'get': 'plans'})),
    re_path(
        r"^apps/(?P<id>{})/resources/?$".format(settings.APP_URL_REGEX),
        views.AppResourcesViewSet.as_view({'get': 'list', 'post': 'create'})),
    re_path(
        r"^apps/(?P<id>{})/resources/(?P<name>{})/?$".format(
            settings.APP_URL_REGEX, settings.NAME_REGEX),
        views.AppSingleResourceViewSet.as_view(
            {'get': 'retrieve', 'delete': 'destroy', 'put': 'update'})),
    re_path(
        r"^apps/(?P<id>{})/resources/(?P<name>{})/binding/?$".format(
            settings.APP_URL_REGEX, settings.NAME_REGEX),
        views.AppResourceBindingViewSet.as_view({'patch': 'binding'})),
    # certificates
    re_path(
        r'^apps/(?P<id>{})/certs/(?P<name>{})/domain/(?P<domain>{})?/?$'.format(
            settings.APP_URL_REGEX, settings.NAME_REGEX, settings.DOMAIN_URL_REGEX),
        views.CertificateViewSet.as_view({'delete': 'detach', 'post': 'attach'})),
    re_path(
        r'^apps/(?P<id>{})/certs/(?P<name>{})/?$'.format(
            settings.APP_URL_REGEX, settings.NAME_REGEX),
        views.CertificateViewSet.as_view({
            'get': 'retrieve',
            'delete': 'destroy'
        })),
    re_path(
        r'^apps/(?P<id>{})/certs/?$'.format(settings.APP_URL_REGEX),
        views.CertificateViewSet.as_view({'get': 'list', 'post': 'create'})),
    # apps base endpoint
    re_path(
        r"^apps/(?P<id>{})/?$".format(settings.APP_URL_REGEX),
        views.AppViewSet.as_view({'get': 'retrieve', 'post': 'update', 'delete': 'destroy'})),
    re_path(
        r'^apps/?$',
        views.AppViewSet.as_view({'get': 'list', 'post': 'create'})),
    # key
    re_path(
        r'^keys/(?P<id>.+)/?$',
        views.KeyViewSet.as_view({'get': 'retrieve', 'delete': 'destroy'})),
    re_path(
        r'^keys/?$',
        views.KeyViewSet.as_view({'get': 'list', 'post': 'create'})),
    # hooks
    re_path(
        r'^hooks/keys/(?P<id>{})/(?P<username>[\w.@+-]+)/?$'.format(settings.APP_URL_REGEX),
        views.KeyHookViewSet.as_view({'get': 'users'})),
    re_path(
        r'^hooks/keys/(?P<id>{})/?$'.format(settings.APP_URL_REGEX),
        views.KeyHookViewSet.as_view({'get': 'app'})),
    re_path(
        r'^hooks/key/(?P<fingerprint>.+)/?$',
        views.KeyHookViewSet.as_view({'get': 'public_key'})),
    re_path(
        r'^hooks/build/?$',
        views.BuildHookViewSet.as_view({'post': 'create'})),
    re_path(
        r'^hooks/config/?$',
        views.ConfigHookViewSet.as_view({'post': 'create'})),
    # authn / authz
    re_path(
        r'^auth/whoami/?$',
        views.UserManagementViewSet.as_view({'get': 'list'})),
    # gateways
    re_path(
        r"^apps/(?P<id>{})/gateways/?$".format(settings.APP_URL_REGEX),
        views.GatewayViewSet.as_view(
            {'post': 'create_or_update', 'get': 'list', 'delete': 'delete'})),
    # routes
    re_path(
        r"^apps/(?P<id>{})/routes/(?P<name>{})?/?$".format(
            settings.APP_URL_REGEX, settings.NAME_REGEX),
        views.RouteViewSet.as_view(
            {'post': 'create', 'get': 'list', 'delete': 'delete'})),
    re_path(
        r"^apps/(?P<id>{})/routes/(?P<name>{})/attach/?$".format(
            settings.APP_URL_REGEX, settings.NAME_REGEX),
        views.RouteViewSet.as_view({'patch': 'attach'})),
    re_path(
        r"^apps/(?P<id>{})/routes/(?P<name>{})/detach/?$".format(
            settings.APP_URL_REGEX, settings.NAME_REGEX),
        views.RouteViewSet.as_view({'patch': 'detach'})),
    re_path(
        r"^apps/(?P<id>{})/routes/(?P<name>{})/rules/?$".format(
            settings.APP_URL_REGEX, settings.NAME_REGEX),
        views.RouteViewSet.as_view({'get': 'get', 'put': 'set'})),
    # users
    re_path(r'^users/?$', views.UserView.as_view({'get': 'list'})),
    re_path(
        r'^users/(?P<username>[\w.@+-]+)/enable/?$',
        views.UserView.as_view({'patch': 'enable'})),
    re_path(
        r'^users/(?P<username>[\w.@+-]+)/disable/?$',
        views.UserView.as_view({'patch': 'disable'})),
    re_path(
        r'^apps/(?P<id>{})/metrics/?$'.format(settings.APP_URL_REGEX),
        views.MetricView.as_view({'get': 'metric'})),
    re_path(
        r'^apps/(?P<id>{})/metrics/(?P<ptype>[a-z0-9]+(\-[a-z0-9]+)*)/status/?$'.format(
            settings.APP_URL_REGEX),
        views.MetricView.as_view({'get': 'status'})),
    re_path(
        r'^manager/(?P<type>[\w.@+-]+)s/(?P<id>{})/block/?$'.format(settings.APP_URL_REGEX),
        views.WorkflowManagerViewset.as_view({'post': 'block'})),
    re_path(
        r'^manager/(?P<type>[\w.@+-]+)s/(?P<id>{})/unblock/?$'.format(settings.APP_URL_REGEX),
        views.WorkflowManagerViewset.as_view({'delete': 'unblock'})),
    # user perms
    re_path(
        r"^apps/(?P<id>{})/perms/?$".format(settings.APP_URL_REGEX),
        views.AppPermViewSet.as_view({'get': 'list', 'post': 'create'})),
    re_path(
        r"^apps/(?P<id>{})/perms/(?P<username>[\w.@+-]+)/?$".format(settings.APP_URL_REGEX),
        views.AppPermViewSet.as_view({'put': 'update', 'delete': 'destroy'})),
    # nodes
    re_path(
        r'^nodes/(?P<node>[a-zA-Z0-9-]+)/proxy/metrics(?:/(?P<metrics>[^/]+))?/?$',
        views.MetricsProxyView.as_view()),
    # quickwit
    re_path(
        r'^quickwit/(?P<username>[\w.@+-]+)/(?P<path>.+)/?$',
        views.QuickwitProxyView.as_view()),
    # prometheus
    re_path(
        r'^prometheus/(?P<username>[\w.@+-]+)/(?P<path>.+)/?$',
        views.PrometheusProxyView.as_view()),
    # tokens
    re_path(r'^tokens/?$', views.TokenViewSet.as_view({'get': 'list'})),
    re_path(
        r"^tokens/(?P<pk>[-_\w]+)/?$",
        views.TokenViewSet.as_view({'get': 'retrieve', 'delete': 'destroy'})),
]

mutate_urlpatterns = [
    re_path(
        r'^mutate/(?P<key>.+)/?$',
        views.AdmissionWebhookViewSet.as_view({'post': 'handle'})
    ),
]

# social login is placed at the end of the URL match
social_urlpatterns = [
    re_path(r'^login/(?P<backend>[^/]+){0}$'.format(extra), views.auth, name='begin'),
    re_path(r'^complete/(?P<backend>[^/]+){0}$'.format(extra), views.complete, name='complete'),
    re_path('', include('social_django.urls', namespace='social')),
]

# If there is a mutating admission mutate configuration, use mutate url
if settings.MUTATE_KEY:
    urlpatterns = mutate_urlpatterns
else:
    urlpatterns = app_urlpatterns + social_urlpatterns
