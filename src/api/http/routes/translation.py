"""Translation routes — compatibility facade.

.. deprecated::
    Use ``/llm/translate`` for new code. This route delegates to
    ``TranslationService`` which itself wraps ``LlmCapabilityService``.
"""

from __future__ import annotations

import warnings

from fastapi import APIRouter, Depends

from src.api.http.dependencies import translation_service
from src.api.http.schemas.translation import TranslateRequest, TranslateResponse
from src.app.services import TranslationService

router = APIRouter(prefix="/translation", tags=["translation"])


@router.post(
    "/translate",
    response_model=TranslateResponse,
    summary="[deprecated] Use POST /llm/translate instead",
)
def translate(
    body: TranslateRequest,
    svc: TranslationService = Depends(translation_service),
):
    warnings.warn(
        "POST /translation/translate is deprecated, use POST /llm/translate",
        DeprecationWarning,
        stacklevel=1,
    )
    result = svc.translate_file(
        input_path=body.input_path,
        output_path=body.output_path,
        provider=body.provider,
        source_lang=body.source_lang,
        target_lang=body.target_lang,
    )
    return TranslateResponse(
        items=result.items,
        provider=result.provider,
        source_lang=result.source_lang,
        target_lang=result.target_lang,
    )
