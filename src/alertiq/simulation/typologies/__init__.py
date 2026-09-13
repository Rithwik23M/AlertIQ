"""
FATF typology generators package.

Each module implements one documented money-laundering typology.
All generators inherit from BaseTypology and return lists of
Transaction objects with ``is_typology=True``.
"""

from .base import BaseTypology
from .cash_intensive import CashIntensiveTypology
from .cross_border import CrossBorderTypology
from .professional_ml import ProfessionalMLTypology
from .real_estate import RealEstateTypology
from .shell_company import ShellCompanyTypology
from .structuring import StructuringTypology
from .trade_based import TradeBasedTypology
from .virtual_assets import VirtualAssetsTypology
from ..entities import TypologyType

# Registry: TypologyType → generator class
TYPOLOGY_REGISTRY: dict[TypologyType, type[BaseTypology]] = {
    TypologyType.STRUCTURING: StructuringTypology,
    TypologyType.SHELL_COMPANY: ShellCompanyTypology,
    TypologyType.REAL_ESTATE: RealEstateTypology,
    TypologyType.TRADE_BASED: TradeBasedTypology,
    TypologyType.CASH_INTENSIVE: CashIntensiveTypology,
    TypologyType.PROFESSIONAL_ML: ProfessionalMLTypology,
    TypologyType.VIRTUAL_ASSETS: VirtualAssetsTypology,
    TypologyType.CROSS_BORDER: CrossBorderTypology,
}


def get_typology(typology_type: TypologyType) -> BaseTypology:
    """Return an instantiated typology generator for the given type."""
    cls = TYPOLOGY_REGISTRY.get(typology_type)
    if cls is None:
        raise ValueError(f"Unknown typology: {typology_type}")
    return cls()


__all__ = [
    "BaseTypology",
    "StructuringTypology",
    "ShellCompanyTypology",
    "RealEstateTypology",
    "TradeBasedTypology",
    "CashIntensiveTypology",
    "ProfessionalMLTypology",
    "VirtualAssetsTypology",
    "CrossBorderTypology",
    "TYPOLOGY_REGISTRY",
    "get_typology",
]
