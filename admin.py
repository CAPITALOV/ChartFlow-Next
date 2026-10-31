from sqladmin import Admin, ModelView
from sqladmin.authentication import AuthenticationBackend
from starlette.requests import Request
from db import User, PriceHistory, ForecastRun, ForecastPoint, WatchlistItem
from config import settings


class AdminAuth(AuthenticationBackend):
    async def login(self, request: Request) -> bool:
        form = await request.form()
        if form.get("username") == settings.admin_user and form.get("password") == settings.admin_password:
            request.session.update({"admin_logged_in": True})
            return True
        return False

    async def logout(self, request: Request) -> bool:
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool:
        return request.session.get("admin_logged_in", False)


class UserAdmin(ModelView, model=User):
    column_list = [User.id, User.username, User.email, User.role, User.is_active, User.created_at]
    column_searchable_list = [User.username, User.email]
    icon = "fa-solid fa-user"


class PriceHistoryAdmin(ModelView, model=PriceHistory):
    column_list = [PriceHistory.ticker, PriceHistory.date, PriceHistory.close, PriceHistory.volume]
    column_searchable_list = [PriceHistory.ticker]
    column_sortable_list = [PriceHistory.date, PriceHistory.ticker]
    page_size = 100
    icon = "fa-solid fa-chart-line"


class ForecastRunAdmin(ModelView, model=ForecastRun):
    column_list = [
        ForecastRun.id, ForecastRun.ticker, ForecastRun.model, ForecastRun.horizon_days,
        ForecastRun.status, ForecastRun.mape_avg, ForecastRun.target_price,
        ForecastRun.created_at,
    ]
    column_searchable_list = [ForecastRun.ticker, ForecastRun.model]
    column_sortable_list = [ForecastRun.created_at, ForecastRun.ticker]
    icon = "fa-solid fa-bullseye"


class ForecastPointAdmin(ModelView, model=ForecastPoint):
    column_list = [
        ForecastPoint.id, ForecastPoint.run_id, ForecastPoint.target_date,
        ForecastPoint.predicted_price, ForecastPoint.actual_price,
        ForecastPoint.ape, ForecastPoint.verified,
    ]
    column_sortable_list = [ForecastPoint.target_date]
    page_size = 100
    icon = "fa-solid fa-list"


class WatchlistAdmin(ModelView, model=WatchlistItem):
    column_list = [WatchlistItem.user_id, WatchlistItem.ticker, WatchlistItem.added_at]
    icon = "fa-solid fa-star"


def setup_admin(app, engine):
    admin = Admin(
        app,
        engine,
        authentication_backend=AdminAuth(secret_key=settings.admin_secret_key),
        title="ChartFlow Admin",
        base_url="/admin",
    )
    admin.add_view(UserAdmin)
    admin.add_view(PriceHistoryAdmin)
    admin.add_view(ForecastRunAdmin)
    admin.add_view(ForecastPointAdmin)
    admin.add_view(WatchlistAdmin)
    return admin