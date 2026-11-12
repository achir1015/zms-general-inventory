"""進銷存服務：把各功能模組組成一個物件（畫面、手機 API 都透過它存取資料）。"""
from .core import Base, BizError, money, qty  # noqa: F401
from .costing import CostMixin
from .docs import DocsMixin
from .finance import FinanceMixin
from .gl import GLMixin
from .reports import ReportsMixin


class Biz(Base, DocsMixin, CostMixin, FinanceMixin, GLMixin, ReportsMixin):
    pass
