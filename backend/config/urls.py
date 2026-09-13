from django.http import HttpResponse
from django.urls import include, path, re_path
from django.views.generic import TemplateView


def spa(request, **kwargs):
    """前端单页应用入口（构建产物存在时由它接管非 /api 路径）。"""
    try:
        return TemplateView.as_view(template_name="index.html")(request)
    except Exception:
        return HttpResponse(
            "前端尚未构建：请先在 frontend/ 执行 npm install && npm run build",
            status=200,
        )


urlpatterns = [
    path("api/", include("revrec.urls")),
    re_path(r"^(?!api/|static/).*$", spa),
]
