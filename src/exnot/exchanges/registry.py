from pathlib import Path

import yaml

from exnot.db.models import Exchange, FeeScheduleFormat, ScraperType

DEFINITIONS_DIR = Path(__file__).parent / "definitions"


def load_exchange_definition(filepath: Path) -> dict:
    with open(filepath) as f:
        return yaml.safe_load(f)


def load_all_definitions() -> list[dict]:
    definitions = []
    for filepath in sorted(DEFINITIONS_DIR.glob("*.yml")):
        defn = load_exchange_definition(filepath)
        definitions.append(defn)
    return definitions


def definition_to_exchange(defn: dict) -> Exchange:
    return Exchange(
        code=defn["code"],
        name=defn["name"],
        operator=defn["operator"],
        fee_schedule_url=defn["fee_schedule_url"],
        alternate_urls=defn.get("alternate_urls"),
        fee_schedule_format=FeeScheduleFormat(defn["fee_schedule_format"]),
        scraper_type=ScraperType(defn["scraper_type"]),
        parser_hints=defn.get("parser_hints"),
        is_active=defn.get("is_active", True),
    )


def get_all_exchanges() -> list[Exchange]:
    definitions = load_all_definitions()
    return [definition_to_exchange(d) for d in definitions]
