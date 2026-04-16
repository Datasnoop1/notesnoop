"""Companies router package — split by topic, mounted under /api/companies."""

from fastapi import APIRouter

from . import search, detail, financials, structure, network, similar, enrichment

router = APIRouter(prefix="/api/companies", tags=["companies"])
router.include_router(search.router)
router.include_router(financials.router)
router.include_router(structure.router)
router.include_router(network.router)
router.include_router(similar.router)
router.include_router(enrichment.router)
router.include_router(detail.router)
