"""Prompt registry — maps exchange codes to their extraction prompts."""

import logging

from exnot.ai.prompts.base import BASE_PROMPT
from exnot.ai.prompts.box_options import PROMPT as BOX_OPTIONS_PROMPT
from exnot.ai.prompts.cboe_bzx import PROMPT as CBOE_BZX_PROMPT
from exnot.ai.prompts.cboe_c1 import PROMPT as CBOE_C1_PROMPT
from exnot.ai.prompts.cboe_c2 import PROMPT as CBOE_C2_PROMPT
from exnot.ai.prompts.cboe_edgx import PROMPT as CBOE_EDGX_PROMPT
from exnot.ai.prompts.memx_options import PROMPT as MEMX_OPTIONS_PROMPT
from exnot.ai.prompts.miax_emerald import PROMPT as MIAX_EMERALD_PROMPT
from exnot.ai.prompts.miax_options import PROMPT as MIAX_OPTIONS_PROMPT
from exnot.ai.prompts.miax_pearl import PROMPT as MIAX_PEARL_PROMPT
from exnot.ai.prompts.miax_sapphire import PROMPT as MIAX_SAPPHIRE_PROMPT
from exnot.ai.prompts.nasdaq_bx import PROMPT as NASDAQ_BX_PROMPT
from exnot.ai.prompts.nasdaq_gemx import PROMPT as NASDAQ_GEMX_PROMPT
from exnot.ai.prompts.nasdaq_ise import PROMPT as NASDAQ_ISE_PROMPT
from exnot.ai.prompts.nasdaq_mrx import PROMPT as NASDAQ_MRX_PROMPT
from exnot.ai.prompts.nasdaq_nom import PROMPT as NASDAQ_NOM_PROMPT
from exnot.ai.prompts.nasdaq_phlx import PROMPT as NASDAQ_PHLX_PROMPT
from exnot.ai.prompts.nyse_american import PROMPT as NYSE_AMERICAN_PROMPT
from exnot.ai.prompts.nyse_arca import PROMPT as NYSE_ARCA_PROMPT

logger = logging.getLogger(__name__)

EXCHANGE_PROMPTS: dict[str, str] = {
    "CBOE_BZX": CBOE_BZX_PROMPT,
    "CBOE_EDGX": CBOE_EDGX_PROMPT,
    "CBOE_C1": CBOE_C1_PROMPT,
    "CBOE_C2": CBOE_C2_PROMPT,
    "NASDAQ_ISE": NASDAQ_ISE_PROMPT,
    "NASDAQ_NOM": NASDAQ_NOM_PROMPT,
    "NASDAQ_PHLX": NASDAQ_PHLX_PROMPT,
    "NASDAQ_GEMX": NASDAQ_GEMX_PROMPT,
    "NASDAQ_MRX": NASDAQ_MRX_PROMPT,
    "NASDAQ_BX": NASDAQ_BX_PROMPT,
    "MIAX_OPTIONS": MIAX_OPTIONS_PROMPT,
    "MIAX_PEARL": MIAX_PEARL_PROMPT,
    "MIAX_EMERALD": MIAX_EMERALD_PROMPT,
    "MIAX_SAPPHIRE": MIAX_SAPPHIRE_PROMPT,
    "NYSE_ARCA": NYSE_ARCA_PROMPT,
    "NYSE_AMERICAN": NYSE_AMERICAN_PROMPT,
    "BOX_OPTIONS": BOX_OPTIONS_PROMPT,
    "MEMX_OPTIONS": MEMX_OPTIONS_PROMPT,
}


def get_extraction_prompt(exchange_code: str) -> str:
    """Get the full extraction prompt for an exchange (base + exchange-specific).

    Args:
        exchange_code: Exchange code (e.g., "CBOE_BZX", "NASDAQ_ISE").

    Returns:
        Combined prompt string. Falls back to base prompt only for unknown exchanges.
    """
    exchange_prompt = EXCHANGE_PROMPTS.get(exchange_code)
    if exchange_prompt is None:
        logger.warning(f"No exchange-specific prompt for {exchange_code}, using base prompt only")
        return BASE_PROMPT
    return f"{BASE_PROMPT}\n\n{exchange_prompt}"
