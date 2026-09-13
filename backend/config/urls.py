from django.conf import settings
from django.http import HttpResponse
from django.urls import include, path, re_path
from django.views.generic import TemplateView
from django.views.static import serve as static_serve

FRONTEND_DIST = settings.BASE_DIR.parent / "frontend" / "dist"


def spa(request, **kwargs):
    """前端单页应用入口（构建产物存在时由它接管非 /api、非静态资源路径）。"""
    try:
        return TemplateView.as_view(template_name="index.html")(request)
    except Exception:
        return HttpResponse(
            "前端尚未构建：请先在 frontend/ 执行 npm install && npm run build",
            status=200,
        )


urlpatterns = [
    path("api/", include("revrec.urls")),
    # Vite 构建产物：/assets/<file> 必须返回真实 JS/CSS，不能被 SPA 兜底成 HTML
    re_path(
        r"^assets/(?P<path>.*)$",
        static_serve,
        {"document_root": FRONTEND_DIST / "assets"},
    ),
    re_path(r"^(?!api/|static/|assets/).*$", spa),
]
