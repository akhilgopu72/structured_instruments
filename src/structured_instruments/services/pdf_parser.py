"""Parse prospectus PDFs for autocallable structured notes using Claude API."""

import base64
import json
import re
from pathlib import Path

from anthropic import Anthropic

from structured_instruments.config import settings
from structured_instruments.schemas.instrument import (
    ParsedInstrumentData,
    ParsedUnderlying,
    ParsedValuationDate,
)

EXTRACTION_PROMPT = """\
You are an expert at reading structured product prospectuses (pricing supplements / final terms) for autocallable contingent income notes (also called "worst-of" barrier notes).

Analyze this PDF and extract the following fields. Return ONLY valid JSON with no markdown fencing or commentary.

Required JSON schema:
{
  "cusip": "<string, 9-character CUSIP identifier>",
  "issuer": "<string, issuing bank name, e.g. 'BNP Paribas', 'Societe Generale', 'Morgan Stanley'>",
  "product_type": "<string, e.g. 'Contingent Income Autocallable Notes', 'Autocallable Barrier Notes'>",
  "coupon_rate_annual": <float, annual coupon rate as decimal, e.g. 0.1021 for 10.21%>,
  "coupon_rate_monthly": <float, monthly coupon rate = annual / 12>,
  "coupon_barrier_pct": <float, coupon barrier as decimal of initial, e.g. 0.60 for 60%>,
  "downside_barrier_pct": <float, downside/principal barrier as decimal, e.g. 0.50 for 50%. This may differ from the coupon barrier. Look for 'downside threshold', 'knock-in barrier', 'principal barrier', or 'buffer level'.>,
  "autocall_barrier_pct": <float, autocall trigger as decimal, typically 1.0 for 100% of initial>,
  "pricing_date": "<string, YYYY-MM-DD format>",
  "maturity_date": "<string, YYYY-MM-DD format>",
  "underlyings": [
    {
      "ticker": "<string, stock ticker symbol, e.g. 'AAPL'>",
      "name": "<string, company name or null>",
      "initial_price": <float, initial/reference price on pricing date>
    }
  ],
  "valuation_dates": [
    {
      "date": "<string, YYYY-MM-DD format>",
      "autocall_eligible": <boolean, true if this date has autocall review>,
      "sequence_number": <int, 1-based sequential number>
    }
  ]
}

Important extraction guidelines:
1. Look in the "Final Terms", "Pricing Supplement", "Key Terms", or summary sections for most fields.
2. The CUSIP is typically 9 characters (letters and digits).
3. Coupon rates: The prospectus usually states a "contingent coupon rate" as an annual percentage. Divide by 12 for monthly.
4. Barriers: There are often TWO different barriers:
   - A COUPON barrier (also called "coupon trigger level" or "observation level") - used to determine if the monthly coupon is paid.
   - A DOWNSIDE barrier (also called "knock-in level", "principal barrier", "downside threshold", "buffer level") - used at maturity to determine if principal is at risk. This may be LOWER than the coupon barrier.
   If only one barrier percentage is listed, use it for both.
5. For underlyings, extract the ticker symbol and initial price. These notes are typically linked to 3 stocks.
6. For valuation/observation dates: list ALL monthly observation dates. Early observation dates (typically the first ~3-6 months) are usually NOT autocall eligible. Later dates ARE autocall eligible. Check the document for which dates have "autocall review" or "early redemption" eligibility.
7. All dates must be in YYYY-MM-DD format.
8. All percentage values must be expressed as decimals (60% = 0.60, 10.21% = 0.1021).

Return ONLY the JSON object, no other text.
"""


def parse_prospectus_pdf(pdf_path: Path) -> ParsedInstrumentData:
    """Parse a structured note prospectus PDF using the Anthropic Claude API.

    Args:
        pdf_path: Path to the prospectus PDF file.

    Returns:
        ParsedInstrumentData with all extracted fields.

    Raises:
        FileNotFoundError: If the PDF file does not exist.
        ValueError: If the API response cannot be parsed into valid data.
        anthropic.APIError: If the API call fails.
    """
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    pdf_bytes = pdf_path.read_bytes()
    pdf_base64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")

    client = Anthropic(api_key=settings.anthropic_api_key)

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8192,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": pdf_base64,
                        },
                    },
                    {
                        "type": "text",
                        "text": EXTRACTION_PROMPT,
                    },
                ],
            }
        ],
    )

    response_text = message.content[0].text.strip()

    # Strip markdown fencing if present
    json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", response_text, re.DOTALL)
    if json_match:
        response_text = json_match.group(1).strip()

    try:
        data = json.loads(response_text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Failed to parse JSON from Claude response: {exc}\nResponse text:\n{response_text}"
        ) from exc

    try:
        parsed = ParsedInstrumentData(**data)
    except Exception as exc:
        raise ValueError(
            f"Claude response JSON does not match expected schema: {exc}\nParsed data:\n{json.dumps(data, indent=2)}"
        ) from exc

    return parsed
